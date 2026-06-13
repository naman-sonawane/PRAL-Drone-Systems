"""End-to-end footage-acquisition pipeline (Stage 1 -> Stage 5).

This is the integration glue (Team T6). It wires the five stages together over
a synthetic :class:`~pral.sim.scenes.VoxelScene`, producing a validated
:class:`~pral.core.schemas.CuratedFootageSet` plus a flyable
:class:`~pral.core.schemas.Mission`.

The flow mirrors the execution spec::

    Stage 1  SELECT + CONFIRM   GPS pin -> home frame -> geofenced AOI
    Stage 2  SURVEY + GEOMETRY  orbit radius r + obstacle map
    Stage 3  360 MAP (NBV/DFS)  orbit + close-ups -> Model3D (surface + coverage)
    Stage 4  INTEREST FIELD     lift surface -> hotspots -> value over viewpoints
    Stage 5  PATH + SHOTS       select -> TSP -> trajectory -> variety -> mission

Everything is deterministic: every RNG is the seeded ``default_rng(0)`` inside
the sim/stage code, no wall-clock, no randomness in asserted values. No real
imagery, no heavy CV -- the synthetic scene is the ground-truth backbone and the
interest signal is taken as a geometric prior (the Tier-C "real heatmap" half is
out of scope, as the test-case spec dictates).

Public entry point: :func:`run_pipeline`. It returns a :class:`PipelineResult`
that bundles every stage artifact for inspection by the E2E tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pral.core.camera import Camera, Pose
from pral.core.schemas import (
    AOI,
    CuratedFootageSet,
    HomeFrame,
    Mission,
    Model3D,
    ObstacleMap,
    ValueField,
)
from pral.sim.flightsim import DroneConfig, FlightResult, simulate_mission
from pral.sim.posed_images import (
    PosedImageSet,
    closeup_pose_for_frontier,
    generate_orbit_poses,
    visible_surface,
)
from pral.sim.scenes import VoxelScene
from pral.stage1_select.aoi import confirm_aoi
from pral.stage1_select.gps_frame import HomeFrameRef, home_from_pin
from pral.stage2_survey.geometry import frames_building
from pral.stage2_survey.obstacles import build_obstacle_map
from pral.stage3_map.mapping import (
    detect_occluded_faces,
    generate_completion_poses,
    map_aoi,
)
from pral.stage4_interest.value_field import (
    FocalParams,
    FramingParams,
    Hotspot,
    build_value_field,
)
from pral.stage5_path.mission import Stage5Result, build_mission

# A tag carried by clips whose viewpoint resolves an occluded face -- the E2E
# occlusion test (Test 25) keys off this to confirm a close-up made the cut.
CLOSEUP_TAG = "occlusion_closeup"


@dataclass
class PipelineResult:
    """Every artifact the end-to-end run produces, for inspection + tests."""

    home: HomeFrameRef
    aoi: AOI
    orbit_radius: float
    frames_ok: bool
    obstacle_map: ObstacleMap
    model: Model3D
    value_field: ValueField
    stage5: Stage5Result
    flight: FlightResult
    closeup_positions: np.ndarray  # [m, 3] ENU close-up camera positions
    closeup_targets: np.ndarray  # [m, 3] ENU occluded-face centers resolved

    # --- convenience accessors the E2E tests read ------------------------
    @property
    def mission(self) -> Mission:
        return self.stage5.mission

    @property
    def footage(self) -> CuratedFootageSet:
        return self.stage5.footage

    @property
    def coverage(self) -> float:
        return self.model.coverage

    @property
    def shot_types(self) -> set[str]:
        return {c.shot_type.value for c in self.footage.clips}


# ---------------------------------------------------------------------------
# Stage 4 helper: lift the Stage-3 surface into 3D interest hotspots
# ---------------------------------------------------------------------------


def _outward_normal(scene: VoxelScene, point_enu: np.ndarray) -> np.ndarray:
    """Outward (away-from-building) unit normal at a surface point.

    For a centroid-symmetric facade the outward direction is the horizontal
    vector from the building axis to the point; the roof points up. We pick
    whichever of the horizontal-radial / vertical-up directions dominates, a
    cheap stand-in for the true voxel face normal that is correct for the
    facade and roof voxels coverage actually cares about.
    """
    d = np.asarray(point_enu, float) - scene.centroid_enu
    horiz = np.array([d[0], d[1], 0.0])
    hn = np.linalg.norm(horiz)
    up_extent = point_enu[2] - (scene.centroid_enu[2] + scene.building_height)
    # Near the roof line the vertical component dominates -> point up.
    if up_extent > -scene.voxel_size and hn < 1e-6:
        return np.array([0.0, 0.0, 1.0])
    if hn < 1e-9:
        return np.array([0.0, 0.0, 1.0])
    return horiz / hn


def build_hotspots(
    scene: VoxelScene,
    image_set: PosedImageSet | None = None,
    base_interest: float = 1.0,
    occlusion_boost: float = 2.0,
) -> list[Hotspot]:
    """Turn the known building surface into a list of interest :class:`Hotspot`.

    Each surface voxel becomes a hotspot at its ENU center with an outward
    normal. Interest is uniform ``base_interest`` except occluded faces (from
    ``image_set`` if given, else the scene's orbit-occlusion ground truth) which
    are up-weighted by ``occlusion_boost`` -- they are the rare, hard-won detail
    the close-up shots exist to capture, so they should attract value.

    In the real pipeline this interest comes from per-image heatmaps (Canny /
    Laplacian / saliency); here it is a deterministic geometric prior, which is
    all the Tier-A/B tests need.
    """
    surface = scene.surface_voxels
    if len(surface) == 0:
        return []
    if image_set is not None:
        occluded = detect_occluded_faces(image_set)
    else:
        occluded = np.asarray(scene.occluded_from_orbit, dtype=bool)
        if occluded.shape[0] != len(surface):
            occluded = np.zeros(len(surface), dtype=bool)

    hotspots: list[Hotspot] = []
    for i, p in enumerate(surface):
        interest = base_interest * (occlusion_boost if occluded[i] else 1.0)
        hotspots.append(Hotspot(position=p, normal=_outward_normal(scene, p), interest=interest))
    return hotspots


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


def run_pipeline(
    scene: VoxelScene,
    camera: Camera,
    *,
    home_lat: float = 37.4275,
    home_lon: float = -122.1697,
    home_alt: float = 0.0,
    aoi_name: str | None = "pipeline_target",
    n_orbit_views: int = 24,
    target_coverage: float = 0.90,
    closeup_standoff: float = 8.0,
    n_distinct_shots: int = 3,
    max_closeups: int = 12,
    max_viewpoints: int | None = None,
    focal_optimal: float | None = None,
    cruise_speed: float = 4.0,
    safety_margin: float = 1.5,
    drone_config: DroneConfig | None = None,
) -> PipelineResult:
    """Run the full Stage 1 -> Stage 5 footage-acquisition pipeline.

    Parameters mirror the per-stage knobs; defaults give a clean daylight happy
    path on a procedural :class:`VoxelScene`. The returned
    :class:`PipelineResult` carries every artifact + the simulated flight.

    Raises
    ------
    ValueError
        If Stage 5 finds no admissible viewpoint to fly (propagated from
        :func:`pral.stage5_path.mission.build_mission`).
    """
    config = drone_config or DroneConfig(
        cruise_speed=cruise_speed, safety_margin=safety_margin
    )

    # ---- Stage 1: GPS pin -> home frame -> geofenced AOI -----------------
    home = home_from_pin(home_lat, home_lon, home_alt)
    aoi = _confirm_scene_aoi(scene, home, aoi_name)

    # ---- Stage 2: orbit geometry + obstacle map --------------------------
    orbit_r, frames_ok = frames_building(
        camera, scene.building_height, margin=4.0, width=0.0
    )
    obstacle_map = build_obstacle_map(scene, camera)

    # ---- Stage 3: 360 NBV map + occlusion close-ups -> Model3D -----------
    model = map_aoi(
        scene,
        camera,
        n_orbit_views=n_orbit_views,
        target_coverage=target_coverage,
        closeup_standoff=closeup_standoff,
        max_closeups=max_closeups,
    )

    # ---- Stage 4: candidate viewpoints + interest value field ------------
    orbit_poses = generate_orbit_poses(scene, n_views=n_orbit_views)
    completion = generate_completion_poses(scene)
    # Occlusion close-ups resolve faces the *orbit ring* cannot see (the
    # tree-blocked facades) -- exactly the frontier Stage-3 close-ups target.
    # Completion (roof/oblique) poses are coverage, not occlusion resolution.
    orbit_set = _image_set(scene, camera, orbit_poses)
    closeup_poses, closeup_targets = _closeup_poses(
        scene, camera, orbit_set, closeup_standoff, max_closeups
    )

    candidate_poses = orbit_poses + completion + closeup_poses
    # Interest prior uses the scene's orbit-occlusion ground truth so the rare
    # blocked faces attract the value that pulls a close-up into the mission.
    hotspots = build_hotspots(scene, image_set=orbit_set)
    focal_params = FocalParams(
        optimal=focal_optimal if focal_optimal is not None else orbit_r,
        sigma=max(4.0, orbit_r * 0.5),
    )
    value_field = build_value_field(
        camera,
        candidate_poses,
        hotspots,
        focal_params=focal_params,
        framing_params=FramingParams(),
    )

    # ---- Stage 5: select -> TSP -> trajectory -> variety -> mission ------
    stage5 = build_mission(
        value_field,
        aoi,
        scene,
        home=home.to_home_frame(),
        aoi_name=aoi_name,
        coverage=model.coverage,
        n_distinct_shots=n_distinct_shots,
        cruise_speed=cruise_speed,
        safety_margin=safety_margin,
        min_altitude=0.0,
        max_count=max_viewpoints,
    )

    # Tag any clip whose viewpoint resolves an occluded face as a close-up.
    closeup_positions = (
        np.array([p.position for p in closeup_poses])
        if closeup_poses
        else np.empty((0, 3))
    )
    _tag_closeup_clips(stage5, closeup_positions)

    # ---- Fly the emitted mission in the kinematic sim --------------------
    flight = simulate_mission(stage5.mission, obstacle=scene, config=config)

    return PipelineResult(
        home=home,
        aoi=aoi,
        orbit_radius=orbit_r,
        frames_ok=frames_ok,
        obstacle_map=obstacle_map,
        model=model,
        value_field=value_field,
        stage5=stage5,
        flight=flight,
        closeup_positions=closeup_positions,
        closeup_targets=(
            np.array(closeup_targets) if closeup_targets else np.empty((0, 3))
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _confirm_scene_aoi(
    scene: VoxelScene, home: HomeFrameRef, name: str | None
) -> AOI:
    """Build a geofenced AOI polygon around the scene building footprint.

    The footprint is a square centred on the building centroid, sized to enclose
    the full orbit annulus (so every flyable viewpoint sits inside the
    geofence). Altitude ceiling is set above the building + orbit altitude.
    """
    c = scene.centroid_enu
    half = scene.orbit_radius * 1.6 + 4.0 * scene.voxel_size
    poly = [
        [float(c[0] - half), float(c[1] - half)],
        [float(c[0] + half), float(c[1] - half)],
        [float(c[0] + half), float(c[1] + half)],
        [float(c[0] - half), float(c[1] + half)],
    ]
    ceiling = max(120.0, scene.building_height + 60.0)
    return confirm_aoi(home, poly, max_altitude=ceiling, name=name)


def _image_set(scene: VoxelScene, camera: Camera, poses: list[Pose]) -> PosedImageSet:
    n = len(scene.surface_indices)
    vis = np.zeros((len(poses), n), dtype=bool)
    for i, pose in enumerate(poses):
        vis[i] = visible_surface(scene, camera, pose)
    return PosedImageSet(scene=scene, camera=camera, poses=poses, visibility=vis)


def _closeup_poses(
    scene: VoxelScene,
    camera: Camera,
    base_set: PosedImageSet,
    standoff: float,
    max_closeups: int,
) -> tuple[list[Pose], list[np.ndarray]]:
    """Generate a LoS close-up pose per resolvable occluded face.

    Returns the close-up poses plus the ENU centers of the occluded faces they
    resolve (parallel lists), so the E2E occlusion test can confirm the final
    footage set covers the blocked face.
    """
    frontier_idx = np.where(detect_occluded_faces(base_set))[0][:max_closeups]
    poses: list[Pose] = []
    targets: list[np.ndarray] = []
    for f in frontier_idx:
        pose = closeup_pose_for_frontier(scene, camera, int(f), standoff=standoff)
        if pose is not None:
            poses.append(pose)
            targets.append(scene.index_to_enu(scene.surface_indices[int(f)]))
    return poses, targets


def _tag_closeup_clips(stage5: Stage5Result, closeup_positions: np.ndarray) -> None:
    """Add the :data:`CLOSEUP_TAG` to clips whose viewpoint is a close-up.

    Matches each ordered viewpoint position against the generated close-up
    camera positions; an exact match (these poses flow through selection
    unchanged) means that clip resolves an occluded face.
    """
    if closeup_positions.size == 0:
        return
    for clip, sv in zip(stage5.footage.clips, stage5.ordered_viewpoints):
        d = np.linalg.norm(closeup_positions - sv.position, axis=1)
        if np.min(d) < 1e-6 and CLOSEUP_TAG not in clip.interest_tags:
            clip.interest_tags.append(CLOSEUP_TAG)


__all__ = [
    "CLOSEUP_TAG",
    "PipelineResult",
    "build_hotspots",
    "run_pipeline",
]
