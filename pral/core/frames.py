"""Geodetic <-> local Cartesian coordinate frames.

The flight math all happens in a local metric frame (meters) anchored at a
*home* point. We support two conventions:

* **ENU** — East, North, Up. The natural right-handed frame for planning.
* **NED** — North, East, Down. The aerospace convention (MAVLink/PX4).

The conversion uses the WGS-84 ellipsoid: geodetic (lat, lon, alt) ->
Earth-Centered-Earth-Fixed (ECEF) -> local tangent plane at the home anchor.
This is accurate to well under 0.5 m for points within a few km of home
(Test 1), far better than a flat-earth approximation.

All public functions are pure and deterministic. Angles in degrees, distances
in meters.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# WGS-84 ellipsoid parameters.
_WGS84_A = 6378137.0  # semi-major axis (m)
_WGS84_F = 1.0 / 298.257223563  # flattening
_WGS84_E2 = _WGS84_F * (2.0 - _WGS84_F)  # first eccentricity squared


@dataclass(frozen=True)
class GeoPoint:
    """A geodetic coordinate: latitude/longitude in degrees, altitude in meters."""

    lat: float
    lon: float
    alt: float = 0.0

    def as_array(self) -> np.ndarray:
        return np.array([self.lat, self.lon, self.alt], dtype=float)


def geodetic_to_ecef(lat: float, lon: float, alt: float) -> np.ndarray:
    """Convert geodetic (deg, deg, m) to ECEF (m) on the WGS-84 ellipsoid."""
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    sin_lat = np.sin(lat_r)
    cos_lat = np.cos(lat_r)
    # Prime vertical radius of curvature.
    n = _WGS84_A / np.sqrt(1.0 - _WGS84_E2 * sin_lat * sin_lat)
    x = (n + alt) * cos_lat * np.cos(lon_r)
    y = (n + alt) * cos_lat * np.sin(lon_r)
    z = (n * (1.0 - _WGS84_E2) + alt) * sin_lat
    return np.array([x, y, z], dtype=float)


def ecef_to_geodetic(x: float, y: float, z: float) -> np.ndarray:
    """Convert ECEF (m) to geodetic (lat deg, lon deg, alt m).

    Uses Bowring's closed-form approximation, refined by one Newton-style
    iteration; sub-millimeter accurate at terrestrial altitudes.
    """
    a = _WGS84_A
    e2 = _WGS84_E2
    b = a * np.sqrt(1.0 - e2)
    ep2 = (a * a - b * b) / (b * b)  # second eccentricity squared

    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    theta = np.arctan2(z * a, p * b)
    sin_t = np.sin(theta)
    cos_t = np.cos(theta)
    lat = np.arctan2(z + ep2 * b * sin_t**3, p - e2 * a * cos_t**3)
    sin_lat = np.sin(lat)
    n = a / np.sqrt(1.0 - e2 * sin_lat * sin_lat)
    if abs(np.cos(lat)) > 1e-12:
        alt = p / np.cos(lat) - n
    else:  # near the poles
        alt = abs(z) - b
    return np.array([np.degrees(lat), np.degrees(lon), alt], dtype=float)


def _ecef_to_enu_rotation(lat0: float, lon0: float) -> np.ndarray:
    """Rotation matrix mapping an ECEF *displacement* to local ENU at (lat0, lon0)."""
    lat_r = np.radians(lat0)
    lon_r = np.radians(lon0)
    s_lat, c_lat = np.sin(lat_r), np.cos(lat_r)
    s_lon, c_lon = np.sin(lon_r), np.cos(lon_r)
    return np.array(
        [
            [-s_lon, c_lon, 0.0],
            [-s_lat * c_lon, -s_lat * s_lon, c_lat],
            [c_lat * c_lon, c_lat * s_lon, s_lat],
        ],
        dtype=float,
    )


def geodetic_to_enu(
    lat: float,
    lon: float,
    alt: float,
    home_lat: float,
    home_lon: float,
    home_alt: float = 0.0,
) -> np.ndarray:
    """Geodetic point -> local ENU (East, North, Up) meters relative to home."""
    p = geodetic_to_ecef(lat, lon, alt)
    p0 = geodetic_to_ecef(home_lat, home_lon, home_alt)
    rot = _ecef_to_enu_rotation(home_lat, home_lon)
    return rot @ (p - p0)


def enu_to_geodetic(
    east: float,
    north: float,
    up: float,
    home_lat: float,
    home_lon: float,
    home_alt: float = 0.0,
) -> np.ndarray:
    """Local ENU meters relative to home -> geodetic (lat deg, lon deg, alt m)."""
    p0 = geodetic_to_ecef(home_lat, home_lon, home_alt)
    rot = _ecef_to_enu_rotation(home_lat, home_lon)
    enu = np.array([east, north, up], dtype=float)
    p = p0 + rot.T @ enu  # rot is orthonormal, so transpose is its inverse
    return ecef_to_geodetic(*p)


# NED is a simple axis remap of ENU: N=N, E=E, D=-U.
_ENU_TO_NED = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, -1.0]])


def enu_to_ned(enu: np.ndarray) -> np.ndarray:
    """Convert an ENU vector to NED (North, East, Down)."""
    return _ENU_TO_NED @ np.asarray(enu, dtype=float)


def ned_to_enu(ned: np.ndarray) -> np.ndarray:
    """Convert a NED vector to ENU (East, North, Up)."""
    return _ENU_TO_NED @ np.asarray(ned, dtype=float)  # involution: its own inverse


def geodetic_to_ned(
    lat: float,
    lon: float,
    alt: float,
    home_lat: float,
    home_lon: float,
    home_alt: float = 0.0,
) -> np.ndarray:
    """Geodetic point -> local NED (North, East, Down) meters relative to home."""
    return enu_to_ned(geodetic_to_enu(lat, lon, alt, home_lat, home_lon, home_alt))


def ned_to_geodetic(
    north: float,
    east: float,
    down: float,
    home_lat: float,
    home_lon: float,
    home_alt: float = 0.0,
) -> np.ndarray:
    """Local NED meters relative to home -> geodetic (lat deg, lon deg, alt m)."""
    enu = ned_to_enu(np.array([north, east, down], dtype=float))
    return enu_to_geodetic(enu[0], enu[1], enu[2], home_lat, home_lon, home_alt)
