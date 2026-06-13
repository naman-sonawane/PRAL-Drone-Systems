"""Stage 2 -- Top-Down Survey, Geometry Estimation & Obstacle Map.

Given a locked AOI + camera, Stage 2 answers two questions the rest of the
pipeline depends on:

1. **How far back do we orbit?** The standoff radius ``r`` that fits a building
   of height ``H`` in frame with margin (the framing equation from the spec):

       r = (H / 2 + margin) / tan(VFOV / 2)

   :func:`orbit_radius` is that math; :func:`frames_building` proves the
   building extremes project inside the image with margin at distance ``r``
   (Test 5).

2. **What could we hit?** A 2.5D / sparse-voxel :class:`~pral.core.schemas.ObstacleMap`
   built from the survey point cloud, plus the labelled no-fly volumes
   (trees / poles / wires) in the planned orbit annulus.

The *height estimate* and *point cloud* themselves come from the sim harness
(:mod:`pral.sim.depth`) -- Stage 2 consumes those products and turns them into
the orbit-radius decision and the :class:`ObstacleMap` artifact that flows to
Stage 3. Real depth + hazard segmentation are Tier-C interfaces.
"""

from pral.stage2_survey.geometry import (
    frames_building,
    fits_in_frame,
    orbit_radius,
)
from pral.stage2_survey.height import estimate_building_height
from pral.stage2_survey.obstacles import (
    build_obstacle_map,
    obstacle_recall_in_annulus,
    obstacle_map_to_index_set,
    path_clear_of_hazards,
    segment_hazard_classes,
)

__all__ = [
    "orbit_radius",
    "fits_in_frame",
    "frames_building",
    "estimate_building_height",
    "build_obstacle_map",
    "obstacle_map_to_index_set",
    "obstacle_recall_in_annulus",
    "path_clear_of_hazards",
    "segment_hazard_classes",
]
