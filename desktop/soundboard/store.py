"""presets.json + settings.json (human-readable, saved atomically)."""
import copy
import json
import os
import threading
import uuid

from .paths import PRESETS_FILE, SETTINGS_FILE
from .starter import build_starter_presets

SLOTS = 12
THEMES = ("cyber", "gothic", "neutral")
TYPES = ("sfx", "loop")
REPEATS = ("overlap", "restart", "toggle")

DEFAULT_HOTKEYS = {
    "mods": ["ctrl", "alt"],
    "slots": [f"Digit{d}" for d in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0)] + ["Minus", "Equal"],
    "panic": "Space",
}

DEFAULT_SETTINGS = {
    "active_preset": "night-city",
    "master": 0.9,
    "groups": {"sfx": 0.9, "ambient": 0.75},
    "hotkeys": DEFAULT_HOTKEYS,
    "panic_fade": 700,
    "freesound_key": "",
}


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def clean_slot(s):
    if not s or not isinstance(s, dict):
        return None
    kind = s.get("type") if s.get("type") in TYPES else "sfx"
    repeat = s.get("repeat") if s.get("repeat") in REPEATS else ("toggle" if kind == "loop" else "overlap")
    try:
        vol = max(0.0, min(1.0, float(s.get("volume", 0.85))))
    except (TypeError, ValueError):
        vol = 0.85
    try:
        fade = max(0, min(10000, int(s.get("fade", 0))))
    except (TypeError, ValueError):
        fade = 0
    return {
        "name": str(s.get("name") or "Untitled")[:40],
        "file": str(s.get("file") or ""),
        "type": kind,
        "volume": round(vol, 3),
        "repeat": repeat,
        "fade": fade,
    }


def clean_preset(p):
    slots = list(p.get("slots") or [])[:SLOTS]
    slots += [None] * (SLOTS - len(slots))
    return {
        "id": str(p.get("id") or uuid.uuid4().hex[:8]),
        "name": str(p.get("name") or "New board")[:32],
        "subtitle": str(p.get("subtitle") or "")[:60],
        "theme": p.get("theme") if p.get("theme") in THEMES else "neutral",
        "slots": [clean_slot(s) for s in slots],
    }


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self._save_timer = None
        data = _read_json(PRESETS_FILE)
        if data and isinstance(data.get("presets"), list) and data["presets"]:
            self.presets = [clean_preset(p) for p in data["presets"]]
        else:
            self.presets = [clean_preset(p) for p in build_starter_presets()]
            self.save_presets()
        s = _read_json(SETTINGS_FILE) or {}
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        for k, v in s.items():
            if k in self.settings:
                self.settings[k] = v
        self.settings["groups"] = {**DEFAULT_SETTINGS["groups"], **(s.get("groups") or {})}
        self.settings["hotkeys"] = self._clean_hotkeys(s.get("hotkeys") or {})
        if not self.get(self.settings["active_preset"]):
            self.settings["active_preset"] = self.presets[0]["id"]
        self.save_settings()

    # ------------------------------------------------------------ presets
    def get(self, pid):
        return next((p for p in self.presets if p["id"] == pid), None)

    def active(self):
        return self.get(self.settings["active_preset"]) or self.presets[0]

    def save_presets(self):
        with self.lock:
            _write_json(PRESETS_FILE, {"version": 1, "presets": self.presets})

    def new_id(self, name):
        base = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")[:20] or "board"
        pid, n = base, 2
        while self.get(pid):
            pid, n = f"{base}-{n}", n + 1
        return pid

    # ----------------------------------------------------------- settings
    @staticmethod
    def _clean_hotkeys(h):
        raw = h["mods"] if isinstance(h.get("mods"), list) else DEFAULT_HOTKEYS["mods"]
        mods = [m for m in ("ctrl", "alt", "shift", "win") if m in raw]
        slots = list(h.get("slots") or DEFAULT_HOTKEYS["slots"])[:SLOTS]
        slots += DEFAULT_HOTKEYS["slots"][len(slots):]
        return {"mods": mods, "slots": [str(x or "") for x in slots],
                "panic": str(h.get("panic") or DEFAULT_HOTKEYS["panic"])}

    def save_settings(self):
        with self.lock:
            _write_json(SETTINGS_FILE, self.settings)

    def save_settings_later(self, delay=0.6):
        """Debounced save for slider drags."""
        with self.lock:
            if self._save_timer:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(delay, self.save_settings)
            self._save_timer.daemon = True
            self._save_timer.start()
