"""Viewpoint selection -- local maxima of the value field, filtered for safety.

Stage 4 hands us a :class:`~pral.core.schemas.ValueField`: a bag of candidate
viewpoints, each a pose with a scalar ``value``. Stage 5 picks the *best places
to shoot from*:

1. **Local maxima** -- a viewpoint is a local maximum if no other viewpoint
   within ``neighbor_radius`` meters has a strictly higher value. This is the
   discrete analogue of "peaks of value(v)".
2. **Admissibility filter** -- every kept viewpoint must pass the Test-19
   predicate: inside the geofence and clear of the obstacle map by the safety
   margin. Inadmissible peaks are dropped (never nudged into a wall).

The output is a deterministic, value-sorted list of admissible
:class:`SelectedViewpoint` records.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pral.core.camera import Pose
from pral.core.schemas import AOI, ValueField, Viewpoint
from pral.stage5_path.geofence import ObstacleSource, is_admissible


@dataclass
class SelectedViewpoint:
    """A chosen viewpoint: its ENU position, value, and the source pose."""

    position: np.ndarray  # [3] ENU
    value: float
    pose: Pose


def _viewpoint_position(vp: Viewpoint) -> np.ndarray:
    return np.asarray(vp.pose.position, float)


def _viewpoint_pose(vp: Viewpoint) -> Pose:
    return Pose.from_quaternion(
        vp.pose.position,
        np.array(
            [vp.pose.orientation.w, vp.pose.orientation.x, vp.pose.orientation.y, vp.pose.orientation.z]
        ),
    )


def local_maxima(field: ValueField, neighbor_radius: float = 6.0) -> list[Viewpoint]:
    """Return viewpoints that are local maxima of value within ``neighbor_radius``.

    Ties are broken deterministically: a viewpoint survives unless a *strictly*
    higher-valued neighbor exists, so duplicate-valued clusters keep their
    lowest-index representative.
    """
    samples = field.samples
    n = len(samples)
    if n == 0:
        return []
    positions = np.array([_viewpoint_position(s) for s in samples])
    values = np.array([s.value if s.value is not None else 0.0 for s in samples])

    maxima: list[Viewpoint] = []
    for i in range(n):
        d = np.linalg.norm(positions - positions[i], axis=1)
        neigh = d <= neighbor_radius + 1e-9
        higher = neigh & (values > values[i] + 1e-12)
        if np.any(higher):
            continue
        # Among equal-valued neighbors, keep only the lowest index (dedupe clusters).
        equal = neigh & (np.abs(values - values[i]) <= 1e-12)
        equal_idx = np.nonzero(equal)[0]
        if equal_idx.min() != i:
            continue
        maxima.append(samples[i])
    return maxima


def select_viewpoints(
    field: ValueField,
    aoi: AOI,
    obstacle: ObstacleSource | None = None,
    *,
    neighbor_radius: float = 6.0,
    safety_margin: float = 1.5,
    min_altitude: float = 0.0,
    max_count: int | None = None,
) -> list[SelectedViewpoint]:
    """Pick admissible local-maximum viewpoints, sorted by value (descending).

    Parameters
    ----------
    field
        Stage-4 value field (candidate viewpoints + scalar values).
    aoi
        Stage-1 geofence (polygon + altitude ceiling).
    obstacle
        Stage-2 obstacle map / voxel scene for clearance, or ``None``.
    neighbor_radius
        Radius (m) defining the local-maximum neighborhood.
    safety_margin
        Minimum clearance (m) required to keep a viewpoint.
    min_altitude
        Geofence altitude floor (m).
    max_count
        If given, keep at most this many highest-value viewpoints.
    """
    peaks = local_maxima(field, neighbor_radius)
    selected: list[SelectedViewpoint] = []
    for vp in peaks:
        pos = _viewpoint_position(vp)
        if not is_admissible(pos, aoi, obstacle, safety_margin, min_altitude):
            continue
        selected.append(
            SelectedViewpoint(
                position=pos,
                value=float(vp.value if vp.value is not None else 0.0),
                pose=_viewpoint_pose(vp),
            )
        )
    # Deterministic order: value descending, then by position for tie-breaks.
    selected.sort(key=lambda s: (-s.value, s.position[0], s.position[1], s.position[2]))
    if max_count is not None:
        selected = selected[:max_count]
    return selected


__all__ = ["SelectedViewpoint", "local_maxima", "select_viewpoints"]
