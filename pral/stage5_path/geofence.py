"""Geofence + obstacle-clearance predicates shared across Stage 5.

A viewpoint is *admissible* iff it is inside the geofence (a horizontal ENU
polygon, with an altitude ceiling and floor) **and** its clearance to the
nearest obstacle is at least the safety margin.

Clearance is measured against either a :class:`~pral.core.schemas.ObstacleMap`
(sparse occupied voxels or a 2.5D height grid) or a
:class:`~pral.sim.scenes.VoxelScene`, reusing the same occupancy lookup the
flight sim uses so the two never disagree.
"""

from __future__ import annotations

import numpy as np

from pral.core.schemas import AOI, ObstacleMap
from pral.sim.flightsim import _occupied_lookup
from pral.sim.scenes import VoxelScene

ObstacleSource = ObstacleMap | VoxelScene


def point_in_polygon(point_en: np.ndarray, polygon_en: np.ndarray) -> bool:
    """Ray-casting test: is ``(east, north)`` inside the closed polygon?

    Points exactly on the boundary count as inside.
    """
    p = np.asarray(point_en, float)
    poly = np.asarray(polygon_en, float)
    n = len(poly)
    x, y = p[0], p[1]
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        # On-segment (boundary) check.
        if min(yi, yj) - 1e-9 <= y <= max(yi, yj) + 1e-9:
            if abs(yj - yi) < 1e-12:
                if min(xi, xj) - 1e-9 <= x <= max(xi, xj) + 1e-9 and abs(y - yi) < 1e-9:
                    return True
            else:
                x_cross = xi + (y - yi) * (xj - xi) / (yj - yi)
                if abs(x - x_cross) < 1e-9:
                    return True
        intersect = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside


def inside_geofence(
    position_enu: np.ndarray,
    aoi: AOI,
    min_altitude: float = 0.0,
) -> bool:
    """True iff ``position_enu`` is within the AOI polygon (E, N) and the
    altitude band ``[min_altitude, aoi.max_altitude]``."""
    p = np.asarray(position_enu, float)
    if not (min_altitude - 1e-9 <= p[2] <= aoi.max_altitude + 1e-9):
        return False
    polygon = np.asarray(aoi.polygon_enu, float)
    return point_in_polygon(p[:2], polygon)


def clearance(position_enu: np.ndarray, obstacle: ObstacleSource, search_cells: int = 4) -> float:
    """Distance (m) from ``position_enu`` to the nearest occupied voxel center.

    Returns ``inf`` if no occupied voxel is found within the scan window.
    """
    origin, vs, shape, occ = _occupied_lookup(obstacle)
    p = np.asarray(position_enu, float)
    base = np.floor((p - origin) / vs).astype(int)
    best = np.inf
    for di in range(-search_cells, search_cells + 1):
        for dj in range(-search_cells, search_cells + 1):
            for dk in range(-search_cells, search_cells + 1):
                i, j, k = int(base[0] + di), int(base[1] + dj), int(base[2] + dk)
                if occ(i, j, k):
                    center = origin + (np.array([i, j, k]) + 0.5) * vs
                    d = float(np.linalg.norm(p - center))
                    if d < best:
                        best = d
    return best


def is_clear(
    position_enu: np.ndarray,
    obstacle: ObstacleSource | None,
    safety_margin: float = 1.5,
) -> bool:
    """True iff clearance at ``position_enu`` is >= ``safety_margin``.

    With no obstacle source, everything is trivially clear.
    """
    if obstacle is None:
        return True
    # Widen the scan window to comfortably exceed the safety margin.
    _, vs, _, _ = _occupied_lookup(obstacle)
    cells = int(np.ceil(safety_margin / vs)) + 2
    return clearance(position_enu, obstacle, search_cells=cells) >= safety_margin


def is_admissible(
    position_enu: np.ndarray,
    aoi: AOI,
    obstacle: ObstacleSource | None,
    safety_margin: float = 1.5,
    min_altitude: float = 0.0,
) -> bool:
    """Combined Test-19 predicate: inside geofence AND obstacle-clear."""
    return inside_geofence(position_enu, aoi, min_altitude) and is_clear(
        position_enu, obstacle, safety_margin
    )


__all__ = [
    "ObstacleSource",
    "point_in_polygon",
    "inside_geofence",
    "clearance",
    "is_clear",
    "is_admissible",
]
