"""Stage 4 -- Interest Field & Value Assignment tests.

Owned tests (per the stage brief):

* Test 14 (A): ``focal()`` peaks at the configured optimal distance and falls
  off monotonically on both sides.
* Test 15 (A): ``value(v)`` matches a hand-computed score on synthetic
  hotspots / framing / focal fixtures.
* Test 16 (A): a fake per-pixel heatmap + a known pose projects onto the
  correct 3D surface point with localization error < 1 m.
* Test 17 (C, SKIP): per-image heatmap correlation >= 0.6 with human labels.
* Test 18 (C, SKIP): value-field top-10 overlap >= 70% with expert viewpoints.

All Tier-A tests are pure geometry/math on deterministic fixtures -- no images.
"""

import numpy as np
import pytest

from pral.core.camera import Camera, Pose
from pral.core.schemas import ValueField
from pral.stage4_interest import (
    FocalParams,
    FramingParams,
    Hotspot,
    build_value_field,
    focal,
    framing,
    project_heatmap_to_surface,
    viewpoint_value,
)


def _cam() -> Camera:
    return Camera(hfov_deg=84.0, vfov_deg=53.0, width=640, height=480)


# ---------------------------------------------------------------------------
# Test 14 (A) -- focal() weighting
# ---------------------------------------------------------------------------


def test_14_focal_peaks_at_optimal_and_falls_off_both_sides():
    params = FocalParams(optimal=12.0, sigma=6.0)

    # Peak is exactly 1.0 at the optimal distance.
    assert focal(params.optimal, params) == pytest.approx(1.0)

    # Sweep a dense range of distances and split at the optimum.
    dists = np.linspace(0.1, 40.0, 400)
    weights = focal(dists, params)

    # The global maximum sits at the optimal distance.
    assert dists[int(np.argmax(weights))] == pytest.approx(params.optimal, abs=0.2)

    # Strictly monotone increasing below the optimum...
    below = weights[dists < params.optimal]
    assert np.all(np.diff(below) > 0)
    # ...and strictly monotone decreasing above it.
    above = weights[dists > params.optimal]
    assert np.all(np.diff(above) < 0)

    # Symmetric falloff: equal offsets on each side give equal weight.
    assert focal(params.optimal - 4.0, params) == pytest.approx(
        focal(params.optimal + 4.0, params)
    )

    # A different optimum shifts the peak.
    near = FocalParams(optimal=5.0, sigma=2.0)
    w = focal(dists, near)
    assert dists[int(np.argmax(w))] == pytest.approx(near.optimal, abs=0.2)


# ---------------------------------------------------------------------------
# Test 15 (A) -- value(v) viewpoint score
# ---------------------------------------------------------------------------


def test_15_value_matches_hand_computed_score():
    cam = _cam()
    fp = FocalParams(optimal=12.0, sigma=6.0)
    frp = FramingParams(facing_power=1.0, center_weight=0.5)

    # Hotspot A: at the world origin, outward normal +E, interest 2.0.
    h_a = Hotspot(position=[0.0, 0.0, 0.0], normal=[1.0, 0.0, 0.0], interest=2.0)

    # Camera straight out along +E at exactly the optimal distance, looking back
    # at the hotspot. By construction: dist == optimal -> focal == 1; view dir is
    # exactly -normal -> facing == 1; the look-at target projects to the image
    # center -> in-frame centredness == 1 -> framing == 1. So value == interest.
    pose = Pose.looking_at(position=[12.0, 0.0, 0.0], target=h_a.position)

    assert focal(12.0, fp) == pytest.approx(1.0)
    assert framing(cam, pose, h_a, frp) == pytest.approx(1.0)
    assert viewpoint_value(cam, pose, [h_a], fp, frp) == pytest.approx(2.0)

    # Add hotspot B off to the side so it is in view but neither straight-on nor
    # at the optimal distance -- recompute the full sum factor by factor.
    h_b = Hotspot(position=[2.0, 6.0, 0.0], normal=[1.0, 0.0, 0.0], interest=1.5)

    expected = 2.0  # contribution of A
    f_b = framing(cam, pose, h_b, frp)
    d_b = float(np.linalg.norm(np.array(h_b.position) - pose.position))
    expected += h_b.interest * f_b * float(focal(d_b, fp))

    assert 0.0 < f_b < 1.0  # B is genuinely off-axis but visible
    assert viewpoint_value(cam, pose, [h_a, h_b], fp, frp) == pytest.approx(expected)

    # A back-facing hotspot (normal pointing away from the camera) scores 0.
    h_back = Hotspot(position=[0.0, 0.0, 0.0], normal=[-1.0, 0.0, 0.0], interest=5.0)
    assert framing(cam, pose, h_back, frp) == 0.0
    assert viewpoint_value(cam, pose, [h_back], fp, frp) == pytest.approx(0.0)


def test_15b_value_field_artifact_is_well_formed():
    cam = _cam()
    h = Hotspot(position=[0.0, 0.0, 0.0], normal=[1.0, 0.0, 0.0], interest=1.0)
    poses = [
        Pose.looking_at(position=[d, 0.0, 0.0], target=h.position)
        for d in (6.0, 12.0, 20.0)
    ]
    vf = build_value_field(cam, poses, [h], FocalParams(optimal=12.0, sigma=6.0))
    assert isinstance(vf, ValueField)
    assert len(vf.samples) == 3
    values = [s.value for s in vf.samples]
    # The viewpoint at the optimal distance is the highest-value sample.
    assert int(np.argmax(values)) == 1


# ---------------------------------------------------------------------------
# Test 16 (A) -- 3D interest-density projection / localization
# ---------------------------------------------------------------------------


def test_16_heatmap_projects_to_correct_surface_point():
    cam = _cam()

    # A small wall of surface points in the E=0 plane, ~0.5 m apart, facing -E.
    coords = np.arange(-3.0, 3.5, 0.5)
    surface = np.array(
        [[0.0, n, u] for n in coords for u in coords], dtype=float
    )

    # Camera 12 m out along -E looking at the wall center; the wall faces it.
    pose = Pose.looking_at(position=[-12.0, 0.0, 0.0], target=[0.0, 0.0, 0.0])

    # Pick a known target surface point and find the pixel it projects to.
    target_pt = np.array([0.0, 1.5, -2.0])
    p_c = pose.world_to_camera(target_pt)
    u = int(round(cam.fx * p_c[0] / p_c[2] + cam.cx))
    v = int(round(cam.fy * p_c[1] / p_c[2] + cam.cy))

    # A heatmap that is bright at exactly that pixel and dark elsewhere.
    heatmap = np.zeros((cam.height, cam.width), dtype=float)
    heatmap[v, u] = 1.0

    hotspots = project_heatmap_to_surface(cam, pose, heatmap, surface, threshold=0.0)

    # Exactly one bright surface point recovered (others sample 0 and drop).
    assert len(hotspots) == 1
    err = float(np.linalg.norm(hotspots[0].position - target_pt))
    assert err < 1.0, f"localization error {err:.3f} m exceeds 1 m"
    assert hotspots[0].interest == pytest.approx(1.0)
    # Recovered normal points back toward the camera (a valid front-face normal).
    assert float(np.dot(hotspots[0].normal, [-1.0, 0.0, 0.0])) > 0.9


def test_16b_offscreen_and_behind_points_are_dropped():
    cam = _cam()
    pose = Pose.looking_at(position=[-12.0, 0.0, 0.0], target=[0.0, 0.0, 0.0])
    heatmap = np.ones((cam.height, cam.width), dtype=float)
    # One point in front (in view) and one behind the camera.
    surface = np.array([[0.0, 0.0, 0.0], [-30.0, 0.0, 0.0]], dtype=float)
    hotspots = project_heatmap_to_surface(cam, pose, heatmap, surface)
    assert len(hotspots) == 1
    assert np.allclose(hotspots[0].position, [0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# Test 17 (C, SKIP) -- per-image heatmap vs human labels
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="needs field data")
def test_17_heatmap_correlates_with_human_labels():
    """Tier C: the per-image interest heatmap (Canny lines + Laplacian/entropy
    texture + saliency) must correlate >= 0.6 (Pearson) with a human-annotated
    saliency map on real captured frames. Requires real RGB + human labels.
    """
    real_rgb = "field/frame_0007.png"  # noqa: F841
    human_saliency = "field/frame_0007_saliency.npy"  # noqa: F841
    # pred = interest_heatmap(real_rgb)
    # human = np.load(human_saliency)
    # r = pearson(pred.ravel(), human.ravel()); assert r >= 0.6
    raise AssertionError("heatmap-vs-human correlation cannot run without field data")


# ---------------------------------------------------------------------------
# Test 18 (C, SKIP) -- value-field top-K vs expert viewpoints
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="needs field data")
def test_18_value_field_top10_overlaps_expert_picks():
    """Tier C: the top-10 viewpoints of the value field must overlap >= 70% with
    a pilot/expert's chosen viewpoints on a real captured scene. Requires a real
    posed-image set + expert-labelled viewpoint picks (field data).
    """
    expert_viewpoints = "field/scene_expert_viewpoints.json"  # noqa: F841
    # vf = build_value_field(cam, candidate_poses, hotspots_from_real_capture)
    # top10 = top_k_viewpoints(vf, 10)
    # assert overlap(top10, load(expert_viewpoints)) >= 0.70
    raise AssertionError("value-field vs expert overlap cannot run without field data")
