"""Audio engine on top of pygame.mixer.

All volume changes and fades are done by our own ticker thread, so slot,
channel-group and master volume can change live while sounds fade in/out.
"""
import os
import threading
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

GROUPS = ("sfx", "ambient")
TICK = 1 / 60


def _curve(x: float) -> float:
    """Slider position (0..1) -> amplitude. Squared feels more natural."""
    x = max(0.0, min(1.0, float(x)))
    return x * x


class Voice:
    __slots__ = ("key", "group", "vol", "sound", "channel", "loop", "t0",
                 "length", "f_from", "f_to", "f_t0", "f_dur", "stopping")

    def __init__(self, key, group, vol, sound, channel, loop, fade_in):
        now = time.monotonic()
        self.key = key
        self.group = group
        self.vol = vol
        self.sound = sound
        self.channel = channel
        self.loop = loop
        self.t0 = now
        self.length = max(sound.get_length(), 0.001)
        self.f_from, self.f_to, self.f_t0 = (0.0, 1.0, now) if fade_in > 0 else (1.0, 1.0, now)
        self.f_dur = fade_in / 1000.0
        self.stopping = False

    def fade_gain(self, now):
        if self.f_dur <= 0:
            return self.f_to
        t = (now - self.f_t0) / self.f_dur
        if t >= 1:
            return self.f_to
        return self.f_from + (self.f_to - self.f_from) * t

    def fade_out(self, ms, now):
        self.f_from = self.fade_gain(now)
        self.f_to = 0.0
        self.f_t0 = now
        self.f_dur = max(ms, 0) / 1000.0
        self.stopping = True

    def alive(self):
        try:
            return self.channel.get_busy() and self.channel.get_sound() is self.sound
        except pygame.error:
            return False


class AudioEngine:
    def __init__(self):
        pygame.mixer.pre_init(44100, -16, 2, 1024)
        pygame.mixer.init()
        pygame.mixer.set_num_channels(48)
        self._lock = threading.RLock()
        self._load_lock = threading.Lock()
        self._cache = {}
        self._voices = []
        self.master = 1.0
        self.groups = {"sfx": 1.0, "ambient": 1.0}
        self._running = True
        self._thread = threading.Thread(target=self._tick_loop, name="audio-tick", daemon=True)
        self._thread.start()

    # ---------------------------------------------------------------- loading
    def load(self, path):
        with self._load_lock:
            snd = self._cache.get(path)
            if snd is None:
                if not os.path.isfile(path):
                    raise FileNotFoundError(path)
                snd = pygame.mixer.Sound(path)
                self._cache[path] = snd
            return snd

    def preload(self, paths):
        """Load sounds in the background; drop everything else from cache."""
        keep = set(p for p in paths if p)

        def work():
            with self._load_lock:
                for p in list(self._cache):
                    if p not in keep:
                        del self._cache[p]
            for p in keep:
                try:
                    self.load(p)
                except Exception:
                    pass

        threading.Thread(target=work, name="preload", daemon=True).start()

    def forget(self, path=None):
        with self._load_lock:
            if path is None:
                self._cache.clear()
            else:
                self._cache.pop(path, None)

    # --------------------------------------------------------------- playback
    def _active(self, key):
        return [v for v in self._voices if v.key == key and not v.stopping]

    def trigger(self, key, path, group="sfx", volume=1.0, loop=False,
                repeat="overlap", fade_ms=0):
        """Press a pad. Returns 'started', 'stopped' or raises on bad file."""
        group = group if group in GROUPS else "sfx"
        with self._lock:
            current = self._active(key)
            if current and repeat == "toggle":
                now = time.monotonic()
                for v in current:
                    v.fade_out(fade_ms, now)
                return "stopped"
            if current and repeat == "restart":
                for v in current:
                    v.channel.stop()
                self._voices = [v for v in self._voices if v not in current]
        sound = self.load(path)  # may take a moment the first time
        with self._lock:
            ch = pygame.mixer.find_channel(True)
            v = Voice(key, group, float(volume), sound, ch, bool(loop), fade_ms)
            ch.set_volume(self._gain(v, time.monotonic()))
            ch.play(sound, loops=-1 if loop else 0)
            ch.set_volume(self._gain(v, time.monotonic()))
            # if we stole a busy channel, the voice that used it is gone now
            self._voices = [x for x in self._voices if x.alive()]
            self._voices.append(v)
        return "started"

    def stop_key(self, key, fade_ms=0):
        with self._lock:
            now = time.monotonic()
            for v in self._voices:
                if v.key == key:
                    v.fade_out(fade_ms, now)

    def stop_prefix(self, prefix, fade_ms=0):
        with self._lock:
            now = time.monotonic()
            for v in self._voices:
                if str(v.key).startswith(prefix):
                    v.fade_out(fade_ms, now)

    def stop_all(self, fade_ms=0):
        with self._lock:
            now = time.monotonic()
            for v in self._voices:
                v.fade_out(fade_ms, now)

    def set_key_volume(self, key, volume):
        with self._lock:
            for v in self._voices:
                if v.key == key:
                    v.vol = float(volume)

    def set_master(self, value):
        self.master = max(0.0, min(1.0, float(value)))

    def set_group(self, group, value):
        if group in self.groups:
            self.groups[group] = max(0.0, min(1.0, float(value)))

    # ------------------------------------------------------------------ state
    def snapshot(self):
        """{key: {'progress': 0..1, 'count': n, 'loop': bool}} for live voices."""
        out = {}
        now = time.monotonic()
        with self._lock:
            for v in self._voices:
                if v.stopping:
                    continue
                el = now - v.t0
                prog = (el % v.length) / v.length if v.loop else min(1.0, el / v.length)
                e = out.setdefault(v.key, {"progress": prog, "count": 0, "loop": v.loop})
                e["count"] += 1
                e["progress"] = max(e["progress"], prog) if not v.loop else prog
        return out

    # ------------------------------------------------------------------ ticker
    def _gain(self, v, now):
        return (_curve(v.vol) * _curve(self.groups.get(v.group, 1.0))
                * _curve(self.master) * v.fade_gain(now))

    def _tick_loop(self):
        while self._running:
            now = time.monotonic()
            with self._lock:
                keep = []
                for v in self._voices:
                    if not v.alive():
                        continue
                    if v.stopping and v.fade_gain(now) <= 0.0001:
                        v.channel.stop()
                        continue
                    try:
                        v.channel.set_volume(self._gain(v, now))
                    except pygame.error:
                        continue
                    keep.append(v)
                self._voices = keep
            time.sleep(TICK)

    def shutdown(self):
        self._running = False
        try:
            pygame.mixer.stop()
            pygame.mixer.quit()
        except Exception:
            pass
