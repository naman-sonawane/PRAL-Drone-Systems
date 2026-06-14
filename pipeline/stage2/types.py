"""Stage 2 data types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class AOI:
    """
    Confirmed building footprint — Stage 1 output / Stage 2 input.
    All coordinates are in ENU meters relative to the home origin.
    """

    polygon_enu: List[Tuple[float, float]]  # (e, n) vertices
    centroid_enu: Tuple[float, float]        # (e, n)
    source: str = "manual"                   # "osm" | "vision" | "manual"


@dataclass
class RangefinderReading:
    timestamp: float
    range_m: float
    drone_pos_enu: Tuple[float, float, float]  # (e, n, u)


@dataclass
class NadirFrame:
    image: np.ndarray                               # HxWx3 BGR
    drone_pos_enu: Tuple[float, float, float]       # (e, n, u)
    drone_attitude_rpy: Tuple[float, float, float]  # roll, pitch, yaw radians
    timestamp: float


@dataclass
class Stage2Output:
    # Primary outputs (Stage 2 → 3 contract)
    H: float               # building height AGL (meters)
    r: float               # orbit radius (meters)
    z_orbit: float         # drone altitude for orbit passes (meters AGL)
    obstacle_map: Any      # octomap.OcTree | MockOctoMap
    no_fly_volumes: List   # list of ((min_e, min_n, min_u), (max_e, max_n, max_u))

    # Diagnostic fields retained for visualization
    H_rangefinder: float = 0.0
    H_dsm: float = 0.0
    r_raw: float = 0.0
    vfov_rad: float = 0.0
    fill_ratio: float = 0.0
    height_disagreed: bool = False
    height_warning: str = ""
    r_clamped: bool = False

    rangefinder_readings: List[RangefinderReading] = field(default_factory=list)
    cloud_enu: Optional[np.ndarray] = None   # (N, 3) filtered annulus cloud
    voxel_labels: Optional[Dict[Tuple[int, int, int], int]] = None
