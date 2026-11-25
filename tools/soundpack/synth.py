"""Procedurally synthesized CC0 sounds for the GM Soundboard starter boards."""
import numpy as np
import wave
from scipy.signal import butter, sosfilt

SR = 44100
rng = np.random.default_rng(7)


def t(sec):
    return np.arange(int(SR * sec)) / SR


def lp(x, f, order=4):
    return sosfilt(butter(order, f, "low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def noise(sec):
    return rng.standard_normal(int(SR * sec))


def env_exp(sec, tau, attack=0.0005):
    tt = t(sec)
    e = np.exp(-tt / tau)
    a = int(SR * attack)
    if a > 0:
        e[:a] *= np.linspace(0, 1, a)
    return e


def reverb(x, sec=1.2, mix=0.25, damp=3000):
    ir = noise(sec) * np.exp(-t(sec) / (sec / 5))
    ir = lp(ir, damp, 2)
    ir /= np.sqrt(np.sum(ir ** 2))
    wet = np.convolve(x, ir)[: len(x) + int(SR * sec)]
    out = np.zeros_like(wet)
    out[: len(x)] += x
    return out * (1 - mix) + wet * mix


def pad(x, sec):
    return np.concatenate([x, np.zeros(int(SR * sec))])


def norm(x, peak=0.89):
    m = np.max(np.abs(x)) or 1
    return x / m * peak


def fade(x, fin=0.0, fout=0.0):
    x = x.copy()
    if fin:
        n = int(SR * fin); x[:n] *= np.linspace(0, 1, n)
    if fout:
        n = int(SR * fout); x[-n:] *= np.linspace(1, 0, n)
    return x


def save(path, x, stereo=False):
    x = np.clip(x, -1, 1)
    if stereo and x.ndim == 1:
        x = np.stack([x, x], 1)
    data = (x * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2 if data.ndim == 2 else 1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


# ---------------------------------------------------------------- weapons
def gunshot(body=1.0, tail=0.6, low=90):
    d = 0.08 + tail
    crack = hp(noise(d), 900) * env_exp(d, 0.012)
    blast = bp(noise(d), 120, 2500) * env_exp(d, 0.045 * body)
    tt = t(d)
    thump = np.sin(2 * np.pi * (low * np.exp(-tt * 9)) * tt) * env_exp(d, 0.07 * body)
    x = crack * 0.7 + blast * 0.9 + thump * 1.2
    x = reverb(fade(x, fout=0.05), sec=tail + 0.6, mix=0.3, damp=2500)
    return norm(fade(x, fout=0.15))


def pistol():
    return gunshot(1.0, 0.5, 110)


def shotgun():
    return gunshot(2.2, 1.0, 70)


def auto_burst():
    shots, gap = 9, 0.085
    one = gunshot(0.8, 0.15, 120)
    total = np.zeros(int(SR * (shots * gap + 1.4)))
    for i in range(shots):
        s = max(0, int(SR * (i * gap + rng.uniform(-0.004, 0.004))))
        g = rng.uniform(0.8, 1.0)
        seg = one[: len(total) - s]
        total[s:s + len(seg)] += seg * g
    return norm(fade(reverb(total, 1.2, 0.2), fout=0.4))


def explosion():
    d = 4.5
    tt = t(d)
    crack = hp(noise(d), 600) * env_exp(d, 0.03)
    body = lp(noise(d), 900) * env_exp(d, 0.6, attack=0.01)
    rumble = lp(noise(d), 160, 2) * env_exp(d, 1.4, attack=0.05) * 3
    sub = np.sin(2 * np.pi * (55 * np.exp(-tt * 1.2) + 22) * tt) * env_exp(d, 0.9, attack=0.005)
    debris = np.zeros(int(SR * d))
    for _ in range(40):
        s = int(SR * rng.uniform(0.3, 3.2))
        n = int(SR * rng.uniform(0.01, 0.05))
        debris[s:s + n] += hp(rng.standard_normal(n), 1500) * np.exp(-np.arange(n) / (n / 4)) * rng.uniform(0.05, 0.2) * np.exp(-s / SR)
    x = crack * 0.8 + body * 1.2 + rumble + sub * 1.3 + debris
    return norm(fade(reverb(x, 1.5, 0.25, 1500), fout=0.8))


def ricochet():
    d = 0.9
    tt = t(d)
    f = 3200 * np.exp(-tt * 1.6) + 900
    ph = 2 * np.pi * np.cumsum(f * (1 + 0.01 * np.sin(2 * np.pi * 37 * tt))) / SR
    whine = np.sin(ph) * env_exp(d, 0.28, attack=0.003)
    hit = hp(noise(d), 2000) * env_exp(d, 0.006)
    return norm(fade(reverb(fade(whine * 0.6 + hit, fout=0.25), 0.8, 0.3), fout=0.1))


def siren():
    d = 9.0
    tt = t(d)
    f = 950 + 380 * np.sin(2 * np.pi * tt / 2.2 - np.pi / 2)  # wail
    ph = 2 * np.pi * np.cumsum(f) / SR
    saw = sum(np.sin(k * ph) / k for k in range(1, 9))
    x = lp(saw, 3200, 2)
    # passing car: swell in, out
    amp = np.exp(-((tt - 4.5) ** 2) / (2 * 2.2 ** 2))
    x = x * (0.25 + 0.75 * amp)
    return norm(fade(reverb(fade(x, 0.3, 1.5), 1.0, 0.25), fout=0.3), 0.8)


def monowire(whoosh):
    d = 0.9
    tt = t(d)
    buzz = sum(np.sin(2 * np.pi * 120 * k * tt) / k for k in range(1, 12))
    crackle = np.zeros(int(SR * d))
    for _ in range(90):
        s = int(SR * rng.uniform(0, 0.5))
        n = int(SR * 0.002)
        crackle[s:s + n] += rng.uniform(-1, 1) * np.hanning(n)
    zap = (buzz * 0.2 + hp(crackle, 2500) * 1.5) * env_exp(d, 0.16, attack=0.02)
    w = np.zeros(int(SR * d))
    w[: len(whoosh)] = whoosh[: int(SR * d)]
    return norm(fade(w * 1.2 + zap, fout=0.15))


# ---------------------------------------------------------------- VtM
def heartbeat(bpm=72, beats=8):
    period = 60 / bpm
    d = period * beats
    x = np.zeros(int(SR * d))

    def thump(f, dur, g):
        tt = t(dur)
        s = np.sin(2 * np.pi * f * (1 - 0.4 * tt / dur) * tt) * np.exp(-tt / (dur / 4))
        s[: int(SR * 0.004)] *= np.linspace(0, 1, int(SR * 0.004))
        s += lp(noise(dur), 300) * np.exp(-tt / 0.02) * 0.3
        return s * g

    lub, dub = thump(52, 0.16, 1.0), thump(44, 0.13, 0.7)
    for b in range(beats):
        s = int(SR * b * period)
        x[s:s + len(lub)] += lub
        s2 = s + int(SR * 0.28)
        x[s2:s2 + len(dub)] += dub[: len(x) - s2]
    x = lp(x, 400, 2)
    return norm(x, 0.9)  # exact length -> seamless loop


def church_bell(tolls=3, gap=3.2):
    f0 = 196.0
    partials = [(0.5, 0.35, 9), (1.0, 0.6, 6), (1.19, 0.45, 4.5), (1.5, 0.3, 3.5),
                (2.0, 0.55, 3), (2.51, 0.25, 2.2), (3.0, 0.2, 1.8), (4.07, 0.15, 1.2), (5.2, 0.08, 0.8)]
    d = 9
    tt = t(d)
    one = np.zeros(len(tt))
    for r, a, dec in partials:
        detune = 1 + rng.uniform(-0.002, 0.002)
        beat = 1 + 0.15 * np.sin(2 * np.pi * rng.uniform(0.5, 1.5) * tt)
        one += a * np.sin(2 * np.pi * f0 * r * detune * tt) * np.exp(-tt / dec) * beat
    strike = hp(noise(d), 1500) * np.exp(-tt / 0.01) * 0.3
    one = fade(one + strike, fout=2.0)
    one[: int(SR * 0.003)] *= np.linspace(0, 1, int(SR * 0.003))
    total = np.zeros(int(SR * (gap * (tolls - 1) + d)))
    for i in range(tolls):
        s = int(SR * gap * i)
        total[s:s + len(one)] += one
    return norm(fade(reverb(total, 3.0, 0.35, 2500), fout=1.5), 0.85)


def hiss():
    d = 1.6
    tt = t(d)
    e = np.minimum(tt / 0.12, 1) * np.exp(-np.maximum(tt - 0.7, 0) / 0.25)
    n = bp(noise(d), 2500, 9000, 3) * e * (1 + 0.25 * np.sin(2 * np.pi * 9 * tt))
    breath = bp(noise(d), 600, 1800) * e * 0.25
    return norm(fade(reverb(fade(n + breath, fout=0.3), 0.6, 0.15), fout=0.1), 0.8)


# ---------------------------------------------------------------- club
def club_loop(bpm=124, bars=8):
    beat = 60 / bpm
    d = beat * 4 * bars
    x = np.zeros(int(SR * d))
    kd = 0.35
    kt = t(kd)
    kick = np.sin(2 * np.pi * (50 + 120 * np.exp(-kt * 35)) * kt) * np.exp(-kt / 0.12)
    for b in range(4 * bars):
        s = int(SR * b * beat)
        x[s:s + len(kick)] += kick[: len(x) - s]
    # offbeat bass notes (A minor-ish riff)
    notes = [55, 55, 65.4, 49]
    for b in range(4 * bars):
        f = notes[(b // 4) % 4]
        s = int(SR * (b * beat + beat / 2))
        nd = beat * 0.45
        nt = t(nd)
        saw = sum(np.sin(2 * np.pi * f * k * nt) / k for k in range(1, 7))
        x[s:s + len(nt)] += saw[: len(x) - s] * np.exp(-nt / 0.15) * 0.5
    # hats, heavily muffled anyway
    for b in range(8 * bars):
        s = int(SR * (b * beat / 2 + beat / 4))
        n = int(SR * 0.03)
        x[s:s + n] += hp(rng.standard_normal(n), 6000) * np.exp(-np.arange(n) / 300) * 0.15
    wall = lp(x, 220, 4)  # through the wall
    rattle = bp(noise(d), 300, 900) * 0.01
    return norm(wall + rattle, 0.45)
