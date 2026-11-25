"""Backend API called from the UI (exposed through pywebview's js_api).

Every public method is callable from JavaScript as
`await pywebview.api.method_name(...)` and returns JSON-able data.
"""
import os
import shutil
import sys
import threading
import webbrowser

from . import __version__
from .audio import AudioEngine
from .hotkeys import HotkeyManager, combo_label
from .paths import DATA_DIR, SOUNDS_DIR, to_abs, to_rel
from .starter import STARTER_BOARDS, DownloadError, download_starter
from .store import SLOTS, THEMES, Store, clean_preset, clean_slot, DEFAULT_HOTKEYS

AUDIO_EXT = (".ogg", ".wav", ".mp3", ".flac", ".opus")
SWITCH_FADE = 300


class Api:
    def __init__(self):
        self._store = Store()
        self._audio = AudioEngine()
        s = self._store.settings
        self._audio.set_master(s["master"])
        for g, v in s["groups"].items():
            self._audio.set_group(g, v)
        self._window = None
        self._triggers = [0] * SLOTS  # bump per press so the UI can flash
        self._files_version = 1
        self._hotkey_errors = {}
        self._dl = {"running": False, "done": 0, "total": 0, "current": "", "log": [], "error": ""}
        self._hk = HotkeyManager(self._on_hotkey)
        self._apply_hotkeys()
        self._preload_active()

    # ============================================================== helpers
    def _key(self, index):
        return f"{self._store.active()['id']}:{index}"

    def _preload_active(self):
        self._audio.preload([to_abs(s["file"]) for s in self._store.active()["slots"] if s and s["file"]])

    def _bindings(self):
        h = self._store.settings["hotkeys"]
        b = {f"slot{i}": (h["mods"], code) for i, code in enumerate(h["slots"]) if code}
        if h["panic"]:
            b["panic"] = (h["mods"], h["panic"])
        return b

    def _apply_hotkeys(self):
        res = self._hk.apply(self._bindings())
        self._hotkey_errors = {a: e for a, e in res.items() if e}
        return self._hotkey_errors

    def _on_hotkey(self, action):
        if action == "panic":
            self.panic()
        elif action.startswith("slot"):
            self.trigger(int(action[4:]))

    def _preset_view(self, p):
        slots = []
        for s in p["slots"]:
            if s:
                s = dict(s)
                s["exists"] = bool(s["file"]) and os.path.isfile(to_abs(s["file"]))
                s["filename"] = os.path.basename(s["file"]) if s["file"] else ""
            slots.append(s)
        starter = next((b for b in STARTER_BOARDS if b["id"] == p["id"]), None)
        return {**p, "slots": slots, "is_starter": bool(starter)}

    def _presets_view(self):
        return [self._preset_view(p) for p in self._store.presets]

    def _bump_files(self):
        self._files_version += 1

    # ============================================================== queries
    def get_init(self):
        s = self._store.settings
        return {
            "version": __version__,
            "presets": self._presets_view(),
            "settings": {k: v for k, v in s.items() if k != "freesound_key"},
            "has_freesound_key": bool(s.get("freesound_key")),
            "freesound_key": s.get("freesound_key", ""),
            "global_hotkeys": self._hk.available,
            "hotkey_errors": self._hotkey_errors,
            "default_hotkeys": DEFAULT_HOTKEYS,
            "themes": list(THEMES),
            "data_dir": DATA_DIR,
        }

    def get_presets(self):
        return self._presets_view()

    def get_state(self):
        active = self._store.active()["id"]
        prefix = active + ":"
        snap = self._audio.snapshot()
        playing = {k[len(prefix):]: v for k, v in snap.items() if str(k).startswith(prefix)}
        return {
            "active": active,
            "playing": playing,
            "preview": "preview" in snap,
            "triggers": self._triggers,
            "files_version": self._files_version,
            "hotkey_errors": self._hotkey_errors,
            "download": {**self._dl, "log": self._dl["log"][-200:]},
        }

    # ============================================================== playback
    def trigger(self, index):
        index = int(index)
        p = self._store.active()
        if not 0 <= index < SLOTS:
            return {"ok": False}
        s = p["slots"][index]
        if not s or not s["file"]:
            return {"ok": False, "error": "empty"}
        self._triggers[index] += 1
        try:
            result = self._audio.trigger(
                self._key(index), to_abs(s["file"]),
                group="ambient" if s["type"] == "loop" else "sfx",
                volume=s["volume"], loop=s["type"] == "loop",
                repeat=s["repeat"], fade_ms=s["fade"])
            return {"ok": True, "result": result}
        except FileNotFoundError:
            return {"ok": False, "error": "File not found — download starter sounds or pick a file."}
        except Exception as e:
            return {"ok": False, "error": f"Cannot play: {e}"}

    def stop_slot(self, index):
        p = self._store.active()
        s = p["slots"][int(index)]
        self._audio.stop_key(self._key(int(index)), s["fade"] if s else 0)
        return True

    def panic(self):
        self._audio.stop_all(int(self._store.settings.get("panic_fade", 700)))
        return True

    def set_volume(self, kind, value):
        value = max(0.0, min(1.0, float(value)))
        s = self._store.settings
        if kind == "master":
            s["master"] = value
            self._audio.set_master(value)
        elif kind in ("sfx", "ambient"):
            s["groups"][kind] = value
            self._audio.set_group(kind, value)
        self._store.save_settings_later()
        return True

    def preview(self, file, volume=0.85, kind="sfx"):
        self._audio.stop_key("preview")
        try:
            self._audio.trigger("preview", to_abs(file), group="sfx", volume=volume,
                                loop=False, repeat="restart")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def stop_preview(self):
        self._audio.stop_key("preview", 150)
        return True

    # ============================================================== presets
    def set_active(self, pid):
        if not self._store.get(pid):
            return False
        if pid != self._store.settings["active_preset"]:
            self._audio.stop_all(SWITCH_FADE)  # all sound stops on switch
            self._store.settings["active_preset"] = pid
            self._store.save_settings()
            self._preload_active()
        return True

    def save_slot(self, pid, index, slot):
        p = self._store.get(pid)
        if not p:
            return {"ok": False, "error": "board not found"}
        index = int(index)
        new = clean_slot(slot) if slot else None
        p["slots"][index] = new
        self._store.save_presets()
        key = f"{pid}:{index}"
        if new is None:
            self._audio.stop_key(key, 200)
        else:
            self._audio.set_key_volume(key, new["volume"])
            if pid == self._store.active()["id"] and new["file"]:
                self._audio.preload([to_abs(s["file"]) for s in p["slots"] if s and s["file"]])
        return {"ok": True, "presets": self._presets_view()}

    def swap_slots(self, pid, a, b):
        p = self._store.get(pid)
        if not p:
            return {"ok": False}
        a, b = int(a), int(b)
        p["slots"][a], p["slots"][b] = p["slots"][b], p["slots"][a]
        self._audio.stop_prefix(pid + ":", 200)
        self._store.save_presets()
        return {"ok": True, "presets": self._presets_view()}

    def create_preset(self, name="New board", theme="neutral", subtitle=""):
        p = clean_preset({"id": self._store.new_id(name), "name": name, "theme": theme,
                          "subtitle": subtitle, "slots": []})
        self._store.presets.append(p)
        self._store.save_presets()
        self.set_active(p["id"])
        return {"ok": True, "id": p["id"], "presets": self._presets_view()}

    def duplicate_preset(self, pid):
        src = self._store.get(pid)
        if not src:
            return {"ok": False}
        p = clean_preset({**src, "id": self._store.new_id(src["name"] + " copy"),
                          "name": (src["name"] + " copy")[:32]})
        self._store.presets.insert(self._store.presets.index(src) + 1, p)
        self._store.save_presets()
        self.set_active(p["id"])
        return {"ok": True, "id": p["id"], "presets": self._presets_view()}

    def update_preset(self, pid, name, subtitle, theme):
        p = self._store.get(pid)
        if not p:
            return {"ok": False}
        p["name"] = (str(name).strip() or p["name"])[:32]
        p["subtitle"] = str(subtitle or "")[:60]
        p["theme"] = theme if theme in THEMES else p["theme"]
        self._store.save_presets()
        return {"ok": True, "presets": self._presets_view()}

    def delete_preset(self, pid):
        if len(self._store.presets) <= 1:
            return {"ok": False, "error": "Keep at least one board."}
        p = self._store.get(pid)
        if not p:
            return {"ok": False}
        i = self._store.presets.index(p)
        self._store.presets.remove(p)
        self._store.save_presets()
        if self._store.settings["active_preset"] == pid:
            self.set_active(self._store.presets[max(0, i - 1)]["id"])
        return {"ok": True, "presets": self._presets_view(), "active": self._store.active()["id"]}

    def move_preset(self, pid, direction):
        p = self._store.get(pid)
        if not p:
            return {"ok": False}
        lst = self._store.presets
        i = lst.index(p)
        j = max(0, min(len(lst) - 1, i + (1 if int(direction) > 0 else -1)))
        lst[i], lst[j] = lst[j], lst[i]
        self._store.save_presets()
        return {"ok": True, "presets": self._presets_view()}

    # ================================================================ files
    def browse_file(self, pid=""):
        """Open a file dialog; copy the chosen file into sounds/custom/<board>/."""
        if not self._window:
            return {"ok": False, "error": "no window"}
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
        if kind is None:
            kind = webview.OPEN_DIALOG
        res = self._window.create_file_dialog(
            kind, allow_multiple=False,
            file_types=("Audio files (*.ogg;*.wav;*.mp3;*.flac;*.opus)", "All files (*.*)"))
        if not res:
            return {"ok": False, "cancelled": True}
        src = res[0] if isinstance(res, (list, tuple)) else res
        return self.import_file(src, pid)

    def import_file(self, src, pid=""):
        if not os.path.isfile(src):
            return {"ok": False, "error": "file not found"}
        if not src.lower().endswith(AUDIO_EXT):
            return {"ok": False, "error": "Unsupported format — use OGG, WAV, MP3 or FLAC."}
        rel = to_rel(src)
        if os.path.isabs(rel):  # outside our folder → copy it in
            folder = os.path.join(SOUNDS_DIR, "custom", pid or "shared")
            os.makedirs(folder, exist_ok=True)
            name = os.path.basename(src)
            dest = os.path.join(folder, name)
            stem, ext = os.path.splitext(name)
            n = 2
            while os.path.exists(dest) and os.path.getsize(dest) != os.path.getsize(src):
                dest = os.path.join(folder, f"{stem}_{n}{ext}")
                n += 1
            if not os.path.exists(dest):
                shutil.copy2(src, dest)
            rel = to_rel(dest)
        self._audio.forget(to_abs(rel))
        name = os.path.splitext(os.path.basename(src))[0].replace("_", " ").replace("-", " ").strip()
        return {"ok": True, "file": rel, "filename": os.path.basename(rel), "suggested_name": name[:40].title()}

    def open_sounds_folder(self):
        os.makedirs(SOUNDS_DIR, exist_ok=True)
        self._open_path(SOUNDS_DIR)
        return True

    @staticmethod
    def _open_path(path):
        if sys.platform == "win32":
            os.startfile(path)  # noqa
        else:
            webbrowser.open("file://" + path)

    def open_url(self, url):
        if str(url).startswith("https://"):
            webbrowser.open(url)
        return True

    # ============================================================== hotkeys
    def save_hotkeys(self, hotkeys):
        h = self._store._clean_hotkeys(hotkeys or {})
        if not h["mods"]:
            return {"ok": False, "error": "Pick at least one modifier — without it the hotkeys would steal normal typing in every program."}
        codes = [c for c in h["slots"] + [h["panic"]] if c]
        dups = sorted({c for c in codes if codes.count(c) > 1})
        if dups:
            return {"ok": False, "error": "Same key used twice: " + ", ".join(combo_label([], c) for c in dups)}
        self._store.settings["hotkeys"] = h
        self._store.save_settings()
        errors = self._apply_hotkeys()
        return {"ok": True, "hotkeys": h, "errors": errors}

    def set_panic_fade(self, ms):
        self._store.settings["panic_fade"] = max(0, min(5000, int(ms)))
        self._store.save_settings()
        return True

    # ============================================================ download
    def set_freesound_key(self, key):
        self._store.settings["freesound_key"] = str(key or "").strip()
        self._store.save_settings()
        return True

    def start_download(self, key=None, reroll=False, board=None, index=None):
        if self._dl["running"]:
            return {"ok": False, "error": "Already downloading."}
        if key is not None:
            self.set_freesound_key(key)
        api_key = self._store.settings.get("freesound_key", "")
        only = {(board, int(index))} if board is not None and index is not None else None
        self._dl.update(running=True, done=0, total=0, current="", log=[], error="")

        def log(line):
            self._dl["log"].append(line)

        def progress(done, total, label):
            self._dl.update(done=done, total=total, current=label)

        def work():
            try:
                ok, failed = download_starter(api_key, reroll=bool(reroll), log=log,
                                              progress=progress, only=only)
                log(f"— {ok} ready, {len(failed)} missing.")
            except DownloadError as e:
                self._dl["error"] = str(e)
                log("✗ " + str(e))
            except Exception as e:
                self._dl["error"] = f"Unexpected error: {e}"
                log("✗ " + self._dl["error"])
            finally:
                self._audio.forget()
                self._preload_active()
                self._bump_files()
                self._dl["running"] = False

        threading.Thread(target=work, name="download", daemon=True).start()
        return {"ok": True}

    # ============================================================== shutdown
    def _shutdown(self):
        self._hk.stop()
        self._audio.shutdown()
