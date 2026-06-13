# How the 16 Shots Are Generated and Processed

## Overview

The 16 shots map across the pipeline as follows:

```
Stage 1 (Select + Confirm)     →  feeds all stages
Stage 2 (Survey + Geometry)    →  generates Survey Shots 1–4
Stage 3 (360 Mapping)          →  data-collection pass (not a deliverable shot)
Stage 4 (Interest Field)       →  generates Interest Point Shots 1–3
Stage 5 (Path + Shots)         →  generates Cinematic Shots 1–9
```

---

## Survey Shots 1–4 (Stage 2)

**What they are:** Four recordings, one per edge of the building perimeter. Each shot is the drone traversing one leg:

- Shot 1: bottom-left corner → top-left corner
- Shot 2: top-left corner → top-right corner
- Shot 3: top-right corner → bottom-right corner
- Shot 4: bottom-right corner → bottom-left corner

The drone pauses at each endpoint, stops recording, then starts a new clip for the next leg.

**How they're calculated:**

Stage 1 produces the AOI (Area of Interest) — either a footprint polygon from OSM/Open Buildings, or a SAM 2 mask reprojected to GPS. The four corners of that footprint are extracted and converted from lat/lon to a local NED (North-East-Down) frame relative to the home point. These become four waypoint pairs.

The drone flies each pair as a straight segment. During each leg, the camera captures overlapping nadir (downward-facing) and angled frames. After all four shots, those frames are fed into:

1. **DSM construction** (via OpenDroneMap or COLMAP sparse cloud): produces a digital surface model of the building and ground. Building height `H` is extracted as `DSM_roof - DSM_ground`.
2. **Orbit radius calculation**: `r = (H/2 + margin) / tan(VFOV/2)` — this is the standoff distance used in Stage 3.
3. **OctoMap obstacle grid**: DepthAnything V2 or stereo depth applied to every frame across all 4 legs → point cloud → voxelized occupancy map. Trees, wires, adjacent structures are labeled as no-fly volumes.

**What they feed:** H, r, and the OctoMap are the three inputs Stage 3 cannot start without.

---

## 360 Mapping — Stage 3 (data-collection pass, not a deliverable shot)

**What it is:** A full orbital pass around the building at radius `r`. This is not captured as a final clip for the footage set — it's the 3D reconstruction pass.

**How it's calculated:**

The drone flies a cylindrical coverage path centered on the AOI centroid at radius `r`, with the gimbal continuously aimed at the centroid. Frames are streamed in real time to a ground station:

1. **Pose estimation**: COLMAP (offline SfM) or ORB-SLAM3 (real-time VIO) determines the camera pose for every frame.
2. **Dense 3D model**: 3D Gaussian Splatting (via gsplat/DroneSplat) or an ODM mesh is built incrementally from the posed frames.
3. **Voxel coverage map**: the model is voxelized; each surface voxel is tracked as `seen / unseen / under-observed`. Walls occluded by trees or other structures stay low-confidence — these are **frontiers**.
4. **DFS/NBV loop**: frontiers are ranked by information gain (how much unseen surface a candidate viewpoint would reveal). The planner goes to the highest-gain frontier first (DFS = keep descending into the most-uncertain region). If a frontier can't be resolved from orbit radius (occluded), a closer line-of-sight pose is generated and checked against the OctoMap — the drone detours for a close-up, then returns.
5. **Stop condition**: loop ends when surface coverage exceeds a threshold or battery reaches the floor.

**Output:** A complete 3D model (Gaussian splat or mesh) with full camera pose history. This is the shared backbone that Stages 4 and 5 operate on.

---

## Interest Point Shots 1–3 (Stage 4 output)

**What they are:** Three shots, one per interest point — the bridge, the engineering sign, and the flowers next to the staircase. Each shot follows the same script: start at home → fly up + top-down view → navigate to interest point → descend + scan → zoom out.

**How the interest points are found (Stage 4):**

Stage 4 runs a multi-signal interest analysis over all the posed images from Stage 3:

- **"Clean lines"** (Canny edge detector, Hough transform, LSD) → high score for strong, coherent geometry
- **"Noise" / texture density** (Laplacian variance, local entropy) → high score for fine detail
- **Visual saliency** (U²-Net) → where the eye naturally goes
- **Aesthetic quality** (NIMA) → predicted human preference score
- **Semantic interest** (CLIP + Grounding DINO) → text-prompted detection: "bridge", "sign", "flowers", "entrance"

These are combined into a per-pixel interest heatmap for each image, then **projected back onto the 3D model** using the known camera poses. The result is a 3D interest density — a scalar field baked onto the model surface. The bridge, eng sign, and flowers appear as the three highest-scoring hotspots.

**How each shot is calculated:**

For each of the three hotspots, the pipeline derives a shot script:

1. **Ascend + top-down view**: drone lifts from home position; gimbal tilts downward. Altitude is chosen to frame the full AOI. This clip establishes context.
2. **Navigate to interest point**: the hotspot's 3D centroid is converted to GPS. The drone flies there via an RRT*/A* path through the OctoMap (avoiding all obstacles). The approach itself is recorded.
3. **Descend + scan**: the drone descends to the optimal subject distance, determined by the `focal(dist)` function from the Stage 4 value formula — `focal(d)` is a Gaussian peaking at ideal subject distance (typically 5–15 m depending on subject size). The gimbal reorients to face the subject directly. The drone may circle or hover to get multiple angles.
4. **Zoom out**: drone ascends or pulls back while maintaining subject framing — recorded as the exit of the shot.

The three shots are:

| Shot | Interest Point | How it's identified |
|---|---|---|
| IP-1 | Bridge | High CLIP "bridge" score + strong Canny line geometry |
| IP-2 | Engineering sign | High CLIP "sign" score + Hough text-area lines + saliency peak |
| IP-3 | Flowers next to staircase | High CLIP "flowers" + U²-Net saliency + fine Laplacian texture |

---

## Cinematic Shots 1–9 (Stage 5 output)

**What they are:** Nine shots produced by combining the three interest points with three path types:

| | Bridge | Eng Sign | Flowers |
|---|---|---|---|
| **Zoom (dolly/push-in)** | Shot 1 | Shot 2 | Shot 3 |
| **Pan (lateral sweep)** | Shot 4 | Shot 5 | Shot 6 |
| **Zoom + Pan (combined)** | Shot 7 | Shot 8 | Shot 9 |

**How they're calculated:**

**Step 1 — Viewpoint selection.** The Stage 4 value field has local maxima around each interest point. For each of the 9 (point, path-type) pairs, gradient ascent is run on `value(v) = Σ interest(p) · framing(v,p) · focal(dist(v,p))` to refine the viewpoint to the best nearby position and orientation. This gives 9 refined camera poses.

**Step 2 — Shot grammar assignment.** Each viewpoint is tagged with its shot type:
- *Zoom (dolly)*: gimbal holds subject center; drone translates toward/away along the subject's optical axis.
- *Pan*: drone holds altitude and distance; gimbal sweeps laterally across the subject.
- *Zoom + Pan*: simultaneous dolly-in and lateral sweep — the most cinematic variant.

Variety is enforced: adjacent subjects cannot use the same grammar, preventing visual repetition.

**Step 3 — Visit ordering (OR-Tools TSP).** The 9 viewpoints are treated as nodes in a Travelling Salesman Problem. OR-Tools finds the shortest visit order, minimizing total flight distance across all 9 shots.

**Step 4 — Path planning.** Between each ordered viewpoint pair:
- RRT*/A* through the OctoMap finds a collision-free global connector path.
- Min-snap polynomial trajectories (or TrajOpt) smooth those waypoints into a continuous, dynamically-feasible trajectory, minimizing `cost = path_length + jerk/snap + obstacle_penalty − captured_value`. This cost-minimization is the "gradient descent on the path" described in the spec.

**Step 5 — Gimbal keyframes.** For each segment, gimbal aim + motion keyframes are computed to execute the assigned shot grammar throughout the approach, hold, and exit.

**Step 6 — Mission emit.** The full sequence is packaged as waypoints + gimbal keyframes in DJI Waypoint Mission V2/V3 format (or MAVSDK mission items). The drone flies the entire 9-shot sequence autonomously, recording each clip.

---

## End-to-end summary

```
Stage 1  →  AOI footprint + GPS coordinates
Stage 2  →  Survey Shots 1–4  →  H, r, OctoMap
Stage 3  →  360 mapping pass   →  3D model + camera poses
Stage 4  →  Interest field      →  3 hotspots identified  →  Interest Point Shots 1–3
Stage 5  →  Path optimization   →  9 viewpoints + trajectories  →  Cinematic Shots 1–9
```

The 3D model from Stage 3 is the backbone. Stages 4 and 5 are the same core operation — score candidate viewpoints, go to the best ones — with different objectives: aesthetic/semantic interest (Stage 4) then smooth-safe-visiting (Stage 5).
