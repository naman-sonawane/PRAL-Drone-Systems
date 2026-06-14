# Stage 5 — Path Optimization & Variety Shots: Implementation Spec

> Status: Draft v0.1
> Companion docs: footage-acquisition-io.md · footage-acquisition-testing.md · stage-4-implementation.md
> Input: value field (interest_scores.npy + building_mesh.ply) from Stage 4; OctoMap from Stage 2; geofence from Stage 1
> Output: 10 ordered waypoints + shot-type tags + smooth trajectory; curated_footage_set.json

---

## Overview

Stage 5 answers: *where exactly should the drone point its camera, and in what order?* It takes the Stage 4 interest field and selects 10 camera viewpoints that (a) target high-value surface regions, (b) span a variety of shot types so the final cut has editorial range, and (c) chain into a smooth, obstacle-free trajectory.

Four sub-steps:

```
5a. Candidate viewpoint sampling    value field → N candidate viewpoints (lat/lon/alt/yaw/pitch)
5b. Shot-type assignment            candidates labeled by type (orbit / reveal / push_in / top_down)
5c. Greedy value-variety selection  10 waypoints selected: maximize value + variety, minimize travel
5d. Trajectory smoothing            Catmull-Rom spline over 10 waypoints; OctoMap collision check
```

---

## I/O Summary

| | Field | Type | Source |
|---|---|---|---|
| **In** | `interest_scores` | `np.ndarray (N_vertices,) float32` | Stage 4 — per-vertex scores 0–1 |
| **In** | `building_mesh` | `o3d.geometry.TriangleMesh` | Stage 4 — source mesh |
| **In** | `octomap` | `octomap.OctoMap` | Stage 2 — occupancy grid (0.2 m resolution) |
| **In** | `geofence_polygon` | `shapely.geometry.Polygon` | Stage 1 — AOI + safety margin in ENU coords |
| **In** | `orbit_radius` | `float` (metres) | Stage 2 — nominal standoff distance |
| **Out** | `waypoints` | `List[Waypoint]`, 10 items | Ordered camera positions, each tagged with shot type |
| **Out** | `trajectory` | `np.ndarray (500, 5) float32` | Dense spline: `[x_enu, y_enu, z_enu, yaw_deg, pitch_deg]` |
| **Out** | `curated_footage_set` | `dict` | Full hand-off: waypoints + trajectory + tags + scores + geofence |

---

## Waypoint Dataclass

```python
from dataclasses import dataclass

@dataclass
class Waypoint:
    lat:       float   # WGS-84 latitude
    lon:       float   # WGS-84 longitude
    alt:       float   # metres AGL
    yaw:       float   # degrees, 0 = North, clockwise
    pitch:     float   # degrees, 0 = horizontal, -90 = nadir
    shot_type: str     # "orbit" | "reveal" | "push_in" | "top_down"
    value:     float   # mean interest score of visible surface (0–1)
    idx:       int     # position in ordered sequence (0–9)
```

---

## Sub-step 5a — Candidate Viewpoint Sampling

### What it does
For every high-interest surface vertex (score ≥ 0.5), generates camera positions on a discretized sphere shell around the building centroid. Each candidate is scored by the total interest visible from that position. Produces N ≈ 300–500 candidates before filtering.

### Implementation steps

1. **Identify high-interest vertices:**
   ```python
   vertices   = np.asarray(building_mesh.vertices)  # (V, 3) ENU
   hot_mask   = interest_scores >= 0.5
   hot_verts  = vertices[hot_mask]
   hot_scores = interest_scores[hot_mask]
   centroid   = vertices.mean(axis=0)
   ```

2. **Discretize sphere shell around centroid:**
   ```python
   import itertools, math

   azimuths   = np.linspace(0, 360, 36, endpoint=False)   # every 10°
   elevations = [-15, 0, 15, 30, 45]                       # degrees above horizontal
   radii      = [orbit_radius * f for f in [0.7, 1.0, 1.5]]

   candidates = []
   for az, el, r in itertools.product(azimuths, elevations, radii):
       az_r, el_r = math.radians(az), math.radians(el)
       dx = r * math.cos(el_r) * math.sin(az_r)
       dy = r * math.cos(el_r) * math.cos(az_r)
       dz = r * math.sin(el_r)
       pos_enu = centroid + np.array([dx, dy, dz])
       yaw   = (math.degrees(math.atan2(dx, dy)) + 180) % 360
       pitch = -math.degrees(math.atan2(dz, math.hypot(dx, dy)))
       candidates.append({"pos_enu": pos_enu, "yaw": yaw, "pitch": pitch,
                          "el_deg": el, "radius": r})
   ```

3. **Score each candidate** by summing interest of vertices with unobstructed line-of-sight:
   ```python
   def candidate_value(pos_enu, hot_verts, hot_scores, octomap):
       total = 0.0
       for v, s in zip(hot_verts, hot_scores):
           direction = v - pos_enu
           dist = float(np.linalg.norm(direction))
           hit, _ = octomap.castRay(pos_enu.tolist(), (direction / dist).tolist(),
                                    maxRange=dist * 1.05)
           if not hit:   # ray reaches target unobstructed
               total += s
       return total / max(len(hot_verts), 1)
   ```

4. **Filter** out-of-geofence and OctoMap-occupied candidates.

### Output
`candidates`: list of dicts `{pos_enu, yaw, pitch, el_deg, radius, value}`, ≈300–500 entries.

---

## Sub-step 5b — Shot-Type Assignment

### What it does
Labels each candidate deterministically from its geometry — no ML.

| Shot type | Rule |
|---|---|
| `top_down` | `pitch < −60°` |
| `push_in` | `radius < orbit_radius × 0.8` |
| `reveal` | `el_deg > 20°` |
| `orbit` | everything else |

```python
def assign_shot_type(el_deg: float, radius: float, orbit_radius: float) -> str:
    pitch = -el_deg   # approximate; exact pitch computed in 5a
    if pitch < -60:
        return "top_down"
    elif radius < orbit_radius * 0.8:
        return "push_in"
    elif el_deg > 20:
        return "reveal"
    else:
        return "orbit"
```

### Output
All candidates carry a `shot_type` field.

---

## Sub-step 5c — Greedy Value-Variety Selection

### What it does
Picks exactly 10 waypoints. Enforces variety (all 4 shot types present) via fixed slots, then fills each slot with the highest-value candidate of that type. Orders the 10 using nearest-neighbor TSP to minimize total flight distance.

### Slot allocation

```python
SHOT_TYPE_SLOTS = {
    "orbit":    4,   # backbone — widest coverage
    "reveal":   2,
    "push_in":  2,
    "top_down": 2,
}
```

### Selection

```python
def select_waypoints(candidates, slots=SHOT_TYPE_SLOTS):
    by_type = {t: sorted([c for c in candidates if c["shot_type"] == t],
                          key=lambda x: -x["value"])
               for t in slots}
    selected = []
    for shot_type, count in slots.items():
        pool = by_type.get(shot_type, [])
        if len(pool) < count:
            raise ValueError(f"Not enough {shot_type} candidates ({len(pool)} < {count})")
        selected.extend(pool[:count])
    return selected
```

### TSP ordering (nearest-neighbor, O(n²))

```python
def order_nn(waypoints):
    unvisited = list(range(len(waypoints)))
    ordered = [unvisited.pop(0)]
    while unvisited:
        last_pos = waypoints[ordered[-1]]["pos_enu"]
        nearest  = min(unvisited,
                       key=lambda i: np.linalg.norm(waypoints[i]["pos_enu"] - last_pos))
        ordered.append(nearest)
        unvisited.remove(nearest)
    return [waypoints[i] for i in ordered]
```

### Output
`waypoints`: 10 entries, ordered, with `idx` 0–9 assigned.

---

## Sub-step 5d — Trajectory Smoothing & Collision Check

### What it does
Fits a `scipy.interpolate.CubicSpline` through the 10 waypoint ENU positions to produce 500 dense samples. Interpolates yaw and pitch linearly. Checks every 10th sample against OctoMap (occupied cell) and geofence (point-in-polygon).

### Tech to install
```
pip install scipy   # only new addition; all others from earlier stages
```

### Implementation steps

1. **Spline over ENU positions:**
   ```python
   from scipy.interpolate import CubicSpline

   pts = np.array([w["pos_enu"] for w in waypoints])   # (10, 3)
   t   = np.linspace(0, 1, 10)
   cs  = CubicSpline(t, pts, bc_type="not-a-knot")
   t_dense  = np.linspace(0, 1, 500)
   traj_enu = cs(t_dense)                               # (500, 3)
   ```

2. **Interpolate heading and pitch:**
   ```python
   yaws    = np.array([w["yaw"]   for w in waypoints])
   pitches = np.array([w["pitch"] for w in waypoints])
   yaw_i   = np.interp(t_dense, t, yaws)
   pitch_i = np.interp(t_dense, t, pitches)
   trajectory = np.column_stack([traj_enu, yaw_i, pitch_i]).astype(np.float32)  # (500, 5)
   ```

3. **Collision check (every 10th sample = 50 checks):**
   ```python
   from shapely.geometry import Point

   collisions = []
   for i in range(0, 500, 10):
       pt = traj_enu[i]
       if octomap.search(pt.tolist()) == octomap.OCCUPIED:
           collisions.append(i)
       if not geofence_polygon.contains(Point(pt[0], pt[1])):
           collisions.append(i)
   if collisions:
       raise TrajectoryCollisionError(
           f"Trajectory collides at sample indices {collisions}. "
           "Adjust the offending waypoints in the Stage 5 visualizer."
       )
   ```

### Output
`trajectory`: `np.ndarray (500, 5) float32`.

---

## Data Artifacts

Files written to `{workspace_dir}/stage5/`:

| File | Format | Description |
|---|---|---|
| `waypoints.json` | JSON, list of 10 | lat/lon/alt/yaw/pitch/shot_type/value/idx |
| `trajectory.npy` | float32 `(500, 5)` | Dense spline: x_enu, y_enu, z_enu, yaw, pitch |
| `curated_footage_set.json` | JSON | Full hand-off: waypoints + trajectory path + geofence + metadata |

---

## Stage 5 Output Contract

| Field | Type | Description |
|---|---|---|
| `waypoints` | `List[Waypoint]`, len 10 | Ordered camera positions |
| `trajectory` | `np.ndarray (500, 5) float32` | Dense smooth path |
| `shot_type_counts` | `dict[str, int]` | Must match SHOT_TYPE_SLOTS |
| `total_distance_m` | `float` | Sum of inter-waypoint distances |
| `mean_value` | `float` | Mean interest score across the 10 waypoints |
| `collision_free` | `bool` | True if all trajectory checks passed |

Gate check:
```python
assert len(waypoints) == 10
assert collision_free, "Unresolved trajectory collisions — adjust in Stage 5 visualizer"
assert set(shot_type_counts.keys()) == set(SHOT_TYPE_SLOTS.keys())
```

---

## Dependencies Summary

| Package | Purpose | Install |
|---|---|---|
| `numpy` | Array ops, spline sampling | from Stage 2 |
| `scipy` | CubicSpline trajectory | `pip install scipy` |
| `open3d` | Mesh vertex access | from Stage 2/3 |
| `octomap` | Candidate filter + collision check | from Stage 2 |
| `shapely` | Geofence polygon checks | from Stage 1/2 |
