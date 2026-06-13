"""Stage-3 coverage, occlusion and next-best-view planning.

Everything here is deterministic geometry/combinatorics over a
:class:`~pral.sim.scenes.VoxelScene` and a set of camera
:class:`~pral.core.camera.Pose` objects. No pixels, no RNG in asserted values
(the one RNG -- the close-up hemisphere search in
:func:`pral.sim.posed_images.closeup_pose_for_frontier` -- is seeded with 0).

The four jobs of this module map onto the four owned Tier-A/B tests:

* coverage metric (9), occlusion detection (10), close-up generation (11),
  and NBV efficiency vs a lawnmower baseline (12).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from pral.core.camera import Camera, Pose
from pral.core.schemas import Model3D
from pral.sim.posed_images import (
    PosedImageSet,
    closeup_pose_for_frontier,
    generate_orbit_poses,
    to_posed_image_refs,
    visible_surface,
)
from pral.sim.scenes import VoxelScene

# ---------------------------------------------------------------------------
# Coverage metric (Test 9)
# ---------------------------------------------------------------------------


def coverage_fraction(seen_mask: np.ndarray) -> float:
    """Fraction of known surface voxels that have been observed.

    ``seen_mask`` is a boolean array, one entry per surface voxel, True where at
    least one camera has seen it. This is the Stage-3 coverage KPI (Test 9):
    coverage >= 0.90 of the AOI surface counts as "covered".
    """
    seen_mask = np.asarray(seen_mask, dtype=bool)
    if seen_mask.size == 0:
        return 0.0
    return float(np.mean(seen_mask))


# ---------------------------------------------------------------------------
# Occlusion / frontier detection (Test 10)
# ---------------------------------------------------------------------------


def detect_occluded_faces(image_set: PosedImageSet) -> np.ndarray:
    """Surface voxels the pose set could *not* see -> the occluded frontier.

    A surface voxel is flagged occluded if no pose in ``image_set`` has it
    visible (in frustum + clear line of sight). Returns a boolean mask
    ``[n_surface]`` (True == occluded / frontier). These are the faces the
    DFS / close-up logic must resolve.
    """
    return ~image_set.seen_mask()


def occlusion_recall(image_set: PosedImageSet) -> float:
    """Fraction of *truly* occluded faces (ground truth) that we flag.

    Ground truth is ``scene.occluded_from_orbit`` (computed at scene-build time
    by ray-marching a dense orbit ring). We flag a voxel occluded iff our pose
    set never saw it. Recall = flagged-and-truly-occluded / truly-occluded.

    This is the Test-10 KPI: detect >= 95% of occluded faces.
    """
    truth = np.asarray(image_set.scene.occluded_from_orbit, dtype=bool)
    if truth.size == 0 or not truth.any():
        return 1.0
    flagged = detect_occluded_faces(image_set)
    return float(np.sum(flagged & truth) / np.sum(truth))


# ---------------------------------------------------------------------------
# Adaptive close-ups (Test 11)
# ---------------------------------------------------------------------------


def target_gsd(camera: Camera, standoff: float) -> float:
    """Ground sample distance (meters/pixel) at ``standoff`` meters.

    GSD = (subject distance) / focal_length_pixels. With ``fx`` in pixels and a
    head-on subject at ``standoff`` meters, one pixel subtends ``standoff / fx``
    meters. A close-up "at target GSD" simply means we choose a standoff that
    yields a GSD at or below the desired detail resolution.
    """
    return float(standoff) / float(camera.fx)


@dataclass
class ClosePlan:
    """The close-up plan for the occluded faces of one scene."""

    frontier_indices: np.ndarray  # indices into scene.surface_indices
    poses: list[Pose]  # one LoS close-up pose per resolved frontier
    resolved: np.ndarray  # bool, parallel to frontier_indices
    standoff: float

    @property
    def n_resolved(self) -> int:
        return int(np.sum(self.resolved))

    @property
    def resolved_fraction(self) -> float:
        if len(self.frontier_indices) == 0:
            return 1.0
        return float(np.mean(self.resolved))


def generate_closeups(
    scene: VoxelScene,
    camera: Camera,
    frontier_indices: np.ndarray,
    standoff: float = 8.0,
    n_candidates: int = 48,
) -> ClosePlan:
    """Generate one line-of-sight close-up viewpoint per occluded face.

    For each frontier voxel we run the deterministic hemisphere search
    (:func:`pral.sim.posed_images.closeup_pose_for_frontier`) at ``standoff``
    meters -- the standoff sets the target GSD (:func:`target_gsd`). Faces that
    are truly buried (no LoS from anywhere) stay unresolved.

    This is Test 11: >= 1 LoS close-up per *resolvable* occluded face.
    """
    frontier_indices = np.asarray(frontier_indices, dtype=int)
    poses: list[Pose] = []
    resolved = np.zeros(len(frontier_indices), dtype=bool)
    for i, f in enumerate(frontier_indices):
        pose = closeup_pose_for_frontier(
            scene, camera, int(f), standoff=standoff, n_candidates=n_candidates
        )
        if pose is not None:
            poses.append(pose)
            resolved[i] = True
    return ClosePlan(
        frontier_indices=frontier_indices,
        poses=poses,
        resolved=resolved,
        standoff=float(standoff),
    )


# ---------------------------------------------------------------------------
# NBV (DFS / information gain) vs lawnmower baseline (Test 12)
# ---------------------------------------------------------------------------


def information_gain(visibility_row: np.ndarray, already_seen: np.ndarray) -> int:
    """How many *new* surface voxels a pose reveals given what's already seen.

    The core viewpoint-scoring primitive shared by Stages 3/4/5: here the
    "information" is unseen surface. ``visibility_row`` is the pose's per-voxel
    visibility mask; ``already_seen`` is the running union.
    """
    visibility_row = np.asarray(visibility_row, dtype=bool)
    already_seen = np.asarray(already_seen, dtype=bool)
    return int(np.sum(visibility_row & ~already_seen))


@dataclass
class CoveragePlan:
    """A selected ordered subset of candidate poses + the coverage it attains."""

    selected: list[int]  # indices into the candidate pose list
    poses: list[Pose]
    coverage: float
    seen_mask: np.ndarray
    order_gain: list[int] = field(default_factory=list)  # info gain at each pick

    @property
    def n_views(self) -> int:
        return len(self.selected)


def _greedy_select(
    visibility: np.ndarray,
    candidate_order: list[int],
    target_coverage: float,
    max_views: int | None,
    dfs: bool,
) -> CoveragePlan:
    """Greedy max-coverage selection over ``visibility`` rows.

    ``candidate_order`` constrains/orders which candidates are eligible. With
    ``dfs=True`` we re-pick, at every step, the *highest remaining information
    gain* pose (deepest uncertainty first); with ``dfs=False`` we simply walk
    ``candidate_order`` (the lawnmower baseline visits its fixed sweep order).
    """
    n_surface = visibility.shape[1] if visibility.ndim == 2 else 0
    seen = np.zeros(n_surface, dtype=bool)
    selected: list[int] = []
    gains: list[int] = []

    if dfs:
        remaining = list(candidate_order)
        while remaining:
            best_idx = None
            best_gain = -1
            best_pos = None
            for pos, c in enumerate(remaining):
                g = information_gain(visibility[c], seen)
                if g > best_gain:
                    best_gain, best_idx, best_pos = g, c, pos
            if best_idx is None or best_gain <= 0:
                break
            seen |= visibility[best_idx]
            selected.append(best_idx)
            gains.append(best_gain)
            remaining.pop(best_pos)
            if coverage_fraction(seen) >= target_coverage:
                break
            if max_views is not None and len(selected) >= max_views:
                break
    else:
        for c in candidate_order:
            g = information_gain(visibility[c], seen)
            seen |= visibility[c]
            selected.append(c)
            gains.append(g)
            if coverage_fraction(seen) >= target_coverage:
                break
            if max_views is not None and len(selected) >= max_views:
                break

    return CoveragePlan(
        selected=selected,
        poses=[],  # filled by the caller that owns the pose list
        coverage=coverage_fraction(seen),
        seen_mask=seen,
        order_gain=gains,
    )


def generate_completion_poses(
    scene: VoxelScene,
    n_oblique: int = 8,
    oblique_radius_frac: float = 0.7,
    height_above: float = 15.0,
) -> list[Pose]:
    """Top-down + high-oblique poses that capture the roof / upper faces.

    A centroid-aimed orbit at mid-height frames the *facades* but never the
    roof (the top face points away from every orbit camera). Stage 3 completes
    coverage with one nadir pose over the building plus a ring of high-oblique
    views looking down at the roof apex -- the standard "oblique / smart
    oblique" capture pattern. Deterministic; no RNG.
    """
    top = scene.centroid_enu + np.array([0.0, 0.0, scene.building_height])
    nadir = Pose.looking_at(
        position=top + np.array([0.0, 0.0, 25.0]),
        target=top,
        up=np.array([0.0, 1.0, 0.0]),  # ENU +N as the image-up for a nadir shot
    )
    poses = [nadir]
    r = scene.orbit_radius * oblique_radius_frac
    z = scene.building_height + height_above
    for a in np.linspace(0, 2 * np.pi, n_oblique, endpoint=False):
        pos = np.array([r * np.cos(a), r * np.sin(a), z])
        poses.append(Pose.looking_at(position=pos, target=top))
    return poses


def order_orbit_poses(scene: VoxelScene, poses: list[Pose]) -> list[Pose]:
    """Sort a selected pose set into a flyable coverage-orbit order.

    A coverage orbit is a *ring*, not a set of arbitrary chords: flying the
    NBV-selected poses in their pick order can cut straight across the scene.
    Ordering by azimuth around the scene centroid turns the selection back into
    a monotone sweep around the building -- the natural, safe flight order for
    the Stage-3 mapping pass (true safe connectors / avoidance are Stage 5).
    """
    c = scene.centroid_enu

    def azimuth(p: Pose) -> float:
        d = p.position - c
        return float(np.arctan2(d[1], d[0]))

    return sorted(poses, key=azimuth)


def _build_visibility(scene: VoxelScene, camera: Camera, poses: list[Pose]) -> np.ndarray:
    n = len(scene.surface_indices)
    vis = np.zeros((len(poses), n), dtype=bool)
    for i, pose in enumerate(poses):
        vis[i] = visible_surface(scene, camera, pose)
    return vis


def nbv_plan(
    scene: VoxelScene,
    camera: Camera,
    candidate_poses: list[Pose],
    target_coverage: float = 0.90,
    max_views: int | None = None,
) -> CoveragePlan:
    """Next-best-view selection: deepest-uncertainty-first (DFS by info gain).

    Repeatedly picks the candidate pose that reveals the most still-unseen
    surface until ``target_coverage`` is reached or candidates are exhausted.
    This is the "DFS: descend into the most uncertain region" planner from the
    spec; it yields a near-minimal view set (Test 12).
    """
    vis = _build_visibility(scene, camera, candidate_poses)
    plan = _greedy_select(
        vis, list(range(len(candidate_poses))), target_coverage, max_views, dfs=True
    )
    plan.poses = [candidate_poses[i] for i in plan.selected]
    return plan


def lawnmower_plan(
    scene: VoxelScene,
    camera: Camera,
    candidate_poses: list[Pose],
    target_coverage: float = 0.90,
    max_views: int | None = None,
) -> CoveragePlan:
    """Dumb baseline: visit candidate poses in their given (sweep) order.

    No information-gain reasoning -- it just flies the fixed lawnmower / orbit
    order and keeps going until coverage is met. Used as the comparison point
    for NBV efficiency (Test 12).
    """
    vis = _build_visibility(scene, camera, candidate_poses)
    plan = _greedy_select(
        vis, list(range(len(candidate_poses))), target_coverage, max_views, dfs=False
    )
    plan.poses = [candidate_poses[i] for i in plan.selected]
    return plan


def theoretical_min_views(
    scene: VoxelScene, camera: Camera, candidate_poses: list[Pose], target_coverage: float = 0.90
) -> int:
    """A lower bound on the views needed to reach ``target_coverage``.

    Bound = ceil(target_voxels / max_single_pose_coverage): even the single
    most-informative pose can't cover more than its own visible set, so no plan
    can reach the target in fewer than this many views. Used as the denominator
    for the "<= 1.5x theoretical minimum" KPI (Test 12).
    """
    vis = _build_visibility(scene, camera, candidate_poses)
    n_surface = vis.shape[1]
    if n_surface == 0:
        return 0
    per_pose = vis.sum(axis=1)
    best = int(per_pose.max()) if per_pose.size else 0
    if best == 0:
        return len(candidate_poses)
    need = target_coverage * n_surface
    return int(np.ceil(need / best))


# ---------------------------------------------------------------------------
# End-to-end Stage-3 entry point
# ---------------------------------------------------------------------------


def map_aoi(
    scene: VoxelScene,
    camera: Camera,
    n_orbit_views: int = 24,
    target_coverage: float = 0.90,
    closeup_standoff: float = 8.0,
    max_closeups: int = 40,
) -> Model3D:
    """Run the Stage-3 plan over ``scene`` and emit a :class:`Model3D`.

    Pipeline: orbit candidates -> NBV-select a covering subset -> detect the
    remaining occluded frontier -> add a LoS close-up per resolvable face ->
    bundle surface voxels + posed image refs + final coverage.
    """
    candidates = generate_orbit_poses(scene, n_views=n_orbit_views)
    candidates = candidates + generate_completion_poses(scene)
    plan = nbv_plan(scene, camera, candidates, target_coverage=target_coverage)

    # Build the working image set from the selected orbit poses.
    chosen = list(plan.poses)
    vis = _build_visibility(scene, camera, chosen)
    image_set = PosedImageSet(scene=scene, camera=camera, poses=chosen, visibility=vis)

    # Resolve the remaining occluded faces with close-ups.
    frontiers = detect_occluded_faces(image_set)
    frontier_idx = np.where(frontiers)[0][:max_closeups]
    close = generate_closeups(scene, camera, frontier_idx, standoff=closeup_standoff)
    all_poses = chosen + close.poses

    final_vis = _build_visibility(scene, camera, all_poses)
    final_set = PosedImageSet(scene=scene, camera=camera, poses=all_poses, visibility=final_vis)

    return Model3D(
        surface_voxels=[list(map(float, v)) for v in scene.surface_voxels],
        voxel_size=scene.voxel_size,
        posed_images=to_posed_image_refs(all_poses),
        coverage=final_set.coverage(),
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
    "occlusion_recall",
    "order_orbit_poses",
    "target_gsd",
    "theoretical_min_views",
]
