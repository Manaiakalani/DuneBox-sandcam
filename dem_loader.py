"""
Load and save Digital Elevation Models (DEMs) for terrain reference overlays.

Supports:
- GeoTIFF (.tif, .tiff) via rasterio (optional dependency)
- Raw heightmap images (.png, .jpg) via PIL/pygame
- NumPy arrays (.npy)
"""

from __future__ import annotations

import logging
import pathlib
from datetime import datetime

import numpy as np

logger = logging.getLogger(__name__)

_TERRAIN_DIR = pathlib.Path(__file__).parent / "assets" / "terrains"
_SAVED_DIR = _TERRAIN_DIR / "saved"


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
