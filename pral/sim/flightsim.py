"""Minimal kinematic flight simulator.

Given a :class:`~pral.core.schemas.Mission`, fly the drone through its
waypoints at constant speed along straight segments, sampling at a fixed time
step. At each sample we record the executed pose (position + gimbal-derived
orientation), check clearance against an :class:`~pral.core.schemas.ObstacleMap`
(or a :class:`~pral.sim.scenes.VoxelScene`), and integrate battery drain.

This is deliberately simple -- no aerodynamics. It exists to answer the Tier-B
questions the tests ask:

* Does the mission *load and fly* without error (Test 23)?
* Are there any collisions along the path (Tests 24-26, E2E)?
* Does the drone stay within the battery budget; under budget pressure does it
  land safely rather than crash (Test 26)?

Determinism: fixed ``dt``, no RNG, no wall-clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from pral.core.schemas import Mission, ObstacleMap
from pral.sim.scenes import VoxelLabel, VoxelScene


@dataclass
class FlightResult:
    """Outcome of a simulated mission flight."""

    executed_positions: np.ndarray  # [n_samples, 3] ENU
    timestamps: np.ndarray  # [n_samples] seconds
    path_length: float  # meters
    duration_s: float
    battery_used: float  # 0..1 fraction of capacity
    battery_remaining: float  # 0..1
    collided: bool
    collision_point: np.ndarray | None
    min_clearance: float  # meters to nearest obstacle along the flown path
    completed: bool  # reached the final waypoint (vs early land on low battery)
    landed_safely: bool

    @property
    def ok(self) -> bool:
        """No collision and either completed or landed safely."""
        return (not self.collided) and (self.completed or self.landed_safely)


@dataclass
class DroneConfig:
    """Kinematic + energy parameters for the sim drone."""

    cruise_speed: float = 5.0  # m/s default if a waypoint has no speed
    max_speed: float = 15.0
    max_accel: float = 5.0  # m/s^2 (for kinodynamic checks elsewhere)
    # Battery: linear model. drain per second of flight, as a fraction.
    battery_capacity_s: float = 18 * 60.0  # ~18 min hover-equivalent
    reserve_fraction: float = 0.15  # land if remaining drops below this
    safety_margin: float = 1.5  # meters; clearance below this = collision


def _occupied_lookup(obstacle: ObstacleMap | VoxelScene):
    """Return (origin, voxel_size, shape, is_occupied(i,j,k)) for either source."""
    if isinstance(obstacle, VoxelScene):
        origin = np.asarray(obstacle.origin_enu, float)
        vs = obstacle.voxel_size
        shape = obstacle.shape

        def occ(i: int, j: int, k: int) -> bool:
            if not (0 <= i < shape[0] and 0 <= j < shape[1] and 0 <= k < shape[2]):
                return False
            # Ground plane (k==0) is not a collision hazard for clearance.
            lab = obstacle.labels[i, j, k]
            return lab != int(VoxelLabel.EMPTY) and lab != int(VoxelLabel.GROUND)

        return origin, vs, shape, occ

    # ObstacleMap (schema): sparse occupied voxels or 2.5D height grid.
    origin = np.asarray(obstacle.origin_enu, float)
    vs = obstacle.resolution
    if obstacle.occupied_voxels is not None:
        occ_set = {tuple(v) for v in obstacle.occupied_voxels}
        shape3 = tuple(obstacle.shape) if len(obstacle.shape) == 3 else (
            obstacle.shape[0],
            obstacle.shape[1],
            10_000,
        )

        def occ(i: int, j: int, k: int) -> bool:
            return (i, j, k) in occ_set

        return origin, vs, shape3, occ

    # 2.5D height grid: cell occupied up to its height.
    hg = np.asarray(obstacle.height_grid, float)
    nx, ny = hg.shape
    shape3 = (nx, ny, 10_000)

    def occ(i: int, j: int, k: int) -> bool:
        if not (0 <= i < nx and 0 <= j < ny):
            return False
        return (k * vs) <= hg[i, j]

    return origin, vs, shape3, occ


def _clearance(p: np.ndarray, origin, vs, shape, occ, search_cells: int = 3) -> float:
    """Distance (m) from point ``p`` to the nearest occupied voxel center.

    Scans a small neighborhood of cells around ``p``; returns ``inf`` if none
    occupied within the window (i.e. clearance >= window radius).
    """
    base = np.floor((p - origin) / vs).astype(int)
    best = np.inf
    for di in range(-search_cells, search_cells + 1):
        for dj in range(-search_cells, search_cells + 1):
            for dk in range(-search_cells, search_cells + 1):
                i, j, k = base[0] + di, base[1] + dj, base[2] + dk
                if occ(int(i), int(j), int(k)):
                    center = origin + (np.array([i, j, k]) + 0.5) * vs
                    d = float(np.linalg.norm(p - center))
                    if d < best:
                        best = d
    return best


def simulate_mission(
    mission: Mission,
    obstacle: ObstacleMap | VoxelScene | None = None,
    config: DroneConfig | None = None,
    dt: float = 0.1,
) -> FlightResult:
    """Fly ``mission`` through the kinematic sim and report the outcome.

    Parameters
    ----------
    mission
        The waypoints (+ gimbal keyframes, shot types) to execute.
    obstacle
        An :class:`ObstacleMap` or :class:`VoxelScene` to check clearance
        against. If ``None``, no collision checking is performed.
    config
        Drone kinematic/energy parameters.
    dt
        Integration time step (seconds).
    """
    cfg = config or DroneConfig()
    wps = [np.asarray(w.position, float) for w in mission.waypoints]
    speeds = [w.speed if w.speed is not None else cfg.cruise_speed for w in mission.waypoints]

    lookup = _occupied_lookup(obstacle) if obstacle is not None else None

    positions: list[np.ndarray] = [wps[0]]
    times: list[float] = [0.0]
    path_length = 0.0
    battery_used = 0.0
    min_clearance = np.inf
    collided = False
    collision_point: np.ndarray | None = None
    completed = True
    landed_safely = False
    t = 0.0

    def check(p: np.ndarray) -> bool:
        """Update clearance/collision for point p. Return True if collision."""
        nonlocal min_clearance, collided, collision_point
        if lookup is None:
            return False
        origin, vs, shape, occ = lookup
        c = _clearance(p, origin, vs, shape, occ)
        if c < min_clearance:
            min_clearance = c
        if c < cfg.safety_margin:
            collided = True
            collision_point = p.copy()
            return True
        return False

    if check(wps[0]):
        return FlightResult(
            executed_positions=np.array(positions),
            timestamps=np.array(times),
            path_length=0.0,
            duration_s=0.0,
            battery_used=0.0,
            battery_remaining=1.0,
            collided=True,
            collision_point=collision_point,
            min_clearance=min_clearance,
            completed=False,
            landed_safely=False,
        )

    drain_per_s = 1.0 / cfg.battery_capacity_s

    for seg in range(len(wps) - 1):
        a, b = wps[seg], wps[seg + 1]
        speed = max(0.1, min(speeds[seg + 1], cfg.max_speed))
        seg_vec = b - a
        seg_len = float(np.linalg.norm(seg_vec))
        if seg_len < 1e-9:
            continue
        direction = seg_vec / seg_len
        seg_time = seg_len / speed
        n_steps = max(1, int(np.ceil(seg_time / dt)))
        for s in range(1, n_steps + 1):
            frac = s / n_steps
            p = a + direction * (seg_len * frac)
            step_t = seg_time / n_steps
            t += step_t
            battery_used += step_t * drain_per_s
            path_length += seg_len / n_steps
            positions.append(p)
            times.append(t)
            if check(p):
                return FlightResult(
                    executed_positions=np.array(positions),
                    timestamps=np.array(times),
                    path_length=path_length,
                    duration_s=t,
                    battery_used=min(battery_used, 1.0),
                    battery_remaining=max(0.0, 1.0 - battery_used),
                    collided=True,
                    collision_point=collision_point,
                    min_clearance=min_clearance,
                    completed=False,
                    landed_safely=False,
                )
            # Budget pressure: if we've hit the reserve, stop and "land".
            if (1.0 - battery_used) <= cfg.reserve_fraction:
                completed = False
                landed_safely = True
                return FlightResult(
                    executed_positions=np.array(positions),
                    timestamps=np.array(times),
                    path_length=path_length,
                    duration_s=t,
                    battery_used=min(battery_used, 1.0),
                    battery_remaining=max(0.0, 1.0 - battery_used),
                    collided=False,
                    collision_point=None,
                    min_clearance=min_clearance,
                    completed=False,
                    landed_safely=True,
                )

    return FlightResult(
        executed_positions=np.array(positions),
        timestamps=np.array(times),
        path_length=path_length,
        duration_s=t,
        battery_used=min(battery_used, 1.0),
        battery_remaining=max(0.0, 1.0 - battery_used),
        collided=False,
        collision_point=None,
        min_clearance=min_clearance,
        completed=completed,
        landed_safely=landed_safely,
    )


__all__ = ["FlightResult", "DroneConfig", "simulate_mission"]
