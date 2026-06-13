"""Stage 5 -- Path Optimization & Variety Shots.

Owned tests (per the execution + test-case specs):

* Test 19 (A): every selected viewpoint passes geofence + ObstacleMap clearance.
* Test 20 (A): OR-Tools TSP path length <= 1.2x the brute-force optimum.
* Test 21 (A): the simulated trajectory respects v_max/a_max/jerk and keeps
  clearance >= the safety margin everywhere.
* Test 22 (A): the emitted shot list has >= N distinct grammars and no two
  adjacent subjects share one.
* Test 23 (B): the emitted Mission loads & flies clean in the kinematic sim.

A Tier-C placeholder (real-pilot path preference) collects and skips.
"""

from __future__ import annotations

import numpy as np
import pytest

from pral.core.camera import Camera, Pose, matrix_to_quaternion
from pral.core.schemas import (
    AOI,
    HomeFrame,
    ObstacleMap,
    PoseModel,
    Quaternion,
    ShotType,
    ValueField,
    Viewpoint,
)
from pral.sim.flightsim import DroneConfig, simulate_mission
from pral.sim.scenes import VoxelScene

from pral.stage5_path.geofence import clearance, inside_geofence, is_admissible
from pral.stage5_path.grammar import (
    DEFAULT_PALETTE,
    assign_shot_types,
    check_variety,
)
from pral.stage5_path.mission import build_mission
from pral.stage5_path.routing import brute_force_tour, solve_tsp, tour_length
from pral.stage5_path.trajectory import build_trajectory
from pral.stage5_path.viewpoints import local_maxima, select_viewpoints

RNG = np.random.default_rng(0)


# ---------------------------------------------------------------------------
# Fixtures: synthetic AOI, obstacle map, value field
# ---------------------------------------------------------------------------


def _square_aoi(half: float = 60.0, max_alt: float = 120.0) -> AOI:
    """A square geofence centered on the origin, +/- ``half`` meters."""
    poly = [[-half, -half], [half, -half], [half, half], [-half, half]]
    return AOI(home=HomeFrame(lat=0.0, lon=0.0, alt=0.0), polygon_enu=poly,
               max_altitude=max_alt, name="test_aoi")


def _pose_at(pos, target=(0.0, 0.0, 10.0)) -> Pose:
    return Pose.looking_at(position=np.asarray(pos, float), target=np.asarray(target, float))


def _viewpoint(pos, value, target=(0.0, 0.0, 10.0)) -> Viewpoint:
    pose = _pose_at(pos, target)
    q = matrix_to_quaternion(pose.R_wc)
    return Viewpoint(
        pose=PoseModel(
            position=[float(x) for x in pose.position],
            orientation=Quaternion(w=float(q[0]), x=float(q[1]), y=float(q[2]), z=float(q[3])),
        ),
        value=float(value),
    )


def _ring_value_field(radius: float, alt: float, n: int = 10, jitter: bool = True) -> ValueField:
    """A ring of candidate viewpoints around the origin with varied values."""
    samples = []
    for i in range(n):
        a = 2 * np.pi * i / n
        r = radius + (RNG.uniform(-1.0, 1.0) if jitter else 0.0)
        pos = [r * np.cos(a), r * np.sin(a), alt]
        val = 1.0 + 0.5 * np.sin(3 * a) + (0.1 * RNG.uniform() if jitter else 0.0)
        samples.append(_viewpoint(pos, val))
    return ValueField(samples=samples)


# ===========================================================================
# Test 19 (A) -- selected viewpoints pass geofence + clearance
# ===========================================================================


def test_19_selected_viewpoints_admissible():
    aoi = _square_aoi(half=60.0)
    scene = VoxelScene.make(building="box", height=30.0, width=20.0, depth=20.0,
                            voxel_size=2.0, n_trees=4, n_poles=2)
    field = _ring_value_field(radius=scene.orbit_radius, alt=18.0, n=14)

    selected = select_viewpoints(field, aoi, scene, safety_margin=1.5)
    assert len(selected) > 0, "expected at least one admissible viewpoint"
    for sv in selected:
        assert inside_geofence(sv.position, aoi), f"{sv.position} outside geofence"
        assert clearance(sv.position, scene, search_cells=4) >= 1.5, "too close to obstacle"
        assert is_admissible(sv.position, aoi, scene, 1.5)


def test_19_rejects_outside_and_colliding():
    aoi = _square_aoi(half=30.0)
    scene = VoxelScene.make(building="box", height=30.0, width=20.0, depth=20.0,
                            voxel_size=2.0, n_trees=0, n_poles=0)
    field = ValueField(samples=[
        _viewpoint([200.0, 0.0, 20.0], 5.0),   # outside geofence
        _viewpoint([0.0, 0.0, 15.0], 9.0),     # inside the building -> collides
        _viewpoint([25.0, 0.0, 20.0], 1.0),    # admissible
    ])
    selected = select_viewpoints(field, aoi, scene, neighbor_radius=1.0, safety_margin=1.5)
    kept = {tuple(np.round(s.position, 3)) for s in selected}
    assert (25.0, 0.0, 20.0) in kept
    assert (200.0, 0.0, 20.0) not in kept
    assert (0.0, 0.0, 15.0) not in kept


def test_19_geofence_altitude_ceiling():
    aoi = _square_aoi(half=60.0, max_alt=40.0)
    assert inside_geofence([10.0, 10.0, 30.0], aoi)
    assert not inside_geofence([10.0, 10.0, 50.0], aoi)   # above ceiling
    assert not inside_geofence([100.0, 0.0, 30.0], aoi)   # outside polygon


# ===========================================================================
# Test 20 (A) -- OR-Tools TSP within 1.2x brute-force optimum
# ===========================================================================


def test_20_tsp_within_1p2x_bruteforce():
    for n in (5, 6, 7, 8):
        pts = RNG.uniform(-50.0, 50.0, size=(n, 3))
        order, length = solve_tsp(pts, time_limit_s=3)
        _, opt = brute_force_tour(pts)
        # Valid permutation.
        assert sorted(order) == list(range(n))
        assert length <= 1.2 * opt + 1e-6, f"n={n}: {length} > 1.2*{opt}"


def test_20_tsp_optimal_on_collinear():
    # Points on a line: optimal open path is monotone; length == span.
    pts = np.array([[0, 0, 0], [3, 0, 0], [1, 0, 0], [2, 0, 0]], float)
    order, length = solve_tsp(pts, time_limit_s=3)
    _, opt = brute_force_tour(pts)
    assert abs(length - opt) < 1e-6
    assert abs(opt - 3.0) < 1e-6


def test_20_tour_length_helper():
    pts = np.array([[0, 0, 0], [0, 4, 0], [3, 4, 0]], float)
    assert abs(tour_length(pts, [0, 1, 2]) - 7.0) < 1e-9


# ===========================================================================
# Test 21 (A) -- trajectory within kinodynamic limits + clearance
# ===========================================================================


def test_21_trajectory_within_limits_and_clear():
    scene = VoxelScene.make(building="box", height=30.0, width=20.0, depth=20.0,
                            voxel_size=2.0, n_trees=0, n_poles=0)
    r = scene.orbit_radius
    alt = 18.0
    angs = np.linspace(0, 1.5 * np.pi, 6)
    wps = np.array([[r * np.cos(a), r * np.sin(a), alt] for a in angs])

    v_max, a_max, j_max, margin = 15.0, 5.0, 10.0, 1.5
    traj = build_trajectory(wps, scene, v_max=v_max, a_max=a_max, j_max=j_max,
                            safety_margin=margin, cruise_speed=5.0)

    assert traj.within_limits(v_max, a_max, j_max), (
        f"limits exceeded: v={traj.max_speed} a={traj.max_accel} j={traj.max_jerk}"
    )
    assert traj.max_speed <= v_max + 1e-6
    assert traj.max_accel <= a_max + 1e-6
    assert traj.max_jerk <= j_max + 1e-6
    assert traj.min_clearance >= margin, f"clearance {traj.min_clearance} < {margin}"
    assert traj.duration > 0


def test_21_starts_and_ends_at_rest():
    wps = np.array([[20.0, 0.0, 15.0], [0.0, 20.0, 18.0], [-20.0, 0.0, 15.0]])
    traj = build_trajectory(wps, None, v_max=10.0, a_max=4.0, j_max=8.0)
    assert np.linalg.norm(traj.velocities[0]) < 0.2
    assert np.linalg.norm(traj.velocities[-1]) < 0.2
    # Endpoints honored.
    assert np.linalg.norm(traj.positions[0] - wps[0]) < 0.5
    assert np.linalg.norm(traj.positions[-1] - wps[-1]) < 0.5


def test_21_tighter_limits_yield_longer_duration():
    wps = np.array([[30.0, 0.0, 20.0], [0.0, 30.0, 20.0], [-30.0, 0.0, 20.0]])
    loose = build_trajectory(wps, None, v_max=15.0, a_max=8.0, j_max=20.0)
    tight = build_trajectory(wps, None, v_max=4.0, a_max=2.0, j_max=4.0)
    assert tight.duration > loose.duration
    assert tight.within_limits(4.0, 2.0, 4.0)


# ===========================================================================
# Test 22 (A) -- shot variety: >= N distinct + no two adjacent equal
# ===========================================================================


def test_22_variety_constraint_holds():
    for n in range(1, 12):
        shots = assign_shot_types(n, n_distinct=3)
        assert len(shots) == n
        # No two adjacent equal.
        for a, b in zip(shots[:-1], shots[1:]):
            assert a != b, f"adjacent duplicate at n={n}: {shots}"
        # >= min(3, n, palette) distinct.
        target = min(3, n, len(DEFAULT_PALETTE))
        assert len(set(shots)) >= target, f"n={n}: only {len(set(shots))} distinct"
        assert check_variety(shots, target)


def test_22_all_shot_types_are_valid_enum():
    shots = assign_shot_types(7, n_distinct=5)
    for s in shots:
        assert isinstance(s, ShotType)
    assert len(set(shots)) == 7  # full palette walked


def test_22_check_variety_rejects_adjacent_dup():
    bad = [ShotType.ORBIT, ShotType.ORBIT, ShotType.FLYBY]
    assert not check_variety(bad, 2)


# ===========================================================================
# Test 23 (B) -- emitted Mission flies clean in the sim
# ===========================================================================


def test_23_mission_flies_clean_in_sim():
    aoi = _square_aoi(half=80.0)
    scene = VoxelScene.make(building="box", height=30.0, width=20.0, depth=20.0,
                            voxel_size=2.0, n_trees=3, n_poles=1)
    field = _ring_value_field(radius=scene.orbit_radius, alt=18.0, n=12)

    result = build_mission(field, aoi, scene, coverage=0.92, n_distinct_shots=3,
                           cruise_speed=4.0, safety_margin=1.5)
    mission = result.mission

    # Mission is well-formed.
    assert len(mission.waypoints) >= 2
    assert len(mission.shot_types) == len(mission.waypoints)
    assert check_variety(mission.shot_types, min(3, len(mission.waypoints)))

    res = simulate_mission(mission, obstacle=scene, config=DroneConfig())
    assert not res.collided, f"mission collided at {res.collision_point}"
    assert res.ok
    assert res.completed
    assert res.min_clearance >= DroneConfig().safety_margin


def test_23_curated_footage_set_emitted():
    aoi = _square_aoi(half=80.0)
    scene = VoxelScene.make(building="box", height=30.0, voxel_size=2.0,
                            n_trees=2, n_poles=1)
    field = _ring_value_field(radius=scene.orbit_radius, alt=18.0, n=10)
    result = build_mission(field, aoi, scene, coverage=0.91, n_distinct_shots=3)

    fs = result.footage
    assert len(fs.clips) == len(result.ordered_viewpoints)
    assert fs.coverage == 0.91
    # Each clip carries a pose, a shot type, and interest tags.
    for clip in fs.clips:
        assert len(clip.poses) >= 1
        assert isinstance(clip.shot_type, ShotType)
        assert len(clip.interest_tags) >= 1
    # Distinct shot types across clips.
    assert len({c.shot_type for c in fs.clips}) >= min(3, len(fs.clips))


def test_23_no_admissible_viewpoint_raises():
    aoi = _square_aoi(half=5.0)  # tiny geofence
    field = ValueField(samples=[_viewpoint([100.0, 100.0, 20.0], 1.0)])
    with pytest.raises(ValueError):
        build_mission(field, aoi, None)


# ===========================================================================
# Supporting: local_maxima selects peaks
# ===========================================================================


def test_local_maxima_picks_peaks():
    # Three clear peaks far apart; valley points between them.
    field = ValueField(samples=[
        _viewpoint([0.0, 0.0, 20.0], 5.0),
        _viewpoint([3.0, 0.0, 20.0], 2.0),
        _viewpoint([40.0, 0.0, 20.0], 7.0),
        _viewpoint([43.0, 0.0, 20.0], 1.0),
        _viewpoint([-40.0, 0.0, 20.0], 6.0),
    ])
    peaks = local_maxima(field, neighbor_radius=6.0)
    peak_vals = sorted(p.value for p in peaks)
    assert 5.0 in peak_vals and 7.0 in peak_vals and 6.0 in peak_vals
    assert 2.0 not in peak_vals  # dominated by the 5.0 peak nearby


# ===========================================================================
# Test 23 corollary -- works with a sparse ObstacleMap (schema type), too
# ===========================================================================


def test_mission_with_obstacle_map_schema():
    aoi = _square_aoi(half=60.0)
    # Sparse ObstacleMap: a single occupied column near the origin.
    omap = ObstacleMap(
        resolution=2.0,
        origin_enu=[-60.0, -60.0, 0.0],
        shape=[60, 60, 30],
        occupied_voxels=[[30, 30, k] for k in range(15)],  # pole at origin-ish
    )
    field = _ring_value_field(radius=30.0, alt=18.0, n=10)
    result = build_mission(field, aoi, omap, coverage=0.9)
    res = simulate_mission(result.mission, obstacle=omap, config=DroneConfig())
    assert not res.collided
    assert res.ok


# ===========================================================================
# Tier C placeholder -- real pilot path preference (collects + skips)
# ===========================================================================


@pytest.mark.skip(reason="needs field data")
def test_c_path_matches_expert_pilot_preference():
    """Tier C: the planned trajectory + shot assignment must match a real
    pilot's chosen path/shots on a captured scene above a similarity threshold.
    Requires expert-labeled flight logs (field data)."""
    expert_log = "field/pilot_flightlog_0001.json"  # noqa: F841
    # plan = build_mission(real_value_field, real_aoi, real_obstacle_map)
    # assert frechet_similarity(plan.trajectory, expert_log) >= 0.7
    raise AssertionError("expert-pilot path preference test not run without field data")
