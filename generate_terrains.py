#!/usr/bin/env python3
"""
Generate built-in terrain assets as .npy files in assets/terrains/.

Run once after checkout to create the sample terrains:

    python generate_terrains.py

Each terrain is a (240, 320) float32 array normalised to 0–1.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np

TERRAIN_DIR = pathlib.Path(__file__).parent / "assets" / "terrains"
HEIGHT, WIDTH = 240, 320


def _normalize(data: np.ndarray) -> np.ndarray:
    lo, hi = float(data.min()), float(data.max())
    if hi - lo < 1e-8:
        return np.full_like(data, 0.5)
    return ((data - lo) / (hi - lo)).astype(np.float32)


def _perlin_like(h: int, w: int, octaves: int = 5, seed: int = 42) -> np.ndarray:
    """Multi-octave value noise (cheap Perlin substitute via scipy)."""
    from scipy.ndimage import gaussian_filter, zoom

    rng = np.random.default_rng(seed)
    result = np.zeros((h, w), dtype=np.float32)
    amplitude = 1.0
    for i in range(octaves):
        freq = 2 ** i
        small_h = max(2, h // (16 // min(freq, 16)))
        small_w = max(2, w // (16 // min(freq, 16)))
        noise = rng.standard_normal((small_h, small_w)).astype(np.float32)
        upscaled = zoom(noise, (h / small_h, w / small_w), order=1)
        sigma = max(1.0, 40.0 / freq)
        upscaled = gaussian_filter(upscaled, sigma=sigma)
        result += amplitude * upscaled
        amplitude *= 0.5
    return _normalize(result)


def generate_canyon(h: int = HEIGHT, w: int = WIDTH) -> np.ndarray:
    from scipy.ndimage import gaussian_filter

    base = _perlin_like(h, w, octaves=5, seed=101)
    yy, xx = np.mgrid[0:h, 0:w]
    centre_x = w / 2 + 30 * np.sin(yy * 2 * np.pi / h * 2)
    canyon_dist = np.abs(xx - centre_x)
    canyon_mask = np.exp(-(canyon_dist ** 2) / (2 * 25 ** 2))
    carved = base * 0.7 + 0.3 - canyon_mask * 0.6
    side = _perlin_like(h, w, octaves=3, seed=202) * 0.15
    result = np.clip(carved + side, 0, 1)
    return _normalize(gaussian_filter(result, sigma=1.5))


def generate_volcano(h: int = HEIGHT, w: int = WIDTH) -> np.ndarray:
    from scipy.ndimage import gaussian_filter

    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = h / 2, w / 2
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    max_r = min(h, w) * 0.45
    cone = np.clip(1.0 - dist / max_r, 0, 1) ** 1.3
    caldera_r = max_r * 0.18
    caldera = np.clip(1.0 - dist / caldera_r, 0, 1) ** 2
    volcano = cone - caldera * 0.35
    noise = _perlin_like(h, w, octaves=4, seed=303) * 0.12
    return _normalize(gaussian_filter(volcano + noise, sigma=2.0))


def generate_valley(h: int = HEIGHT, w: int = WIDTH) -> np.ndarray:
    from scipy.ndimage import gaussian_filter

    yy, xx = np.mgrid[0:h, 0:w]
    ridge_l = np.exp(-((xx - w * 0.25) ** 2) / (2 * (w * 0.10) ** 2))
    ridge_r = np.exp(-((xx - w * 0.75) ** 2) / (2 * (w * 0.10) ** 2))
    ridges = ridge_l + ridge_r
    slope = 0.15 * (yy / h)
    noise = _perlin_like(h, w, octaves=5, seed=404) * 0.25
    return _normalize(gaussian_filter(ridges + slope + noise, sigma=2.5))


def generate_islands(h: int = HEIGHT, w: int = WIDTH) -> np.ndarray:
    from scipy.ndimage import gaussian_filter

    base = _perlin_like(h, w, octaves=5, seed=505)
    water_level = 0.45
    islands = np.where(base > water_level, base, water_level)
    yy, xx = np.mgrid[0:h, 0:w]
    edge_fade = np.ones((h, w), dtype=np.float32)
    margin = 30
    for arr, size in [(yy, h), (xx, w)]:
        edge_fade *= np.clip(arr / margin, 0, 1) * np.clip((size - 1 - arr) / margin, 0, 1)
    blended = islands * edge_fade + water_level * (1 - edge_fade)
    return _normalize(gaussian_filter(blended, sigma=1.5))


def generate_flat(h: int = HEIGHT, w: int = WIDTH) -> np.ndarray:
    return np.full((h, w), 0.5, dtype=np.float32)


GENERATORS = {
    "canyon": generate_canyon,
    "volcano": generate_volcano,
    "valley": generate_valley,
    "islands": generate_islands,
    "flat": generate_flat,
}


def main() -> int:
    TERRAIN_DIR.mkdir(parents=True, exist_ok=True)
    (TERRAIN_DIR / "saved").mkdir(exist_ok=True)

    for name, gen in GENERATORS.items():
        dest = TERRAIN_DIR / f"{name}.npy"
        print(f"Generating {name:>8s} → {dest} ... ", end="", flush=True)
        terrain = gen()
        np.save(dest, terrain)
        print(f"OK  shape={terrain.shape}  range=[{terrain.min():.3f}, {terrain.max():.3f}]")

    print("\nDone. All terrains saved to", TERRAIN_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
