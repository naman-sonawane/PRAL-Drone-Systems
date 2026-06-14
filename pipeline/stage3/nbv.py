"""Sub-step 3d -- Frontier Detection & Next-Best-View."""
from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

import numpy as np

from pipeline.stage2.obstacle import LABEL_NO_GO, MockOctoMap
from .coverage import world_to_voxel_key
from .types import Frontier

log = logging.getLogger(__name__)

_SPHERE_SAMPLES_N = 12  # candidates per frontier


def rank_frontiers(frontiers: List[Frontier]) -> List[Frontier]:
    """
    Sort frontiers by information_gain descending (highest unseen area first).

    Also refreshes information_gain from voxel_count before sorting.
    """
    for f in frontiers:
        f.information_gain = float(f.voxel_count)
    return sorted(frontiers, key=lambda f: f.information_gain, reverse=True)


def sphere_sample(
    center: Tuple[float, float, float],
    radius: float,
    n: int = _SPHERE_SAMPLES_N,
) -> List[Tuple[float, float, float]]:
    """
    Return n evenly-spread points on a sphere of given radius around center.

    Uses the Fibonacci / golden-angle method for uniform distribution.
    """
    pts: List[Tuple[float, float, float]] = []
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(n):
        y = 1.0 - (i / max(n - 1, 1)) * 2.0
        r_xy = math.sqrt(max(0.0, 1.0 - y * y))
        theta = golden * i
        x = math.cos(theta) * r_xy
        z = math.sin(theta) * r_xy
        pts.append((
            center[0] + radius * x,
            center[1] + radius * y,
            center[2] + radius * z,
        ))
    return pts


def los_check(
    start: Tuple[float, float, float],
    end: Tuple[float, float, float],
    obstacle_map,
    step: float = 0.25,
) -> bool:
    """
    March from start to end at step intervals.

    Return False if any no-go voxel is hit, True if the path is clear.
    """
    direction = np.array(end, dtype=float) - np.array(start, dtype=float)
    dist = float(np.linalg.norm(direction))
    if dist < 1e-6:
        return True
    direction /= dist
    n_steps = int(dist / step) + 1
    for s in range(n_steps):
        pt = np.array(start) + min(s * step, dist) * direction
        key = world_to_voxel_key(pt, step)
        if isinstance(obstacle_map, MockOctoMap):
            if obstacle_map._nodes.get(key) == LABEL_NO_GO:
                return False
    return True


def generate_closeup_viewpoint(
    frontier: Frontier,
    obstacle_map,
    r: float,
) -> Optional[Tuple[Tuple[float, float, float], float]]:
    """
    Sample candidate viewpoints at r*0.5 radius around the frontier centroid.

    Return the first collision-free (pos, yaw) pair pointing toward the frontier,
    or None if no safe candidate exists.
    """
    close_r = r * 0.5
    candidates = sphere_sample(frontier.centroid_enu, radius=close_r)
    fc = frontier.centroid_enu
    for pos in candidates:
        if pos[2] < 0.5:    # keep above ground
            continue
        if los_check(pos, fc, obstacle_map):
            yaw = math.atan2(fc[1] - pos[1], fc[0] - pos[0])
            return (pos, yaw)
    return None
