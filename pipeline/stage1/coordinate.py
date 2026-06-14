"""
Sub-step 1a — Coordinate frame conversion.

All internal geometry lives in ENU (East-North-Up, metres relative to a home origin).
This module owns every geodetic ↔ ENU transform in the pipeline.
"""
from math import cos, sin

import numpy as np
import pymap3d

from .types import CameraPose, HomeOrigin


def geodetic_to_enu(
    lat: float, lon: float, alt: float, origin: HomeOrigin
) -> tuple[float, float, float]:
    e, n, u = pymap3d.geodetic2enu(lat, lon, alt, origin.lat, origin.lon, origin.alt)
    return (float(e), float(n), float(u))


def enu_to_geodetic(
    e: float, n: float, u: float, origin: HomeOrigin
) -> tuple[float, float, float]:
    lat, lon, alt = pymap3d.enu2geodetic(e, n, u, origin.lat, origin.lon, origin.alt)
    return (float(lat), float(lon), float(alt))


def polygon_latlon_to_enu(
    ring: list[tuple[float, float]], origin: HomeOrigin
) -> list[tuple[float, float]]:
    result = []
    for lat, lon in ring:
        e, n, _ = geodetic_to_enu(lat, lon, origin.alt, origin)
        result.append((e, n))
    return result


def centroid_enu(polygon: list[tuple[float, float]]) -> tuple[float, float]:
    e = sum(p[0] for p in polygon) / len(polygon)
    n = sum(p[1] for p in polygon) / len(polygon)
    return (e, n)


def nadir_camera_pose(
    position_enu: tuple[float, float, float], yaw: float
) -> CameraPose:
    """
    Build a CameraPose for a straight-down (nadir) gimbal shot.

    Camera convention (OpenCV): +x right in image, +y down in image, +z into scene.
    For a level drone with gimbal at -90° pitch:
      camera +x → ENU east  (rotated by drone yaw)
      camera +y → ENU south (rotated by drone yaw)
      camera +z → ENU -up

    yaw: drone heading in radians (0 = north, π/2 = east, ZYX convention).
    """
    # Base rotation for nadir gimbal (no yaw): cam→world
    R_nadir = np.array(
        [[ 1,  0,  0],
         [ 0, -1,  0],
         [ 0,  0, -1]],
        dtype=float,
    )
    # Apply drone yaw around ENU z-axis
    Rz = np.array(
        [[cos(yaw), -sin(yaw), 0],
         [sin(yaw),  cos(yaw), 0],
         [0,         0,        1]],
        dtype=float,
    )
    return CameraPose(
        position_enu=position_enu,
        R_cam_to_world=Rz @ R_nadir,
    )
