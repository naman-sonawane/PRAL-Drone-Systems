"""Synthetic posed image *set* + per-pose surface visibility.

Stages 3-5 don't need pixels -- they need, for each camera pose, *which surface
voxels it sees*. That is a pure geometry/visibility query against the scene:
a surface voxel is "seen" from a pose if it is in front of the camera, inside
the field of view, facing the camera, and has clear line of sight.

This module produces:

* :class:`PosedImageSet` -- a list of :class:`~pral.core.camera.Pose` (the
  orbit ring plus optional extra views) and a boolean ``visibility`` matrix
  ``[n_poses, n_surface_voxels]``.
* :func:`coverage` -- fraction of surface voxels seen by at least one pose
  (Test 9). Monotone in the pose set (more poses never lowers coverage).
* :func:`frontier_voxels` -- surface voxels seen by *no* pose so far; the
  coverage gaps the NBV / close-up logic must resolve (Tests 10/11).
* :func:`to_model3d` / :func:`to_posed_image_refs` -- bridge to the
  :mod:`pral.core.schemas` artifacts the rest of the pipeline consumes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pral.core.camera import Camera, Pose
from pral.core.schemas import Model3D, PosedImageRef, PoseModel, Quaternion
from pral.sim.scenes import VoxelScene


def _in_view(camera: Camera, pose: Pose, point_w: np.ndarray) -> bool:
    """True if ``point_w`` is in front of the camera and inside the image."""
    p_c = pose.world_to_camera(point_w)
    if p_c[2] <= 1e-6:
        return False
    u = camera.fx * p_c[0] / p_c[2] + camera.cx
    v = camera.fy * p_c[1] / p_c[2] + camera.cy
    return 0.0 <= u < camera.width and 0.0 <= v < camera.height


def visible_surface(
    scene: VoxelScene,
    camera: Camera,
    pose: Pose,
) -> np.ndarray:
    """Boolean mask ``[n_surface]`` of surface voxels visible from ``pose``.

    A voxel is visible iff it is in the frustum *and* the segment from the
    camera to the voxel center is unobstructed (its own voxel + neighbors are
    excluded so the surface doesn't occlude itself).
    """
    n = len(scene.surface_indices)
    vis = np.zeros(n, dtype=bool)
    for idx, ijk in enumerate(scene.surface_indices):
        center = scene.index_to_enu(ijk)
        if not _in_view(camera, pose, center):
            continue
        ignore = {
            (int(ijk[0]) + di, int(ijk[1]) + dj, int(ijk[2]) + dk)
            for di in (-1, 0, 1)
            for dj in (-1, 0, 1)
            for dk in (-1, 0, 1)
        }
        if scene.line_of_sight_clear(pose.position, center, ignore_indices=ignore):
            vis[idx] = True
    return vis


@dataclass
class PosedImageSet:
    """A set of camera poses + their per-surface-voxel visibility."""

    scene: VoxelScene
    camera: Camera
    poses: list[Pose]
    visibility: np.ndarray  # bool [n_poses, n_surface]

    @property
    def n_surface(self) -> int:
        return int(self.visibility.shape[1])

    def seen_mask(self) -> np.ndarray:
        """Surface voxels seen by at least one pose (bool ``[n_surface]``)."""
        if self.visibility.size == 0:
            return np.zeros(self.n_surface, dtype=bool)
        return np.any(self.visibility, axis=0)

    def coverage(self) -> float:
        """Fraction of surface voxels seen by at least one pose (Test 9)."""
        if self.n_surface == 0:
            return 0.0
        return float(np.mean(self.seen_mask()))

    def frontier_indices(self) -> np.ndarray:
        """Indices into ``scene.surface_indices`` of voxels seen by no pose."""
        return np.where(~self.seen_mask())[0]

    def to_model3d(self, coverage_override: float | None = None) -> Model3D:
        """Bridge to the :class:`~pral.core.schemas.Model3D` artifact."""
        cov = self.coverage() if coverage_override is None else coverage_override
        return Model3D(
            surface_voxels=[list(map(float, v)) for v in self.scene.surface_voxels],
            voxel_size=self.scene.voxel_size,
            posed_images=to_posed_image_refs(self.poses),
            coverage=cov,
        )


def to_posed_image_refs(poses: list[Pose], prefix: str = "img") -> list[PosedImageRef]:
    """Wrap raw poses as schema :class:`PosedImageRef` records."""
    refs = []
    for i, pose in enumerate(poses):
        q = pose.quaternion
        refs.append(
            PosedImageRef(
                image_id=f"{prefix}_{i:04d}",
                pose=PoseModel(
                    position=[float(x) for x in pose.position],
                    orientation=Quaternion(w=float(q[0]), x=float(q[1]), y=float(q[2]), z=float(q[3])),
                ),
            )
        )
    return refs


def generate_orbit_poses(
    scene: VoxelScene,
    n_views: int = 16,
    altitude: float | None = None,
) -> list[Pose]:
    """Orbit ring of poses at the orbit radius, each aimed at the centroid."""
    positions = scene.orbit_poses_enu(n_views=n_views, altitude=altitude)
    target = scene.centroid_enu + np.array([0.0, 0.0, scene.building_height / 2.0])
    return [Pose.looking_at(position=p, target=target) for p in positions]


def generate_posed_image_set(
    scene: VoxelScene,
    camera: Camera,
    n_views: int = 16,
    altitude: float | None = None,
    extra_poses: list[Pose] | None = None,
) -> PosedImageSet:
    """Build the orbit posed-image set (plus any ``extra_poses``) + visibility."""
    poses = generate_orbit_poses(scene, n_views=n_views, altitude=altitude)
    if extra_poses:
        poses = poses + list(extra_poses)
    n = len(scene.surface_indices)
    vis = np.zeros((len(poses), n), dtype=bool)
    for p_i, pose in enumerate(poses):
        vis[p_i] = visible_surface(scene, camera, pose)
    return PosedImageSet(scene=scene, camera=camera, poses=poses, visibility=vis)


def closeup_pose_for_frontier(
    scene: VoxelScene,
    camera: Camera,
    frontier_index: int,
    standoff: float = 8.0,
    n_candidates: int = 48,
) -> Pose | None:
    """Find a closer, re-angled line-of-sight pose for an occluded frontier.

    Searches a hemisphere of candidate camera positions at ``standoff`` meters
    around the frontier voxel for one with clear line of sight *and* the voxel
    in view. Returns the first viable :class:`Pose`, or ``None`` if the
    frontier truly cannot be resolved (fully buried). This is the Stage-3
    adaptive close-up generator (Test 11).
    """
    ijk = scene.surface_indices[frontier_index]
    target = scene.index_to_enu(ijk)
    ignore = {
        (int(ijk[0]) + di, int(ijk[1]) + dj, int(ijk[2]) + dk)
        for di in (-1, 0, 1)
        for dj in (-1, 0, 1)
        for dk in (-1, 0, 1)
    }
    rng = np.random.default_rng(0)
    # Deterministic hemisphere sampling (azimuth x elevation grid + jitter).
    azis = np.linspace(0, 2 * np.pi, n_candidates, endpoint=False)
    elevs = np.array([np.radians(e) for e in (10.0, 25.0, 45.0, 60.0)])
    for elev in elevs:
        for az in azis:
            offset = standoff * np.array(
                [np.cos(elev) * np.cos(az), np.cos(elev) * np.sin(az), np.sin(elev)]
            )
            cam_pos = target + offset
            if cam_pos[2] <= scene.voxel_size:  # don't go underground
                continue
            if not scene.line_of_sight_clear(cam_pos, target, ignore_indices=ignore):
                continue
            pose = Pose.looking_at(position=cam_pos, target=target)
            if _in_view(camera, pose, target):
                return pose
    return None


__all__ = [
    "PosedImageSet",
    "visible_surface",
    "to_posed_image_refs",
    "generate_orbit_poses",
    "generate_posed_image_set",
    "closeup_pose_for_frontier",
]
