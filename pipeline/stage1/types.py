from dataclasses import dataclass
from typing import Literal

import numpy as np


@dataclass
class HomeOrigin:
    lat: float
    lon: float
    alt: float


@dataclass
class CameraIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    @property
    def K(self) -> np.ndarray:
        return np.array(
            [[self.fx, 0, self.cx],
             [0, self.fy, self.cy],
             [0, 0, 1]],
            dtype=float,
        )


@dataclass
class CameraPose:
    position_enu: tuple[float, float, float]  # (east, north, up) metres
    R_cam_to_world: np.ndarray                # 3×3, camera frame → ENU


@dataclass
class Candidate:
    id: str
    source: Literal["osm", "vision", "manual"]
    polygon_enu: list[tuple[float, float]]   # (e, n) ground-plane ring
    centroid_enu: tuple[float, float]        # (e, n)
    confidence: float                        # 0–1


@dataclass
class AOI:
    polygon_enu: list[tuple[float, float]]
    centroid_enu: tuple[float, float]
    home_origin: HomeOrigin
    source: Literal["osm", "vision", "manual"]
