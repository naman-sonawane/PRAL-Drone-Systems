"""Mission assembly -- tie Stage 5 together into a flyable Mission + footage set.

This is the orchestrator: value field + obstacle map + geofence in, a
:class:`~pral.core.schemas.Mission` and a
:class:`~pral.core.schemas.CuratedFootageSet` out.

Pipeline
--------
1. :func:`~pral.stage5_path.viewpoints.select_viewpoints` -- admissible peaks.
2. :func:`~pral.stage5_path.routing.solve_tsp` -- visit order.
3. :func:`~pral.stage5_path.trajectory.build_trajectory` -- smooth, feasible
   curve (used to time-stamp / validate; the emitted Mission carries the routed
   waypoints with a cruise speed the sim re-times itself).
4. :func:`~pral.stage5_path.grammar.assign_shot_types` -- variety per subject.
5. Emit a :class:`Mission` (waypoints + gimbal keyframes + shot types) and a
   :class:`CuratedFootageSet` (one clip per subject, posed + tagged).

The emitted Mission loads and flies clean in :func:`pral.sim.flightsim.
simulate_mission` (Test 23): waypoints are admissible (cleared by Stage-5
selection) and speeds sit at cruise, well inside the sim's limits.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pral.core.camera import Pose, matrix_to_quaternion
from pral.core.schemas import (
    AOI,
    Clip,
    CuratedFootageSet,
    GimbalKeyframe,
    HomeFrame,
    Mission,
    PoseModel,
    Quaternion,
    ShotType,
    ValueField,
    Waypoint,
)
from pral.stage5_path.grammar import assign_shot_types
from pral.stage5_path.geofence import ObstacleSource
from pral.stage5_path.routing import solve_tsp
from pral.stage5_path.trajectory import Trajectory, build_trajectory
from pral.stage5_path.viewpoints import SelectedViewpoint, select_viewpoints


@dataclass
class Stage5Result:
    """Everything Stage 5 produces, for inspection and downstream use."""

    mission: Mission
    footage: CuratedFootageSet
    ordered_viewpoints: list[SelectedViewpoint]
    order: list[int]
    trajectory: Trajectory


def _pose_to_model(pose: Pose) -> PoseModel:
    q = matrix_to_quaternion(pose.R_wc)
    return PoseModel(
        position=[float(x) for x in pose.position],
        orientation=Quaternion(w=float(q[0]), x=float(q[1]), y=float(q[2]), z=float(q[3])),
    )


def _aim_from_pose(pose: Pose) -> np.ndarray:
    """A point 10 m down the camera optical axis -- the gimbal aim target."""
    forward = pose.R_wc @ np.array([0.0, 0.0, 1.0])
    return pose.position + 10.0 * forward


def build_mission(
    value_field: ValueField,
    aoi: AOI,
    obstacle: ObstacleSource | None = None,
    *,
    home: HomeFrame | None = None,
    aoi_name: str | None = None,
    coverage: float = 0.9,
    n_distinct_shots: int = 3,
    cruise_speed: float = 5.0,
    v_max: float = 15.0,
    a_max: float = 5.0,
    j_max: float = 10.0,
    safety_margin: float = 1.5,
    min_altitude: float = 0.0,
    neighbor_radius: float = 6.0,
    max_count: int | None = None,
) -> Stage5Result:
    """Run Stage 5 end-to-end and return the Mission + CuratedFootageSet.

    Raises
    ------
    ValueError
        If no admissible viewpoint survives selection (nothing to fly).
    """
    selected = select_viewpoints(
        value_field,
        aoi,
        obstacle,
        neighbor_radius=neighbor_radius,
        safety_margin=safety_margin,
        min_altitude=min_altitude,
        max_count=max_count,
    )
    if not selected:
        raise ValueError("no admissible viewpoint to build a mission from")

    positions = np.array([s.position for s in selected])
    order, _ = solve_tsp(positions)
    ordered = [selected[i] for i in order]
    ordered_pos = np.array([s.position for s in ordered])

    trajectory = build_trajectory(
        ordered_pos,
        obstacle,
        v_max=v_max,
        a_max=a_max,
        j_max=j_max,
        safety_margin=safety_margin,
        cruise_speed=cruise_speed,
    )

    shot_types = assign_shot_types(len(ordered), n_distinct=n_distinct_shots)

    # Waypoints at the routed viewpoints, cruise speed (sim re-times internally).
    waypoints = [
        Waypoint(position=[float(x) for x in s.position], speed=cruise_speed)
        for s in ordered
    ]
    gimbal_keyframes = [
        GimbalKeyframe(
            waypoint_index=i,
            aim_enu=[float(x) for x in _aim_from_pose(s.pose)],
        )
        for i, s in enumerate(ordered)
    ]
    mission = Mission(
        waypoints=waypoints,
        gimbal_keyframes=gimbal_keyframes,
        shot_types=shot_types,
    )

    home = home or HomeFrame(lat=0.0, lon=0.0, alt=0.0)
    clips = [
        Clip(
            clip_id=f"clip_{i:03d}",
            shot_type=shot_types[i],
            poses=[_pose_to_model(s.pose)],
            interest_tags=[shot_types[i].value, f"value_{s.value:.2f}"],
        )
        for i, s in enumerate(ordered)
    ]
    footage = CuratedFootageSet(
        aoi_name=aoi_name or aoi.name,
        home=home,
        clips=clips,
        coverage=coverage,
    )

    return Stage5Result(
        mission=mission,
        footage=footage,
        ordered_viewpoints=ordered,
        order=order,
        trajectory=trajectory,
    )


__all__ = ["Stage5Result", "build_mission"]
