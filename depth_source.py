"""
Depth source abstraction — backward-compatibility shim.

This module re-exports sensor classes from :mod:`sensor_api` under their
original names so that existing ``from depth_source import …`` statements
continue to work.

For new code, prefer importing directly from :mod:`sensor_api`.
"""

from __future__ import annotations

from sensor_api import (  # noqa: F401  — re-exports
    DepthSensor as DepthSource,
)
