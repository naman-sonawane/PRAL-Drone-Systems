"""Sub-step 3a -- Base Orbit Capture."""
from __future__ import annotations

import glob as _glob
import logging
import math
import os
from typing import List, Tuple

import numpy as np

from .types import OrbitFrame

log = logging.getLogger(__name__)


def generate_orbit_waypoints(
    aoi_centroid_enu: Tuple[float, float],
    r: float,
    z_orbit: float,
) -> List[Tuple[float, float, float]]:
    """
    Return N equally-spaced waypoints on a circle of radius r at altitude z_orbit.

    N = max(24, ceil(2π r / 3.0)), ensuring ≤3 m between positions (≥60% overlap).
    """
    ce, cn = aoi_centroid_enu
    N = max(24, math.ceil(2 * math.pi * r / 3.0))
    thetas = np.linspace(0, 2 * math.pi, N, endpoint=False)
    return [(ce + r * np.cos(t), cn + r * np.sin(t), z_orbit) for t in thetas]


class MockOrbit:
    """
    Simulates the base orbit without a real drone.

    Fetches frames from stream_server/frame (or returns blank images on failure).
    """

    def __init__(
        self,
        aoi_centroid_enu: Tuple[float, float],
        r: float,
        z_orbit: float,
        stream_url: str = "http://localhost:5001",
        n_frames: int = 36,
    ) -> None:
        self.aoi_centroid_enu = aoi_centroid_enu
        self.r = r
        self.z_orbit = z_orbit
        self.stream_url = stream_url
        self.n_frames = n_frames

    def run(self) -> List[OrbitFrame]:
        """Fly mock orbit and return OrbitFrame list."""
        waypoints = generate_orbit_waypoints(self.aoi_centroid_enu, self.r, self.z_orbit)
        # Use only n_frames evenly spaced waypoints
        indices = np.linspace(0, len(waypoints) - 1, self.n_frames, dtype=int)
        ce, cn = self.aoi_centroid_enu
        frames = []
        for i, idx in enumerate(indices):
            e, n, u = waypoints[idx]
            yaw = math.atan2(cn - n, ce - e)
            pitch = -math.atan2(u, self.r)
            image = self._fetch_frame()
            frames.append(OrbitFrame(
                image=image,
                drone_pos_enu=(e, n, u),
                drone_attitude_rpy=(0.0, pitch, yaw),
                timestamp=float(i),
                pass_type="orbit",
            ))
        log.info(f"MockOrbit: captured {len(frames)} frames")
        return frames

    def _fetch_frame(self) -> np.ndarray:
        """Fetch one frame from the stream server, fall back to blank image."""
        try:
            import requests
            resp = requests.get(f"{self.stream_url}/frame", timeout=2)
            if resp.status_code == 200:
                import cv2
                arr = np.frombuffer(resp.content, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    return img
        except Exception:
            pass
        return np.zeros((480, 640, 3), dtype=np.uint8)


class FolderOrbit:
    """
    Loads pre-captured frames from a directory instead of flying a drone.

    Reads all JPG/PNG images in sorted filename order and wraps them as
    OrbitFrame objects with dummy GPS poses (0, 0, 0). COLMAP recovers the
    actual camera positions from the imagery itself, so GPS values here are
    irrelevant.

    Usage::

        orbit = FolderOrbit("stage4data/M60")
        frames = orbit.run()
    """

    _EXTENSIONS = ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG", "*.png", "*.PNG")

    def __init__(self, image_dir: str) -> None:
        self.image_dir = image_dir

    def run(self) -> List[OrbitFrame]:
        """Load all images from image_dir and return as OrbitFrame list."""
        import cv2

        paths: List[str] = []
        for ext in self._EXTENSIONS:
            paths.extend(_glob.glob(os.path.join(self.image_dir, ext)))
        paths = sorted(set(paths))

        if not paths:
            raise FileNotFoundError(f"No images found in {self.image_dir!r}")

        frames: List[OrbitFrame] = []
        for i, p in enumerate(paths):
            img = cv2.imread(p)
            if img is None:
                log.warning(f"FolderOrbit: could not read {p} — skipping")
                continue
            frames.append(OrbitFrame(
                image=img,
                drone_pos_enu=(0.0, 0.0, 0.0),     # unknown; COLMAP recovers poses
                drone_attitude_rpy=(0.0, 0.0, 0.0),
                timestamp=float(i),
                pass_type="orbit",
            ))

        log.info(f"FolderOrbit: loaded {len(frames)} frames from {self.image_dir!r}")
        return frames
