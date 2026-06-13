"""Test 2 (Tier A) -- camera project/backproject round-trip.

3D point -> pixel -> GPS round-trip within < 3 m given a known pose. The GPS
leg uses :mod:`pral.core.frames`; here we verify the metric (ENU) round-trip,
which dominates the error budget.
"""

import numpy as np

from pral.core.camera import (
    Camera,
    Pose,
    backproject,
    intrinsics_from_fov,
    matrix_to_quaternion,
    project,
    quaternion_to_matrix,
)
from pral.core.frames import enu_to_geodetic, geodetic_to_ecef


def _cam() -> Camera:
    return Camera(hfov_deg=84.0, vfov_deg=53.0, width=1920, height=1080)


def test_intrinsics_principal_point_center():
    K = intrinsics_from_fov(84.0, 53.0, 1920, 1080)
    assert K[0, 2] == 960.0
    assert K[1, 2] == 540.0
    assert K[0, 0] > 0 and K[1, 1] > 0


def test_center_pixel_for_point_on_axis():
    cam = _cam()
    pose = Pose.looking_at(position=[0.0, 0.0, 30.0], target=[0.0, 50.0, 30.0])
    px = project(cam, pose, np.array([0.0, 50.0, 30.0]))
    assert np.allclose(px, [cam.cx, cam.cy], atol=1e-6)


def test_project_backproject_depth_roundtrip():
    cam = _cam()
    pose = Pose.looking_at(position=[5.0, -10.0, 40.0], target=[0.0, 0.0, 10.0])
    pt = np.array([3.0, 8.0, 12.0])
    px = project(cam, pose, pt)
    depth = pose.world_to_camera(pt)[2]
    recovered = backproject(cam, pose, px, depth=depth)
    assert np.linalg.norm(recovered - pt) < 1e-6


def test_groundplane_backproject_then_gps_within_3m():
    cam = _cam()
    # Camera 40 m up, looking down at a ground point.
    pose = Pose.looking_at(position=[0.0, 0.0, 40.0], target=[10.0, 5.0, 0.0])
    ground_pt = np.array([10.0, 5.0, 0.0])
    px = project(cam, pose, ground_pt)
    recovered = backproject(cam, pose, px, ground_z=0.0)
    assert np.linalg.norm(recovered - ground_pt) < 1e-6

    # Lift to GPS and back; compare metric error.
    home = (37.4275, -122.1697, 0.0)
    gps = enu_to_geodetic(recovered[0], recovered[1], recovered[2], *home)
    p_recovered = geodetic_to_ecef(*gps)
    p_truth = geodetic_to_ecef(*enu_to_geodetic(ground_pt[0], ground_pt[1], ground_pt[2], *home))
    assert np.linalg.norm(p_recovered - p_truth) < 3.0


def test_quaternion_matrix_roundtrip():
    rng = np.random.default_rng(0)
    for _ in range(50):
        q = rng.normal(size=4)
        q /= np.linalg.norm(q)
        R = quaternion_to_matrix(q)
        # R must be orthonormal with det +1.
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)
        assert np.isclose(np.linalg.det(R), 1.0, atol=1e-9)
        q2 = matrix_to_quaternion(R)
        # q and -q are the same rotation; compare matrices.
        assert np.allclose(quaternion_to_matrix(q2), R, atol=1e-9)


def test_pose_quaternion_property_roundtrips():
    pose = Pose.looking_at(position=[1.0, 2.0, 30.0], target=[0.0, 0.0, 0.0])
    q = pose.quaternion
    R2 = quaternion_to_matrix(q)
    assert np.allclose(R2, pose.R_wc, atol=1e-9)
