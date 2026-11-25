"""Starter boards (Night City / Elysium) and the Freesound downloader.

The downloader searches Freesound for CC0 sounds that match each slot and
saves the high-quality OGG preview to sounds/starter/<board>/NN_name.ogg.
Searching (instead of hard-coded IDs) keeps it working even when individual
uploads disappear. Needs a free Freesound API key:
https://freesound.org/apiv2/apply
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .paths import SOUNDS_DIR, to_rel

API_ROOT = "https://freesound.org/apiv2"
UA = "GM-Soundboard/1.0 (tabletop RPG sound board)"
CC0 = 'license:"Creative Commons 0"'

NO_MUSIC = " -music -song -melody -piano -guitar -synth -beat"


def _slot(name, kind, queries, dur, volume=0.85, repeat=None, fade=None, exclude=""):
    loop = kind == "loop"
    return {
        "name": name,
        "type": kind,
        "volume": volume,
        "repeat": repeat or ("toggle" if loop else "overlap"),
        "fade": fade if fade is not None else (1500 if loop else 0),
        "_queries": [q + exclude for q in queries],
        "_dur": dur,
    }


LOOP_DUR = (25, 150)

STARTER_BOARDS = [
    {
        "id": "night-city",
        "name": "NIGHT CITY",
        "subtitle": "Cyberpunk 2077 · street & combat",
        "theme": "cyber",
        "slots": [
            _slot("Neon Rain", "loop", ["rain city street", "rain street ambience", "rain urban"], LOOP_DUR, 0.75, exclude=" -music -thunder"),
            _slot("Megacity Hum", "loop", ["city traffic night ambience", "city traffic ambience", "urban traffic"], LOOP_DUR, 0.7, exclude=" -music"),
            _slot("Club Behind Wall", "loop", ["muffled club music", "club music through wall", "muffled bass music"], LOOP_DUR, 0.65),
            _slot("Street Market", "loop", ["street market crowd", "crowd market ambience", "busy street crowd"], LOOP_DUR, 0.65, exclude=" -music"),
            _slot("NCPD Siren", "sfx", ["police siren passing", "police siren", "siren"], (3, 20), 0.75, repeat="toggle", fade=600, exclude=" -music"),
            _slot("Pistol Shot", "sfx", ["pistol gunshot", "pistol shot", "handgun shot"], (0.2, 4), 0.9, exclude=" -music"),
            _slot("Auto Burst", "sfx", ["machine gun burst", "automatic rifle burst", "submachine gun"], (0.4, 5), 0.85, exclude=" -music"),
            _slot("Shotgun", "sfx", ["shotgun blast", "shotgun shot", "shotgun"], (0.3, 4), 0.9, exclude=" -music"),
            _slot("Explosion", "sfx", ["explosion", "grenade explosion", "big explosion"], (1, 8), 0.9, exclude=" -music"),
            _slot("Monowire Lash", "sfx", ["electric whip", "laser whip", "energy whoosh", "whip crack"], (0.2, 4), 0.85, exclude=" -music"),
            _slot("Ricochet", "sfx", ["bullet ricochet", "ricochet"], (0.2, 3), 0.85, exclude=" -music"),
            _slot("Glass Shatter", "sfx", ["glass shatter", "glass break", "window smash"], (0.3, 5), 0.85, exclude=" -music"),
        ],
    },
    {
        "id": "elysium",
        "name": "ELYSIUM",
        "subtitle": "Vampire: The Masquerade · Hunger & the night",
        "theme": "gothic",
        "slots": [
            _slot("Night Rain", "loop", ["rain on pavement night", "rain ambience", "rain gentle"], LOOP_DUR, 0.7, exclude=NO_MUSIC + " -thunder"),
            _slot("Wind in Alleys", "loop", ["wind howling", "wind ambience night", "wind gusts"], LOOP_DUR, 0.65, exclude=NO_MUSIC),
            _slot("Heartbeat · Hunger", "loop", ["heartbeat loop", "heartbeat", "heart beat slow"], (4, 90), 0.8, fade=800, exclude=NO_MUSIC),
            _slot("Elysium Murmur", "loop", ["crowd murmur indoor", "room crowd murmur", "people talking indoor quiet"], LOOP_DUR, 0.55, exclude=NO_MUSIC),
            _slot("Church Bell", "sfx", ["church bell toll", "church bell single", "bell toll"], (2, 20), 0.75, repeat="toggle", fade=900, exclude=NO_MUSIC),
            _slot("The Beast Growls", "sfx", ["monster growl low", "beast growl", "growl"], (0.5, 5), 0.9, exclude=NO_MUSIC),
            _slot("Hiss", "sfx", ["creature hiss", "hiss", "cat hiss"], (0.3, 4), 0.85, exclude=NO_MUSIC),
            _slot("Whispers", "sfx", ["creepy whisper", "whispering voices", "whisper"], (1, 12), 0.8, exclude=NO_MUSIC),
            _slot("Frenzy Roar", "sfx", ["monster roar", "creature roar", "roar"], (1, 6), 0.9, exclude=NO_MUSIC),
            _slot("Feeding", "sfx", ["bite flesh", "gulp drinking", "drinking gulp"], (0.5, 6), 0.85, exclude=NO_MUSIC),
            _slot("Heavy Door", "sfx", ["old wooden door creak", "door creak", "heavy door creak"], (1, 8), 0.85, exclude=NO_MUSIC),
            _slot("Thunder", "sfx", ["thunder clap", "thunder", "thunder rumble"], (2, 15), 0.85, exclude=NO_MUSIC),
        ],
    },
]


def _slug(s):
    out = "".join(c.lower() if c.isalnum() else "_" for c in s)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def starter_file(board_id, index, slot):
    return os.path.join(SOUNDS_DIR, "starter", board_id, f"{index + 1:02d}_{_slug(slot['name'])}.ogg")


def build_starter_presets():
    """Clean preset dicts (no private _keys) pointing at expected files."""
    presets = []
    for b in STARTER_BOARDS:
        slots = []
        for i, s in enumerate(b["slots"]):
            clean = {k: v for k, v in s.items() if not k.startswith("_")}
            clean["file"] = to_rel(starter_file(b["id"], i, s))
            slots.append(clean)
        presets.append({"id": b["id"], "name": b["name"], "subtitle": b["subtitle"],
                        "theme": b["theme"], "slots": slots})
    return presets


# --------------------------------------------------------------- downloader
class DownloadError(Exception):
    pass


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


_search_endpoint = None


def _search(api_key, query, dur):
    global _search_endpoint
    params = {
        "query": query,
        "filter": f"{CC0} duration:[{dur[0]} TO {dur[1]}]",
        "fields": "id,name,username,license,duration,previews,url",
        "sort": "downloads_desc",
        "page_size": "15",
        "token": api_key,
    }
    qs = urllib.parse.urlencode(params)
    endpoints = [_search_endpoint] if _search_endpoint else ["/search/", "/search/text/"]
    last = None
    for ep in endpoints:
        try:
            data = _get_json(f"{API_ROOT}{ep}?{qs}")
            _search_endpoint = ep
            return data.get("results", [])
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise DownloadError("Freesound rejected the API key (check it in Settings).")
            if e.code == 429:
                raise DownloadError("Freesound rate limit hit — wait a minute and retry.")
            last = e
            if e.code != 404:
                break
        except urllib.error.URLError as e:
            raise DownloadError(f"Can't reach freesound.org ({e.reason}). Check the internet connection.")
    raise DownloadError(f"Search failed: {last}")


def _download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, dest)


def _credits_path():
    return os.path.join(SOUNDS_DIR, "starter", "CREDITS.json")


def _load_credits():
    try:
        with open(_credits_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_credits(credits):
    os.makedirs(os.path.dirname(_credits_path()), exist_ok=True)
    with open(_credits_path(), "w", encoding="utf-8") as f:
        json.dump(credits, f, indent=2, ensure_ascii=False)
    lines = ["Starter sounds — all CC0 (public domain) from freesound.org", ""]
    for path, c in sorted(credits.items()):
        lines.append(f"{path}\n    \"{c['name']}\" by {c['username']} — {c['url']}")
    with open(os.path.join(SOUNDS_DIR, "starter", "CREDITS.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def download_starter(api_key, reroll=False, log=print, progress=None, board_ids=None, only=None):
    """Fetch every starter sound. Skips files that already exist unless reroll.

    reroll=True picks the next-best search result instead of the current one.
    only: optional set of (board_id, slot_index) to limit the run.
    Returns (ok_count, failed_names).
    """
    api_key = (api_key or "").strip()
    if not api_key:
        raise DownloadError("No Freesound API key. Get a free one at https://freesound.org/apiv2/apply")
    credits = _load_credits()
    used_ids = {c["id"] for c in credits.values()}
    jobs = [(b, i, s) for b in STARTER_BOARDS if not board_ids or b["id"] in board_ids
            for i, s in enumerate(b["slots"])
            if only is None or (b["id"], i) in only]
    ok, failed = 0, []
    for n, (board, i, slot) in enumerate(jobs, 1):
        dest = starter_file(board["id"], i, slot)
        rel = to_rel(dest)
        label = f"{board['name']} / {i + 1:02d} {slot['name']}"
        if progress:
            progress(n - 1, len(jobs), label)
        if os.path.isfile(dest) and not reroll:
            log(f"✓ {label} — already here")
            ok += 1
            continue
        current = credits.get(rel, {}).get("id")
        chosen = None
        for q in slot["_queries"]:
            results = _search(api_key, q, slot["_dur"])
            time.sleep(0.4)  # be polite: Freesound allows 60 requests/min
            for r in results:
                url = (r.get("previews") or {}).get("preview-hq-ogg")
                if not url or r["id"] == current:
                    continue
                if r["id"] in used_ids and r["id"] != current:
                    continue
                chosen = (r, url)
                break
            if chosen:
                break
        if not chosen:
            log(f"✗ {label} — nothing suitable found")
            failed.append(label)
            continue
        r, url = chosen
        try:
            _download(url, dest)
        except Exception as e:  # network hiccup: keep going
            log(f"✗ {label} — download failed: {e}")
            failed.append(label)
            continue
        if current:
            used_ids.discard(current)
        used_ids.add(r["id"])
        credits[rel] = {"id": r["id"], "name": r.get("name", ""), "username": r.get("username", ""),
                        "url": r.get("url", f"https://freesound.org/s/{r['id']}/"),
                        "license": r.get("license", "")}
        _save_credits(credits)
        log(f"✓ {label} — \"{r.get('name', '')}\" by {r.get('username', '?')}")
        ok += 1
    if progress:
        progress(len(jobs), len(jobs), "done")
    return ok, failed
