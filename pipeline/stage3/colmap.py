"""Sub-step 3b -- COLMAP SfM Pose Estimation."""
from __future__ import annotations

import logging
import math
import os
from typing import List, Optional, Tuple

import numpy as np

from .types import OrbitFrame, PosedFrame

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional-import guard (mirrors _try_real_octomap in stage2/obstacle.py)
# ---------------------------------------------------------------------------

def _try_pycolmap():
    """Return pycolmap module if available, else None."""
    try:
        import pycolmap
        return pycolmap
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Rotation helpers
# ---------------------------------------------------------------------------

def _rotation_from_rpy(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """
    Build a 3x3 rotation matrix from roll-pitch-yaw (radians, ZYX convention).

    Mirrors the same math used in pose_to_Rt in pipeline/stage2/height.py.
    """
    cr, sr = math.cos(roll),  math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw),   math.sin(yaw)

    Rz = np.array([[cy, -sy, 0.0],
                   [sy,  cy, 0.0],
                   [0.0, 0.0, 1.0]], dtype=np.float64)
    Ry = np.array([[ cp, 0.0, sp],
                   [0.0, 1.0, 0.0],
                   [-sp, 0.0, cp]], dtype=np.float64)
    Rx = np.array([[1.0, 0.0, 0.0],
                   [0.0,  cr, -sr],
                   [0.0,  sr,  cr]], dtype=np.float64)
    return Rz @ Ry @ Rx


def _colmap_to_enu(
    colmap_pos: np.ndarray,
    aoi_centroid_enu: Tuple[float, float],
) -> Tuple[float, float, float]:
    """
    Convert a COLMAP-internal position to ENU by adding the AOI centroid offset.

    COLMAP works in an arbitrary local frame; we treat the centroid as origin.
    """
    ce, cn = aoi_centroid_enu
    return (float(colmap_pos[0]) + ce, float(colmap_pos[1]) + cn, float(colmap_pos[2]))


# ---------------------------------------------------------------------------
# Mock pose estimator (used when pycolmap is absent or reconstruction fails)
# ---------------------------------------------------------------------------

class MockPoseEstimator:
    """
    Assigns analytically computed poses based on GPS position in each OrbitFrame.

    Used when pycolmap is unavailable or when COLMAP reconstruction fails.
    reprojection_error_px is always 0.0 (no real SfM performed).
    """

    def estimate(
        self,
        frames: List[OrbitFrame],
        K: np.ndarray,
        aoi_centroid_enu: Tuple[float, float],
        r: float,
        z_orbit: float,
    ) -> List[PosedFrame]:
        """Return PosedFrame list with analytically assigned camera poses."""
        ce, cn = aoi_centroid_enu
        posed: List[PosedFrame] = []
        for i, frame in enumerate(frames):
            e, n, u = frame.drone_pos_enu
            roll, pitch, yaw = frame.drone_attitude_rpy
            R = _rotation_from_rpy(roll, pitch, yaw)
            posed.append(PosedFrame(
                image=frame.image,
                drone_pos_enu=frame.drone_pos_enu,
                camera_pos_enu=(e, n, u),
                R_cam_to_world=R,
                reprojection_error_px=0.0,
                timestamp=frame.timestamp,
                pass_type=frame.pass_type,
                image_path="",
            ))
        log.info(f"MockPoseEstimator: assigned poses to {len(posed)} frames")
        return posed


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_colmap(
    frames: List[OrbitFrame],
    K: np.ndarray,
    workspace_dir: str,
    aoi_centroid_enu: Tuple[float, float],
    r: float = 10.0,
    z_orbit: float = 15.0,
) -> List[PosedFrame]:
    """
    Run COLMAP incremental SfM on orbit frames and return posed frames.

    Creates workspace_dir/images/, writes JPEGs and cameras.txt, then attempts
    pycolmap.incremental_mapping(). Falls back to MockPoseEstimator if pycolmap
    is unavailable or reconstruction fails.

    Parameters
    ----------
    frames            : OrbitFrame list from stage 3a
    K                 : 3x3 camera intrinsics
    workspace_dir     : working directory for COLMAP files
    aoi_centroid_enu  : (e, n) centroid used to convert COLMAP poses to ENU
    r                 : orbit radius (used by mock fallback)
    z_orbit           : orbit altitude (used by mock fallback)

    Returns
    -------
    List[PosedFrame] with camera_pos_enu in ENU metres and R_cam_to_world set.
    """
    images_dir = os.path.join(workspace_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # Write JPEG frames to disk
    image_paths: List[str] = []
    try:
        import cv2
        for i, frame in enumerate(frames):
            img_path = os.path.join(images_dir, f"{i:04d}.jpg")
            cv2.imwrite(img_path, frame.image)
            image_paths.append(img_path)
    except Exception as exc:
        log.warning(f"run_colmap: could not write images ({exc}); using empty paths")
        image_paths = [""] * len(frames)

    # Write cameras.txt (COLMAP SIMPLE_RADIAL model)
    h, w = frames[0].image.shape[:2] if frames else (480, 640)
    fx = float(K[0, 0])
    cx = float(K[0, 2])
    cy = float(K[1, 2])
    cameras_txt = os.path.join(workspace_dir, "cameras.txt")
    with open(cameras_txt, "w") as f:
        f.write(f"1 SIMPLE_RADIAL {w} {h} {fx} {cx} {cy} 0.0\n")

    pycolmap = _try_pycolmap()
    if pycolmap is not None:
        try:
            database_path = os.path.join(workspace_dir, "database.db")
            output_path = os.path.join(workspace_dir, "sparse")
            os.makedirs(output_path, exist_ok=True)

            reconstructions = pycolmap.incremental_mapping(
                database_path=database_path,
                image_path=images_dir,
                output_path=output_path,
            )

            if reconstructions:
                recon = reconstructions[0]
                # Compute mean reprojection error from 3D points
                errors = []
                for pt in recon.points3D.values():
                    errors.append(pt.error)
                mean_error = float(np.mean(errors)) if errors else 0.0

                posed: List[PosedFrame] = []
                for img_id, image in recon.images.items():
                    i = img_id - 1  # COLMAP image IDs start at 1
                    if i < 0 or i >= len(frames):
                        continue
                    frame = frames[i]
                    # COLMAP gives camera-to-world rotation as R.T (world-to-cam stored)
                    R_w2c = image.rotation_matrix()
                    R_cam_to_world = R_w2c.T
                    t_world = -R_cam_to_world @ image.tvec
                    camera_pos_enu = _colmap_to_enu(t_world, aoi_centroid_enu)
                    posed.append(PosedFrame(
                        image=frame.image,
                        drone_pos_enu=frame.drone_pos_enu,
                        camera_pos_enu=camera_pos_enu,
                        R_cam_to_world=R_cam_to_world,
                        reprojection_error_px=mean_error,
                        timestamp=frame.timestamp,
                        pass_type=frame.pass_type,
                        image_path=image_paths[i] if i < len(image_paths) else "",
                    ))
                log.info(f"run_colmap: pycolmap succeeded, {len(posed)} posed frames")
                return posed
            else:
                log.warning("run_colmap: pycolmap returned empty reconstruction — falling back to mock")
        except Exception as exc:
            log.warning(f"run_colmap: pycolmap failed ({exc}) — falling back to mock")

    # Fallback
    mock = MockPoseEstimator()
    posed = mock.estimate(frames, K, aoi_centroid_enu, r, z_orbit)
    # Attach image paths written above
    for i, pf in enumerate(posed):
        pf.image_path = image_paths[i] if i < len(image_paths) else ""
    return posed
