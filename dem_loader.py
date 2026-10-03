"""
Load and save Digital Elevation Models (DEMs) for terrain reference overlays.

Supports:
- GeoTIFF (.tif, .tiff) via rasterio (optional dependency)
- Raw heightmap images (.png, .jpg) via PIL/pygame
- NumPy arrays (.npy)
"""

from __future__ import annotations

import logging
import math
import pathlib
import re
from datetime import datetime
from typing import Any

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


# ── snapshot export / reload ─────────────────────────────────────────────────

SAVED_DIR = _SAVED_DIR
SNAPSHOT_RE = re.compile(r"^terrain_\d{8}_\d{6}(?:_\d+)?$")
EXPORT_SUFFIXES = (".npy", ".asc", ".png")

# Horizontal field of view of the depth camera, used to estimate the real
# size of one cell for the DEM. Kinect v1/v2 are 57-70 deg; 62 is a fair middle.
_SENSOR_HFOV_DEG = 62.0


def cell_size_mm(width_px: int, distance_mm: float) -> float:
    """Approximate ground size of one pixel at *distance_mm* from the camera."""
    span = 2.0 * distance_mm * math.tan(math.radians(_SENSOR_HFOV_DEG / 2.0))
    return span / max(1, width_px)


def write_esri_ascii(height_mm: np.ndarray, path: pathlib.Path, cellsize: float) -> pathlib.Path:
    """Write an ESRI ASCII grid (.asc): opens in QGIS, ArcGIS and most GIS tools."""
    rows, cols = height_mm.shape
    header = (
        f"ncols {cols}\nnrows {rows}\nxllcorner 0\nyllcorner 0\n"
        f"cellsize {cellsize:.3f}\nNODATA_value -9999\n"
    )
    with path.open("w", encoding="ascii", newline="\n") as fh:
        fh.write(header)
        np.savetxt(fh, height_mm, fmt="%.1f")
    return path


def export_snapshot(
    height_data: np.ndarray,
    *,
    depth_range_mm: tuple[int, int],
    image: Any = None,
) -> list[pathlib.Path]:
    """Save the terrain as .npy (to reload), .asc (heights in mm) and, when a
    rendered pygame surface is given, .png. All three share one stem."""
    SAVED_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"terrain_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    n = 1
    while (SAVED_DIR / f"{stem}.npy").exists():
        n += 1
        stem = f"terrain_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{n}"

    lo, hi = depth_range_mm
    data = np.clip(height_data.astype(np.float32), 0.0, 1.0)
    paths = [save_dem(data, str(SAVED_DIR / f"{stem}.npy"))]
    paths.append(write_esri_ascii(
        data * float(hi - lo), SAVED_DIR / f"{stem}.asc", cell_size_mm(data.shape[1], hi)
    ))
    if image is not None:
        import pygame

        png = SAVED_DIR / f"{stem}.png"
        pygame.image.save(image, str(png))
        paths.append(png)
    return paths


def list_snapshots(limit: int = 12) -> list[dict[str, Any]]:
    """Newest-first saved terrains: {"name", "time", "files": [suffix, ...]}."""
    if not SAVED_DIR.is_dir():
        return []
    found = []
    for npy in SAVED_DIR.glob("terrain_*.npy"):
        if not SNAPSHOT_RE.match(npy.stem):
            continue
        found.append({
            "name": npy.stem,
            "time": npy.stat().st_mtime,
            "files": [s for s in EXPORT_SUFFIXES if npy.with_suffix(s).exists()],
        })
    found.sort(key=lambda s: s["time"], reverse=True)
    return found[:limit]


def snapshot_path(name: str, suffix: str = ".npy") -> pathlib.Path | None:
    """Resolve a snapshot file by stem, refusing anything outside SAVED_DIR."""
    if not SNAPSHOT_RE.match(name) or suffix not in EXPORT_SUFFIXES:
        return None
    path = SAVED_DIR / f"{name}{suffix}"
    return path if path.is_file() else None


def fit_to(data: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Resample *data* to exactly *shape* (zoom can be off by a pixel)."""
    from scipy.ndimage import zoom

    h, w = shape
    data = np.asarray(data, dtype=np.float32)
    if data.shape != (h, w):
        data = zoom(data, (h / data.shape[0], w / data.shape[1]), order=1)
        data = np.pad(
            data[:h, :w], ((0, max(0, h - data.shape[0])), (0, max(0, w - data.shape[1]))), mode="edge"
        )
    return data.astype(np.float32)


def load_snapshot(name: str) -> np.ndarray:
    path = snapshot_path(name)
    if path is None:
        raise FileNotFoundError(f"No saved terrain called {name}")
    return np.clip(np.load(path).astype(np.float32), 0.0, 1.0)
