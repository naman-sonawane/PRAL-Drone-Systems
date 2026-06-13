"""Stage 1 -- GPS Target Selection & Confirmation.

The user drops a pin (or draws a boundary) on a map; the drone ascends and a
detector proposes candidate structures; the user taps one to lock the Area of
Interest (AOI). This package turns that flow into deterministic geometry:

* :mod:`gps_frame`  -- a GPS pin establishes the local ENU/NED *home* frame and
  converts geodetic points into / out of it (Test 1).
* :mod:`reproject`  -- a detection (pixel or box) is reprojected onto the ground
  plane via the camera pose and turned back into GPS (Test 2).
* :mod:`aoi`        -- a confirmed polygon becomes a geofenced :class:`~pral.core.schemas.AOI`;
  helpers measure polygon IoU against a ground-truth footprint (Test 3) and test
  containment for downstream geofence checks.
* :mod:`detector`   -- the open-vocabulary detector *interface* (a stub the real
  YOLO-World / Grounding DINO model would implement); Test 4 (Tier C) exercises
  a real detector and is skipped until field data exists.

Downstream output contract: a geofenced :class:`AOI` + its :class:`HomeFrame`.
"""

from __future__ import annotations

from .aoi import (
    confirm_aoi,
    point_in_polygon,
    polygon_area,
    polygon_iou,
)
from .detector import (
    Detection,
    OpenVocabDetector,
    StubDetector,
)
from .gps_frame import (
    HomeFrameRef,
    home_from_pin,
)
from .reproject import (
    reproject_box_to_gps,
    reproject_pixel_to_enu,
    reproject_pixel_to_gps,
)

__all__ = [
    "HomeFrameRef",
    "home_from_pin",
    "reproject_pixel_to_enu",
    "reproject_pixel_to_gps",
    "reproject_box_to_gps",
    "confirm_aoi",
    "polygon_iou",
    "polygon_area",
    "point_in_polygon",
    "Detection",
    "OpenVocabDetector",
    "StubDetector",
]
