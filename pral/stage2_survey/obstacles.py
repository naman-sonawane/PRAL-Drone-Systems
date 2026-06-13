"""Obstacle map: a 2.5D / sparse-voxel occupancy of the orbit volume (Test 7).

The drone's top-down survey produces a point cloud (here: exact depth fused
into a voxel grid by the sim). Stage 2 turns that into an
:class:`~pral.core.schemas.ObstacleMap` -- the artifact the planner consults to
keep the orbit path clear -- and reports two things the gate cares about:

* **Recall in the orbit annulus** (>= 95%): of the hazard voxels lying in the
  ring the drone will actually fly, what fraction did the survey map mark
  occupied? Misses there are obstacles the planner can't see.
* **Zero missed wires/poles on the planned path** (the thin-but-deadly ones):
  every wire/pole voxel within a clearance tube of the orbit ring must be in
  the map.

Why a *survey grid* of poses and not the orbit ring itself? The orbit looks
*horizontally* at facades; it barely sees the tops of trees/poles. A top-down
survey (nadir + a few obliques) looks *down* on the annulus and lights up the
obstacle tops, which is exactly the geometry a real nadir mapping pass uses.

Hazard segmentation from real imagery (Test 8) is Tier C:
:func:`segment_hazard_classes` is the interface; the real model needs field data.
"""

from __future__ import annotations

import numpy as np

from pral.core.camera import Camera, Pose
from pral.core.schemas import ObstacleMap
from pral.sim.depth import occupancy_from_depth
from pral.sim.scenes import VoxelLabel, VoxelScene


# ---------------------------------------------------------------------------
# Survey pose generation (top-down nadir grid + obliques)
# ---------------------------------------------------------------------------


def survey_poses(
    scene: VoxelScene,
    camera: Camera,
    altitude: float | None = None,
    grid: int = 3,
    span: float | None = None,
    n_oblique: int = 8,
) -> list[Pose]:
    """Deterministic top-down survey: a nadir grid + a ring of oblique looks.

    ``grid`` x ``grid`` nadir cameras over the orbit footprint give clean tops
    of every obstacle; ``n_oblique`` tilted cameras around the ring fill in the
    sides of trees/poles so thin hazards aren't missed. All aimed to cover the
    orbit annulus, all deterministic (no RNG).
    """
    if altitude is None:
        altitude = scene.building_height + 60.0
    if span is None:
        # Cover the full annulus the drone will orbit through.
        span = 2.0 * scene.orbit_radius
    c = scene.centroid_enu
    poses: list[Pose] = []

    # Nadir grid looking straight down.
    coords = np.linspace(-span / 2.0, span / 2.0, grid)
    for de in coords:
        for dn in coords:
            pos = c + np.array([de, dn, altitude])
            target = c + np.array([de, dn, 0.0])
            poses.append(Pose.looking_at(pos, target, up=np.array([0.0, 1.0, 0.0])))

    # Oblique ring: tilted inward to catch the sides of vertical hazards.
    obl_alt = altitude * 0.6
    obl_r = scene.orbit_radius * 1.1
    for a in np.linspace(0.0, 2.0 * np.pi, n_oblique, endpoint=False):
        pos = c + np.array([obl_r * np.cos(a), obl_r * np.sin(a), obl_alt])
        # Aim at a point partway in and low so the look grazes obstacle sides.
        target = c + np.array([0.5 * obl_r * np.cos(a), 0.5 * obl_r * np.sin(a), 3.0])
        poses.append(Pose.looking_at(pos, target))

    return poses


# ---------------------------------------------------------------------------
# Build the ObstacleMap artifact
# ---------------------------------------------------------------------------


def _survey_camera(camera: Camera, max_dim: int = 120) -> Camera:
    """A coarse copy of ``camera`` (same FOV) for the survey ray-march.

    The fake-depth render is a per-pixel Python ray-march, so cost scales with
    pixel count. A nadir mapping survey does not need the full imaging sensor
    resolution to resolve metre-scale voxels -- it only has to *land a ray* in
    each obstacle voxel. We therefore down-scale the survey camera so its larger
    side is at most ``max_dim`` pixels while preserving the field of view (and
    thus the projection geometry back-projection relies on). For a 2 m voxel
    grid this keeps annulus recall at 1.0 and zero missed thin hazards while
    cutting the ray count -- and runtime -- by an order of magnitude.
    """
    longest = max(camera.width, camera.height)
    if longest <= max_dim:
        return camera
    scale = max_dim / longest
    w = max(2, int(round(camera.width * scale)))
    h = max(2, int(round(camera.height * scale)))
    return Camera(hfov_deg=camera.hfov_deg, vfov_deg=camera.vfov_deg, width=w, height=h)


def build_obstacle_map(
    scene: VoxelScene,
    camera: Camera,
    poses: list[Pose] | None = None,
    stride: int = 1,
    survey_max_dim: int = 120,
) -> ObstacleMap:
    """Fuse the survey depth into a sparse-voxel :class:`ObstacleMap`.

    Back-projects the survey depth maps into a voxel grid matching the scene
    geometry (the sim's :func:`occupancy_from_depth`), drops the ground layer
    (``k=0``), and packs the remaining occupied indices into the schema.

    ``poses`` defaults to :func:`survey_poses` (a top-down nadir grid + oblique
    ring). The depth render uses a coarse survey camera (same FOV, larger side
    capped at ``survey_max_dim`` px) so the per-pixel ray-march stays cheap
    without changing the projection geometry; pass ``survey_max_dim`` large
    enough to disable the cap. The returned map is the artifact handed to
    Stage 3 / the planner.
    """
    survey_cam = _survey_camera(camera, max_dim=survey_max_dim)
    if poses is None:
        poses = survey_poses(scene, survey_cam)

    occ = occupancy_from_depth(scene, survey_cam, poses, stride=stride)
    # Drop the ground plane -- it is not an obstacle, just the floor.
    occ[:, :, 0] = False

    idx = np.argwhere(occ)
    occupied = [[int(i), int(j), int(k)] for i, j, k in idx]

    return ObstacleMap(
        resolution=float(scene.voxel_size),
        origin_enu=[float(x) for x in scene.origin_enu],
        shape=[int(s) for s in scene.shape],
        occupied_voxels=occupied,
    )


def obstacle_map_to_index_set(omap: ObstacleMap) -> set[tuple[int, int, int]]:
    """Occupied ``(i, j, k)`` indices of an :class:`ObstacleMap` as a set."""
    if omap.occupied_voxels is None:
        return set()
    return {(int(i), int(j), int(k)) for i, j, k in omap.occupied_voxels}


# ---------------------------------------------------------------------------
# Annulus geometry + recall (Test 7)
# ---------------------------------------------------------------------------


def _annulus_mask(
    scene: VoxelScene,
    indices: np.ndarray,
    inner: float,
    outer: float,
) -> np.ndarray:
    """Boolean mask over ``indices`` (an ``[m,3]`` int array) for voxels whose
    horizontal distance from the centroid lies in ``[inner, outer]``."""
    if len(indices) == 0:
        return np.zeros((0,), bool)
    enu = np.array([scene.index_to_enu(v) for v in indices])
    rad = np.hypot(enu[:, 0] - scene.centroid_enu[0], enu[:, 1] - scene.centroid_enu[1])
    return (rad >= inner) & (rad <= outer)


def obstacle_recall_in_annulus(
    scene: VoxelScene,
    omap: ObstacleMap,
    band: float = 0.35,
) -> float:
    """Fraction of ground-truth hazard voxels in the orbit annulus recalled.

    The annulus is ``orbit_radius * (1 ± band)``. Of the scene's labelled
    obstacle voxels (tree/pole/wire) in that ring, what fraction did the
    obstacle map mark occupied? Returns 1.0 if there are no hazards in the ring.
    """
    r = scene.orbit_radius
    inner, outer = r * (1.0 - band), r * (1.0 + band)
    haz = scene.occupied_voxels(only_obstacles=True)
    in_ring = _annulus_mask(scene, haz, inner, outer)
    haz_ring = haz[in_ring]
    if len(haz_ring) == 0:
        return 1.0
    mapped = obstacle_map_to_index_set(omap)
    hit = sum(1 for v in haz_ring if (int(v[0]), int(v[1]), int(v[2])) in mapped)
    return hit / len(haz_ring)


def path_clear_of_hazards(
    scene: VoxelScene,
    omap: ObstacleMap,
    altitude: float | None = None,
    clearance: float = 4.0,
    n_samples: int = 360,
) -> tuple[int, int]:
    """Check the planned orbit path against unmapped thin hazards (wires/poles).

    Samples the orbit ring at the planned altitude and counts, among the
    scene's ground-truth **wire/pole** voxels within ``clearance`` meters of any
    path sample, how many are *missing* from the obstacle map. Returns
    ``(n_missed, n_on_path)``; the gate wants ``n_missed == 0``.
    """
    if altitude is None:
        altitude = scene.building_height / 2.0
    r = scene.orbit_radius
    angs = np.linspace(0.0, 2.0 * np.pi, n_samples, endpoint=False)
    path = scene.centroid_enu + np.column_stack(
        [r * np.cos(angs), r * np.sin(angs), np.full(n_samples, altitude)]
    )

    thin = np.isin(
        scene.labels, [int(VoxelLabel.WIRE), int(VoxelLabel.POLE)]
    )
    thin_idx = np.argwhere(thin)
    if len(thin_idx) == 0:
        return 0, 0
    thin_enu = np.array([scene.index_to_enu(v) for v in thin_idx])

    mapped = obstacle_map_to_index_set(omap)
    n_on_path = 0
    n_missed = 0
    for v_idx, v_enu in zip(thin_idx, thin_enu):
        # Closest distance from this hazard voxel to any path sample.
        d = np.min(np.linalg.norm(path - v_enu, axis=1))
        if d <= clearance:
            n_on_path += 1
            if (int(v_idx[0]), int(v_idx[1]), int(v_idx[2])) not in mapped:
                n_missed += 1
    return n_missed, n_on_path


# ---------------------------------------------------------------------------
# Tier C interface: hazard-class segmentation from real imagery (Test 8)
# ---------------------------------------------------------------------------


def segment_hazard_classes(image: np.ndarray) -> np.ndarray:
    """Per-pixel hazard-class mask from a top-down RGB image (Tier C interface).

    Real implementation: an open-vocab / semantic segmenter (SAM 2 + a class
    head) labelling tree / wire / pole / person no-fly classes, evaluated at
    IoU >= 0.6 (Test 8). Not implementable without a trained model + field
    imagery, so this is a typed stub the Tier-C test exercises and skips.
    """
    raise NotImplementedError(
        "real hazard-class segmentation needs a trained model + field imagery"
    )


__all__ = [
    "survey_poses",
    "build_obstacle_map",
    "obstacle_map_to_index_set",
    "obstacle_recall_in_annulus",
    "path_clear_of_hazards",
    "segment_hazard_classes",
]
