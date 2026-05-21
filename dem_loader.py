"""
Load and save Digital Elevation Models (DEMs) for terrain reference overlays.

Supports:
- GeoTIFF (.tif, .tiff) via rasterio (optional dependency)
- Raw heightmap images (.png, .jpg) via PIL/pygame
- NumPy arrays (.npy)
- Built-in sample terrains (generated procedurally)
"""

from __future__ import annotations

import logging
import pathlib
from datetime import datetime

import numpy as np

logger = logging.getLogger(__name__)

_TERRAIN_DIR = pathlib.Path(__file__).parent / "assets" / "terrains"
_SAVED_DIR = _TERRAIN_DIR / "saved"

BUILTIN_TERRAINS = ["canyon", "volcano", "valley", "islands", "flat"]


def _try_load_geotiff(path: pathlib.Path) -> np.ndarray | None:
    """Attempt to load a GeoTIFF via rasterio, falling back to PIL."""
    try:
        import rasterio  # type: ignore[import-untyped]

        with rasterio.open(path) as dataset:
            data = dataset.read(1).astype(np.float32)
            nodata = dataset.nodata
            if nodata is not None:
                mask = data == nodata
                valid = data[~mask]
                if valid.size > 0:
                    data[mask] = valid.min()
            return data
    except ImportError:
        logger.info(
            "rasterio not installed — falling back to image loader for %s. "
            "Install with: pip install sandcam[geo]",
            path.name,
        )
        return None


def _load_image(path: pathlib.Path) -> np.ndarray:
    """Load an image file as a greyscale float32 array via pygame."""
    import pygame

    surface = pygame.image.load(str(path))
    arr = pygame.surfarray.array3d(surface)  # (W, H, 3)
    grey = arr.mean(axis=2).astype(np.float32).T  # (H, W)
    return grey


def _normalize(data: np.ndarray) -> np.ndarray:
    """Normalize array to 0.0–1.0 float32, handling constant surfaces."""
    data = data.astype(np.float32)
    lo, hi = float(data.min()), float(data.max())
    if hi - lo < 1e-8:
        return np.full_like(data, 0.5)
    return (data - lo) / (hi - lo)


def load_dem(path: str) -> np.ndarray:
    """
    Load a DEM from *path* and return a normalised float32 height map (0–1).

    Supported formats:
    - .npy          — raw NumPy array
    - .tif / .tiff  — GeoTIFF (rasterio preferred, PIL fallback)
    - .png / .jpg   — greyscale heightmap image
    """
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"DEM file not found: {path}")

    suffix = p.suffix.lower()

    if suffix == ".npy":
        data = np.load(p).astype(np.float32)
    elif suffix in (".tif", ".tiff"):
        data = _try_load_geotiff(p)
        if data is None:
            data = _load_image(p)
    elif suffix in (".png", ".jpg", ".jpeg", ".bmp"):
        data = _load_image(p)
    else:
        raise ValueError(f"Unsupported DEM format: {suffix}")

    # Replace any NaN/inf with minimum valid value
    finite_mask = np.isfinite(data)
    if not finite_mask.all():
        valid_min = float(data[finite_mask].min()) if finite_mask.any() else 0.0
        data[~finite_mask] = valid_min

    return _normalize(data)


def save_dem(height_data: np.ndarray, path: str) -> pathlib.Path:
    """Save a height map to *path* (.npy format). Returns the resolved path."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.save(p, height_data.astype(np.float32))
    logger.info("Saved terrain to %s", p)
    return p


def save_terrain_snapshot(height_data: np.ndarray) -> pathlib.Path:
    """Save the current terrain to assets/terrains/saved/ with a timestamp name."""
    _SAVED_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = _SAVED_DIR / f"terrain_{stamp}.npy"
    return save_dem(height_data, str(dest))


def list_builtin_terrains() -> list[str]:
    """Return the names of all available built-in terrains."""
    available: list[str] = []
    for name in BUILTIN_TERRAINS:
        npy = _TERRAIN_DIR / f"{name}.npy"
        if npy.exists():
            available.append(name)
    return available


def load_builtin_terrain(name: str, target_shape: tuple[int, int] | None = None) -> np.ndarray:
    """
    Load a built-in terrain by name.

    If *target_shape* ``(H, W)`` is given the terrain is resized to match.
    Falls back to procedural generation when the .npy asset is missing.
    """
    if name not in BUILTIN_TERRAINS:
        raise ValueError(
            f"Unknown terrain '{name}'. Choose from: {', '.join(BUILTIN_TERRAINS)}"
        )

    npy = _TERRAIN_DIR / f"{name}.npy"
    if npy.exists():
        data = _normalize(np.load(npy).astype(np.float32))
    else:
        logger.info("Terrain asset %s not found — generating procedurally", npy.name)
        data = _generate_terrain(name, 240, 320)

    if target_shape is not None and data.shape != target_shape:
        from scipy.ndimage import zoom

        factors = (target_shape[0] / data.shape[0], target_shape[1] / data.shape[1])
        data = zoom(data, factors, order=1)
        data = _normalize(data)

    return data


# ── procedural terrain generators ─────────────────────────────────────────────

def _perlin_like(h: int, w: int, octaves: int = 5, seed: int = 42) -> np.ndarray:
    """Multi-octave value noise (cheap Perlin substitute using scipy)."""
    from scipy.ndimage import gaussian_filter

    rng = np.random.default_rng(seed)
    result = np.zeros((h, w), dtype=np.float32)
    amplitude = 1.0
    for i in range(octaves):
        freq = 2 ** i
        small_h = max(2, h // (16 // min(freq, 16)))
        small_w = max(2, w // (16 // min(freq, 16)))
        noise = rng.standard_normal((small_h, small_w)).astype(np.float32)
        from scipy.ndimage import zoom as _zoom

        upscaled = _zoom(noise, (h / small_h, w / small_w), order=1)
        sigma = max(1.0, 40.0 / freq)
        upscaled = gaussian_filter(upscaled, sigma=sigma)
        result += amplitude * upscaled
        amplitude *= 0.5
    return _normalize(result)


def _generate_terrain(name: str, h: int = 240, w: int = 320) -> np.ndarray:
    """Generate a built-in terrain procedurally."""
    from scipy.ndimage import gaussian_filter

    if name == "flat":
        return np.full((h, w), 0.5, dtype=np.float32)

    if name == "canyon":
        base = _perlin_like(h, w, octaves=5, seed=101)
        # Carve a winding canyon through the centre
        yy, xx = np.mgrid[0:h, 0:w]
        centre_x = w / 2 + 30 * np.sin(yy * 2 * np.pi / h * 2)
        canyon_dist = np.abs(xx - centre_x)
        canyon_mask = np.exp(-(canyon_dist ** 2) / (2 * 25 ** 2))
        carved = base * 0.7 + 0.3 - canyon_mask * 0.6
        # Add side-channel erosion
        side = _perlin_like(h, w, octaves=3, seed=202) * 0.15
        result = np.clip(carved + side, 0, 1)
        return _normalize(gaussian_filter(result, sigma=1.5))

    if name == "volcano":
        yy, xx = np.mgrid[0:h, 0:w]
        cy, cx = h / 2, w / 2
        dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
        max_r = min(h, w) * 0.45
        cone = np.clip(1.0 - dist / max_r, 0, 1) ** 1.3
        # Caldera
        caldera_r = max_r * 0.18
        caldera = np.clip(1.0 - dist / caldera_r, 0, 1) ** 2
        volcano = cone - caldera * 0.35
        noise = _perlin_like(h, w, octaves=4, seed=303) * 0.12
        return _normalize(gaussian_filter(volcano + noise, sigma=2.0))

    if name == "valley":
        yy, xx = np.mgrid[0:h, 0:w]
        # Two ridges with a valley between
        ridge_l = np.exp(-((xx - w * 0.25) ** 2) / (2 * (w * 0.10) ** 2))
        ridge_r = np.exp(-((xx - w * 0.75) ** 2) / (2 * (w * 0.10) ** 2))
        ridges = ridge_l + ridge_r
        # Gentle slope along y
        slope = 0.15 * (yy / h)
        noise = _perlin_like(h, w, octaves=5, seed=404) * 0.25
        return _normalize(gaussian_filter(ridges + slope + noise, sigma=2.5))

    if name == "islands":
        base = _perlin_like(h, w, octaves=5, seed=505)
        # Water plane at ~0.45 — anything below is flat ocean
        water_level = 0.45
        islands = np.where(base > water_level, base, water_level)
        # Fade edges to ocean
        yy, xx = np.mgrid[0:h, 0:w]
        edge_fade = np.ones((h, w), dtype=np.float32)
        margin = 30
        for arr, size in [(yy, h), (xx, w)]:
            edge_fade *= np.clip(arr / margin, 0, 1) * np.clip((size - 1 - arr) / margin, 0, 1)
        blended = islands * edge_fade + water_level * (1 - edge_fade)
        return _normalize(gaussian_filter(blended, sigma=1.5))

    # Fallback
    return np.full((h, w), 0.5, dtype=np.float32)
