"""Procedural synthetic worlds for Tier-B tests.

This subpackage builds *deterministic* synthetic scenes so the pipeline's
Tier-B tests (synthetic scene / sim / fake depth) need no real photographs.

Modules
-------
* :mod:`pral.sim.scenes`        -- :class:`VoxelScene`: a procedural building +
  obstacles on a ground plane, with ground-truth surface voxels, labeled
  occupancy, and per-voxel "occluded-from-orbit" truth.
* :mod:`pral.sim.depth`         -- :func:`fake_depth_map`: ray/voxel depth render.
* :mod:`pral.sim.posed_images`  -- synthetic posed image set + per-pose visibility.
* :mod:`pral.sim.flightsim`     -- minimal kinematic sim: step a Mission, report
  executed poses, collisions vs an ObstacleMap, and battery consumption.
"""

from pral.sim import depth, flightsim, posed_images, scenes

__all__ = ["scenes", "depth", "posed_images", "flightsim"]
