"""Stage 3 -- 360 mapping (NBV / DFS) and occlusion close-ups.

The stage takes the geofenced AOI, the orbit radius ``r`` and the obstacle map
from Stage 2, flies a coverage orbit + adaptive close-ups, and emits a
:class:`~pral.core.schemas.Model3D` (surface voxels + posed image refs +
coverage fraction).

The heavy geometry already lives in :mod:`pral.sim` (visibility, line of sight,
frontier detection, close-up search). This package is the *planning* layer on
top of it:

* :func:`coverage_fraction` -- the surface-coverage metric (Test 9).
* :func:`detect_occluded_faces` -- frontier / occlusion detection from a pose
  set against ground truth (Test 10).
* :func:`generate_closeups` -- one line-of-sight close-up viewpoint per
  occluded face at target standoff/GSD (Test 11).
* :func:`nbv_plan` / :func:`lawnmower_plan` -- next-best-view (DFS: deepest
  uncertainty first, by information gain) vs a dumb lawnmower baseline, used to
  show the NBV plan is no more than 1.5x the theoretical minimum view count and
  within battery budget (Test 12).
* :func:`map_aoi` -- the end-to-end Stage-3 entry point (AOI + r + ObstacleMap
  -> Model3D).
"""

from __future__ import annotations

from pral.stage3_map.mapping import (
    ClosePlan,
    CoveragePlan,
    coverage_fraction,
    detect_occluded_faces,
    generate_closeups,
    generate_completion_poses,
    information_gain,
    lawnmower_plan,
    map_aoi,
    nbv_plan,
    order_orbit_poses,
    target_gsd,
    theoretical_min_views,
)

__all__ = [
    "ClosePlan",
    "CoveragePlan",
    "coverage_fraction",
    "detect_occluded_faces",
    "generate_closeups",
    "generate_completion_poses",
    "information_gain",
    "lawnmower_plan",
    "map_aoi",
    "nbv_plan",
    "order_orbit_poses",
    "target_gsd",
    "theoretical_min_views",
]
