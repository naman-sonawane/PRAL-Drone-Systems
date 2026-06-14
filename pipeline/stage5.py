"""
Stage 5 -- Path Optimization & Variety Shots.

Orchestrates 5a -> 5b -> 5c -> 5d and returns the Stage 5 output contract dict.

Sub-steps:
  5a. Candidate viewpoint sampling    interest field -> N candidate viewpoints
  5b. Shot-type assignment            deterministic label from geometry
  5c. Greedy value-variety selection  10 waypoints: maximize value + variety
  5d. Trajectory smoothing            CubicSpline over 10 waypoints + collision check

Writes to {workspace_dir}/stage5/:
  waypoints.json          -- list of 10 waypoint dicts
  trajectory.npy          -- float32 (500, 5): [x_enu, y_enu, z_enu, yaw_deg, pitch_deg]
  curated_footage_set.json -- full hand-off dict

Gate checks (assert statements) are enforced before returning.
"""
from __future__ import annotations

import itertools
import json
import logging
import math
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from scipy.interpolate import CubicSpline
from shapely.geometry import Point

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHOT_TYPE_SLOTS: Dict[str, int] = {
    "orbit":    4,   # backbone -- widest coverage
    "reveal":   2,
    "push_in":  2,
    "top_down": 2,
}

_AZIMUTHS   = np.linspace(0, 360, 36, endpoint=False)   # every 10 deg, 36 steps
_ELEVATIONS = [-15, 0, 15, 30, 45]                       # degrees above horizontal
_RADIUS_FACTORS = [0.7, 1.0, 1.5]                        # multiples of orbit_radius

_N_TRAJECTORY_SAMPLES = 500
_TRAJECTORY_CHECK_STEP = 10   # check every 10th sample = 50 checks total


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TrajectoryCollisionError(RuntimeError):
    """Raised when the smoothed trajectory intersects an occupied voxel or exits geofence."""


# ---------------------------------------------------------------------------
# Waypoint dataclass
# ---------------------------------------------------------------------------

@dataclass
class Waypoint:
    lat:       float   # WGS-84 latitude
    lon:       float   # WGS-84 longitude
    alt:       float   # metres AGL
    yaw:       float   # degrees, 0 = North, clockwise
    pitch:     float   # degrees, 0 = horizontal, -90 = nadir
    shot_type: str     # "orbit" | "reveal" | "push_in" | "top_down"
    value:     float   # mean interest score of visible surface (0-1)
    idx:       int     # position in ordered sequence (0-9)


# ---------------------------------------------------------------------------
# Sub-step helpers
# ---------------------------------------------------------------------------

def candidate_value(
    pos_enu: np.ndarray,
    hot_verts: np.ndarray,
    hot_scores: np.ndarray,
    octomap: Any,
) -> float:
    """
    Score a viewpoint by summing interest of hot vertices with unobstructed LOS.

    Parameters
    ----------
    pos_enu    : (3,) camera position in ENU metres
    hot_verts  : (M, 3) high-interest surface vertices
    hot_scores : (M,) per-vertex interest scores
    octomap    : OctoMap (real or MockOctoMap) for ray casting

    Returns
    -------
    Mean visible interest score in [0, 1].
    """
    total = 0.0
    for v, s in zip(hot_verts, hot_scores):
        direction = v - pos_enu
        dist = float(np.linalg.norm(direction))
        if dist < 1e-6:
            continue
        hit, _ = octomap.castRay(
            pos_enu.tolist(),
            (direction / dist).tolist(),
            maxRange=dist * 1.05,
        )
        if not hit:   # ray reaches target unobstructed
            total += s
    return total / max(len(hot_verts), 1)


def assign_shot_type(el_deg: float, radius: float, orbit_radius: float) -> str:
    """
    Deterministically label a candidate by its geometry.

    Rules (checked in priority order):
      top_down : pitch < -60 deg  (el_deg > 60)
      push_in  : radius < orbit_radius * 0.8
      reveal   : el_deg > 20
      orbit    : everything else
    """
    pitch = -el_deg   # approximate; exact pitch computed in 5a
    if pitch < -60:
        return "top_down"
    elif radius < orbit_radius * 0.8:
        return "push_in"
    elif el_deg > 20:
        return "reveal"
    else:
        return "orbit"


def select_waypoints(
    candidates: List[Dict[str, Any]],
    slots: Dict[str, int] = SHOT_TYPE_SLOTS,
) -> List[Dict[str, Any]]:
    """
    Greedy slot-based selection: pick the top-value candidates for each shot type.

    Parameters
    ----------
    candidates : list of candidate dicts, each with keys including
                 "shot_type" and "value"
    slots      : mapping of shot_type -> number of waypoints required

    Returns
    -------
    Flat list of selected candidate dicts (len == sum(slots.values()) == 10).

    Raises
    ------
    ValueError if any shot type has fewer candidates than its slot count.
    """
    by_type = {
        t: sorted(
            [c for c in candidates if c["shot_type"] == t],
            key=lambda x: -x["value"],
        )
        for t in slots
    }
    selected: List[Dict[str, Any]] = []
    for shot_type, count in slots.items():
        pool = by_type.get(shot_type, [])
        if len(pool) < count:
            raise ValueError(
                f"Not enough {shot_type!r} candidates ({len(pool)} < {count})"
            )
        selected.extend(pool[:count])
    return selected


def order_nn(waypoints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Nearest-neighbor TSP ordering of waypoints (O(n^2)).

    Starts from index 0 and greedily visits the closest unvisited waypoint
    by ENU distance at each step.

    Returns
    -------
    Re-ordered list of the same waypoint dicts.
    """
    unvisited = list(range(len(waypoints)))
    ordered = [unvisited.pop(0)]
    while unvisited:
        last_pos = waypoints[ordered[-1]]["pos_enu"]
        nearest = min(
            unvisited,
            key=lambda i: np.linalg.norm(waypoints[i]["pos_enu"] - last_pos),
        )
        ordered.append(nearest)
        unvisited.remove(nearest)
    return [waypoints[i] for i in ordered]


def smooth_trajectory(waypoints: List[Dict[str, Any]]) -> np.ndarray:
    """
    Fit a CubicSpline through the 10 ENU waypoint positions and sample 500 points.
    Yaw and pitch are interpolated linearly.

    Returns
    -------
    trajectory : np.ndarray, shape (500, 5), dtype float32
                 Columns: [x_enu, y_enu, z_enu, yaw_deg, pitch_deg]
    """
    pts = np.array([w["pos_enu"] for w in waypoints])   # (10, 3)
    t   = np.linspace(0, 1, len(waypoints))

    cs       = CubicSpline(t, pts, bc_type="not-a-knot")
    t_dense  = np.linspace(0, 1, _N_TRAJECTORY_SAMPLES)
    traj_enu = cs(t_dense)                               # (500, 3)

    yaws    = np.array([w["yaw"]   for w in waypoints])
    pitches = np.array([w["pitch"] for w in waypoints])
    yaw_i   = np.interp(t_dense, t, yaws)
    pitch_i = np.interp(t_dense, t, pitches)

    trajectory = np.column_stack([traj_enu, yaw_i, pitch_i]).astype(np.float32)
    return trajectory


def check_collisions(
    trajectory: np.ndarray,
    octomap: Any,
    geofence_polygon: Any,
) -> None:
    """
    Check every _TRAJECTORY_CHECK_STEP-th trajectory sample against the OctoMap
    and geofence polygon.

    Parameters
    ----------
    trajectory       : (500, 5) float32 array [x, y, z, yaw, pitch]
    octomap          : OctoMap (real or MockOctoMap)
    geofence_polygon : shapely.geometry.Polygon in ENU (x, y) coords

    Raises
    ------
    TrajectoryCollisionError if any sample is occupied or outside the geofence.
    """
    collisions: List[int] = []

    # Resolve the OCCUPIED sentinel: real octomap has .OCCUPIED; mock uses int key 0
    try:
        occupied_sentinel = octomap.OCCUPIED
        use_search = True
    except AttributeError:
        use_search = False

    for i in range(0, _N_TRAJECTORY_SAMPLES, _TRAJECTORY_CHECK_STEP):
        pt = trajectory[i, :3]

        # OctoMap occupancy check
        if use_search:
            if octomap.search(pt.tolist()) == occupied_sentinel:
                collisions.append(i)
                continue
        else:
            # MockOctoMap: check via _key lookup
            key = (
                int(math.floor(pt[0] / octomap.resolution)),
                int(math.floor(pt[1] / octomap.resolution)),
                int(math.floor(pt[2] / octomap.resolution)),
            )
            if key in octomap._nodes:
                collisions.append(i)
                continue

        # Geofence check (XY plane only)
        if not geofence_polygon.contains(Point(float(pt[0]), float(pt[1]))):
            collisions.append(i)

    if collisions:
        raise TrajectoryCollisionError(
            f"Trajectory collides at sample indices {collisions}. "
            "Adjust the offending waypoints in the Stage 5 visualizer."
        )


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------

def run_stage5(
    interest_scores: np.ndarray,
    building_mesh: Any,
    octomap: Any,
    geofence_polygon: Any,
    orbit_radius: float,
    workspace_dir: str,
) -> Dict[str, Any]:
    """
    Run Stage 5: Path Optimization & Variety Shots.

    Parameters
    ----------
    interest_scores  : (N_vertices,) float32 per-vertex scores from Stage 4
    building_mesh    : open3d.geometry.TriangleMesh from Stage 4
    octomap          : OctoMap / MockOctoMap from Stage 2
    geofence_polygon : shapely.geometry.Polygon (ENU coords) from Stage 1
    orbit_radius     : float, nominal standoff distance in metres from Stage 2
    workspace_dir    : root directory; outputs are written to {workspace_dir}/stage5/

    Returns
    -------
    dict with keys:
      waypoints          : List[Waypoint], 10 items ordered for flight
      trajectory         : np.ndarray (500, 5) float32
      shot_type_counts   : Dict[str, int]
      total_distance_m   : float
      mean_value         : float
      collision_free     : bool
    """
    log.info("Stage 5 started")

    out_dir = os.path.join(workspace_dir, "stage5")
    os.makedirs(out_dir, exist_ok=True)

    # ---- 5a: Candidate viewpoint sampling ----
    log.info("  5a: Candidate viewpoint sampling")

    vertices   = np.asarray(building_mesh.vertices)   # (V, 3) ENU
    hot_mask   = interest_scores >= 0.5
    hot_verts  = vertices[hot_mask]
    hot_scores = interest_scores[hot_mask]
    centroid   = vertices.mean(axis=0)

    log.info(
        f"  5a: {hot_mask.sum()} hot vertices of {len(vertices)}, "
        f"centroid={centroid}"
    )

    radii = [orbit_radius * f for f in _RADIUS_FACTORS]

    raw_candidates: List[Dict[str, Any]] = []
    for az, el, r in itertools.product(_AZIMUTHS, _ELEVATIONS, radii):
        az_r = math.radians(az)
        el_r = math.radians(el)
        dx = r * math.cos(el_r) * math.sin(az_r)
        dy = r * math.cos(el_r) * math.cos(az_r)
        dz = r * math.sin(el_r)
        pos_enu = centroid + np.array([dx, dy, dz])
        yaw     = (math.degrees(math.atan2(dx, dy)) + 180) % 360
        pitch   = -math.degrees(math.atan2(dz, math.hypot(dx, dy)))
        raw_candidates.append({
            "pos_enu": pos_enu,
            "yaw":     yaw,
            "pitch":   pitch,
            "el_deg":  el,
            "radius":  r,
        })

    log.info(f"  5a: {len(raw_candidates)} raw candidates on sphere shell")

    # Filter: must be inside geofence and not occupied
    filtered: List[Dict[str, Any]] = []
    for c in raw_candidates:
        pt = c["pos_enu"]
        if not geofence_polygon.contains(Point(float(pt[0]), float(pt[1]))):
            continue
        # Occupancy check (real OctoMap has .search; MockOctoMap uses _nodes)
        try:
            if octomap.search(pt.tolist()) == octomap.OCCUPIED:
                continue
        except AttributeError:
            key = (
                int(math.floor(pt[0] / octomap.resolution)),
                int(math.floor(pt[1] / octomap.resolution)),
                int(math.floor(pt[2] / octomap.resolution)),
            )
            if key in octomap._nodes:
                continue
        filtered.append(c)

    log.info(f"  5a: {len(filtered)} candidates after geofence + occupancy filter")

    # Score each candidate by summing visible interest
    for c in filtered:
        c["value"] = candidate_value(c["pos_enu"], hot_verts, hot_scores, octomap)

    log.info("  5a: candidate scoring complete")

    # ---- 5b: Shot-type assignment ----
    log.info("  5b: Shot-type assignment")
    for c in filtered:
        c["shot_type"] = assign_shot_type(c["el_deg"], c["radius"], orbit_radius)

    shot_type_dist = {
        t: sum(1 for c in filtered if c["shot_type"] == t)
        for t in SHOT_TYPE_SLOTS
    }
    log.info(f"  5b: shot type distribution: {shot_type_dist}")

    # ---- 5c: Greedy value-variety selection + NN ordering ----
    log.info("  5c: Greedy slot-based selection")
    selected = select_waypoints(filtered, SHOT_TYPE_SLOTS)

    log.info("  5c: Nearest-neighbor TSP ordering")
    ordered = order_nn(selected)

    # Assign idx and build Waypoint objects
    # ENU pos_enu is in local coords; lat/lon/alt require a geodetic origin.
    # We store x_enu, y_enu as (lat, lon) placeholders when no geodetic
    # reference is provided (the visualizer and downstream consumers use
    # pos_enu directly). Callers with a geodetic origin should convert after.
    waypoints: List[Waypoint] = []
    for i, w in enumerate(ordered):
        pos = w["pos_enu"]
        wp = Waypoint(
            lat=float(pos[0]),       # placeholder: x_enu
            lon=float(pos[1]),       # placeholder: y_enu
            alt=float(pos[2]),       # z_enu (metres AGL relative to centroid)
            yaw=float(w["yaw"]),
            pitch=float(w["pitch"]),
            shot_type=w["shot_type"],
            value=float(w["value"]),
            idx=i,
        )
        waypoints.append(wp)

    log.info(f"  5c: {len(waypoints)} waypoints selected and ordered")

    # Compute total flight distance (inter-waypoint)
    total_distance_m = 0.0
    for i in range(1, len(ordered)):
        total_distance_m += float(
            np.linalg.norm(ordered[i]["pos_enu"] - ordered[i - 1]["pos_enu"])
        )

    mean_value = float(np.mean([wp.value for wp in waypoints]))

    # ---- 5d: Trajectory smoothing ----
    log.info("  5d: CubicSpline trajectory smoothing")
    trajectory = smooth_trajectory(ordered)    # (500, 5) float32

    log.info("  5d: Collision check")
    collision_free = True
    try:
        check_collisions(trajectory, octomap, geofence_polygon)
        log.info("  5d: trajectory is collision-free")
    except TrajectoryCollisionError as exc:
        collision_free = False
        log.warning(f"  5d: {exc}")

    # ---- Write artifacts ----
    waypoints_path   = os.path.join(out_dir, "waypoints.json")
    trajectory_path  = os.path.join(out_dir, "trajectory.npy")
    curated_path     = os.path.join(out_dir, "curated_footage_set.json")

    # waypoints.json -- list of plain dicts (no dataclass types)
    waypoints_dicts = [asdict(wp) for wp in waypoints]
    with open(waypoints_path, "w") as fh:
        json.dump(waypoints_dicts, fh, indent=2)
    log.info(f"  wrote {waypoints_path}")

    # trajectory.npy -- float32 (500, 5)
    np.save(trajectory_path, trajectory)
    log.info(f"  wrote {trajectory_path}")

    # shot_type_counts
    shot_type_counts: Dict[str, int] = {}
    for t in SHOT_TYPE_SLOTS:
        shot_type_counts[t] = sum(1 for wp in waypoints if wp.shot_type == t)

    # curated_footage_set.json
    curated_footage_set: Dict[str, Any] = {
        "waypoints":         waypoints_dicts,
        "trajectory_path":   trajectory_path,
        "shot_type_counts":  shot_type_counts,
        "total_distance_m":  total_distance_m,
        "mean_value":        mean_value,
        "collision_free":    collision_free,
    }
    with open(curated_path, "w") as fh:
        json.dump(curated_footage_set, fh, indent=2)
    log.info(f"  wrote {curated_path}")

    # ---- Gate checks ----
    assert len(waypoints) == 10, (
        f"Expected 10 waypoints, got {len(waypoints)}"
    )
    assert collision_free, (
        "Unresolved trajectory collisions -- adjust in Stage 5 visualizer"
    )
    assert set(shot_type_counts.keys()) == set(SHOT_TYPE_SLOTS.keys()), (
        f"shot_type_counts keys {set(shot_type_counts.keys())} "
        f"!= expected {set(SHOT_TYPE_SLOTS.keys())}"
    )
    log.info("Stage 5 gate check: PASSED")

    return {
        "waypoints":        waypoints,
        "trajectory":       trajectory,
        "shot_type_counts": shot_type_counts,
        "total_distance_m": total_distance_m,
        "mean_value":       mean_value,
        "collision_free":   collision_free,
    }
