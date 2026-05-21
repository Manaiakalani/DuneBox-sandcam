"""
Generate placeholder WAV sound effects for DuneBox-sandcam.

Each sound is synthesised from numpy arrays and written with scipy.io.wavfile.
Replace these with real recordings later — they exist so the SoundManager
has something to load on first run.
"""

from __future__ import annotations

import pathlib

import numpy as np
from scipy.io import wavfile

SAMPLE_RATE = 44100
SOUND_DIR = pathlib.Path(__file__).with_name("assets") / "sounds"


def _fade(samples: np.ndarray, fade_in: int = 0, fade_out: int = 0) -> np.ndarray:
    if fade_in > 0:
        samples[:fade_in] *= np.linspace(0, 1, fade_in)
    if fade_out > 0:
        samples[-fade_out:] *= np.linspace(1, 0, fade_out)
    return samples


def _save(name: str, samples: np.ndarray) -> None:
    peak = np.max(np.abs(samples))
    if peak > 0:
        samples = samples / peak * 0.85
    pcm = (samples * 32767).astype(np.int16)
    path = SOUND_DIR / name
    wavfile.write(str(path), SAMPLE_RATE, pcm)
    print(f"  ✓ {path.name}  ({len(pcm) / SAMPLE_RATE:.2f}s)")


def water_ambient() -> None:
    """Low-frequency rumble with slow modulation — loopable ocean drone."""
    duration = 4.0
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    noise = np.random.default_rng(42).normal(0, 1, n)
    # Low-pass via cumulative sum (simple integrator)
    lp = np.cumsum(noise) / 80
    lp -= np.linspace(lp[0], lp[-1], n)  # remove DC drift
    # Modulate with a slow sine
    mod = 0.5 + 0.5 * np.sin(2 * np.pi * 0.15 * t)
    samples = lp * mod
    _fade(samples, int(0.3 * SAMPLE_RATE), int(0.3 * SAMPLE_RATE))
    _save("water_ambient.wav", samples)


def wind_ambient() -> None:
    """Filtered white noise with gentle amplitude swell."""
    duration = 4.0
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 1, n)
    # Simple moving-average low-pass
    kernel_size = 120
    kernel = np.ones(kernel_size) / kernel_size
    filtered = np.convolve(noise, kernel, mode="same")
    # Slow volume swell
    env = 0.6 + 0.4 * np.sin(2 * np.pi * 0.25 * t)
    samples = filtered * env
    _fade(samples, int(0.4 * SAMPLE_RATE), int(0.4 * SAMPLE_RATE))
    _save("wind_ambient.wav", samples)


def creature_spawn() -> None:
    """Short rising chirp (~0.25 s)."""
    duration = 0.25
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    freq = np.linspace(400, 1200, n)
    samples = np.sin(2 * np.pi * np.cumsum(freq) / SAMPLE_RATE) * np.linspace(1, 0, n)
    _save("creature_spawn.wav", samples)


def creature_despawn() -> None:
    """Short falling tone (~0.3 s)."""
    duration = 0.3
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    freq = np.linspace(900, 300, n)
    samples = np.sin(2 * np.pi * np.cumsum(freq) / SAMPLE_RATE) * np.linspace(0.8, 0, n)
    _save("creature_despawn.wav", samples)


def marker_detected() -> None:
    """Ascending two-note chime."""
    note_dur = 0.15
    gap = 0.05
    n1 = int(SAMPLE_RATE * note_dur)
    ng = int(SAMPLE_RATE * gap)
    n2 = int(SAMPLE_RATE * note_dur)
    t1 = np.linspace(0, note_dur, n1, endpoint=False)
    t2 = np.linspace(0, note_dur, n2, endpoint=False)
    env1 = np.exp(-t1 * 12)
    env2 = np.exp(-t2 * 10)
    s1 = np.sin(2 * np.pi * 523.25 * t1) * env1  # C5
    s2 = np.sin(2 * np.pi * 659.25 * t2) * env2  # E5
    samples = np.concatenate([s1, np.zeros(ng), s2])
    _save("marker_detected.wav", samples)


def marker_lost() -> None:
    """Descending two-note chime."""
    note_dur = 0.15
    gap = 0.05
    n1 = int(SAMPLE_RATE * note_dur)
    ng = int(SAMPLE_RATE * gap)
    n2 = int(SAMPLE_RATE * (note_dur + 0.1))
    t1 = np.linspace(0, note_dur, n1, endpoint=False)
    t2 = np.linspace(0, note_dur + 0.1, n2, endpoint=False)
    env1 = np.exp(-t1 * 12)
    env2 = np.exp(-t2 * 8)
    s1 = np.sin(2 * np.pi * 659.25 * t1) * env1  # E5
    s2 = np.sin(2 * np.pi * 440.00 * t2) * env2  # A4
    samples = np.concatenate([s1, np.zeros(ng), s2])
    _save("marker_lost.wav", samples)


def crickets_ambient() -> None:
    """Loopable cricket chirp texture — rapid high-frequency pulses."""
    duration = 4.0
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    rng = np.random.default_rng(99)
    # Base chirp: amplitude-modulated high-frequency sine
    carrier = np.sin(2 * np.pi * 4800 * t)
    # Pulse envelope at ~12 Hz
    pulse = np.clip(np.sin(2 * np.pi * 12 * t), 0, 1) ** 4
    # Slow volume swell
    swell = 0.5 + 0.5 * np.sin(2 * np.pi * 0.3 * t)
    samples = carrier * pulse * swell * 0.4
    # Add a second chirper offset
    carrier2 = np.sin(2 * np.pi * 5200 * t)
    pulse2 = np.clip(np.sin(2 * np.pi * 14 * t + 1.2), 0, 1) ** 4
    swell2 = 0.5 + 0.5 * np.sin(2 * np.pi * 0.22 * t + 0.8)
    samples += carrier2 * pulse2 * swell2 * 0.3
    _fade(samples, int(0.3 * SAMPLE_RATE), int(0.3 * SAMPLE_RATE))
    _save("crickets_ambient.wav", samples)


def owl_ambient() -> None:
    """Loopable low hoot pattern — two-note owl call repeating."""
    duration = 4.0
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    # Two hoots per cycle
    hoot_freq = 280
    hoot_env = np.zeros(n)
    for offset in (0.5, 1.0, 2.5, 3.0):
        centre = int(offset * SAMPLE_RATE)
        width = int(0.15 * SAMPLE_RATE)
        start = max(0, centre - width)
        end = min(n, centre + width)
        local_t = np.linspace(0, 1, end - start)
        hoot_env[start:end] += np.sin(np.pi * local_t) ** 2
    samples = np.sin(2 * np.pi * hoot_freq * t) * hoot_env * 0.6
    # Add subtle harmonic
    samples += np.sin(2 * np.pi * hoot_freq * 2 * t) * hoot_env * 0.15
    _fade(samples, int(0.2 * SAMPLE_RATE), int(0.2 * SAMPLE_RATE))
    _save("owl_ambient.wav", samples)


def dawn_birds() -> None:
    """Short bird chirp sequence (~0.8 s) — one-shot dawn event."""
    duration = 0.8
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    samples = np.zeros(n)
    # Three quick chirps at rising pitches
    for i, (start_s, freq) in enumerate([(0.0, 1800), (0.25, 2200), (0.5, 2600)]):
        chirp_len = int(0.12 * SAMPLE_RATE)
        start_idx = int(start_s * SAMPLE_RATE)
        end_idx = min(n, start_idx + chirp_len)
        chirp_t = np.linspace(0, 0.12, end_idx - start_idx, endpoint=False)
        env = np.exp(-chirp_t * 25)
        samples[start_idx:end_idx] += np.sin(2 * np.pi * freq * chirp_t) * env * 0.7
    _save("dawn_birds.wav", samples)


def main() -> None:
    SOUND_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating placeholder sounds...")
    water_ambient()
    wind_ambient()
    creature_spawn()
    creature_despawn()
    marker_detected()
    marker_lost()
    crickets_ambient()
    owl_ambient()
    dawn_birds()
    print("Done.")


if __name__ == "__main__":
    main()
