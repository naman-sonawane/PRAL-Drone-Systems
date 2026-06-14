"""
Stage 1 orchestrator — GPS Target Selection & Confirmation.

Wires sub-steps 1a–1d into a single blocking call that returns a locked AOI.

Usage:
    runner = Stage1Runner(intrinsics, sam2_cfg, sam2_checkpoint)
    aoi = runner.run(lat, lon, drone)

The drone argument must satisfy the DroneInterface protocol.
For simulation and unit testing use MockDrone (see below).
"""
from typing import Protocol

import numpy as np

from .confirmation import (
    closest_to_pin,
    confirm_candidate,
    confirm_manual,
    merge_candidates,
)
from .coordinate import geodetic_to_enu, nadir_camera_pose
from .detection import vision_candidates
from .footprint import filter_by_distance, query_osm_footprints
from .types import AOI, Candidate, CameraIntrinsics, HomeOrigin

SURVEY_ALTITUDE_M = 40.0


# ---------------------------------------------------------------------------
# Drone interface (protocol — swap in DJI SDK or MAVSDK implementation)
# ---------------------------------------------------------------------------

class DroneInterface(Protocol):
    def ascend_to(self, altitude_m: float) -> None: ...
    def get_position_enu(self) -> tuple[float, float, float]: ...
    def get_attitude_rpy(self) -> tuple[float, float, float]: ...  # radians: roll, pitch, yaw
    def capture_frame(self) -> np.ndarray: ...
    def hover(self) -> None: ...


class MockDrone:
    """Minimal stub for testing Stage 1 without a real drone."""

    def __init__(
        self,
        position_enu: tuple[float, float, float] = (0.0, 0.0, 40.0),
        yaw: float = 0.0,
        frame: np.ndarray | None = None,
    ):
        self._position = position_enu
        self._yaw = yaw
        self._frame = frame if frame is not None else np.zeros((480, 640, 3), dtype=np.uint8)

    def ascend_to(self, altitude_m: float) -> None:
        self._position = (self._position[0], self._position[1], altitude_m)

    def get_position_enu(self) -> tuple[float, float, float]:
        return self._position

    def get_attitude_rpy(self) -> tuple[float, float, float]:
        return (0.0, 0.0, self._yaw)

    def capture_frame(self) -> np.ndarray:
        return self._frame

    def hover(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Stage 1 runner
# ---------------------------------------------------------------------------

class Stage1Runner:
    def __init__(
        self,
        intrinsics: CameraIntrinsics,
        sam2_cfg: str,
        sam2_checkpoint: str,
        survey_altitude_m: float = SURVEY_ALTITUDE_M,
    ):
        self.intrinsics = intrinsics
        self.sam2_cfg = sam2_cfg
        self.sam2_checkpoint = sam2_checkpoint
        self.survey_altitude_m = survey_altitude_m

    def run(self, lat: float, lon: float, drone: DroneInterface) -> AOI:
        """
        Full Stage 1 execution. Returns a locked AOI or raises on unrecoverable failure.
        Stage 2 must not start if this raises.
        """
        origin = HomeOrigin(lat=lat, lon=lon, alt=0.0)
        pin_enu = geodetic_to_enu(lat, lon, 0.0, origin)[:2]

        # 1b — prior footprint lookup (pre-flight, no cost)
        print("[Stage 1] Querying OSM building footprints...")
        prior = query_osm_footprints(lat, lon, radius_m=100.0)
        prior = filter_by_distance(prior, pin_enu, max_dist_m=50.0)
        print(f"[Stage 1] {len(prior)} OSM candidate(s) found")

        # 1c — onboard vision detection
        print(f"[Stage 1] Ascending to {self.survey_altitude_m} m for nadir scan...")
        drone.ascend_to(self.survey_altitude_m)
        drone.hover()

        pos_enu = drone.get_position_enu()
        _, _, yaw = drone.get_attitude_rpy()
        pose = nadir_camera_pose(pos_enu, yaw)

        frame = drone.capture_frame()
        print("[Stage 1] Running vision detection on nadir frame...")
        vision = vision_candidates(
            frame, pose, self.intrinsics, self.sam2_cfg, self.sam2_checkpoint
        )
        print(f"[Stage 1] {len(vision)} vision candidate(s) found")

        # merge priors and vision detections
        candidates = merge_candidates(prior, vision)
        print(f"[Stage 1] {len(candidates)} merged candidate(s)")

        # 1d — confirm
        aoi = self._confirm(candidates, pin_enu, origin)
        print(
            f"[Stage 1] AOI confirmed — source: {aoi.source}, "
            f"centroid ENU: ({aoi.centroid_enu[0]:.1f} m E, {aoi.centroid_enu[1]:.1f} m N)"
        )
        return aoi

    def _confirm(
        self,
        candidates: list[Candidate],
        pin_enu: tuple[float, float],
        origin: HomeOrigin,
    ) -> AOI:
        """
        Confirmation step.

        In production: surface candidates to the UI and wait for the user to tap one.
        Here: auto-select the candidate closest to the pin. Replace this method with
        a UI callback when integrating with a ground-control application.
        """
        if not candidates:
            print("[Stage 1] No candidates — falling back to manual 20×20 m box")
            return self._manual_fallback(pin_enu, origin)

        best = closest_to_pin(candidates, pin_enu)
        return confirm_candidate(best, origin)

    @staticmethod
    def _manual_fallback(
        pin_enu: tuple[float, float],
        origin: HomeOrigin,
    ) -> AOI:
        """
        Fallback when no candidates are found (T1.5).
        Creates a 20×20 m square AOI centred on the pin.
        In production this prompts the user to draw a polygon.
        """
        e, n = pin_enu
        half = 10.0
        polygon = [
            (e - half, n - half),
            (e + half, n - half),
            (e + half, n + half),
            (e - half, n + half),
        ]
        return confirm_manual(polygon, origin)
