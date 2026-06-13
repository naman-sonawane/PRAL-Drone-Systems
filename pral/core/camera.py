"""Pinhole camera model + rigid pose, in the local ENU frame.

Conventions
-----------
* World frame: local **ENU** meters (see :mod:`pral.core.frames`).
* Camera frame: standard computer-vision optical frame -- ``+x`` right,
  ``+y`` down, ``+z`` forward (along the optical axis / viewing direction).
* A :class:`Pose` is the rigid transform *camera-from-world*: it stores the
  camera position in world coordinates and a rotation ``R_wc`` (world-from-
  camera) so that a point in camera coords is ``p_c = R_wc.T @ (p_w - position)``.

Intrinsics come from horizontal/vertical field-of-view + pixel resolution:

    fx = (W / 2) / tan(HFOV / 2)
    fy = (H / 2) / tan(VFOV / 2)

with the principal point at the image center. ``project`` maps a world point
to a pixel; ``backproject`` inverts it against either a known depth or a
ground plane (``z = ground_z``), which is how a detection in the image is
turned back into a 3D / GPS location (Test 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def intrinsics_from_fov(
    hfov_deg: float, vfov_deg: float, width: int, height: int
) -> np.ndarray:
    """Build a 3x3 pinhole intrinsics matrix K from FOV (deg) and resolution."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    fx = (width / 2.0) / np.tan(np.radians(hfov_deg) / 2.0)
    fy = (height / 2.0) / np.tan(np.radians(vfov_deg) / 2.0)
    cx = width / 2.0
    cy = height / 2.0
    return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=float)


@dataclass(frozen=True)
class Camera:
    """Pinhole camera intrinsics derived from field of view + resolution."""

    hfov_deg: float
    vfov_deg: float
    width: int
    height: int
    K: np.ndarray = field(default_factory=lambda: np.eye(3))

    def __post_init__(self) -> None:
        # Allow callers to omit K and have it computed from the FOV.
        if np.allclose(self.K, np.eye(3)):
            object.__setattr__(
                self,
                "K",
                intrinsics_from_fov(
                    self.hfov_deg, self.vfov_deg, self.width, self.height
                ),
            )

    @property
    def fx(self) -> float:
        return float(self.K[0, 0])

    @property
    def fy(self) -> float:
        return float(self.K[1, 1])

    @property
    def cx(self) -> float:
        return float(self.K[0, 2])

    @property
    def cy(self) -> float:
        return float(self.K[1, 2])


def quaternion_to_matrix(q: np.ndarray) -> np.ndarray:
    """Convert a quaternion (w, x, y, z) to a 3x3 rotation matrix."""
    q = np.asarray(q, dtype=float)
    n = np.linalg.norm(q)
    if n < 1e-12:
        raise ValueError("zero-norm quaternion")
    w, x, y, z = q / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


def matrix_to_quaternion(R: np.ndarray) -> np.ndarray:
    """Convert a 3x3 rotation matrix to a quaternion (w, x, y, z)."""
    R = np.asarray(R, dtype=float)
    t = np.trace(R)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2.0
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], dtype=float)
    return q / np.linalg.norm(q)


def look_at(position: np.ndarray, target: np.ndarray, up: np.ndarray | None = None) -> np.ndarray:
    """Rotation matrix R_wc (world-from-camera) for a camera at ``position``
    looking toward ``target`` (optical +z points at the target)."""
    position = np.asarray(position, dtype=float)
    target = np.asarray(target, dtype=float)
    if up is None:
        up = np.array([0.0, 0.0, 1.0])  # ENU up
    up = np.asarray(up, dtype=float)

    forward = target - position
    n = np.linalg.norm(forward)
    if n < 1e-12:
        raise ValueError("camera position coincides with target")
    z_c = forward / n  # optical axis: +z forward
    x_c = np.cross(z_c, up)  # +x right
    if np.linalg.norm(x_c) < 1e-9:  # looking straight up/down: pick a fallback up
        x_c = np.cross(z_c, np.array([0.0, 1.0, 0.0]))
    x_c /= np.linalg.norm(x_c)
    y_c = np.cross(z_c, x_c)  # +y down (completes right-handed frame)
    return np.column_stack([x_c, y_c, z_c])


@dataclass(frozen=True)
class Pose:
    """Rigid camera pose in the world (ENU) frame.

    ``position`` is the camera center in world coords. ``R_wc`` is the rotation
    that maps camera-frame vectors into world-frame vectors (world-from-camera).
    """

    position: np.ndarray
    R_wc: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", np.asarray(self.position, dtype=float).reshape(3))
        object.__setattr__(self, "R_wc", np.asarray(self.R_wc, dtype=float).reshape(3, 3))

    @classmethod
    def from_quaternion(cls, position: np.ndarray, quat_wxyz: np.ndarray) -> "Pose":
        return cls(position=np.asarray(position, dtype=float), R_wc=quaternion_to_matrix(quat_wxyz))

    @classmethod
    def looking_at(
        cls, position: np.ndarray, target: np.ndarray, up: np.ndarray | None = None
    ) -> "Pose":
        return cls(position=np.asarray(position, dtype=float), R_wc=look_at(position, target, up))

    @property
    def quaternion(self) -> np.ndarray:
        """Pose orientation as a quaternion (w, x, y, z)."""
        return matrix_to_quaternion(self.R_wc)

    def world_to_camera(self, point_w: np.ndarray) -> np.ndarray:
        """Transform a world point into the camera frame."""
        point_w = np.asarray(point_w, dtype=float)
        return self.R_wc.T @ (point_w - self.position)

    def camera_to_world(self, point_c: np.ndarray) -> np.ndarray:
        """Transform a camera-frame point into world coordinates."""
        point_c = np.asarray(point_c, dtype=float)
        return self.R_wc @ point_c + self.position


def project(camera: Camera, pose: Pose, point_w: np.ndarray) -> np.ndarray:
    """Project a world point to a pixel ``(u, v)``.

    Raises ``ValueError`` if the point is behind the camera.
    """
    p_c = pose.world_to_camera(point_w)
    if p_c[2] <= 1e-9:
        raise ValueError("point is at or behind the camera plane")
    uvw = camera.K @ p_c
    return np.array([uvw[0] / uvw[2], uvw[1] / uvw[2]], dtype=float)


def backproject(
    camera: Camera,
    pose: Pose,
    pixel: np.ndarray,
    depth: float | None = None,
    ground_z: float | None = None,
) -> np.ndarray:
    """Back-project a pixel ``(u, v)`` to a world point.

    Exactly one of ``depth`` (meters along the optical ray) or ``ground_z``
    (intersect the ray with the world plane ``z = ground_z``) must be given.
    """
    if (depth is None) == (ground_z is None):
        raise ValueError("provide exactly one of `depth` or `ground_z`")

    pixel = np.asarray(pixel, dtype=float)
    # Pixel -> normalized camera ray direction.
    inv_k = np.linalg.inv(camera.K)
    ray_c = inv_k @ np.array([pixel[0], pixel[1], 1.0])
    ray_w = pose.R_wc @ ray_c  # ray direction in world frame
    origin = pose.position

    if depth is not None:
        # `depth` is along the optical axis (camera +z). Scale so the z-component
        # of the camera-frame ray equals `depth`.
        scale = depth / ray_c[2]
        return origin + scale * ray_w

    # Plane intersection: origin + t * ray_w has z == ground_z.
    if abs(ray_w[2]) < 1e-12:
        raise ValueError("ray is parallel to the ground plane")
    t = (ground_z - origin[2]) / ray_w[2]
    if t <= 0:
        raise ValueError("ground plane is behind the camera")
    return origin + t * ray_w
