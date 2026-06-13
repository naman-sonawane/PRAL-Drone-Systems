"""Sanity tests for the sim harness (pral.sim).

These are Tier-B (synthetic scene / fake depth / flight sim) checks that the
procedural worlds behave as the downstream stages assume:

* fake nadir depth of a known box recovers H within 10% (relates to Test 6);
* the visibility set is non-empty and monotone as poses are added (Test 9);
* occupancy built from depth recalls the building (relates to Test 7);
* an occluded face is flagged and a line-of-sight close-up is generated
  (relates to Tests 10/11);
* a simple mission flies clean in the kinematic sim and a path through an
  obstacle collides (relates to Test 23 + E2E collision checks).

A Tier-C placeholder (real-depth fidelity) collects and skips.
"""

import numpy as np
import pytest

from pral.core.camera import Camera, Pose
from pral.core.schemas import Mission, Waypoint
from pral.sim.depth import estimate_height, occupancy_from_depth, fake_depth_map
from pral.sim.flightsim import DroneConfig, simulate_mission
from pral.sim.posed_images import (
    closeup_pose_for_frontier,
    generate_posed_image_set,
)
from pral.sim.scenes import VoxelLabel, VoxelScene


def _cam() -> Camera:
    return Camera(hfov_deg=84.0, vfov_deg=53.0, width=640, height=480)


# ---------------------------------------------------------------------------
# scenes
# ---------------------------------------------------------------------------


def test_scene_builds_box_with_surface_and_obstacles():
    scene = VoxelScene.make(building="box", height=30.0, voxel_size=2.0, n_trees=4, n_poles=2)
    assert scene.orbit_radius > 0
    assert len(scene.surface_indices) > 0
    # Obstacles were placed.
    assert len(scene.occupied_voxels(only_obstacles=True)) > 0
    # Surface voxels are all building-labeled.
    for ijk in scene.surface_indices:
        assert scene.labels[tuple(ijk)] == int(VoxelLabel.BUILDING)


def test_l_shape_has_fewer_voxels_than_box():
    box = VoxelScene.make(building="box", height=20.0, voxel_size=2.0, n_trees=0, n_poles=0)
    ell = VoxelScene.make(building="L", height=20.0, voxel_size=2.0, n_trees=0, n_poles=0)
    assert len(ell.occupied_voxels()) < len(box.occupied_voxels())


# ---------------------------------------------------------------------------
# depth -> height (Test 6)
# ---------------------------------------------------------------------------


def test_fake_depth_recovers_height_within_10pct():
    for H in (20.0, 30.0, 45.0):
        scene = VoxelScene.make(building="box", height=H, width=24.0, depth=24.0,
                                voxel_size=2.0, n_trees=0, n_poles=0)
        est = estimate_height(scene, _cam())
        assert abs(est - H) <= 0.10 * H, f"H={H} est={est}"


# ---------------------------------------------------------------------------
# depth -> occupancy (Test 7)
# ---------------------------------------------------------------------------


def test_occupancy_from_depth_recalls_building():
    scene = VoxelScene.make(building="box", height=24.0, voxel_size=2.0, n_trees=0, n_poles=0)
    cam = _cam()
    set_ = generate_posed_image_set(scene, cam, n_views=12)
    occ = occupancy_from_depth(scene, cam, set_.poses, stride=4)
    # The orbit only sees facades (not the solid interior), so recall is
    # measured against surface voxels the orbit actually observed.
    seen_surface = set_.seen_mask()
    hit = 0
    for s_i, ijk in enumerate(scene.surface_indices):
        if seen_surface[s_i] and occ[tuple(ijk)]:
            hit += 1
    recalled = hit / max(1, int(np.sum(seen_surface)))
    assert recalled > 0.6  # most observed facade voxels get marked occupied


# ---------------------------------------------------------------------------
# visibility + coverage monotonicity (Test 9)
# ---------------------------------------------------------------------------


def test_visibility_nonempty_and_monotone():
    scene = VoxelScene.make(building="box", height=30.0, voxel_size=2.0, n_trees=0, n_poles=0)
    cam = _cam()
    cov_prev = -1.0
    for n in (4, 8, 16, 24):
        set_ = generate_posed_image_set(scene, cam, n_views=n)
        assert set_.visibility.any(), "no surface voxel visible from any pose"
        cov = set_.coverage()
        assert cov >= cov_prev - 1e-9, f"coverage dropped: {cov_prev} -> {cov}"
        cov_prev = cov
    assert cov_prev > 0.4  # an open box should be well covered by a full orbit


# ---------------------------------------------------------------------------
# occlusion + close-up (Tests 10/11)
# ---------------------------------------------------------------------------


def test_blocked_face_is_occluded_and_closeup_resolves_it():
    scene = VoxelScene.make(
        building="box", height=24.0, width=20.0, depth=20.0,
        voxel_size=2.0, n_trees=0, n_poles=0, block_face=True,
    )
    assert scene.occluded_from_orbit.any(), "block_face produced no occluded voxels"
    cam = _cam()
    set_ = generate_posed_image_set(scene, cam, n_views=24)
    frontiers = set_.frontier_indices()
    assert len(frontiers) > 0, "expected unseen frontier voxels behind the tree"
    # At least one frontier gets a line-of-sight close-up pose.
    resolved = 0
    for f in frontiers[:20]:
        pose = closeup_pose_for_frontier(scene, cam, int(f))
        if pose is not None:
            resolved += 1
    assert resolved > 0, "no close-up could resolve any frontier"


# ---------------------------------------------------------------------------
# flightsim (Test 23 + collision)
# ---------------------------------------------------------------------------


def test_clean_mission_flies_without_collision():
    scene = VoxelScene.make(building="box", height=30.0, voxel_size=2.0, n_trees=2, n_poles=1)
    r = scene.orbit_radius
    alt = 20.0
    # A small orbit arc well above obstacles, at the orbit radius.
    angs = np.linspace(0, np.pi / 2, 5)
    wps = [Waypoint(position=[r * np.cos(a), r * np.sin(a), alt]) for a in angs]
    mission = Mission(waypoints=wps)
    res = simulate_mission(mission, obstacle=scene, config=DroneConfig())
    assert not res.collided
    assert res.completed
    assert res.ok
    assert res.path_length > 0
    assert 0.0 <= res.battery_used <= 1.0


def test_mission_into_building_collides():
    scene = VoxelScene.make(building="box", height=30.0, width=20.0, depth=20.0,
                            voxel_size=2.0, n_trees=0, n_poles=0)
    # Fly straight through the building center at mid-height.
    wps = [
        Waypoint(position=[-40.0, 0.0, 15.0]),
        Waypoint(position=[40.0, 0.0, 15.0]),
    ]
    mission = Mission(waypoints=wps)
    res = simulate_mission(mission, obstacle=scene, config=DroneConfig())
    assert res.collided
    assert res.collision_point is not None
    assert not res.ok


def test_budget_pressure_lands_safely():
    scene = VoxelScene.make(building="box", height=30.0, voxel_size=2.0, n_trees=0, n_poles=0)
    r = scene.orbit_radius
    # Long orbit; tiny battery so it must land before finishing.
    angs = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    wps = [Waypoint(position=[r * np.cos(a), r * np.sin(a), 20.0], speed=3.0) for a in angs]
    mission = Mission(waypoints=wps)
    cfg = DroneConfig(battery_capacity_s=30.0, reserve_fraction=0.2)
    res = simulate_mission(mission, obstacle=scene, config=cfg)
    assert not res.collided
    assert res.landed_safely
    assert not res.completed
    assert res.battery_remaining <= 0.2 + 1e-6


# ---------------------------------------------------------------------------
# fake_depth_map basic shape/behavior
# ---------------------------------------------------------------------------


def test_fake_depth_map_sees_building_from_orbit():
    scene = VoxelScene.make(building="box", height=30.0, voxel_size=2.0, n_trees=0, n_poles=0)
    cam = _cam()
    target = scene.centroid_enu + np.array([0.0, 0.0, 15.0])
    pose = Pose.looking_at(position=[scene.orbit_radius, 0.0, 15.0], target=target)
    depth = fake_depth_map(scene, cam, pose, stride=8)
    finite = depth[np.isfinite(depth)]
    assert finite.size > 0
    # Closest hit roughly the standoff minus half the building width.
    assert finite.min() < scene.orbit_radius


# ---------------------------------------------------------------------------
# Tier C placeholder -- real depth fidelity (collects + skips)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="needs field data")
def test_real_depth_fidelity_against_lidar():
    """Tier C: fake depth is exact; real monocular/stereo depth must match a
    LiDAR reference within tolerance on a captured frame. Requires real RGB +
    a registered LiDAR depth map (field data)."""
    real_rgb = "field/frame_0001.png"  # noqa: F841
    lidar_depth = "field/frame_0001_lidar.npy"  # noqa: F841
    # est = monocular_depth(real_rgb); assert median_abs_err(est, lidar_depth) < 0.1*range
    raise AssertionError("real-data depth fidelity test not run without field data")
