"""End-to-end / integration tests (Team T6) for the footage pipeline.

These exercise :func:`pral.pipeline.run_pipeline` -- the Stage 1 -> Stage 5 glue
-- over synthetic :class:`~pral.sim.scenes.VoxelScene` worlds, plus the final
artifact contract against a stubbed downstream processing consumer.

Owned tests (from prd/footage-acquisition-test-cases.md):

* Test 24 (B): happy path -- one target, daylight -> CuratedFootageSet with
  >= 90% coverage, >= 3 shot types, 0 collisions, within battery.
* Test 25 (B): occlusion -- a tree-blocked face -> the final set contains a
  resolving close-up of that face.
* Test 26 (B): budget pressure -- reduced battery -> prioritizes the
  highest-value shots, lands safely, no crash.
* Test 27 (A): artifact contract -- the final CuratedFootageSet validates
  against the schema and is consumable by a stubbed downstream pipeline.
* Tests 28-31 (C, SKIP): real detection / interest-vs-human / reconstruction
  fidelity / footage quality -- real tests that collect and skip (need field
  data).
"""

from __future__ import annotations

import numpy as np
import pytest

from pral.core.camera import Camera, Pose
from pral.core.schemas import (
    CuratedFootageSet,
    ShotType,
    validate_curated_footage_set,
)
from pral.sim.flightsim import DroneConfig
from pral.sim.scenes import VoxelScene
from pral.stage5_path.grammar import check_variety

from pral.pipeline import CLOSEUP_TAG, PipelineResult, run_pipeline


def _cam() -> Camera:
    return Camera(hfov_deg=84.0, vfov_deg=53.0, width=640, height=480)


# ===========================================================================
# Test 24 (B) -- E2E happy path
# ===========================================================================


def test_24_happy_path_curated_footage_set():
    """One target, sim, daylight -> a complete, flyable, well-formed footage set.

    Asserts the four happy-path KPIs end-to-end: coverage >= 90%, >= 3 distinct
    shot types, 0 collisions, and the flight stays within the battery budget.
    """
    cam = _cam()
    scene = VoxelScene.make(
        building="box", height=30.0, width=20.0, depth=20.0,
        voxel_size=2.0, n_trees=4, n_poles=2,
    )

    result = run_pipeline(scene, cam, n_orbit_views=24, target_coverage=0.90)
    assert isinstance(result, PipelineResult)

    # --- coverage >= 90% of the AOI surface -------------------------------
    assert result.coverage >= 0.90, f"coverage {result.coverage:.3f} < 0.90"
    assert result.footage.coverage == pytest.approx(result.coverage)

    # --- >= 3 distinct shot types -----------------------------------------
    assert len(result.shot_types) >= 3, f"only {result.shot_types} shot types"
    assert check_variety(
        result.mission.shot_types, min(3, len(result.mission.shot_types))
    )

    # --- 0 collisions, within battery -------------------------------------
    flight = result.flight
    assert not flight.collided, f"collision at {flight.collision_point}"
    assert flight.completed, "happy path should complete the full mission"
    assert flight.ok
    assert flight.min_clearance >= DroneConfig().safety_margin
    assert 0.0 <= flight.battery_used <= 1.0
    assert flight.battery_remaining > 0.0, "ran out of battery on the happy path"

    # --- the emitted artifact is a real, validated CuratedFootageSet ------
    assert isinstance(result.footage, CuratedFootageSet)
    assert len(result.footage.clips) >= 3
    validate_curated_footage_set(result.footage.model_dump())


def test_24_mission_loads_and_flies_clean():
    """The emitted Mission loads into the sim and flies without error."""
    cam = _cam()
    scene = VoxelScene.make(building="box", height=28.0, voxel_size=2.0,
                            n_trees=3, n_poles=1)
    result = run_pipeline(scene, cam, target_coverage=0.90)

    mission = result.mission
    assert len(mission.waypoints) >= 2
    assert len(mission.shot_types) == len(mission.waypoints)
    # Every clip carries a pose, a shot type, and at least one interest tag.
    for clip in result.footage.clips:
        assert len(clip.poses) >= 1
        assert isinstance(clip.shot_type, ShotType)
        assert len(clip.interest_tags) >= 1


# ===========================================================================
# Test 25 (B) -- E2E occlusion -> resolving close-up
# ===========================================================================


def test_25_occlusion_yields_resolving_closeup():
    """A tree-blocked face must end up resolved by a close-up in the final set.

    The ``block_face`` scene plants a tree dead-on the +N orbit line, so that
    facade is occluded from every orbit camera (ground truth:
    ``scene.occluded_from_orbit``). The pipeline must (a) generate a
    line-of-sight close-up of a genuinely occluded face and (b) carry at least
    one such close-up clip into the final CuratedFootageSet.
    """
    cam = _cam()
    scene = VoxelScene.make(
        building="box", height=24.0, width=20.0, depth=20.0,
        voxel_size=2.0, n_trees=0, n_poles=0, block_face=True,
    )
    assert scene.occluded_from_orbit.any(), "block_face produced no occlusion truth"

    result = run_pipeline(scene, cam, target_coverage=0.85, max_closeups=12)

    # --- the pipeline generated close-ups, each resolving an occluded face --
    assert len(result.closeup_positions) > 0, "no close-up generated for blocked face"
    assert len(result.closeup_targets) == len(result.closeup_positions)

    occluded_centers = scene.surface_voxels[np.asarray(scene.occluded_from_orbit, bool)]
    for pos, target in zip(result.closeup_positions, result.closeup_targets):
        # The target is a genuine occluded-from-orbit face.
        d = np.linalg.norm(occluded_centers - target, axis=1)
        assert float(d.min()) < 1e-6, "close-up target is not an occluded face"
        # The close-up has clear line of sight to that face (and closes in).
        ijk = _nearest_surface_index(scene, target)
        ignore = {
            (int(ijk[0]) + di, int(ijk[1]) + dj, int(ijk[2]) + dk)
            for di in (-1, 0, 1) for dj in (-1, 0, 1) for dk in (-1, 0, 1)
        }
        assert scene.line_of_sight_clear(pos, target, ignore_indices=ignore)
        assert np.linalg.norm(pos - target) < scene.orbit_radius

    # --- at least one close-up clip survives into the final footage set ----
    closeup_clips = [c for c in result.footage.clips if CLOSEUP_TAG in c.interest_tags]
    assert len(closeup_clips) >= 1, "no resolving close-up made it into the footage set"

    # Each tagged clip's viewpoint matches a generated close-up position and
    # therefore resolves an occluded face.
    for clip in closeup_clips:
        cpos = np.asarray(clip.poses[0].position, float)
        d = np.linalg.norm(result.closeup_positions - cpos, axis=1)
        assert float(d.min()) < 1e-6

    # The whole thing still flies clean.
    assert not result.flight.collided
    assert result.flight.ok


def _nearest_surface_index(scene: VoxelScene, point_enu: np.ndarray) -> np.ndarray:
    """Index ``(i,j,k)`` of the surface voxel nearest ``point_enu``."""
    d = np.linalg.norm(scene.surface_voxels - point_enu, axis=1)
    return scene.surface_indices[int(np.argmin(d))]


# ===========================================================================
# Test 26 (B) -- E2E budget pressure
# ===========================================================================


def test_26_budget_pressure_lands_safely_prioritizing_value():
    """Reduced battery -> land safely, no crash, highest-value shots first.

    A tight battery cannot fly the whole mission. The drone must land safely
    (never crash), and the viewpoints it *selected* are the highest-value peaks
    (Stage-5 selection is value-sorted), so it spends its limited budget on the
    best shots.
    """
    cam = _cam()
    scene = VoxelScene.make(
        building="box", height=30.0, width=20.0, depth=20.0,
        voxel_size=2.0, n_trees=4, n_poles=2,
    )

    # Reference flight with a full battery completes.
    full = run_pipeline(scene, cam, target_coverage=0.90)
    assert full.flight.completed

    # Now squeeze the battery so the mission cannot finish.
    tight_cfg = DroneConfig(
        cruise_speed=4.0,
        safety_margin=1.5,
        battery_capacity_s=120.0,
        reserve_fraction=0.2,
    )
    tight = run_pipeline(
        scene, cam, target_coverage=0.90, cruise_speed=4.0, drone_config=tight_cfg
    )
    flight = tight.flight

    # --- no crash, lands safely -------------------------------------------
    assert not flight.collided, f"crashed under budget pressure at {flight.collision_point}"
    assert flight.landed_safely, "did not land safely under budget pressure"
    assert flight.ok
    assert not flight.completed, "tight battery should NOT complete the full mission"
    # Landed near the reserve floor: it kept flying until the budget hit the
    # reserve, then put down (one sim timestep of drain past the threshold).
    assert flight.battery_remaining > 0.0
    assert flight.battery_remaining <= tight_cfg.reserve_fraction + 1e-3

    # --- prioritizes the highest-value shots ------------------------------
    # Selection is value-sorted; the ordered viewpoints carry the top values.
    values = [sv.value for sv in tight.stage5.ordered_viewpoints]
    assert len(values) >= 1
    assert max(values) > 0.0

    # An explicit value cap keeps only the top-K highest-value viewpoints, and
    # the kept set's minimum value is no lower than the dropped ones.
    capped = run_pipeline(
        scene, cam, target_coverage=0.90, max_viewpoints=5, drone_config=tight_cfg,
        cruise_speed=4.0,
    )
    assert len(capped.stage5.ordered_viewpoints) <= 5
    kept_min = min(sv.value for sv in capped.stage5.ordered_viewpoints)
    all_values = sorted((sv.value for sv in tight.stage5.ordered_viewpoints), reverse=True)
    # Every kept viewpoint is among the highest-valued available.
    assert kept_min >= all_values[min(len(all_values), 5) - 1] - 1e-6
    assert not capped.flight.collided
    assert capped.flight.ok


# ===========================================================================
# Test 27 (A) -- E2E artifact contract + stubbed downstream consumer
# ===========================================================================


class StubProcessingPipeline:
    """A stubbed downstream consumer of a Curated Footage Set.

    Stands in for the real post-processing stage (stabilize / color / cut /
    publish). It validates the artifact against the schema, then walks every
    clip extracting exactly the fields the contract promises -- proving the
    deliverable is *consumable*, not just well-formed. Deterministic, no I/O.
    """

    def consume(self, footage_obj: dict) -> dict:
        """Validate + ingest a footage set; return a processing summary.

        Raises whatever :func:`validate_curated_footage_set` raises on a
        malformed artifact (jsonschema / pydantic ValidationError).
        """
        footage = validate_curated_footage_set(footage_obj)

        shot_types: set[str] = set()
        all_tags: set[str] = set()
        total_poses = 0
        rendered_clip_ids: list[str] = []

        for clip in footage.clips:
            # Each clip must expose a stable id, a known shot type, >= 1 pose,
            # and interest tags -- the contract the renderer relies on.
            assert clip.clip_id
            assert isinstance(clip.shot_type, ShotType)
            assert len(clip.poses) >= 1
            shot_types.add(clip.shot_type.value)
            all_tags.update(clip.interest_tags)
            total_poses += len(clip.poses)
            rendered_clip_ids.append(clip.clip_id)

        return {
            "aoi_name": footage.aoi_name,
            "home": (footage.home.lat, footage.home.lon, footage.home.alt),
            "coverage": footage.coverage,
            "n_clips": len(footage.clips),
            "n_shot_types": len(shot_types),
            "n_poses": total_poses,
            "tags": all_tags,
            "rendered_clip_ids": rendered_clip_ids,
        }


def test_27_artifact_validates_and_is_consumable():
    """The final CuratedFootageSet validates and the stub consumer ingests it."""
    cam = _cam()
    scene = VoxelScene.make(building="box", height=30.0, voxel_size=2.0,
                            n_trees=3, n_poles=1)
    result = run_pipeline(scene, cam, target_coverage=0.90)

    obj = result.footage.model_dump()

    # --- validates against the schema (jsonschema + pydantic) -------------
    validated = validate_curated_footage_set(obj)
    assert isinstance(validated, CuratedFootageSet)

    # --- consumable by a stubbed downstream processing pipeline -----------
    consumer = StubProcessingPipeline()
    summary = consumer.consume(obj)

    assert summary["n_clips"] == len(result.footage.clips)
    assert summary["n_clips"] >= 1
    assert summary["n_shot_types"] >= 3
    assert summary["n_poses"] >= summary["n_clips"]
    assert summary["coverage"] == pytest.approx(result.coverage)
    # Clip ids are unique (the renderer keys on them).
    assert len(set(summary["rendered_clip_ids"])) == summary["n_clips"]


def test_27_stub_consumer_rejects_malformed_artifact():
    """The stub consumer enforces the contract: a broken artifact is rejected."""
    import jsonschema

    cam = _cam()
    scene = VoxelScene.make(building="box", height=24.0, voxel_size=2.0,
                            n_trees=2, n_poles=1)
    result = run_pipeline(scene, cam, target_coverage=0.85)

    obj = result.footage.model_dump()
    obj["clips"][0]["shot_type"] = "barrel_roll"  # not a valid ShotType

    consumer = StubProcessingPipeline()
    with pytest.raises(jsonschema.ValidationError):
        consumer.consume(obj)


# ===========================================================================
# Tests 28-31 (C, SKIP) -- real-world fidelity (need field data)
# ===========================================================================


@pytest.mark.skip(reason="needs field data")
def test_28_detection_accuracy_on_real_aerial_set():
    """Tier C: building + hazard detection must hit recall/precision targets on a
    real, human-labeled aerial image set (recall >= 90%, <= 1 false positive per
    scene; hazard segmentation IoU >= 0.6). Synthetic scenes have no pixels, so
    only real imagery + labels can settle detection accuracy. Requires field
    data + a trained open-vocab detector / segmenter.
    """
    labeled_aerial = "field/aerial_labeled/*.json"  # noqa: F841
    # dets = detector.detect(load_images(labeled_aerial), ["building", "tree", "wire"])
    # recall, precision = score(dets, load_labels(labeled_aerial))
    # assert recall >= 0.90 and false_positives_per_scene(dets) <= 1
    raise AssertionError("detection accuracy cannot run without field data")


@pytest.mark.skip(reason="needs field data")
def test_29_interest_field_matches_human_picks():
    """Tier C: the per-image interest heatmaps must correlate (>= 0.6 Pearson)
    with human saliency labels, AND the value-field top-K viewpoints must overlap
    (>= 70%) with an expert pilot's chosen viewpoints, on a real captured scene.
    Synthetic interest is a geometric prior by construction; only real imagery +
    expert labels can prove the interest model matches human taste.
    """
    real_frames = "field/scene_frames/*.png"  # noqa: F841
    human_labels = "field/scene_human_saliency.npz"  # noqa: F841
    # heat = interest_heatmaps(real_frames); assert pearson(heat, human_labels) >= 0.6
    # vf = build_value_field(...); assert top_k_overlap(vf, expert_picks) >= 0.70
    raise AssertionError("interest-vs-human correlation cannot run without field data")


@pytest.mark.skip(reason="needs field data")
def test_30_reconstruction_fidelity_on_real_capture():
    """Tier C: running SfM (e.g. COLMAP) on the real captured orbit + close-ups
    must give mean reprojection residual < 2 px, and the close-ups must meet the
    target GSD on the real subject. Synthetic poses are exact by construction; a
    real capture with detected/matched features is the only honest fidelity test.
    Requires a field capture + SfM tooling.
    """
    real_capture = "field/aoi_capture/*.jpg"  # noqa: F841
    # recon = run_sfm(real_capture)
    # assert recon.mean_reprojection_error_px < 2.0
    # assert measured_gsd(recon, closeups) <= target_gsd
    raise AssertionError("reconstruction fidelity cannot run without field data")


@pytest.mark.skip(reason="needs field data")
def test_31_final_footage_quality_judged_by_human():
    """Tier C: the final rendered clips must be judged acceptable by a human
    reviewer (the ultimate footage-quality KPI). No synthetic proxy can settle
    whether the footage actually looks good -- it needs a real flight, real
    capture, and a human in the loop.
    """
    rendered_clips = "field/curated_set/clips/*.mp4"  # noqa: F841
    # scores = human_review(rendered_clips)
    # assert mean(scores) >= ACCEPTABLE_THRESHOLD
    raise AssertionError("footage-quality human judgement cannot run without field data")
