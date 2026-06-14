"""Stage 3 data types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Re-export AOI from stage2 for convenience
from pipeline.stage2.types import AOI, Stage2Output  # noqa: F401


@dataclass
class OrbitFrame:
    """One frame captured during the orbit or a close-up pass."""

    image: np.ndarray                               # HxWx3 BGR
    drone_pos_enu: Tuple[float, float, float]       # (e, n, u) GPS position
    drone_attitude_rpy: Tuple[float, float, float]  # (roll, pitch, yaw) radians
    timestamp: float
    pass_type: str = "orbit"                        # "orbit" | "closeup"


@dataclass
class PosedFrame:
    """OrbitFrame with COLMAP/SLAM-estimated camera pose."""

    image: np.ndarray
    drone_pos_enu: Tuple[float, float, float]       # GPS position
    camera_pos_enu: Tuple[float, float, float]      # COLMAP-refined position (e, n, u)
    R_cam_to_world: np.ndarray                      # 3x3 rotation
    reprojection_error_px: float
    timestamp: float
    pass_type: str = "orbit"
    image_path: str = ""                            # path on disk (for gsplat)


@dataclass
class CoverageMap:
    """Per-surface-voxel observation count tracking."""

    voxel_size: float = 0.25
    seen: Dict[Tuple[int, int, int], int] = field(default_factory=dict)
    total_surface_voxels: int = 0


@dataclass
class Frontier:
    """Unseen or under-observed surface voxel cluster."""

    centroid_enu: Tuple[float, float, float]
    voxel_count: int
    information_gain: float = 0.0
    is_occluded: bool = False


@dataclass
class Stage3Output:
    """All outputs produced by Stage 3, consumed by Stage 4."""

    # Primary outputs (Stage 3 → 4 contract)
    posed_frames: List[PosedFrame]
    scene_path: str
    model_type: str                                 # "3dgs" | "colmap"

    # Coverage
    coverage_fraction: float
    coverage_target_met: bool
    battery_floor_hit: bool
    n_orbit_frames: int
    n_closeup_frames: int

    # Quality metrics
    psnr_db: float
    ssim: float
    mean_reprojection_error_px: float

    # Diagnostic fields (for visualization)
    coverage_map: Optional[CoverageMap] = None
    frontiers_detected: int = 0
    closeup_viewpoints_flown: int = 0
    quality_warning: str = ""
    reduced_confidence: bool = False
