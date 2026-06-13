"""Interest-field value scoring + heatmap-to-surface projection (Stage 4 core).

All geometry is in the local **ENU** world frame and the standard CV camera
frame from :mod:`pral.core.camera` (``+x`` right, ``+y`` down, ``+z`` forward).

A :class:`Hotspot` is a point in 3D space worth filming: an ENU position, an
outward surface normal (unit ENU vector pointing away from the structure toward
free space), and a scalar ``interest`` (the baked per-surface interest density).

The value of a candidate viewpoint is a product of three independent factors,
summed over the hotspots that viewpoint can actually see::

    value(v) = sum_p interest(p) * framing(v, p) * focal(dist(v, p))

* ``focal(d)``   -- Gaussian peaking at the optimal subject distance.
* ``framing``    -- how straight-on the look is (ray vs surface normal) times how
  well-centred the subject sits in frame.
* ``interest``   -- the hotspot's own importance.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pral.core.camera import Camera, Pose
from pral.core.schemas import PoseModel, Quaternion, ValueField, Viewpoint

# ---------------------------------------------------------------------------
# focal() -- distance weighting (Test 14)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FocalParams:
    """Parameters of the :func:`focal` distance weighting.

    ``optimal`` is the ideal subject standoff (meters) where the weight peaks at
    ``1.0``; ``sigma`` is the Gaussian width controlling how fast the reward
    falls off on either side.
    """

    optimal: float = 12.0
    sigma: float = 6.0

    def __post_init__(self) -> None:
        if self.optimal <= 0.0:
            raise ValueError("optimal distance must be positive")
        if self.sigma <= 0.0:
            raise ValueError("sigma must be positive")


def focal(dist: float | np.ndarray, params: FocalParams | None = None) -> np.ndarray:
    """Distance weighting that peaks at the optimal subject distance.

    A Gaussian centred on ``params.optimal``: returns ``1.0`` exactly at the
    optimal distance and decays monotonically (strictly) toward ``0`` as the
    distance moves away in either direction. Vectorized over ``dist``.
    """
    if params is None:
        params = FocalParams()
    d = np.asarray(dist, dtype=float)
    return np.exp(-((d - params.optimal) ** 2) / (2.0 * params.sigma**2))


# ---------------------------------------------------------------------------
# framing() -- look quality (angle vs normal + in-frame position)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FramingParams:
    """Weights for the :func:`framing` reward.

    ``facing_power`` sharpens the straight-on reward (higher = punishes oblique
    looks harder). ``center_weight`` in ``[0, 1]`` blends the in-frame centring
    reward: ``0`` ignores where the subject sits in the image, ``1`` requires it
    dead-centre. A hotspot outside the image gets framing ``0``.
    """

    facing_power: float = 1.0
    center_weight: float = 0.5

    def __post_init__(self) -> None:
        if self.facing_power <= 0.0:
            raise ValueError("facing_power must be positive")
        if not 0.0 <= self.center_weight <= 1.0:
            raise ValueError("center_weight must be in [0, 1]")


@dataclass(frozen=True)
class Hotspot:
    """A 3D point worth filming: ENU position, outward unit normal, interest."""

    position: np.ndarray
    normal: np.ndarray
    interest: float = 1.0

    def __post_init__(self) -> None:
        pos = np.asarray(self.position, dtype=float).reshape(3)
        nrm = np.asarray(self.normal, dtype=float).reshape(3)
        n = np.linalg.norm(nrm)
        if n < 1e-12:
            raise ValueError("hotspot normal must be non-zero")
        object.__setattr__(self, "position", pos)
        object.__setattr__(self, "normal", nrm / n)
        object.__setattr__(self, "interest", float(self.interest))


def _facing_reward(pose: Pose, hotspot: Hotspot, power: float) -> float:
    """Straight-on reward: how aligned the look is with the surface normal.

    The view direction from camera to hotspot, compared against the *inward*
    normal (``-normal``). When the camera sits straight out along the outward
    normal, the view direction equals ``-normal`` and the reward is ``1``; it
    falls to ``0`` as the look grazes the surface (and is clamped at ``0`` when
    looking at the back face).
    """
    to_hotspot = hotspot.position - pose.position
    dist = np.linalg.norm(to_hotspot)
    if dist < 1e-9:
        return 0.0
    view_dir = to_hotspot / dist
    align = float(np.dot(view_dir, -hotspot.normal))
    if align <= 0.0:
        return 0.0
    return align**power


def _in_frame_reward(camera: Camera, pose: Pose, hotspot: Hotspot, center_weight: float) -> float:
    """In-frame centring reward in ``[0, 1]``; ``0`` if the subject is off-image.

    Projects the hotspot to a pixel and measures normalized distance from the
    principal point. ``center_weight`` blends between "anywhere in frame is fine"
    (``0``) and "must be dead centre" (``1``).
    """
    p_c = pose.world_to_camera(hotspot.position)
    if p_c[2] <= 1e-9:
        return 0.0
    u = camera.fx * p_c[0] / p_c[2] + camera.cx
    v = camera.fy * p_c[1] / p_c[2] + camera.cy
    if not (0.0 <= u < camera.width and 0.0 <= v < camera.height):
        return 0.0
    # Normalized offset from image center in [0, 1] (1 == corner).
    du = (u - camera.cx) / (camera.width / 2.0)
    dv = (v - camera.cy) / (camera.height / 2.0)
    offset = min(1.0, float(np.hypot(du, dv) / np.sqrt(2.0)))
    centredness = 1.0 - offset
    return (1.0 - center_weight) + center_weight * centredness


def framing(
    camera: Camera,
    pose: Pose,
    hotspot: Hotspot,
    params: FramingParams | None = None,
) -> float:
    """Combined look-quality reward in ``[0, 1]`` for filming ``hotspot``.

    Product of the straight-on (angle-vs-normal) reward and the in-frame
    centring reward. Returns ``0`` if the hotspot is behind the camera, outside
    the image, or on a back face.
    """
    if params is None:
        params = FramingParams()
    facing = _facing_reward(pose, hotspot, params.facing_power)
    if facing <= 0.0:
        return 0.0
    in_frame = _in_frame_reward(camera, pose, hotspot, params.center_weight)
    return facing * in_frame


# ---------------------------------------------------------------------------
# value(v) -- viewpoint score (Test 15)
# ---------------------------------------------------------------------------


def viewpoint_value(
    camera: Camera,
    pose: Pose,
    hotspots: list[Hotspot],
    focal_params: FocalParams | None = None,
    framing_params: FramingParams | None = None,
) -> float:
    """Score a candidate viewpoint by summing over the hotspots it can film.

    ``value(v) = sum_p interest(p) * framing(v, p) * focal(dist(v, p))`` over the
    hotspots in view. Hotspots that are behind the camera, off-image, on a back
    face, or otherwise badly framed contribute ``0``.
    """
    total = 0.0
    for h in hotspots:
        f = framing(camera, pose, h, framing_params)
        if f <= 0.0:
            continue
        dist = float(np.linalg.norm(h.position - pose.position))
        total += h.interest * f * float(focal(dist, focal_params))
    return total


# ---------------------------------------------------------------------------
# Heatmap -> 3D surface projection (Test 16)
# ---------------------------------------------------------------------------


def project_heatmap_to_surface(
    camera: Camera,
    pose: Pose,
    heatmap: np.ndarray,
    surface_points: np.ndarray,
    threshold: float = 0.0,
) -> list[Hotspot]:
    """Lift a per-pixel interest heatmap onto known 3D surface points.

    For each surface point in view, sample the heatmap at its projected pixel
    (nearest-pixel) and emit a :class:`Hotspot` carrying that interest value.
    The outward normal is estimated as the unit vector from the surface point
    back toward the camera (a stand-in for the true surface normal that is
    correct for points facing the camera).

    This is the geometric core of "project per-pixel heatmaps onto the 3D model"
    (Test 16): a bright heatmap pixel localizes to the surface point that
    projects there, with localization error bounded by the surface resolution.

    ``heatmap`` is ``[H, W]`` matching ``camera.height x camera.width``. Surface
    points with interest ``<= threshold`` are dropped.
    """
    heatmap = np.asarray(heatmap, dtype=float)
    if heatmap.shape != (camera.height, camera.width):
        raise ValueError(
            f"heatmap shape {heatmap.shape} != (height, width) "
            f"({camera.height}, {camera.width})"
        )
    surface_points = np.asarray(surface_points, dtype=float).reshape(-1, 3)

    hotspots: list[Hotspot] = []
    for p_w in surface_points:
        p_c = pose.world_to_camera(p_w)
        if p_c[2] <= 1e-9:
            continue
        u = camera.fx * p_c[0] / p_c[2] + camera.cx
        v = camera.fy * p_c[1] / p_c[2] + camera.cy
        ui = int(round(u))
        vi = int(round(v))
        if not (0 <= ui < camera.width and 0 <= vi < camera.height):
            continue
        interest = float(heatmap[vi, ui])
        if interest <= threshold:
            continue
        to_cam = pose.position - p_w
        n = np.linalg.norm(to_cam)
        if n < 1e-9:
            continue
        hotspots.append(Hotspot(position=p_w, normal=to_cam / n, interest=interest))
    return hotspots


# ---------------------------------------------------------------------------
# build_value_field -- score candidate viewpoints into the artifact
# ---------------------------------------------------------------------------


def build_value_field(
    camera: Camera,
    candidate_poses: list[Pose],
    hotspots: list[Hotspot],
    focal_params: FocalParams | None = None,
    framing_params: FramingParams | None = None,
) -> ValueField:
    """Score every candidate viewpoint and pack into a :class:`ValueField`.

    Each pose becomes a :class:`~pral.core.schemas.Viewpoint` whose ``value`` is
    :func:`viewpoint_value`. Stage 5 reads this field's peaks.
    """
    samples: list[Viewpoint] = []
    for pose in candidate_poses:
        val = viewpoint_value(camera, pose, hotspots, focal_params, framing_params)
        q = pose.quaternion
        samples.append(
            Viewpoint(
                pose=PoseModel(
                    position=[float(x) for x in pose.position],
                    orientation=Quaternion(
                        w=float(q[0]), x=float(q[1]), y=float(q[2]), z=float(q[3])
                    ),
                ),
                value=val,
            )
        )
    return ValueField(samples=samples)


__all__ = [
    "FocalParams",
    "FramingParams",
    "Hotspot",
    "focal",
    "framing",
    "viewpoint_value",
    "project_heatmap_to_surface",
    "build_value_field",
]
