"""Orbit-radius geometry: how far back to orbit so the building frames cleanly.

The spec's framing equation: to fit a subject of height ``H`` (plus a ``margin``
of headroom) inside a camera with vertical field of view ``VFOV``, the standoff
distance is

    r = (H / 2 + margin) / tan(VFOV / 2)

Derivation (first principles): a pinhole camera at distance ``r`` from a target
sees, on the image plane, everything within a half-angle ``VFOV/2`` of the
optical axis. The vertical half-extent of the scene that just fills the frame
is ``r * tan(VFOV/2)``. We want that to equal half the building height plus the
margin, ``H/2 + margin``; solving for ``r`` gives the equation above.

:func:`fits_in_frame` is the *check* behind Test 5: it projects the building's
vertical (and horizontal) extremes into the image from a camera at distance
``r`` and confirms they land inside the frame with the requested margin -- i.e.
no clipping. We verify the geometry, not just re-assert the formula.
"""

from __future__ import annotations

import numpy as np

from pral.core.camera import Camera, Pose, project


def orbit_radius(height: float, vfov_deg: float, margin: float = 4.0) -> float:
    """Standoff radius ``r`` that frames a building of height ``H`` with margin.

    ``r = (H/2 + margin) / tan(VFOV/2)``. Raises ``ValueError`` for a
    non-positive height or a VFOV outside ``(0, 180)`` degrees.
    """
    if height <= 0:
        raise ValueError("height must be positive")
    if not (0.0 < vfov_deg < 180.0):
        raise ValueError("vfov_deg must be in (0, 180)")
    if margin < 0:
        raise ValueError("margin must be non-negative")
    return (height / 2.0 + margin) / np.tan(np.radians(vfov_deg) / 2.0)


def fits_in_frame(
    camera: Camera,
    height: float,
    radius: float,
    width: float = 0.0,
    margin_frac: float = 0.0,
) -> bool:
    """Does a building of ``height`` (and optional ``width``) frame cleanly?

    Places a camera at distance ``radius`` on the +N orbit line at mid-building
    altitude, looking at the building centroid raised to mid-height, then
    projects the building's extreme points (top/bottom, and left/right corners
    if ``width`` given) and checks each lands inside the image with at least a
    ``margin_frac`` fractional border on every side.

    ``margin_frac=0.0`` means "must be inside the image"; ``0.1`` means "must
    leave a 10% border", a stricter no-clipping guarantee.
    """
    if not (0.0 <= margin_frac < 0.5):
        raise ValueError("margin_frac must be in [0, 0.5)")

    mid = height / 2.0
    centroid = np.array([0.0, 0.0, 0.0])
    cam_pos = np.array([0.0, radius, mid])  # +N orbit point
    pose = Pose.looking_at(cam_pos, target=centroid + np.array([0.0, 0.0, mid]))

    half_w = width / 2.0
    # Building extreme points in ENU: full vertical span at the near face,
    # plus the two horizontal corners at mid-height.
    extremes = [
        np.array([0.0, -half_w, 0.0]),          # base center (near face, U=0)
        np.array([0.0, -half_w, height]),        # top center
    ]
    if width > 0:
        extremes += [
            np.array([-half_w, -half_w, mid]),   # left corner
            np.array([half_w, -half_w, mid]),    # right corner
        ]

    bx = margin_frac * camera.width
    by = margin_frac * camera.height
    for p in extremes:
        try:
            u, v = project(camera, pose, p)
        except ValueError:
            return False  # behind camera -> definitely not framed
        if not (bx <= u <= camera.width - bx and by <= v <= camera.height - by):
            return False
    return True


def frames_building(
    camera: Camera,
    height: float,
    margin: float = 4.0,
    width: float = 0.0,
    margin_frac: float = 0.0,
) -> tuple[float, bool]:
    """Convenience: compute ``r`` then confirm the building frames in it.

    Returns ``(r, ok)`` where ``r`` is the orbit radius and ``ok`` is the
    :func:`fits_in_frame` verdict at that radius.
    """
    r = orbit_radius(height, camera.vfov_deg, margin=margin)
    ok = fits_in_frame(camera, height, r, width=width, margin_frac=margin_frac)
    return r, ok


__all__ = ["orbit_radius", "fits_in_frame", "frames_building"]
