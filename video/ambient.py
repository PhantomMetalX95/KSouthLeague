"""
Soft ambient background music, made from scratch (so there is nothing to license), plus a mixer that
lowers the music while the voice is speaking.

    from ambient import ambient, mix_under
    music = ambient(seconds=120, sr=24000)
    final = mix_under(voice_array, music, sr=24000)
"""
import numpy as np

CHORDS = [(57, 60, 64, 67), (53, 57, 60, 64), (48, 55, 60, 64), (55, 59, 62, 66)]  # Am7, Fmaj7, C(add9-ish), G6: slow and warm
PENTA = [69, 72, 74, 76, 79, 81]  # A minor pentatonic, for the soft bell notes


def _hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _movavg(x, k):
    k = max(1, int(k))
    cs = np.cumsum(np.concatenate([np.zeros(k), x]))
    return (cs[k:] - cs[:-k]) / k


def _reverb(x, sr, seconds=2.8, wet=0.45, seed=3):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    ir = rng.standard_normal(len(t)) * np.exp(-t * 2.3)
    ir = _movavg(ir, 6)  # take the harshness off
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    n = len(x) + len(ir)
    size = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
    return (1 - wet) * x + wet * y


def ambient(seconds, sr=24000, seed=7, chord_seconds=8.0):
    """A slow pad that changes chord every 8 seconds, a soft low note, and the odd bell. Returns floats in about -0.5..0.5."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)
    for ci in range(int(np.ceil(seconds / chord_seconds)) + 1):
        chord, start, dur = CHORDS[ci % len(CHORDS)], ci * chord_seconds - 3.0, chord_seconds + 6.0
        i0, i1 = max(0, int(start * sr)), min(n, int((start + dur) * sr))
        if i1 <= i0:
            continue
        tt = t[i0:i1] - start
        env = np.sin(np.pi * np.clip(tt / dur, 0, 1)) ** 2  # fades in and out, overlapping the next chord
        sig = np.zeros(i1 - i0)
        for m in chord:
            f = _hz(m)
            for det in (-1.0, 0.0, 1.0):  # three slightly detuned copies make it shimmer
                ph = rng.uniform(0, 2 * np.pi)
                ff = f * (1 + det * 0.0035)
                sig += np.sin(2 * np.pi * ff * tt + ph) + 0.30 * np.sin(2 * np.pi * 2 * ff * tt + ph) + 0.10 * np.sin(2 * np.pi * 3 * ff * tt + ph)
        sig *= 1 + 0.12 * np.sin(2 * np.pi * (0.06 + 0.015 * ci) * tt)  # slow breathing
        out[i0:i1] += env * sig * 0.05
        out[i0:i1] += env * 0.10 * np.sin(2 * np.pi * _hz(chord[0] - 12) * tt)
    cur = 2.5
    while cur < seconds - 3:  # soft bell notes now and then
        f, idx = _hz(int(rng.choice(PENTA))), int(cur * sr)
        seg = min(int(3.5 * sr), n - idx)
        tt = np.arange(seg) / sr
        ping = (np.sin(2 * np.pi * f * tt) * np.exp(-tt * 1.3) + 0.3 * np.sin(2 * np.pi * 2.01 * f * tt) * np.exp(-tt * 2.4)) * (1 - np.exp(-tt * 90))
        out[idx:idx + seg] += 0.045 * ping
        cur += rng.uniform(3.0, 7.0)
    out += 0.004 * _movavg(rng.standard_normal(n), 160)  # a touch of air
    out = _reverb(out, sr)
    out *= 0.5 / (np.abs(out).max() + 1e-9)
    f = int(2.5 * sr)
    out[:f] *= np.linspace(0, 1, f) ** 2
    out[-f:] *= np.linspace(1, 0, f) ** 2
    return out.astype(np.float32)


def loop_to(m, n, sr, fade=0.6):
    """Repeat a music clip to n samples, crossfading the joins."""
    if len(m) >= n:
        return m[:n].astype(np.float32)
    f = int(fade * sr)
    out = m.astype(np.float32).copy()
    while len(out) < n:
        out[-f:] = out[-f:] * np.linspace(1, 0, f) + m[:f] * np.linspace(0, 1, f)
        out = np.concatenate([out, m[f:]])
    return out[:n].astype(np.float32)


def mix_under(voice, music, sr, music_db=-20.0, duck_db=-10.0, tail=3.0):
    """Mix music under a voice track. music_db: loudness of the music relative to the voice. The music then dips a further
    duck_db while someone is speaking and swells back in the gaps. It fades out over the last `tail` seconds."""
    n = len(voice)
    m = loop_to(music, n, sr)
    active = np.abs(voice) > 0.02
    vr = float(np.sqrt(np.mean(voice[active] ** 2))) if active.any() else 0.1
    m = m * (vr * 10 ** (music_db / 20) / (float(np.sqrt(np.mean(m ** 2))) + 1e-9))
    env = _movavg(np.abs(voice), int(0.30 * sr))
    env = np.clip(env / (vr * 0.6), 0, 1)
    env = _movavg(env, int(0.40 * sr))  # smooth, so the music glides rather than pumps
    m = m * (1 - (1 - 10 ** (duck_db / 20)) * env)
    f = int(tail * sr)
    if 0 < f < n:
        m[-f:] *= np.linspace(1, 0, f)
    return np.clip(voice + m, -1.0, 1.0).astype(np.float32)
