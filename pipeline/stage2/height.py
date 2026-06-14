"""
Sub-step 2b -- Height Estimation.

Method A: rangefinder delta (ground truth).
Method B: DSM from Depth Anything V2 (secondary).
Fusion: average when within 10%, rangefinder wins otherwise.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

from .overflight import point_in_polygon
from .types import AOI, NadirFrame, RangefinderReading

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Camera helpers (shared with obstacle.py via import)
# ---------------------------------------------------------------------------

def unproject(depth_map: np.ndarray, K: np.ndarray) -> np.ndarray:
    """Back-project a depth map to camera-frame points. Returns (N, 3)."""
    h, w = depth_map.shape
    u_grid, v_grid = np.meshgrid(np.arange(w), np.arange(h))
    fx, fy = K[0, 0], K[1, 1]
    cx, cy = K[0, 2], K[1, 2]
    z = depth_map.ravel().astype(np.float64)
    x = (u_grid.ravel() - cx) * z / fx
    y = (v_grid.ravel() - cy) * z / fy
    return np.stack([x, y, z], axis=1)


def pose_to_Rt(frame: NadirFrame) -> Tuple[np.ndarray, np.ndarray]:
    """Build 3x3 rotation matrix and translation vector from a NadirFrame pose."""
    roll, pitch, yaw = frame.drone_attitude_rpy
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cr, sr = np.cos(roll), np.sin(roll)
    # ZYX convention (body → world)
    R = np.array([
        [cy * cp,  cy * sp * sr - sy * cr,  cy * sp * cr + sy * sr],
        [sy * cp,  sy * sp * sr + cy * cr,  sy * sp * cr - cy * sr],
        [-sp,      cp * sr,                  cp * cr],
    ])
    t = np.array(frame.drone_pos_enu, dtype=np.float64)
    return R, t


# ---------------------------------------------------------------------------
# Method A -- Rangefinder delta
# ---------------------------------------------------------------------------

def rangefinder_height(
    readings: List[RangefinderReading],
    aoi: AOI,
) -> float:
    """
    Surface elevation = drone_u - range_m.
    h_ground = 10th pct of outside readings; h_roof = 90th pct of inside.
    """
    agl_inside: List[float] = []
    agl_outside: List[float] = []
    for r in readings:
        e, n, u = r.drone_pos_enu
        surf = u - r.range_m
        if point_in_polygon(e, n, aoi.polygon_enu):
            agl_inside.append(surf)
        else:
            agl_outside.append(surf)

    if not agl_outside or not agl_inside:
        log.warning("Insufficient rangefinder coverage for height estimation")
        return 0.0

    h_ground = float(np.percentile(agl_outside, 10))
    h_roof = float(np.percentile(agl_inside, 90))
    return h_roof - h_ground


# ---------------------------------------------------------------------------
# Method B -- DSM from Depth Anything V2
# ---------------------------------------------------------------------------

def _load_depth_model(encoder: str = "vits", checkpoint: str = ""):
    """
    Try to load Depth Anything V2. Returns model or None.

    encoder    : "vits" (Small, ~99 MB, works on CPU/MPS) or
                 "vitl" (Large, ~1.3 GB, requires CUDA for real-time use)
    checkpoint : path to the .pth weights file; if empty, tries the default
                 location pipeline/stage2/depth_anything_v2_{encoder}.pth
    """
    try:
        import torch
        from depth_anything_v2.dpt import DepthAnythingV2

        _CONFIGS = {
            "vits": dict(features=64,  out_channels=[48,  96,  192,  384]),
            "vitl": dict(features=256, out_channels=[256, 512, 1024, 1024]),
        }
        if encoder not in _CONFIGS:
            raise ValueError(f"Unknown encoder '{encoder}'; choose 'vits' or 'vitl'")

        if not checkpoint:
            checkpoint = f"pipeline/stage2/depth_anything_v2_{encoder}.pth"

        if torch.cuda.is_available():
            device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            device = torch.device("mps")
        else:
            device = torch.device("cpu")

        model = DepthAnythingV2(encoder=encoder, max_depth=80, **_CONFIGS[encoder])
        model.load_state_dict(torch.load(checkpoint, map_location=device))
        model = model.to(device).eval()
        return model
    except Exception:
        return None


def _mock_depth(frame: NadirFrame, building_height: float = 15.0) -> np.ndarray:
    """
    Synthetic depth map for a nadir camera.
    Building region (center quarter of image) is H meters closer.
    """
    h, w = frame.image.shape[:2]
    drone_z = frame.drone_pos_enu[2]
    depth = np.full((h, w), float(drone_z), dtype=np.float32)
    r1, r2 = h // 4, 3 * h // 4
    c1, c2 = w // 4, 3 * w // 4
    depth[r1:r2, c1:c2] = float(drone_z - building_height)
    return depth


def dsm_height(
    frames: List[NadirFrame],
    aoi: AOI,
    K: np.ndarray,
    depth_model=None,
) -> float:
    """
    Estimate building height from monocular depth.
    Uses Depth Anything V2 when available; falls back to mock depth.
    """
    if not frames:
        return 0.0

    # open3d optional
    try:
        import open3d as o3d
        _has_o3d = True
    except ImportError:
        _has_o3d = False
        log.warning("open3d not installed -- using percentile fallback for DSM height")

    all_pts: List[np.ndarray] = []
    for frame in frames[:5]:
        if depth_model is not None:
            try:
                import cv2
                rgb = cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB)
                depth = depth_model.infer_image(rgb)
            except Exception as exc:
                log.warning(f"Depth model inference failed: {exc} -- using mock depth")
                depth = _mock_depth(frame)
        else:
            depth = _mock_depth(frame)

        pts_cam = unproject(depth, K)
        R, t = pose_to_Rt(frame)
        pts_enu = (R @ pts_cam.T).T + t
        all_pts.append(pts_enu)

    cloud_np = np.vstack(all_pts)
    cloud_np = cloud_np[np.isfinite(cloud_np).all(axis=1)]
    if len(cloud_np) < 10:
        return 0.0

    if _has_o3d:
        import open3d as o3d
        cloud = o3d.geometry.PointCloud()
        cloud.points = o3d.utility.Vector3dVector(cloud_np)
        try:
            plane_model, _ = cloud.segment_plane(
                distance_threshold=0.3, ransac_n=3, num_iterations=1000
            )
            a, b, c, d = plane_model
            norm = np.sqrt(a**2 + b**2 + c**2)
            dists = (cloud_np @ np.array([a, b, c]) + d) / norm
            inside = np.array([
                point_in_polygon(pt[0], pt[1], aoi.polygon_enu) for pt in cloud_np
            ])
            if not inside.any():
                return 0.0
            return float(max(0.0, np.max(dists[inside])))
        except Exception as exc:
            log.warning(f"RANSAC ground plane failed: {exc}")
            return 0.0
    else:
        # Fallback: z-range of points inside the AOI
        inside = np.array([
            point_in_polygon(pt[0], pt[1], aoi.polygon_enu) for pt in cloud_np
        ])
        outside = ~inside
        if not inside.any() or not outside.any():
            return 0.0
        z_ground = float(np.percentile(cloud_np[outside, 2], 10))
        z_roof = float(np.percentile(cloud_np[inside, 2], 90))
        return max(0.0, z_roof - z_ground)


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

def fuse_heights(
    H_rangefinder: float,
    H_dsm: float,
) -> Tuple[float, bool]:
    """
    Returns (H_fused, disagreed).
    Rangefinder wins when |H_rf - H_dsm| >= 10% of the larger value.
    """
    if H_rangefinder <= 0 and H_dsm <= 0:
        return 0.0, False
    if H_rangefinder <= 0:
        return H_dsm, False
    if H_dsm <= 0:
        return H_rangefinder, False

    disagreed = abs(H_rangefinder - H_dsm) >= 0.1 * max(H_rangefinder, H_dsm)
    if disagreed:
        log.warning(
            f"DSM height {H_dsm:.1f} m disagrees with rangefinder "
            f"{H_rangefinder:.1f} m -- using rangefinder"
        )
        return H_rangefinder, True
    return (H_rangefinder + H_dsm) / 2.0, False


def apply_height_edge_cases(H: float) -> Tuple[float, str]:
    """Clamp minimum; flag if > 60 m. Returns (H_final, warning_message)."""
    if H < 2.0:
        msg = f"H clamped from {H:.2f} m to 2.0 m minimum"
        log.warning(msg)
        return 2.0, msg
    if H > 60.0:
        msg = f"H = {H:.1f} m exceeds 60 m -- operator acknowledgment required before Stage 3"
        log.warning(msg)
        return H, msg
    return H, ""
