import os, subprocess, sys, wave
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import synth

# Source packs (all CC0), cloned next to each other in SRC:
#   git clone --depth 1 https://github.com/facebookincubator/meta-open-sound
#   git clone --depth 1 https://github.com/localhostnick/open-sleep-sounds
#   git clone --depth 1 https://github.com/wyzowl/sfx-kit
# Needs numpy, scipy and ffmpeg (libvorbis).  Usage: python build_pack.py [SRC]
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "src")
META = f"{SRC}/meta-open-sound/corpora/oculus-audio-pack/ogg"
SLEEP = f"{SRC}/open-sleep-sounds/sounds"
KIT = f"{SRC}/sfx-kit/sounds"
OUT = os.path.join(HERE, "..", "..", "web", "public", "sounds", "starter")
TMP = os.path.join(HERE, "tmp")
os.makedirs(TMP, exist_ok=True)

# (board, file stem, source, kind)  kind: loop -> loudness for ambience, sfx -> punchier
PLAN = [
    ("night-city", "01_neon_rain", ("file", f"{META}/RAIN_CityRain_LOOP_01.ogg"), "loop"),
    ("night-city", "02_megacity_hum", ("file", f"{META}/AMBUrbn_CityAmerican_LOOP_01.ogg"), "loop"),
    ("night-city", "03_club_behind_wall", ("synth", "club_loop"), "loop"),
    ("night-city", "04_street_market", ("file", f"{META}/AMBUrbn_CityEuroDaytime_LOOP_01.ogg"), "loop"),
    ("night-city", "05_ncpd_siren", ("synth", "siren"), "sfx"),
    ("night-city", "06_pistol_shot", ("synth", "pistol"), "sfx"),
    ("night-city", "07_auto_burst", ("synth", "auto_burst"), "sfx"),
    ("night-city", "08_shotgun", ("synth", "shotgun"), "sfx"),
    ("night-city", "09_explosion", ("synth", "explosion"), "sfx"),
    ("night-city", "10_monowire_lash", ("synth", "monowire"), "sfx"),
    ("night-city", "11_ricochet", ("synth", "ricochet"), "sfx"),
    ("night-city", "12_glass_shatter", ("file", f"{META}/GLASBrk_WindowPaneSmallBreak_OS_01.ogg"), "sfx"),
    ("elysium", "01_night_rain", ("file", f"{SLEEP}/01-rain-and-storms/rain-on-window.mp3"), "loop"),
    ("elysium", "02_wind_in_alleys", ("file", f"{SLEEP}/05-wind-and-breeze/howling-winter-wind.mp3"), "loop"),
    ("elysium", "03_heartbeat_hunger", ("synth", "heartbeat"), "loop"),
    ("elysium", "04_elysium_murmur", ("file", f"{META}/CRWDConv_Restaurant_LOOP_01.ogg"), "loop"),
    ("elysium", "05_church_bell", ("synth", "church_bell"), "sfx"),
    ("elysium", "06_the_beast_growls", ("pitch", f"{META}/CREAMnstr_CreatureCreepy_OS_01.ogg", 0.82), "sfx"),
    ("elysium", "07_hiss", ("synth", "hiss"), "sfx"),
    ("elysium", "08_whispers", ("file", f"{META}/VOXWhsp_WhispersCreepyReverb_OS_01.ogg"), "sfx"),
    ("elysium", "09_frenzy_roar", ("pitch", f"{META}/CREAMnstr_CreatureCreepyReverb_OS_02.ogg", 0.75), "sfx"),
    ("elysium", "10_feeding", ("file", f"{META}/GORESqsh_BloodSquishSlimy_OS_01.ogg"), "sfx"),
    ("elysium", "11_heavy_door", ("file", f"{META}/WOODFric_CreaksCreepyReverb_OS_01.ogg"), "sfx"),
    ("elysium", "12_thunder", ("file", f"{KIT}/cinematic-hits/cinematic-thunder-massive.wav"), "sfx"),
]

CREDITS = {
    "file:" + META: "Meta Open Sound — Oculus Audio Pack (CC0) — github.com/facebookincubator/meta-open-sound",
    "file:" + SLEEP: "Open Sleep Sounds (CC0) — github.com/localhostnick/open-sleep-sounds",
    "file:" + KIT: "SFX Kit by Wyzowl (CC0) — github.com/wyzowl/sfx-kit",
}


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def read_wav(path):
    with wave.open(path) as w:
        d = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        if w.getnchannels() == 2:
            d = d.reshape(-1, 2).mean(1)
    return d


credits = []
for board, stem, src, kind in PLAN:
    os.makedirs(f"{OUT}/{board}", exist_ok=True)
    dest = f"{OUT}/{board}/{stem}.ogg"
    if src[0] == "synth":
        if src[1] == "monowire":
            ff("-i", f"{KIT}/whooshes/whoosh-fast-hard.wav", "-ac", "1", "-ar", "44100", f"{TMP}/w.wav")
            x = synth.monowire(read_wav(f"{TMP}/w.wav"))
        else:
            x = getattr(synth, src[1])()
        synth.save(f"{TMP}/{stem}.wav", x)
        inp = f"{TMP}/{stem}.wav"
        credits.append((f"{board}/{stem}.ogg", "synthesized for GM Soundboard (CC0)"))
        filt = []
    else:
        inp = src[1]
        filt = [f"asetrate=44100*{src[2]},aresample=44100"] if src[0] == "pitch" else []
        origin = next(v for k, v in CREDITS.items() if inp.startswith(k[5:]))
        credits.append((f"{board}/{stem}.ogg", f"{os.path.basename(inp)} — {origin}"))
    if src[0] != "synth":
        # loudness-match library files; loops sit lower than one-shots
        target = "-23" if kind == "loop" else "-16"
        filt.append(f"loudnorm=I={target}:TP=-1.5:LRA=11")
    args = ["-i", inp]
    if filt:
        args += ["-af", ",".join(filt)]
    args += ["-ar", "44100", "-c:a", "libvorbis", "-q:a", "5", dest]
    ff(*args)
    print("ok", board, stem)

with open(f"{OUT}/CREDITS.txt", "w") as f:
    f.write("GM Soundboard starter sounds — all CC0 / public domain\n\n")
    for p, c in credits:
        f.write(f"{p}\n    {c}\n")
print(open(f"{OUT}/CREDITS.txt").read())
