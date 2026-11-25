"""Global hotkeys.

Windows: RegisterHotKey via ctypes — works while other windows (Foundry,
Roll20, Discord, a browser) have focus, needs no admin rights and no extra
packages. Windows also tells us when another program already owns a combo,
which is how conflicts are detected.

Other OSes: not available; the UI falls back to in-window shortcuts.

Keys are stored as KeyboardEvent.code names ("Digit1", "KeyQ", "Minus"...),
so they do not depend on the keyboard layout (UA / EN / RU).
"""
import queue
import sys
import threading

MOD_FLAGS = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
MOD_ORDER = ("ctrl", "alt", "shift", "win")

CODE_TO_VK = {
    "Space": 0x20, "Backspace": 0x08, "Tab": 0x09, "Enter": 0x0D,
    "Pause": 0x13, "Insert": 0x2D, "Delete": 0x2E, "Home": 0x24, "End": 0x23,
    "PageUp": 0x21, "PageDown": 0x22,
    "ArrowLeft": 0x25, "ArrowUp": 0x26, "ArrowRight": 0x27, "ArrowDown": 0x28,
    "Minus": 0xBD, "Equal": 0xBB, "BracketLeft": 0xDB, "BracketRight": 0xDD,
    "Semicolon": 0xBA, "Quote": 0xDE, "Backquote": 0xC0, "Backslash": 0xDC,
    "Comma": 0xBC, "Period": 0xBE, "Slash": 0xBF,
    "NumpadMultiply": 0x6A, "NumpadAdd": 0x6B, "NumpadSubtract": 0x6D,
    "NumpadDecimal": 0x6E, "NumpadDivide": 0x6F, "ScrollLock": 0x91,
}
for _d in range(10):
    CODE_TO_VK[f"Digit{_d}"] = 0x30 + _d
    CODE_TO_VK[f"Numpad{_d}"] = 0x60 + _d
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    CODE_TO_VK[f"Key{_c}"] = 0x41 + _i
for _f in range(1, 25):
    CODE_TO_VK[f"F{_f}"] = 0x70 + _f - 1

KEY_LABELS = {
    "Space": "Space", "Backspace": "Bksp", "Minus": "-", "Equal": "=",
    "BracketLeft": "[", "BracketRight": "]", "Semicolon": ";", "Quote": "'",
    "Backquote": "`", "Backslash": "\\", "Comma": ",", "Period": ".", "Slash": "/",
    "PageUp": "PgUp", "PageDown": "PgDn", "ArrowLeft": "←", "ArrowUp": "↑",
    "ArrowRight": "→", "ArrowDown": "↓", "NumpadMultiply": "Num*",
    "NumpadAdd": "Num+", "NumpadSubtract": "Num-", "NumpadDecimal": "Num.",
    "NumpadDivide": "Num/", "ScrollLock": "ScrLk", "Delete": "Del", "Insert": "Ins",
}


def key_label(code: str) -> str:
    if code in KEY_LABELS:
        return KEY_LABELS[code]
    if code.startswith("Digit"):
        return code[5:]
    if code.startswith("Key"):
        return code[3:]
    if code.startswith("Numpad"):
        return "Num" + code[6:]
    return code


def combo_label(mods, code) -> str:
    parts = [m.capitalize() for m in MOD_ORDER if m in mods]
    return "+".join(parts + [key_label(code)])


AVAILABLE = sys.platform == "win32"


class HotkeyManager:
    """bindings: {action_name: (mods_list, code)}; callback(action_name)."""

    def __init__(self, callback):
        self._callback = callback
        self.available = AVAILABLE
        self._pending = {}
        self._results = {}
        self._registered = {}  # id -> action
        self._applied = threading.Event()
        self._ready = threading.Event()
        self._tid = None
        self._jobs = queue.Queue()
        threading.Thread(target=self._worker, name="hotkey-worker", daemon=True).start()
        if self.available:
            threading.Thread(target=self._loop, name="hotkeys", daemon=True).start()
            self._ready.wait(3)

    # Work triggered by hotkeys runs here so the message loop never blocks.
    def _worker(self):
        while True:
            action = self._jobs.get()
            if action is None:
                return
            try:
                self._callback(action)
            except Exception as e:  # never let a bad sound kill hotkeys
                print("hotkey action failed:", action, e)

    def apply(self, bindings):
        """Register bindings, return {action: error_text_or_None}."""
        if not self.available:
            return {a: None for a in bindings}
        import ctypes
        self._pending = dict(bindings)
        self._applied.clear()
        ctypes.windll.user32.PostThreadMessageW(self._tid, 0x8000 + 1, 0, 0)
        self._applied.wait(3)
        return dict(self._results)

    def stop(self):
        self._jobs.put(None)
        if self.available and self._tid:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT

    # ---------------------------------------------------------------- win32
    def _loop(self):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32")
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]

        WM_HOTKEY = 0x0312
        WM_APPLY = 0x8000 + 1

        self._tid = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create the queue
        self._ready.set()

        def do_apply():
            for hid in list(self._registered):
                user32.UnregisterHotKey(None, hid)
            self._registered.clear()
            results = {}
            hid = 1
            for action, (mods, code) in self._pending.items():
                vk = CODE_TO_VK.get(code)
                if vk is None:
                    results[action] = f"Unsupported key: {code}"
                    continue
                flags = MOD_NOREPEAT
                for m in mods:
                    flags |= MOD_FLAGS.get(m, 0)
                if user32.RegisterHotKey(None, hid, flags, vk):
                    self._registered[hid] = action
                    results[action] = None
                else:
                    err = ctypes.get_last_error()
                    results[action] = ("Already used by another program"
                                       if err == 1409 else f"Windows error {err}")
                hid += 1
            self._results = results
            self._applied.set()

        while True:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            if msg.message == WM_HOTKEY:
                action = self._registered.get(int(msg.wParam))
                if action:
                    self._jobs.put(action)
            elif msg.message == WM_APPLY:
                do_apply()

        for hid in list(self._registered):
            user32.UnregisterHotKey(None, hid)
