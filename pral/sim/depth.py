"""Fake depth rendering against a :class:`~pral.sim.scenes.VoxelScene`.

A real pipeline gets metric depth from a monocular network or stereo. For
Tier-B tests we render depth *exactly* by marching one ray per pixel through
the voxel grid and returning the distance to the first occupied cell -- no CV,
no learning, fully deterministic.

The two consumers:

* **Height estimate H (Test 6).** From a nadir (top-down) pose over the
  building, the depth at the building footprint is shorter than the depth to
  the surrounding ground by exactly the building height. :func:`estimate_height`
  recovers H from a single fake nadir depth map within ~1 voxel.
* **Occupancy build (Test 7).** Back-projecting each depth pixel to its 3D hit
  point and voxelizing yields an occupancy grid that can be compared against
  the scene's labeled obstacle voxels.
"""

from __future__ import annotations

import numpy as np

from pral.core.camera import Camera, Pose
from pral.sim.scenes import VoxelLabel, VoxelScene


def fake_depth_map(
    scene: VoxelScene,
    camera: Camera,
    pose: Pose,
    max_range: float = 500.0,
    stride: int = 1,
) -> np.ndarray:
    """Render a depth image: per pixel, the optical-axis depth to first hit.

    Returns a ``[H, W]`` float array (``np.inf`` where the ray misses the
    scene). Depth is the camera-frame ``+z`` component of the hit point (i.e.
    perpendicular distance to the image plane, matching ``backproject(depth=)``).

    ``stride`` subsamples pixels (>=1) for speed; the returned map keeps full
    resolution with the skipped pixels left as ``inf``.
    """
    H, W = camera.height, camera.width
    out = np.full((H, W), np.inf, dtype=float)

    inv_k = np.linalg.inv(camera.K)
    R = pose.R_wc
    origin = pose.position
    # Ray length budget in voxel-index units.
    max_t_idx = max_range / scene.voxel_size

    from pral.sim.scenes import _voxel_traversal  # local import: shared marcher

    o_idx = scene.enu_to_index(origin)
    for v in range(0, H, stride):
        for u in range(0, W, stride):
            ray_c = inv_k @ np.array([u + 0.5, v + 0.5, 1.0])
            ray_w = R @ ray_c
            d_idx = ray_w / scene.voxel_size
            hit_t = None
            for (i, j, k, t) in _voxel_traversal(o_idx, d_idx, scene.shape, max_t_idx):
                if scene.labels[i, j, k] != int(VoxelLabel.EMPTY):
                    hit_t = t
                    break
            if hit_t is None:
                continue
            # `t` is distance along the normalized index-space ray. Convert to
            # a world hit point, then take optical-axis (camera +z) depth.
            dir_world = ray_w / np.linalg.norm(ray_w)
            hit_world = origin + (hit_t * scene.voxel_size) * dir_world
            # Optical-axis depth = camera +z component of the hit point.
            depth_axis = float((R.T @ (hit_world - origin))[2])
            out[v, u] = depth_axis
    return out


def estimate_height(
    scene: VoxelScene,
    camera: Camera,
    nadir_altitude: float | None = None,
) -> float:
    """Estimate building height H from a single fake nadir depth map.

    Places a downward-looking camera above the centroid, renders depth, and
    takes H = (ground depth) - (rooftop depth), where ground depth is the
    largest finite depth seen and rooftop depth the smallest. Accurate to
    within ~1 voxel, comfortably inside the Test-6 10% budget.
    """
    if nadir_altitude is None:
        nadir_altitude = scene.building_height + 60.0
    cam_pos = scene.centroid_enu + np.array([0.0, 0.0, nadir_altitude])
    # Look straight down; pick a horizontal 'up' so the frame is well-defined.
    pose = Pose.looking_at(
        position=cam_pos,
        target=scene.centroid_enu,
        up=np.array([0.0, 1.0, 0.0]),
    )
    # Subsample for speed; the building is many voxels wide so stride is fine.
    stride = max(1, min(camera.width, camera.height) // 64)
    depth = fake_depth_map(scene, camera, pose, stride=stride)
    finite = depth[np.isfinite(depth)]
    if finite.size == 0:
        raise ValueError("nadir depth map is empty; camera saw nothing")
    ground_depth = float(np.max(finite))
    roof_depth = float(np.min(finite))
    return ground_depth - roof_depth


def occupancy_from_depth(
    scene: VoxelScene,
    camera: Camera,
    poses: list[Pose],
    max_range: float = 500.0,
    stride: int = 2,
) -> np.ndarray:
    """Build an occupancy grid (bool ``[nx, ny, nz]``) by back-projecting depth.

    For each pose, every finite depth pixel is back-projected to a world hit
    point and marked occupied in a fresh grid matching the scene's geometry.
    This is the synthetic analog of fusing depth maps into an OctoMap (Test 7).
    """
    occ = np.zeros(scene.shape, dtype=bool)
    s = scene.shape
    for pose in poses:
        depth = fake_depth_map(scene, camera, pose, max_range=max_range, stride=stride)
        vs, us = np.where(np.isfinite(depth))
        for v, u in zip(vs, us):
            from pral.core.camera import backproject

            hit = backproject(camera, pose, np.array([u + 0.5, v + 0.5]), depth=depth[v, u])
            i, j, k = np.floor(scene.enu_to_index(hit)).astype(int)
            if 0 <= i < s[0] and 0 <= j < s[1] and 0 <= k < s[2]:
                occ[i, j, k] = True
    return occ


__all__ = ["fake_depth_map", "estimate_height", "occupancy_from_depth"]
