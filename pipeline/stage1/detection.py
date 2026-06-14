"""
Sub-step 1c — Onboard vision detection.

Pipeline: nadir frame → YOLO-World bounding boxes → SAM 2 masks → reproject to ENU → Candidates.
Acceptance criteria: centroid within ±3 m of true GPS, mask IoU ≥ 0.75 (T1.3).
"""
import numpy as np
import cv2

from .types import Candidate, CameraIntrinsics, CameraPose


def _best_device() -> str:
    """Return the best available torch device: cuda > mps > cpu."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_buildings(
    frame: np.ndarray,
    confidence_threshold: float = 0.3,
) -> list[np.ndarray]:
    """
    Run YOLO-World on a nadir frame.
    Returns a list of bounding boxes as [x1, y1, x2, y2] pixel arrays.
    """
    from ultralytics import YOLO

    model = YOLO("yolov8x-worldv2.pt")
    model.set_classes(["building", "house", "structure", "roof"])
    results = model.predict(frame, conf=confidence_threshold, verbose=False)
    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return []
    return boxes.xyxy.cpu().numpy()


def segment_box(
    frame: np.ndarray,
    box: np.ndarray,
    model_cfg: str,
    checkpoint: str,
) -> np.ndarray:
    """
    Run SAM 2 on a single bounding box.
    Returns the highest-confidence binary mask (H×W bool array).
    model_cfg and checkpoint must point to downloaded SAM 2 weights.
    """
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    device = _best_device()
    predictor = SAM2ImagePredictor(build_sam2(model_cfg, checkpoint, device=device))
    predictor.set_image(frame)
    masks, scores, _ = predictor.predict(box=box, multimask_output=True)
    return masks[int(np.argmax(scores))]


# ---------------------------------------------------------------------------
# Reprojection
# ---------------------------------------------------------------------------

def mask_centroid(mask: np.ndarray) -> tuple[float, float]:
    """Pixel centroid of a binary mask via image moments."""
    moments = cv2.moments(mask.astype(np.uint8))
    if moments["m00"] == 0:
        raise ValueError("Empty mask — cannot compute centroid")
    return (moments["m10"] / moments["m00"], moments["m01"] / moments["m00"])


def reproject_pixel_to_enu(
    px: float,
    py: float,
    pose: CameraPose,
    intrinsics: CameraIntrinsics,
) -> tuple[float, float, float]:
    """
    Ray-cast pixel (px, py) to the ground plane (ENU up = 0).

    Steps:
      1. Unproject pixel to a unit ray in camera frame via K⁻¹.
      2. Rotate ray to ENU frame via R_cam_to_world.
      3. Intersect ray with the flat ground plane u = 0.

    Returns (east, north, up=0) of the ground intersection in metres.
    Raises ValueError if the ray cannot reach the ground (parallel or behind camera).
    """
    ray_cam = np.linalg.inv(intrinsics.K) @ np.array([px, py, 1.0])
    ray_world = pose.R_cam_to_world @ ray_cam

    pos = np.array(pose.position_enu)

    if abs(ray_world[2]) < 1e-6:
        raise ValueError("Ray is parallel to the ground plane")
    if pos[2] <= 0:
        raise ValueError("Drone is at or below ground level")

    t = -pos[2] / ray_world[2]
    if t < 0:
        raise ValueError("Ground intersection is behind the camera")

    hit = pos + t * ray_world
    return (float(hit[0]), float(hit[1]), float(hit[2]))


def mask_to_ground_polygon(
    mask: np.ndarray,
    pose: CameraPose,
    intrinsics: CameraIntrinsics,
    n_points: int = 12,
) -> list[tuple[float, float]]:
    """
    Approximate the mask boundary as a ground-plane ENU polygon.
    Samples n_points uniformly from the mask contour and reprojects each.
    """
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return []

    contour = max(contours, key=cv2.contourArea)
    indices = np.linspace(0, len(contour) - 1, n_points, dtype=int)
    sampled = contour[indices].reshape(-1, 2)

    polygon: list[tuple[float, float]] = []
    for px, py in sampled:
        try:
            e, n, _ = reproject_pixel_to_enu(float(px), float(py), pose, intrinsics)
            polygon.append((e, n))
        except ValueError:
            continue

    return polygon


# ---------------------------------------------------------------------------
# Full sub-step 1c
# ---------------------------------------------------------------------------

def vision_candidates(
    frame: np.ndarray,
    pose: CameraPose,
    intrinsics: CameraIntrinsics,
    sam2_cfg: str,
    sam2_checkpoint: str,
) -> list[Candidate]:
    """
    Full vision detection: YOLO-World → SAM 2 → reproject → Candidate list.
    Silently skips boxes that fail segmentation or reprojection.
    """
    boxes = detect_buildings(frame)
    candidates: list[Candidate] = []

    for i, box in enumerate(boxes):
        try:
            mask = segment_box(frame, box, sam2_cfg, sam2_checkpoint)
            cx, cy = mask_centroid(mask)
            centroid = reproject_pixel_to_enu(cx, cy, pose, intrinsics)
            polygon = mask_to_ground_polygon(mask, pose, intrinsics)

            if len(polygon) < 3:
                continue

            candidates.append(
                Candidate(
                    id=f"vision-{i}",
                    source="vision",
                    polygon_enu=polygon,
                    centroid_enu=(centroid[0], centroid[1]),
                    confidence=0.8,
                )
            )
        except Exception:
            continue

    return candidates
