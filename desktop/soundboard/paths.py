"""Where things live on disk.

* DATA dir   – writable; next to the .exe (or the project root when run from
               source). Holds presets.json, settings.json and sounds/.
* RESOURCE   – read-only bundled files (the ui/ folder). Inside PyInstaller's
               _internal folder when frozen.
"""
import os
import sys


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", _base_dir())
    return _base_dir()


DATA_DIR = _base_dir()
RESOURCE_DIR = _resource_dir()
SOUNDS_DIR = os.path.join(DATA_DIR, "sounds")
PRESETS_FILE = os.path.join(DATA_DIR, "presets.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def data_path(*parts: str) -> str:
    return os.path.join(DATA_DIR, *parts)


def to_abs(path: str) -> str:
    if not path:
        return ""
    path = path.replace("/", os.sep)
    return path if os.path.isabs(path) else os.path.join(DATA_DIR, path)


def to_rel(path: str) -> str:
    """Store paths inside the data dir as relative (portable folder)."""
    if not path:
        return ""
    ap = os.path.abspath(path)
    try:
        rel = os.path.relpath(ap, DATA_DIR)
    except ValueError:  # different drive on Windows
        return ap
    if rel.startswith(".."):
        return ap
    return rel.replace(os.sep, "/")
