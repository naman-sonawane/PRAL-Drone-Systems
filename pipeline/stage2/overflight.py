"""
Sub-step 2a -- AOI Overflight & Data Capture.

In a real deployment this module drives the drone SDK.
Here it produces a MockOverflight: synthetic rangefinder data + nadir frames
pulled from the stream server (or blank if unavailable).
"""
from __future__ import annotations

import math
import time
from typing import List, Optional, Tuple

import numpy as np

from .types import AOI, NadirFrame, RangefinderReading


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def aoi_bbox_diagonal(aoi: AOI) -> float:
    """Return the diagonal of the AOI bounding box in ENU meters."""
    if not aoi.polygon_enu:
        return 0.0
    es = [v[0] for v in aoi.polygon_enu]
    ns = [v[1] for v in aoi.polygon_enu]
    return math.sqrt((max(es) - min(es)) ** 2 + (max(ns) - min(ns)) ** 2)


def survey_altitude(diagonal_m: float) -> float:
    """h_survey = bbox_diagonal * 0.8, floor 30 m, ceiling 80 m AGL."""
    return float(np.clip(diagonal_m * 0.8, 30.0, 80.0))


def generate_lawnmower_path(
    aoi: AOI,
    h_survey: float,
    step_m: float = 5.0,
) -> List[Tuple[float, float, float]]:
    """
    East-West lawnmower traversal of the AOI bounding box.
    Returns waypoints as (e, n, u) ENU tuples.
    """
    if not aoi.polygon_enu:
        return [(aoi.centroid_enu[0], aoi.centroid_enu[1], h_survey)]

    es = [v[0] for v in aoi.polygon_enu]
    ns = [v[1] for v in aoi.polygon_enu]
    e_min, e_max = min(es) - 2.0, max(es) + 2.0
    n_min, n_max = min(ns) - 2.0, max(ns) + 2.0

    waypoints: List[Tuple[float, float, float]] = []
    n_cur = n_min
    direction = 1
    while n_cur <= n_max + 0.5:
        if direction == 1:
            waypoints += [(e_min, n_cur, h_survey), (e_max, n_cur, h_survey)]
        else:
            waypoints += [(e_max, n_cur, h_survey), (e_min, n_cur, h_survey)]
        n_cur += step_m
        direction *= -1
    return waypoints


# ---------------------------------------------------------------------------
# Point-in-polygon (ray-casting)
# ---------------------------------------------------------------------------

def point_in_polygon(e: float, n: float, polygon: List[Tuple[float, float]]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if ((yi > n) != (yj > n)) and (e < (xj - xi) * (n - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# ---------------------------------------------------------------------------
# MockOverflight
# ---------------------------------------------------------------------------

class MockOverflight:
    """
    Simulates the Stage 2a overflight without a physical drone.

    Rangefinder: synthetic readings -- drone at h_survey, building modeled as
    a solid box of height H_true at the AOI centroid. Readings over the polygon
    see a shorter range (roof); readings outside see the full h_survey (ground).

    Nadir frames: fetched from the stream server if reachable, else blank.
    """

    def __init__(
        self,
        aoi: AOI,
        H_true: float = 15.0,
        stream_url: str = "http://localhost:5001",
        n_frames: int = 5,
    ) -> None:
        self.aoi = aoi
        self.H_true = H_true
        self.stream_url = stream_url
        self.n_frames = n_frames

    # ------------------------------------------------------------------
    def run(self) -> Tuple[List[RangefinderReading], List[NadirFrame]]:
        diagonal = aoi_bbox_diagonal(self.aoi)
        h_survey = survey_altitude(diagonal)
        waypoints = generate_lawnmower_path(self.aoi, h_survey)

        rangefinder: List[RangefinderReading] = []
        frames: List[NadirFrame] = []
        rng = np.random.default_rng(42)
        t0 = time.time()

        # -- Rangefinder at ~10 Hz: interpolate along each E-W strip --
        # Waypoints come in pairs (west-end, east-end) per lawnmower row.
        # Sample intermediate points so readings cover the full AOI interior.
        for i in range(0, len(waypoints) - 1, 2):
            e0, n0, u0 = waypoints[i]
            e1, n1, _ = waypoints[i + 1]
            strip_len = abs(e1 - e0)
            n_samples = max(4, int(strip_len / 2.0))  # ~1 reading per 2 m
            for k in range(n_samples):
                frac = k / max(n_samples - 1, 1)
                e_pos = e0 + frac * (e1 - e0) + float(rng.uniform(-0.3, 0.3))
                n_pos = n0 + float(rng.uniform(-0.3, 0.3))
                over = point_in_polygon(e_pos, n_pos, self.aoi.polygon_enu)
                noise = float(rng.normal(0, 0.05))
                range_m = (h_survey - self.H_true if over else h_survey) + noise
                rangefinder.append(
                    RangefinderReading(
                        timestamp=t0 + len(rangefinder) * 0.1,
                        range_m=max(0.5, range_m),
                        drone_pos_enu=(e_pos, n_pos, u0),
                    )
                )

        # -- Nadir frames from stream server --
        base_frame = self._fetch_frame()
        step = max(1, len(waypoints) // self.n_frames)
        for i, wp in enumerate(waypoints[::step][: self.n_frames]):
            e_wp, n_wp, u_wp = wp
            frames.append(
                NadirFrame(
                    image=base_frame.copy(),
                    drone_pos_enu=(e_wp, n_wp, u_wp),
                    drone_attitude_rpy=(0.0, -math.pi / 2, 0.0),
                    timestamp=t0 + i * 2.0,
                )
            )

        return rangefinder, frames

    # ------------------------------------------------------------------
    def _fetch_frame(self) -> np.ndarray:
        try:
            import cv2
            import requests

            resp = requests.get(f"{self.stream_url}/frame", timeout=2)
            resp.raise_for_status()
            arr = np.frombuffer(resp.content, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                return frame
        except Exception:
            pass
        return np.zeros((1080, 1920, 3), dtype=np.uint8)
