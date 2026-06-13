"""Subject-height estimation from the top-down survey (Test 6).

A real drone gets ``H`` from a downward rangefinder + a quick DSM. For Tier-B
we render an exact nadir depth map of the synthetic scene and read the height
off it: ground depth minus rooftop depth. The math lives in the sim's
:func:`pral.sim.depth.estimate_height`; this module is the Stage-2 entry point
so callers import height estimation from the stage, not the sim internals.
"""

from __future__ import annotations

from pral.core.camera import Camera
from pral.sim.depth import estimate_height as _sim_estimate_height
from pral.sim.scenes import VoxelScene


def estimate_building_height(
    scene: VoxelScene,
    camera: Camera,
    nadir_altitude: float | None = None,
) -> float:
    """Estimate subject height ``H`` (meters) from a synthetic nadir depth map.

    Thin Stage-2 wrapper over :func:`pral.sim.depth.estimate_height`: places a
    downward camera above the centroid and takes ``H = ground_depth -
    roof_depth``. Accurate to ~1 voxel, well inside the Test-6 10% budget.
    """
    return _sim_estimate_height(scene, camera, nadir_altitude=nadir_altitude)


__all__ = ["estimate_building_height"]
