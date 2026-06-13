"""GPS pin -> local metric *home* frame (Stage 1, Test 1).

The user's map pin is a geodetic point ``(lat, lon, alt)``. Everything
downstream -- camera poses, obstacle maps, flight paths -- lives in a local
metric frame anchored at that pin. This module wraps :mod:`pral.core.frames`
behind a small :class:`HomeFrameRef` that remembers the anchor so callers stop
threading ``home_lat, home_lon, home_alt`` through every call.

The heavy lifting (WGS-84 ECEF tangent-plane conversion, accurate to well under
0.5 m within a few km) is already done in the core; this is the Stage-1 facade
over it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pral.core import frames
from pral.core.schemas import HomeFrame


@dataclass(frozen=True)
class HomeFrameRef:
    """A locked geodetic anchor + conversions into/out of its local frame.

    ``lat``/``lon`` in degrees, ``alt`` in meters. Constructed from a user's GPS
    pin via :func:`home_from_pin`. All conversions are pure and deterministic.
    """

    lat: float
    lon: float
    alt: float = 0.0

    def enu(self, lat: float, lon: float, alt: float = 0.0) -> np.ndarray:
        """Geodetic point -> local ENU (East, North, Up) meters."""
        return frames.geodetic_to_enu(lat, lon, alt, self.lat, self.lon, self.alt)

    def ned(self, lat: float, lon: float, alt: float = 0.0) -> np.ndarray:
        """Geodetic point -> local NED (North, East, Down) meters."""
        return frames.geodetic_to_ned(lat, lon, alt, self.lat, self.lon, self.alt)

    def geodetic_from_enu(
        self, east: float, north: float, up: float = 0.0
    ) -> np.ndarray:
        """Local ENU meters -> geodetic ``[lat, lon, alt]``."""
        return frames.enu_to_geodetic(east, north, up, self.lat, self.lon, self.alt)

    def geodetic_from_ned(
        self, north: float, east: float, down: float = 0.0
    ) -> np.ndarray:
        """Local NED meters -> geodetic ``[lat, lon, alt]``."""
        return frames.ned_to_geodetic(north, east, down, self.lat, self.lon, self.alt)

    def to_home_frame(self) -> HomeFrame:
        """Export as the schema :class:`HomeFrame` for the AOI artifact."""
        return HomeFrame(lat=self.lat, lon=self.lon, alt=self.alt)


def home_from_pin(lat: float, lon: float, alt: float = 0.0) -> HomeFrameRef:
    """Establish the local frame from a user's GPS pin.

    The pin becomes the origin of the ENU/NED frame: ``home_from_pin(lat, lon)``
    then ``.enu(lat, lon)`` returns ~zero.
    """
    return HomeFrameRef(lat=float(lat), lon=float(lon), alt=float(alt))
