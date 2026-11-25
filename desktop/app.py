"""GM Soundboard — entry point. Opens the board in its own window."""
import os
import sys

from soundboard.paths import RESOURCE_DIR


def _unblock_bundle():
    """Windows marks files from a downloaded zip as 'from the internet'
    (Zone.Identifier). .NET then refuses to load Python.Runtime.dll and
    pywebview crashes with 'Failed to resolve Python.Runtime.Loader.Initialize'.
    Strip that mark from our own bundled files before anything loads."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    root = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    for folder, _dirs, files in os.walk(root):
        for name in files:
            try:
                os.remove(os.path.join(folder, name) + ":Zone.Identifier")
            except OSError:
                pass


def main():
    _unblock_bundle()
    try:
        import webview
    except ImportError:
        print("pywebview is not installed: pip install -r requirements.txt")
        sys.exit(1)
    from soundboard.api import Api

    api = Api()
    window = webview.create_window(
        "GM Soundboard",
        url=os.path.join(RESOURCE_DIR, "ui", "index.html"),
        js_api=api,
        width=1280,
        height=840,
        min_size=(960, 640),
        background_color="#08080a",
    )
    api._window = window
    try:
        webview.start(http_server=True, debug="--debug" in sys.argv)
    finally:
        api._shutdown()


if __name__ == "__main__":
    main()
