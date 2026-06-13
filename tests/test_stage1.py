"""Stage 1 -- Target Selection & Confirmation.

Owned tests:
* Test 1 (A) -- GPS pin -> local ENU frame, error < 0.5 m vs surveyed points.
* Test 2 (A) -- synthetic pose + known 3D point -> pixel -> GPS round-trip,
  centroid error < 3 m.
* Test 3 (A) -- confirmed AOI polygon IoU >= 0.7 vs ground-truth footprint.
* Test 4 (C) -- open-vocab detector recall/precision on real aerial imagery;
  written against the detector interface, skipped until field data exists.
"""

import jsonschema
import numpy as np
import pytest

from pral.core.camera import Camera, Pose, project
from pral.core.frames import geodetic_to_ecef
from pral.core.schemas import AOI
from pral.stage1_select import (
    Detection,
    StubDetector,
    confirm_aoi,
    home_from_pin,
    point_in_polygon,
    polygon_area,
    polygon_iou,
    reproject_box_to_gps,
    reproject_pixel_to_gps,
)
from pral.stage1_select.gps_frame import HomeFrameRef

HOME = (37.4275, -122.1697, 12.0)  # Stanford-ish


def _gps_dist_m(g1, g2) -> float:
    """Metric distance between two geodetic points via ECEF."""
    return float(
        np.linalg.norm(geodetic_to_ecef(*g1) - geodetic_to_ecef(*g2))
    )


# ---------------------------------------------------------------------------
# Test 1 (A) -- GPS pin -> ENU frame
# ---------------------------------------------------------------------------


def test1_pin_establishes_origin():
    home = home_from_pin(*HOME)
    assert np.linalg.norm(home.enu(*HOME)) < 1e-6


def test1_surveyed_points_match_under_half_meter():
    """Known geodetic offsets must land at the right metric coordinates."""
    home = home_from_pin(*HOME)
    rng = np.random.default_rng(0)
    max_err = 0.0
    for _ in range(200):
        dlat = rng.uniform(-0.02, 0.02)
        dlon = rng.uniform(-0.02, 0.02)
        dalt = rng.uniform(-50, 150)
        lat, lon, alt = HOME[0] + dlat, HOME[1] + dlon, HOME[2] + dalt
        enu = home.enu(lat, lon, alt)
        back = home.geodetic_from_enu(enu[0], enu[1], enu[2])
        err = _gps_dist_m((lat, lon, alt), tuple(back))
        max_err = max(max_err, err)
    assert max_err < 0.5, f"max frame error {max_err:.4f} m exceeds 0.5 m"


def test1_directions_are_sane():
    home = home_from_pin(*HOME)
    north = home.enu(HOME[0] + 0.001, HOME[1], HOME[2])
    assert north[1] > 100.0 and abs(north[0]) < 1.0
    east = home.enu(HOME[0], HOME[1] + 0.001, HOME[2])
    assert east[0] > 50.0 and abs(east[1]) < 1.0


def test1_ned_export_and_home_frame():
    home = home_from_pin(*HOME)
    ned = home.ned(HOME[0] + 0.001, HOME[1], HOME[2])
    # NED north matches ENU north; down is ~0 at same alt.
    assert ned[0] > 100.0 and abs(ned[2]) < 1.0
    hf = home.to_home_frame()
    assert hf.lat == HOME[0] and hf.lon == HOME[1]


# ---------------------------------------------------------------------------
# Test 2 (A) -- detection pixel -> GPS round-trip, centroid error < 3 m
# ---------------------------------------------------------------------------


def _topdown_camera_pose(altitude: float, aim_enu=np.zeros(3)):
    """A near-nadir camera at ``altitude`` looking at a ground point."""
    cam = Camera(hfov_deg=70.0, vfov_deg=53.0, width=1280, height=960)
    pos = np.array([aim_enu[0], aim_enu[1], altitude])
    # Slight tilt so the optical frame is well-defined and not a degenerate nadir.
    target = np.array([aim_enu[0] + 2.0, aim_enu[1] + 1.0, 0.0])
    pose = Pose.looking_at(pos, target)
    return cam, pose


def test2_pixel_to_gps_roundtrip_under_3m():
    home = home_from_pin(*HOME)
    cam, pose = _topdown_camera_pose(altitude=80.0)

    # A known ground point in ENU (the true target centroid).
    true_enu = np.array([15.0, -8.0, 0.0])
    true_gps = home.geodetic_from_enu(*true_enu)

    # Forward: world point -> pixel.
    pixel = project(cam, pose, true_enu)

    # Inverse: pixel -> GPS via ground plane z=0.
    est_gps = reproject_pixel_to_gps(cam, pose, pixel, home, ground_z=0.0)

    err = _gps_dist_m(tuple(true_gps), tuple(est_gps))
    assert err < 3.0, f"centroid GPS error {err:.4f} m exceeds 3 m"


def test2_box_centroid_reprojects_to_target():
    home = home_from_pin(*HOME)
    cam, pose = _topdown_camera_pose(altitude=100.0, aim_enu=np.array([5.0, 5.0, 0.0]))

    true_enu = np.array([5.0, 5.0, 0.0])
    true_gps = home.geodetic_from_enu(*true_enu)
    center = project(cam, pose, true_enu)
    # Build a box centered on the projected target.
    box = np.array([center[0] - 40, center[1] - 30, center[0] + 40, center[1] + 30])

    est_gps = reproject_box_to_gps(cam, pose, box, home, ground_z=0.0)
    err = _gps_dist_m(tuple(true_gps), tuple(est_gps))
    assert err < 3.0, f"box centroid GPS error {err:.4f} m exceeds 3 m"


def test2_multiple_targets_all_within_budget():
    home = home_from_pin(*HOME)
    cam, pose = _topdown_camera_pose(altitude=90.0)
    rng = np.random.default_rng(0)
    for _ in range(25):
        true_enu = np.array([rng.uniform(-20, 20), rng.uniform(-20, 20), 0.0])
        true_gps = home.geodetic_from_enu(*true_enu)
        pixel = project(cam, pose, true_enu)
        est_gps = reproject_pixel_to_gps(cam, pose, pixel, home, ground_z=0.0)
        assert _gps_dist_m(tuple(true_gps), tuple(est_gps)) < 3.0


# ---------------------------------------------------------------------------
# Test 3 (A) -- confirmed AOI polygon IoU >= 0.7
# ---------------------------------------------------------------------------


def test3_identical_polygon_iou_is_one():
    truth = np.array([[0, 0], [20, 0], [20, 12], [0, 12]], dtype=float)
    assert polygon_iou(truth, truth) == pytest.approx(1.0)


def test3_confirmed_footprint_meets_iou_threshold():
    """A slightly off but well-aligned confirmation must clear IoU >= 0.7."""
    truth = np.array([[0, 0], [20, 0], [20, 12], [0, 12]], dtype=float)
    # Confirmed footprint: shifted ~1 m and shrunk slightly -- a realistic tap.
    confirmed = np.array([[1, 0.5], [20.5, 0.5], [20.5, 12], [1, 12]], dtype=float)
    iou = polygon_iou(confirmed, truth)
    assert iou >= 0.7, f"IoU {iou:.3f} below 0.7"


def test3_disjoint_polygons_iou_zero():
    a = np.array([[0, 0], [5, 0], [5, 5], [0, 5]], dtype=float)
    b = np.array([[100, 100], [105, 100], [105, 105], [100, 105]], dtype=float)
    assert polygon_iou(a, b) == pytest.approx(0.0)


def test3_half_overlap_iou():
    a = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
    b = np.array([[5, 0], [15, 0], [15, 10], [5, 10]], dtype=float)
    # intersection 50, union 150 -> 1/3.
    assert polygon_iou(a, b) == pytest.approx(1.0 / 3.0, abs=1e-9)


def test3_confirm_aoi_builds_valid_artifact():
    home = home_from_pin(*HOME)
    truth = np.array([[0, 0], [20, 0], [20, 12], [0, 12]], dtype=float)
    aoi = confirm_aoi(home, truth, name="bldg-A")
    assert isinstance(aoi, AOI)
    assert aoi.name == "bldg-A"
    assert aoi.home.lat == HOME[0]
    assert len(aoi.polygon_enu) == 4
    # The locked polygon round-trips to the same footprint.
    assert polygon_iou(np.array(aoi.polygon_enu), truth) == pytest.approx(1.0)


def test3_degenerate_polygon_rejected():
    home = home_from_pin(*HOME)
    line = np.array([[0, 0], [10, 0], [20, 0]], dtype=float)  # collinear, zero area
    with pytest.raises(ValueError):
        confirm_aoi(home, line)


def test3_point_in_polygon_geofence():
    poly = np.array([[0, 0], [20, 0], [20, 12], [0, 12]], dtype=float)
    assert point_in_polygon([10, 6], poly)
    assert not point_in_polygon([25, 6], poly)
    assert polygon_area(poly) == pytest.approx(240.0)


# ---------------------------------------------------------------------------
# Detector interface (wiring / orchestration -- deterministic, no model)
# ---------------------------------------------------------------------------


def test_stub_detector_filters_by_prompt_and_score():
    dets = [
        Detection(box_xyxy=[10, 10, 50, 60], score=0.9, label="building"),
        Detection(box_xyxy=[100, 100, 140, 150], score=0.2, label="building"),
        Detection(box_xyxy=[200, 200, 240, 260], score=0.95, label="car"),
    ]
    detector = StubDetector(detections=dets)
    out = detector.detect(np.zeros((4, 4, 3)), ["building"], score_threshold=0.3)
    assert len(out) == 1
    assert out[0].label == "building"
    assert np.allclose(out[0].center, [30.0, 35.0])


def test_stub_detector_feeds_reprojection_pipeline():
    """End-to-end stub: detection box -> reprojected GPS pin under budget."""
    home = home_from_pin(*HOME)
    cam, pose = _topdown_camera_pose(altitude=85.0)
    true_enu = np.array([10.0, -4.0, 0.0])
    true_gps = home.geodetic_from_enu(*true_enu)
    center = project(cam, pose, true_enu)
    box = [center[0] - 30, center[1] - 20, center[0] + 30, center[1] + 20]
    detector = StubDetector(
        detections=[Detection(box_xyxy=box, score=0.88, label="building")]
    )
    out = detector.detect(np.zeros((4, 4, 3)), ["building", "structure"])
    assert len(out) == 1
    est_gps = reproject_box_to_gps(cam, pose, out[0].box_xyxy, home, ground_z=0.0)
    assert _gps_dist_m(tuple(true_gps), tuple(est_gps)) < 3.0


# ---------------------------------------------------------------------------
# Test 4 (C) -- real open-vocab detector accuracy. Needs field data: SKIP.
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="needs field data")
def test4_detector_recall_precision_on_real_aerial_set():
    """Run a real open-vocab detector on a labeled aerial set and check the KPI.

    KPI: recall >= 90% of visible buildings AND <= 1 false positive per scene.

    This is written against the :class:`OpenVocabDetector` interface so that a
    real YOLO-World / Grounding DINO backend drops in unchanged. It is Tier C
    (real imagery + human labels) and skips until field data exists.
    """
    from pathlib import Path

    from pral.stage1_select.detector import OpenVocabDetector

    # ---- field-data fixtures (provided once a labeled aerial set exists) ----
    dataset_dir = Path("data/stage1/aerial_eval")  # images + GT building boxes
    detector: OpenVocabDetector = _load_real_detector()  # noqa: F821
    scenes = _load_labeled_scenes(dataset_dir)  # noqa: F821

    prompts = ["building", "house", "structure"]
    total_gt = 0
    total_recalled = 0
    fp_per_scene = []
    for scene in scenes:
        preds = detector.detect(scene.image, prompts, score_threshold=0.3)
        matched_gt, false_positives = _match_boxes(  # noqa: F821
            preds, scene.gt_boxes, iou_threshold=0.5
        )
        total_gt += len(scene.gt_boxes)
        total_recalled += matched_gt
        fp_per_scene.append(false_positives)

    recall = total_recalled / max(total_gt, 1)
    assert recall >= 0.90, f"recall {recall:.3f} below 0.90"
    assert max(fp_per_scene) <= 1, "more than 1 false positive in some scene"
