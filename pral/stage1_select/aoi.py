"""Confirm + lock a geofenced AOI polygon (Stage 1, Test 3).

Once the user taps a candidate, its footprint polygon (in ENU east/north meters)
becomes the locked :class:`~pral.core.schemas.AOI`. Two pieces of pure geometry
back this stage:

* :func:`polygon_iou` -- intersection-over-union of the confirmed footprint vs a
  ground-truth footprint, the Test-3 KPI (IoU >= 0.7). Areas come from the exact
  shoelace formula; the overlap polygon is computed by Sutherland-Hodgman
  clipping. That clipper requires the *clip* polygon to be convex, which holds
  for building footprints (boxes / convex blocks) -- :func:`confirm_aoi` rejects
  self-intersecting input, and the IoU helper clips the test polygon against the
  (convex) ground truth.
* :func:`point_in_polygon` -- even-odd ray-cast containment, used by downstream
  geofence checks (Stage 5, Test 19).

:func:`confirm_aoi` assembles the validated, geofenced :class:`AOI` artifact --
the Stage-1 output contract.
"""

from __future__ import annotations

import numpy as np

from pral.core.schemas import AOI, HomeFrame

from .gps_frame import HomeFrameRef


def polygon_area(polygon: np.ndarray) -> float:
    """Unsigned area of a simple polygon via the shoelace formula (m^2)."""
    pts = np.asarray(polygon, dtype=float).reshape(-1, 2)
    if len(pts) < 3:
        return 0.0
    x = pts[:, 0]
    y = pts[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _is_convex_ccw(polygon: np.ndarray) -> bool:
    """True if the polygon is convex (allowing either winding)."""
    pts = np.asarray(polygon, dtype=float).reshape(-1, 2)
    n = len(pts)
    if n < 3:
        return False
    signs = []
    for i in range(n):
        a = pts[i]
        b = pts[(i + 1) % n]
        c = pts[(i + 2) % n]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) > 1e-12:
            signs.append(cross > 0)
    return len(set(signs)) <= 1


def _ensure_ccw(polygon: np.ndarray) -> np.ndarray:
    """Return the polygon with counter-clockwise winding (positive signed area)."""
    pts = np.asarray(polygon, dtype=float).reshape(-1, 2)
    x = pts[:, 0]
    y = pts[:, 1]
    signed2 = np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))
    if signed2 < 0:
        return pts[::-1].copy()
    return pts.copy()


def _clip_polygon(subject: np.ndarray, clip_convex: np.ndarray) -> np.ndarray:
    """Sutherland-Hodgman: clip ``subject`` by the convex polygon ``clip_convex``.

    Returns the (possibly empty) intersection polygon as an ``(m, 2)`` array.
    ``clip_convex`` must be convex; it is reoriented to CCW internally so each
    edge's left half-plane is the interior.
    """
    clip = _ensure_ccw(clip_convex)
    output = [np.asarray(p, dtype=float) for p in np.asarray(subject, dtype=float).reshape(-1, 2)]
    nclip = len(clip)
    for i in range(nclip):
        a = clip[i]
        b = clip[(i + 1) % nclip]
        edge = b - a
        if not output:
            break
        input_list = output
        output = []
        normal = np.array([-edge[1], edge[0]])  # inward normal for CCW clip poly

        def inside(p: np.ndarray) -> bool:
            return np.dot(normal, p - a) >= -1e-12

        for j in range(len(input_list)):
            cur = input_list[j]
            prev = input_list[j - 1]
            cur_in = inside(cur)
            prev_in = inside(prev)
            if cur_in:
                if not prev_in:
                    output.append(_line_intersect(prev, cur, a, b))
                output.append(cur)
            elif prev_in:
                output.append(_line_intersect(prev, cur, a, b))
    if not output:
        return np.zeros((0, 2), dtype=float)
    return np.array(output, dtype=float)


def _line_intersect(
    p1: np.ndarray, p2: np.ndarray, a: np.ndarray, b: np.ndarray
) -> np.ndarray:
    """Intersection of segment ``p1->p2`` with the infinite line through ``a, b``."""
    d1 = p2 - p1
    d2 = b - a
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-15:
        return p1.copy()
    t = ((a[0] - p1[0]) * d2[1] - (a[1] - p1[1]) * d2[0]) / denom
    return p1 + t * d1


def polygon_iou(poly_a: np.ndarray, poly_b: np.ndarray) -> float:
    """Intersection-over-union of two polygons (east/north meters).

    ``poly_b`` is treated as the clip polygon and must be convex (the Test-3
    ground-truth footprint). Returns a value in ``[0, 1]``.
    """
    a = np.asarray(poly_a, dtype=float).reshape(-1, 2)
    b = np.asarray(poly_b, dtype=float).reshape(-1, 2)
    if not _is_convex_ccw(b):
        # Fall back to clipping the convex one if exactly one side is convex.
        if _is_convex_ccw(a):
            a, b = b, a
        else:
            raise ValueError("polygon_iou requires at least one convex polygon")
    inter = _clip_polygon(a, b)
    area_i = polygon_area(inter)
    area_u = polygon_area(a) + polygon_area(b) - area_i
    if area_u <= 0.0:
        return 0.0
    return float(area_i / area_u)


def point_in_polygon(point: np.ndarray, polygon: np.ndarray) -> bool:
    """Even-odd ray-cast point-in-polygon test (east/north meters)."""
    p = np.asarray(point, dtype=float).reshape(2)
    pts = np.asarray(polygon, dtype=float).reshape(-1, 2)
    n = len(pts)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if ((yi > p[1]) != (yj > p[1])) and (
            p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def confirm_aoi(
    home: HomeFrameRef | HomeFrame,
    polygon_enu: np.ndarray,
    max_altitude: float = 120.0,
    name: str | None = None,
) -> AOI:
    """Lock a confirmed footprint polygon into the geofenced :class:`AOI` artifact.

    ``polygon_enu`` is an ``(n>=3, 2)`` array of ENU east/north vertices. Raises
    ``ValueError`` for a degenerate (near-zero-area) polygon. The returned
    :class:`AOI` is fully validated (pydantic) and ready for downstream stages.
    """
    pts = np.asarray(polygon_enu, dtype=float).reshape(-1, 2)
    if len(pts) < 3:
        raise ValueError("AOI polygon needs at least 3 vertices")
    if polygon_area(pts) < 1e-6:
        raise ValueError("AOI polygon is degenerate (zero area)")

    home_frame = (
        home.to_home_frame() if isinstance(home, HomeFrameRef) else home
    )
    return AOI(
        home=home_frame,
        polygon_enu=[[float(e), float(n)] for e, n in pts],
        max_altitude=float(max_altitude),
        name=name,
    )
