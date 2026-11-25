"""Download the starter sound packs from Freesound (CC0 only).

Usage:
    python download_sounds.py YOUR_API_KEY            # fetch missing sounds
    python download_sounds.py YOUR_API_KEY --reroll   # replace all with other picks

The key can also be saved in the app (Settings → Starter sounds) — then just
run `python download_sounds.py`. Same thing as the Download button in the app.
"""
import argparse
import sys

from soundboard.starter import DownloadError, download_starter
from soundboard.store import Store


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("api_key", nargs="?", help="Freesound API key (https://freesound.org/apiv2/apply)")
    ap.add_argument("--reroll", action="store_true", help="replace existing files with different picks")
    args = ap.parse_args()

    store = Store()
    key = args.api_key or store.settings.get("freesound_key", "")
    if args.api_key:
        store.settings["freesound_key"] = args.api_key
        store.save_settings()
    try:
        ok, failed = download_starter(key, reroll=args.reroll)
    except DownloadError as e:
        print("Error:", e)
        sys.exit(1)
    print(f"\n{ok} sounds ready, {len(failed)} missing.")
    for f in failed:
        print("  missing:", f)


if __name__ == "__main__":
    main()
