"""
Mock data for Stage 2 — produces a fully-populated Stage2Output without any
real sensor input. Useful for unit tests, pipeline dry-runs, and UI demos.

All randomness is seeded at 42 for reproducibility.
"""
from __future__ import annotations

import math
import os
import struct
from typing import List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# PLY building geometry
# ---------------------------------------------------------------------------

_PLY_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "e7.ply")


def _load_ply_raw() -> Tuple[np.ndarray, List[Tuple]]:
    """Parse e7.ply → (verts (N,3) in metres, faces list of index tuples)."""
    verts: List[Tuple] = []
    faces: List[Tuple] = []
    with open(os.path.abspath(_PLY_PATH), "rb") as f:
        n_verts = n_faces = 0
        while True:
            line = f.readline().decode("ascii").strip()
            if line.startswith("element vertex"):
                n_verts = int(line.split()[-1])
            elif line.startswith("element face"):
                n_faces = int(line.split()[-1])
            elif line == "end_header":
                break
        for _ in range(n_verts):
            verts.append(struct.unpack("<fff", f.read(12)))
        for _ in range(n_faces):
            f.read(4)  # skip RGBA
            count = struct.unpack("<B", f.read(1))[0]
            faces.append(struct.unpack(f"<{count}i", f.read(count * 4)))
    return np.array(verts, dtype=np.float64) / 1000.0, faces  # mm → m


def _scale_ply_to_scene(
    verts_m: np.ndarray, cx: float, cy: float, H: float, r: float
) -> np.ndarray:
    """Centre and uniformly scale PLY vertices to fit within the orbit ring."""
    v = verts_m.copy()
    v[:, 0] -= (v[:, 0].min() + v[:, 0].max()) / 2.0
    v[:, 1] -= (v[:, 1].min() + v[:, 1].max()) / 2.0
    v[:, 2] -= v[:, 2].min()

    x_half = (v[:, 0].max() - v[:, 0].min()) / 2.0
    y_half = (v[:, 1].max() - v[:, 1].min()) / 2.0
    z_span = v[:, 2].max() - v[:, 2].min()

    # Scale so the building fits within r*0.65 (inside the inner annulus boundary)
    scale_xy = (r * 0.65) / max(x_half, y_half)
    scale_z = H / z_span if z_span > 0 else 1.0

    v[:, 0] = v[:, 0] * scale_xy + cx
    v[:, 1] = v[:, 1] * scale_xy + cy
    v[:, 2] = v[:, 2] * scale_z
    return v


def _sample_ply_surface(
    verts: np.ndarray,
    faces: List[Tuple],
    rng: np.random.Generator,
    n_per_m2: float = 64.0,
) -> np.ndarray:
    """Uniformly sample points on triangle surfaces. Returns (N,3)."""
    all_pts: List[np.ndarray] = []
    for idx in faces:
        v0, v1, v2 = verts[idx[0]], verts[idx[1]], verts[idx[2]]
        e1, e2 = v1 - v0, v2 - v0
        area = 0.5 * float(np.linalg.norm(np.cross(e1, e2)))
        n = max(4, int(area * n_per_m2))
        r1 = rng.random(n)
        r2 = rng.random(n)
        fold = r1 + r2 > 1
        r1[fold] = 1.0 - r1[fold]
        r2[fold] = 1.0 - r2[fold]
        all_pts.append(v0 + r1[:, None] * e1 + r2[:, None] * e2)
    return np.vstack(all_pts) if all_pts else np.zeros((0, 3), dtype=np.float64)


def _add_ply_building(
    tree,
    centers: list,
    cx: float,
    cy: float,
    H: float,
    r: float,
    rng: np.random.Generator,
) -> None:
    """Voxelise the e7.ply mesh into the OctoMap as TRAVERSABLE building geometry."""
    try:
        verts_m, faces = _load_ply_raw()
    except Exception:
        # Graceful fallback to the original cylindrical-wall mock
        _add_building_walls(tree, centers, cx, cy, r, H, rng)
        return

    verts = _scale_ply_to_scene(verts_m, cx, cy, H, r)
    pts = _sample_ply_surface(verts, faces, rng, n_per_m2=64.0)

    # Build a per-column height map from the surface samples
    vs = VOXEL_SIZE
    height_map: dict = {}
    for pt in pts:
        ix = int(math.floor(pt[0] / vs))
        iy = int(math.floor(pt[1] / vs))
        z = float(pt[2])
        key = (ix, iy)
        if key not in height_map or height_map[key] < z:
            height_map[key] = z

    # Fill solid voxel columns from ground to the surface height
    for (ix, iy), max_z in height_map.items():
        z = vs / 2.0
        while z <= max_z:
            pt_arr = np.array(
                [ix * vs + vs / 2.0, iy * vs + vs / 2.0, z], dtype=np.float32
            )
            tree.update_node(pt_arr, True)
            tree.set_label(pt_arr, LABEL_TRAVERSABLE)
            centers.append(pt_arr.copy())
            z += vs


def get_ply_footprint_polygon(
    H: float, r: float, cx: float = 0.0, cy: float = 0.0
) -> Optional[List[Tuple[float, float]]]:
    """
    Return the XY convex hull of the scaled PLY vertices as an ordered polygon.
    Used by the visualiser to replace the default rectangular AOI with the
    actual building footprint in mock mode.
    Returns None if the PLY file is unavailable.
    """
    try:
        verts_m, _ = _load_ply_raw()
    except Exception:
        return None

    verts = _scale_ply_to_scene(verts_m, cx, cy, H, r)
    xy = verts[:, :2]

    try:
        from scipy.spatial import ConvexHull
        hull = ConvexHull(xy)
        pts = xy[hull.vertices]
        return [(float(p[0]), float(p[1])) for p in pts]
    except Exception:
        # Fallback: axis-aligned bounding box
        return [
            (float(xy[:, 0].min()), float(xy[:, 1].min())),
            (float(xy[:, 0].max()), float(xy[:, 1].min())),
            (float(xy[:, 0].max()), float(xy[:, 1].max())),
            (float(xy[:, 0].min()), float(xy[:, 1].max())),
        ]


def get_ply_height_map(
    aoi,
    H: float,
    r: float,
    grid_res: float = 0.5,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Public helper for visualize_stage2.py.

    Returns (e_centers, n_centers, z_grid) where z_grid is shape
    (len(n_centers), len(e_centers)) with NaN where no geometry exists,
    or (None, None, None) if the PLY file is unavailable.
    """
    cx, cy = aoi.centroid_enu
    try:
        verts_m, faces = _load_ply_raw()
    except Exception:
        return None, None, None

    verts = _scale_ply_to_scene(verts_m, cx, cy, H, r)
    rng = np.random.default_rng(42)
    pts = _sample_ply_surface(verts, faces, rng, n_per_m2=16.0)

    if pts.shape[0] == 0:
        return None, None, None

    e_min = pts[:, 0].min() - grid_res
    e_max = pts[:, 0].max() + grid_res
    n_min = pts[:, 1].min() - grid_res
    n_max = pts[:, 1].max() + grid_res

    e_edges = np.arange(e_min, e_max + grid_res, grid_res)
    n_edges = np.arange(n_min, n_max + grid_res, grid_res)
    ne = len(e_edges) - 1
    nn = len(n_edges) - 1

    z_grid = np.full((nn, ne), np.nan)
    for pt in pts:
        ie = int((pt[0] - e_min) / grid_res)
        jn = int((pt[1] - n_min) / grid_res)
        if 0 <= ie < ne and 0 <= jn < nn:
            if np.isnan(z_grid[jn, ie]) or z_grid[jn, ie] < pt[2]:
                z_grid[jn, ie] = pt[2]

    e_centers = (e_edges[:-1] + e_edges[1:]) / 2.0
    n_centers = (n_edges[:-1] + n_edges[1:]) / 2.0
    return e_centers, n_centers, z_grid

from .obstacle import (
    LABEL_NO_GO,
    LABEL_TRAVERSABLE,
    MockOctoMap,
    VOXEL_SIZE,
    extract_no_fly_volumes,
)
from .types import AOI, RangefinderReading, Stage2Output


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _snap(coord: float) -> float:
    return math.floor(coord / VOXEL_SIZE) * VOXEL_SIZE


def _voxel_center(ix: int, iy: int, iz: int) -> np.ndarray:
    return np.array([
        ix * VOXEL_SIZE + VOXEL_SIZE / 2,
        iy * VOXEL_SIZE + VOXEL_SIZE / 2,
        iz * VOXEL_SIZE + VOXEL_SIZE / 2,
    ], dtype=np.float32)


def _insert_column(
    tree: MockOctoMap,
    centers: list,
    e: float,
    n: float,
    z_min: float,
    z_max: float,
    label: int,
) -> None:
    z = z_min
    while z < z_max:
        pt = np.array([e, n, z + VOXEL_SIZE / 2], dtype=np.float32)
        tree.update_node(pt, True)
        tree.set_label(pt, label)
        centers.append(pt.copy())
        z += VOXEL_SIZE


def _insert_block(
    tree: MockOctoMap,
    centers: list,
    e_min: float,
    n_min: float,
    z_min: float,
    e_max: float,
    n_max: float,
    z_max: float,
    label: int,
) -> None:
    e = e_min
    while e < e_max:
        n = n_min
        while n < n_max:
            _insert_column(tree, centers, e, n, z_min, z_max, label)
            n += VOXEL_SIZE
        e += VOXEL_SIZE


# ---------------------------------------------------------------------------
# Feature builders
# ---------------------------------------------------------------------------

def _add_building_walls(
    tree: MockOctoMap,
    centers: list,
    cx: float,
    cy: float,
    r: float,
    H: float,
    rng: np.random.Generator,
) -> None:
    n_angles = max(32, int(2 * math.pi * r / VOXEL_SIZE))
    wall_height = rng.uniform(8.0, min(12.0, H))
    for i in range(n_angles):
        angle = 2 * math.pi * i / n_angles
        e = cx + r * math.cos(angle)
        n = cy + r * math.sin(angle)
        e_snapped = _snap(e)
        n_snapped = _snap(n)
        _insert_column(tree, centers, e_snapped, n_snapped, 0.0, wall_height, LABEL_TRAVERSABLE)


def _add_trees(
    tree: MockOctoMap,
    centers: list,
    cx: float,
    cy: float,
    r: float,
    rng: np.random.Generator,
) -> None:
    n_clusters = int(rng.integers(3, 6))
    for _ in range(n_clusters):
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(r * 0.7, r * 1.5)
        e_center = cx + dist * math.cos(angle)
        n_center = cy + dist * math.sin(angle)
        cluster_r = rng.uniform(0.5, 1.5)
        height = rng.uniform(3.0, 8.0)
        e_min = _snap(e_center - cluster_r)
        n_min = _snap(n_center - cluster_r)
        e_max = _snap(e_center + cluster_r) + VOXEL_SIZE
        n_max = _snap(n_center + cluster_r) + VOXEL_SIZE
        _insert_block(tree, centers, e_min, n_min, 0.0, e_max, n_max, height, LABEL_NO_GO)


def _add_utility_poles(
    tree: MockOctoMap,
    centers: list,
    cx: float,
    cy: float,
    r: float,
    rng: np.random.Generator,
) -> None:
    n_poles = int(rng.integers(2, 4))
    for _ in range(n_poles):
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(r * 0.8, r * 1.4)
        e = _snap(cx + dist * math.cos(angle))
        n = _snap(cy + dist * math.sin(angle))
        height = rng.uniform(4.0, 10.0)
        _insert_column(tree, centers, e, n, 0.0, height, LABEL_NO_GO)


def _add_ground_plane(
    tree: MockOctoMap,
    centers: list,
    cx: float,
    cy: float,
    r: float,
) -> None:
    r_inner = r * 0.7
    r_outer = r * 1.5
    e_min = _snap(cx - r_outer)
    n_min = _snap(cy - r_outer)
    e_max = _snap(cx + r_outer) + VOXEL_SIZE
    n_max = _snap(cy + r_outer) + VOXEL_SIZE

    e = e_min
    while e < e_max:
        n = n_min
        while n < n_max:
            dist = math.hypot(e - cx, n - cy)
            if r_inner <= dist <= r_outer:
                pt = np.array([e, n, VOXEL_SIZE / 2], dtype=np.float32)
                tree.update_node(pt, True)
                tree.set_label(pt, LABEL_NO_GO)
                centers.append(pt.copy())
            n += VOXEL_SIZE
        e += VOXEL_SIZE


# ---------------------------------------------------------------------------
# Rangefinder readings
# ---------------------------------------------------------------------------

def _point_in_polygon(px: float, py: float, polygon: List[Tuple[float, float]]) -> bool:
    n = len(polygon)
    inside = False
    x, y = px, py
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _build_rangefinder_readings(
    aoi: AOI,
    r: float,
    H: float,
    vfov_rad: float,
    rng: np.random.Generator,
    n_readings: int = 60,
) -> List[RangefinderReading]:
    cx, cy = aoi.centroid_enu
    readings: List[RangefinderReading] = []
    orbit_alts = [H * 1.1, H * 1.2, H * 1.3]

    for i in range(n_readings):
        t = float(i) * 0.5
        angle = 2 * math.pi * i / n_readings
        drone_e = cx + r * math.cos(angle)
        drone_n = cy + r * math.sin(angle)
        alt_idx = i % len(orbit_alts)
        drone_u = orbit_alts[alt_idx]

        if _point_in_polygon(drone_e, drone_n, aoi.polygon_enu):
            range_m = drone_u * rng.uniform(0.85, 1.05)
        else:
            ground_clearance = drone_u
            wall_dist = abs(math.hypot(drone_e - cx, drone_n - cy) - r)
            range_m = min(ground_clearance, wall_dist + rng.uniform(-0.5, 0.5))
            range_m = max(1.0, range_m)

        readings.append(RangefinderReading(
            timestamp=t,
            range_m=float(range_m),
            drone_pos_enu=(float(drone_e), float(drone_n), float(drone_u)),
        ))

    return readings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_mock_stage2_output(
    aoi: AOI,
    r: float = 20.0,
    H: float = 15.0,
    vfov_rad: float = 0.93,
) -> Stage2Output:
    rng = np.random.default_rng(42)
    cx, cy = aoi.centroid_enu

    tree = MockOctoMap(VOXEL_SIZE)
    voxel_centers: list = []

    _add_ply_building(tree, voxel_centers, cx, cy, H, r, rng)
    _add_trees(tree, voxel_centers, cx, cy, r, rng)
    _add_utility_poles(tree, voxel_centers, cx, cy, r, rng)

    cloud_enu = np.array(voxel_centers, dtype=np.float32) if voxel_centers else np.zeros((0, 3), dtype=np.float32)

    voxel_labels = {k: v for k, v in tree.items()}

    rangefinder_readings = _build_rangefinder_readings(aoi, r, H, vfov_rad, rng)

    no_fly_volumes = extract_no_fly_volumes(tree)

    z_orbit = H / 2.0

    return Stage2Output(
        H=H,
        r=r,
        z_orbit=z_orbit,
        obstacle_map=tree,
        no_fly_volumes=no_fly_volumes,
        H_rangefinder=H,
        H_dsm=H * rng.uniform(0.95, 1.05),
        r_raw=r,
        vfov_rad=vfov_rad,
        fill_ratio=float(np.clip(len(voxel_centers) / max(1, int((2 * math.pi * r / VOXEL_SIZE) * (H / VOXEL_SIZE))), 0.0, 1.0)),
        height_disagreed=False,
        height_warning="",
        r_clamped=False,
        rangefinder_readings=rangefinder_readings,
        cloud_enu=cloud_enu,
        voxel_labels=voxel_labels,
    )
