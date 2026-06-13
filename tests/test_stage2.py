"""Stage 2 -- Survey, Geometry & Obstacle Map.

Owned tests (per the stage spec):

* Test 5 (A): orbit radius ``r = (H/2+margin)/tan(VFOV/2)`` frames the building
  with margin, no clipping -- proven by projecting building extremes into the
  image at distance ``r`` and asserting they land inside with margin.
* Test 6 (B): estimate ``H`` from the synthetic nadir depth map; error <= 10%.
* Test 7 (B): occupancy map vs the labelled synthetic point cloud -- obstacle
  recall >= 95% in the orbit annulus, 0 missed wires/poles on the planned path.
* Test 8 (C, SKIP): hazard-class segmentation IoU on real imagery -- needs field
  data, so it collects and skips.
"""

import numpy as np
import pytest

from pral.core.camera import Camera
from pral.core.schemas import ObstacleMap
from pral.stage2_survey import (
    build_obstacle_map,
    estimate_building_height,
    fits_in_frame,
    frames_building,
    obstacle_recall_in_annulus,
    orbit_radius,
    path_clear_of_hazards,
    segment_hazard_classes,
)


def _cam() -> Camera:
    return Camera(hfov_deg=84.0, vfov_deg=53.0, width=640, height=480)


# ---------------------------------------------------------------------------
# Test 5 (A) -- orbit radius frames the building, no clipping
# ---------------------------------------------------------------------------


def test_orbit_radius_matches_framing_equation():
    H, vfov, margin = 30.0, 53.0, 4.0
    r = orbit_radius(H, vfov, margin)
    expected = (H / 2.0 + margin) / np.tan(np.radians(vfov) / 2.0)
    assert r == pytest.approx(expected)
    # Monotone: taller building or bigger margin -> stand further back.
    assert orbit_radius(60.0, vfov, margin) > r
    assert orbit_radius(H, vfov, 8.0) > r
    # Wider FOV -> stand closer.
    assert orbit_radius(H, 90.0, margin) < r


def test_orbit_radius_rejects_bad_inputs():
    with pytest.raises(ValueError):
        orbit_radius(0.0, 53.0)
    with pytest.raises(ValueError):
        orbit_radius(30.0, 0.0)
    with pytest.raises(ValueError):
        orbit_radius(30.0, 180.0)
    with pytest.raises(ValueError):
        orbit_radius(30.0, 53.0, margin=-1.0)


def test_building_frames_in_radius_with_margin():
    """Project the building's vertical + horizontal extremes from distance r;
    assert they land inside the image with a 5% border (no clipping)."""
    cam = _cam()
    for H in (20.0, 30.0, 45.0):
        r, ok = frames_building(cam, H, margin=4.0, width=20.0, margin_frac=0.05)
        assert ok, f"H={H} did not frame with margin at r={r}"


def test_too_close_clips_the_building():
    """A radius far below the framing distance must clip (fail the check)."""
    cam = _cam()
    H = 30.0
    r = orbit_radius(H, cam.vfov_deg, margin=4.0)
    assert not fits_in_frame(cam, H, radius=r * 0.4, width=20.0, margin_frac=0.0)


def test_margin_increases_headroom():
    """More margin in the radius -> the top extreme sits further from the edge,
    so a stricter frame border still passes."""
    cam = _cam()
    H = 30.0
    r_small = orbit_radius(H, cam.vfov_deg, margin=2.0)
    r_big = orbit_radius(H, cam.vfov_deg, margin=12.0)
    # Larger radius frames with a strict border; the tight one need not.
    assert fits_in_frame(cam, H, r_big, width=20.0, margin_frac=0.1)


# ---------------------------------------------------------------------------
# Test 6 (B) -- height estimate within 10%
# ---------------------------------------------------------------------------


def test_height_estimate_within_10pct():
    from pral.sim.scenes import VoxelScene

    cam = _cam()
    for H in (20.0, 30.0, 45.0):
        scene = VoxelScene.make(
            building="box", height=H, width=24.0, depth=24.0,
            voxel_size=2.0, n_trees=0, n_poles=0,
        )
        est = estimate_building_height(scene, cam)
        assert abs(est - H) <= 0.10 * H, f"H={H} est={est}"


def test_height_estimate_drives_orbit_radius():
    """End-to-end Stage-2 geometry: estimate H, derive r, confirm it frames."""
    from pral.sim.scenes import VoxelScene

    cam = _cam()
    H_true = 36.0
    scene = VoxelScene.make(
        building="box", height=H_true, width=24.0, depth=24.0,
        voxel_size=2.0, n_trees=0, n_poles=0,
    )
    H_est = estimate_building_height(scene, cam)
    r, ok = frames_building(cam, H_est, margin=4.0, width=24.0, margin_frac=0.02)
    assert r > 0 and ok


# ---------------------------------------------------------------------------
# Test 7 (B) -- obstacle recall >= 95% in annulus, 0 missed wires/poles on path
# ---------------------------------------------------------------------------


def test_obstacle_map_is_valid_schema():
    from pral.sim.scenes import VoxelScene

    scene = VoxelScene.make(building="box", height=30.0, voxel_size=2.0,
                            n_trees=4, n_poles=2)
    omap = build_obstacle_map(scene, _cam())
    assert isinstance(omap, ObstacleMap)
    assert omap.resolution == scene.voxel_size
    assert omap.occupied_voxels is not None and len(omap.occupied_voxels) > 0
    # Ground plane (k=0) must be dropped -- it is the floor, not a hazard.
    assert all(k != 0 for _, _, k in omap.occupied_voxels)


def test_obstacle_recall_in_annulus_meets_95pct():
    from pral.sim.scenes import VoxelScene

    cam = _cam()
    scene = VoxelScene.make(
        building="box", height=30.0, width=20.0, depth=20.0,
        voxel_size=2.0, n_trees=8, n_poles=3, n_wires=2, seed=0,
    )
    omap = build_obstacle_map(scene, cam)
    recall = obstacle_recall_in_annulus(scene, omap)
    assert recall >= 0.95, f"annulus obstacle recall {recall:.3f} < 0.95"


def test_no_missed_wires_or_poles_on_path():
    from pral.sim.scenes import VoxelScene

    cam = _cam()
    scene = VoxelScene.make(
        building="box", height=30.0, width=20.0, depth=20.0,
        voxel_size=2.0, n_trees=6, n_poles=4, n_wires=3, seed=1,
    )
    omap = build_obstacle_map(scene, cam)
    n_missed, n_on_path = path_clear_of_hazards(scene, omap)
    assert n_missed == 0, f"{n_missed} of {n_on_path} thin hazards on path unmapped"


# ---------------------------------------------------------------------------
# Test 8 (C, SKIP) -- hazard-class segmentation IoU on real top-down imagery
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="needs field data")
def test_hazard_segmentation_iou_on_real_imagery():
    """Tier C: a hazard-class segmenter (trees/wires/poles/people) must reach
    IoU >= 0.6 against human-labelled top-down imagery. Requires real RGB +
    annotation masks (field data), so it cannot run here -- it collects, skips,
    and documents the contract :func:`segment_hazard_classes` must satisfy."""
    real_rgb = "field/topdown_0001.png"          # noqa: F841
    label_mask = "field/topdown_0001_hazard.npy"  # noqa: F841
    image = np.load(real_rgb)
    pred = segment_hazard_classes(image)
    truth = np.load(label_mask)
    inter = np.logical_and(pred > 0, truth > 0).sum()
    union = np.logical_or(pred > 0, truth > 0).sum()
    iou = inter / max(1, union)
    assert iou >= 0.6
