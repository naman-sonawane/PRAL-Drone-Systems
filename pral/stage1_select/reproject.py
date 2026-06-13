"""Reproject a detection (pixel / box) back to a ground location, then to GPS.

Stage 1, Test 2. The onboard detector returns a bounding box in image pixels.
To place that target on the map we cast the ray through the box center, intersect
it with the **ground plane** ``z = ground_z`` in the ENU frame (the drone is
looking down during the ascent/top-down pass), and convert the resulting ENU
point back to geodetic via the home frame.

This reuses :func:`pral.core.camera.backproject` (the pinhole ray/plane math) and
:class:`~pral.stage1_select.gps_frame.HomeFrameRef` (the geodetic anchor); the
only Stage-1-specific logic is taking a box -> its center pixel.
"""

from __future__ import annotations

import numpy as np

from pral.core.camera import Camera, Pose, backproject

from .gps_frame import HomeFrameRef


def reproject_pixel_to_enu(
    camera: Camera, pose: Pose, pixel: np.ndarray, ground_z: float = 0.0
) -> np.ndarray:
    """Pixel ``(u, v)`` -> ENU point where its ray meets the plane ``z = ground_z``."""
    return backproject(camera, pose, np.asarray(pixel, dtype=float), ground_z=ground_z)


def reproject_pixel_to_gps(
    camera: Camera,
    pose: Pose,
    pixel: np.ndarray,
    home: HomeFrameRef,
    ground_z: float = 0.0,
) -> np.ndarray:
    """Pixel ``(u, v)`` -> geodetic ``[lat, lon, alt]`` via the ground plane + home frame."""
    enu = reproject_pixel_to_enu(camera, pose, pixel, ground_z=ground_z)
    return home.geodetic_from_enu(enu[0], enu[1], enu[2])


def reproject_box_to_gps(
    camera: Camera,
    pose: Pose,
    box_xyxy: np.ndarray,
    home: HomeFrameRef,
    ground_z: float = 0.0,
) -> np.ndarray:
    """Detection box ``[x0, y0, x1, y1]`` -> geodetic centroid ``[lat, lon, alt]``.

    The box center pixel is reprojected onto the ground plane. This is how a
    candidate detection becomes a map pin the user can confirm.
    """
    box = np.asarray(box_xyxy, dtype=float).reshape(4)
    cx = 0.5 * (box[0] + box[2])
    cy = 0.5 * (box[1] + box[3])
    return reproject_pixel_to_gps(
        camera, pose, np.array([cx, cy]), home, ground_z=ground_z
    )
