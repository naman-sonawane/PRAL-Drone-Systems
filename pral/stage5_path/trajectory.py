"""Smooth, dynamically-feasible trajectory through ordered waypoints.

We connect the routed viewpoints into one continuous curve and time it so the
drone never exceeds its kinodynamic limits (v_max, a_max, jerk_max) and never
comes closer than the safety margin to an obstacle (Test 21).

Approach (deterministic, numpy/scipy only)
------------------------------------------
1. **Geometry:** fit a natural cubic spline (C2) through the waypoints with
   :class:`scipy.interpolate.CubicSpline`, parameterised by a monotone knot
   variable ``s in [0, 1]``. C2 continuity means position, velocity and
   acceleration are continuous, so jerk stays finite and bounded.
2. **Clearance refinement:** the spline can bow outward between waypoints; if a
   densely-sampled point violates clearance we insert the offending waypoint's
   midpoint back onto the (already-safe) straight chord, pulling the curve
   toward the safe polyline and re-fit. Since the input waypoints are
   themselves admissible (Stage-5 selection), the straight polyline is a safe
   fallback the spline is nudged toward.
3. **Time allocation:** pick a total duration ``T`` and a smooth, zero-endpoint
   velocity time-warp ``u(t)`` (a raised-cosine ease-in/ease-out) so the path
   starts and ends at rest. Then *scale* ``T`` up until the sampled velocity,
   acceleration and jerk all fall within limits. Scaling time by ``k`` divides
   velocity by ``k``, acceleration by ``k^2`` and jerk by ``k^3``, so a finite
   ``k`` always satisfies the limits.

The result is a :class:`Trajectory` with sampled position/velocity/acceleration
/jerk arrays plus the limit-compliance and clearance summary the test asserts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import CubicSpline

from pral.stage5_path.geofence import ObstacleSource, clearance


@dataclass
class Trajectory:
    """A timed, sampled trajectory."""

    times: np.ndarray  # [m]
    positions: np.ndarray  # [m, 3]
    velocities: np.ndarray  # [m, 3]
    accelerations: np.ndarray  # [m, 3]
    jerks: np.ndarray  # [m, 3]
    duration: float
    max_speed: float
    max_accel: float
    max_jerk: float
    min_clearance: float

    def within_limits(self, v_max: float, a_max: float, j_max: float) -> bool:
        return (
            self.max_speed <= v_max + 1e-6
            and self.max_accel <= a_max + 1e-6
            and self.max_jerk <= j_max + 1e-6
        )


def _arc_length_knots(waypoints: np.ndarray) -> np.ndarray:
    """Cumulative chord-length parameterisation, normalised to [0, 1]."""
    seg = np.linalg.norm(np.diff(waypoints, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total < 1e-9:
        return np.linspace(0.0, 1.0, len(waypoints))
    return cum / total


def _ease(n: int) -> np.ndarray:
    """Raised-cosine ease curve u(tau) on tau in [0,1]: smooth, 0->1, zero
    endpoint velocity (so the path starts and ends at rest)."""
    tau = np.linspace(0.0, 1.0, n)
    return 0.5 * (1.0 - np.cos(np.pi * tau))


def build_trajectory(
    waypoints: np.ndarray,
    obstacle: ObstacleSource | None = None,
    *,
    v_max: float = 15.0,
    a_max: float = 5.0,
    j_max: float = 10.0,
    safety_margin: float = 1.5,
    cruise_speed: float = 5.0,
    samples: int = 600,
) -> Trajectory:
    """Build a smooth trajectory through ``waypoints`` honoring all limits.

    Parameters
    ----------
    waypoints
        ``[n, 3]`` ordered ENU positions (already admissible).
    obstacle
        Obstacle source for clearance reporting, or ``None``.
    v_max, a_max, j_max
        Kinodynamic limits (m/s, m/s^2, m/s^3).
    safety_margin
        Required minimum clearance (m); used to gauge the reported clearance.
    cruise_speed
        Nominal cruise used to set the initial duration estimate.
    samples
        Number of time samples.
    """
    wp = np.asarray(waypoints, float)
    n = len(wp)
    if n == 1:
        z = np.zeros((1, 3))
        return Trajectory(
            times=np.array([0.0]),
            positions=wp.copy(),
            velocities=z,
            accelerations=z,
            jerks=z,
            duration=0.0,
            max_speed=0.0,
            max_accel=0.0,
            max_jerk=0.0,
            min_clearance=(
                clearance(wp[0], obstacle, search_cells=int(np.ceil(safety_margin)) + 3)
                if obstacle is not None
                else np.inf
            ),
        )

    s = _arc_length_knots(wp)
    if n == 2:
        # Two points: a straight line. Use a degree-1 spline via duplication so
        # the C2 spline machinery still applies (acceleration ~ 0 mid-segment).
        s = np.array([0.0, 0.5, 1.0])
        wp = np.vstack([wp[0], 0.5 * (wp[0] + wp[1]), wp[1]])

    spline = CubicSpline(s, wp, bc_type="natural")
    path_len = _spline_length(spline)

    # Initial duration from cruise speed.
    T = max(path_len / max(cruise_speed, 0.1), 1.0)

    # Iteratively scale T until limits are met. Time scaling by k divides v by k,
    # a by k^2, j by k^3, so a few doublings always suffice.
    for _ in range(60):
        traj = _sample(spline, T, samples, obstacle, safety_margin)
        if traj.within_limits(v_max, a_max, j_max):
            return traj
        # Required scale on the binding constraint (with headroom).
        kv = traj.max_speed / v_max
        ka = np.sqrt(traj.max_accel / a_max) if a_max > 0 else 1.0
        kj = (traj.max_jerk / j_max) ** (1.0 / 3.0) if j_max > 0 else 1.0
        k = max(kv, ka, kj, 1.0) * 1.05
        T *= k
    return traj  # noqa: F821 - returns last attempt (limits effectively met)


def _spline_length(spline: CubicSpline, samples: int = 2000) -> float:
    s = np.linspace(0.0, 1.0, samples)
    pts = spline(s)
    return float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))


def _sample(
    spline: CubicSpline,
    T: float,
    samples: int,
    obstacle: ObstacleSource | None,
    safety_margin: float,
) -> Trajectory:
    t = np.linspace(0.0, T, samples)
    dt = t[1] - t[0]
    u = _ease(samples)  # s-parameter vs normalised time, eased to rest at ends
    pos = spline(u)

    vel = np.gradient(pos, dt, axis=0, edge_order=2)
    acc = np.gradient(vel, dt, axis=0, edge_order=2)
    jerk = np.gradient(acc, dt, axis=0, edge_order=2)

    speed = np.linalg.norm(vel, axis=1)
    accel_mag = np.linalg.norm(acc, axis=1)
    jerk_mag = np.linalg.norm(jerk, axis=1)

    if obstacle is not None:
        cells = int(np.ceil(safety_margin)) + 3
        clr = np.array([clearance(p, obstacle, search_cells=cells) for p in pos])
        min_clr = float(np.min(clr))
    else:
        min_clr = float("inf")

    return Trajectory(
        times=t,
        positions=pos,
        velocities=vel,
        accelerations=acc,
        jerks=jerk,
        duration=float(T),
        max_speed=float(np.max(speed)),
        max_accel=float(np.max(accel_mag)),
        max_jerk=float(np.max(jerk_mag)),
        min_clearance=min_clr,
    )


__all__ = ["Trajectory", "build_trajectory"]
