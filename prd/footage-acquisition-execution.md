# Footage Acquisition — Execution Spec (How Each Stage Actually Works)

> **Status:** Draft v0.1 · **Scope:** Pipeline 1 only. This is the "how would we really build it" companion to [footage-acquisition.md](./footage-acquisition.md).
> **For each stage:** what it does → the algorithm/transform → the APIs & market tools that already do it → a concrete "if executed" sketch.

This refines the earlier 8-stage flow into the 5 concrete steps you described:

```
1. SELECT + CONFIRM   2. SURVEY + GEOMETRY   3. 360 MAP (DFS)   4. INTEREST FIELD   5. PATH + SHOTS
   GPS pick, drone        top-down, height       orbit + close-ups   highlight + value    optimize path,
   scans, user clicks      → radius, obstacles    of occluded faces   per point in space   variety shots
```

A note that shapes everything below: **two of these stages reconstruct a 3D model of the scene, and the last two reason over that model.** The 3D model (a point cloud / mesh / Gaussian-splat scene with camera poses) is the internal backbone. Get that right and stages 4–5 become geometry problems with known solutions.

---

## Stage 1 — GPS Target Selection & Confirmation

**What it does:** User picks a rough location on a map. Drone ascends, scans the region, detects candidate targets (buildings/structures), shows them to the user, who taps to confirm the real subject.

### Algorithm / transform
- **Map → GPS intent:** user drops a pin or draws a polygon; you get a lat/lon (+ optional boundary). Convert to a local **NED / ENU** frame (north-east-down meters relative to a home point) for all flight math.
- **Candidate detection from the air:** two ways, used together —
  - *Prior-based (free, instant):* look up known building footprints at that GPS from a database (no flying needed to propose candidates).
  - *Onboard vision:* from the ascent/top-down frame, run **open-vocabulary detection** ("building", "house", "structure") → bounding boxes / masks → reproject box centers to GPS using camera pose + ground plane.
- **Confirm:** user taps a box; that mask/footprint becomes the **Area of Interest (AOI)**.

### APIs & what's on the market
- **Map UI:** Mapbox GL JS, Google Maps Platform, or **CesiumJS** (3D globe, lets you show building heights). Ground-control-style: QGroundControl / DroneKit-era UIs.
- **Building-footprint priors:** OpenStreetMap (Overpass API), **Google Open Buildings**, **Microsoft Global Building Footprints** (many now include height estimates).
- **Onboard detection:** **Grounding DINO** / **YOLO-World** (open-vocabulary, text-promptable) for "find the building"; **SAM 2** (Segment Anything 2) to turn a box into a clean mask.
- **Flight control:** **DJI Mobile/Onboard SDK** (consumer/enterprise DJI), or **MAVSDK + MAVLink** for PX4/ArduPilot (vendor-neutral). **RTK GPS** for cm-level positioning if available.

### If executed
```
user pin (lat,lon) ──▶ set home, define geofence radius
   │
   ├─ query OSM/Google Open Buildings at (lat,lon) ─▶ candidate footprints
   └─ takeoff → ascend → capture nadir (top-down) frame
            └─ YOLO-World/Grounding DINO("building") ─▶ boxes
                  └─ SAM 2 ─▶ masks ─▶ reproject to GPS via camera pose
   ▼
present candidates on map ──▶ user taps one ──▶ AOI locked
```

---

## Stage 2 — Top-Down Survey, Geometry Estimation & Obstacle Map

**What it does:** Center on the target, figure out how *tall* it is and how *far back* the drone must orbit to fit the whole building in frame, and scan the ground below for things it could crash into.

### Algorithm / transform
- **Height of the subject (H):**
  - *Onboard:* downward **LiDAR/rangefinder** or **GPS-altitude − barometric ground** gives drone height; subtract structure-top vs ground using a quick **DSM** (digital surface model) from the survey images.
  - *Prior:* many footprint datasets ship a height attribute — use as a first guess.
- **Orbit radius (the key bit of math):** to fit a building of height `H` in a camera with vertical field-of-view `VFOV`, the standoff distance is
  ```
  r ≈ (H/2 + margin) / tan(VFOV / 2)
  ```
  Pick `margin` for headroom; this `r` becomes the radius of the 360 in Stage 3. (Same idea horizontally for width using HFOV.)
- **Obstacle map:** from the top-down pass, build a **2.5D elevation / occupancy map** — what's tall (trees, wires, poles, other buildings) within the planned orbit annulus.
  - *Transforms:* monocular **metric depth** (Depth Anything V2) or stereo depth → point cloud → **OctoMap / 2.5D height grid**; **semantic segmentation** to label trees/wires/people as no-go.

### APIs & what's on the market
- **Depth:** Depth Anything V2 (monocular), onboard stereo (Skydio-style), or RGB-D.
- **Occupancy mapping:** **OctoMap**, **Nav2** costmaps, or **VDB**-based grids; ArduPilot/PX4 obstacle-avoidance modules.
- **Elevation/DSM on the fly:** **OpenDroneMap (ODM)** produces DSM/orthophoto from overlapping nadir shots; or quick **COLMAP** sparse cloud.
- **Reference products:** Skydio's onboard obstacle avoidance, DJI APAS / omnidirectional sensing — both prove this is solved in real time on commodity drones.

### If executed
```
center over AOI ──▶ nadir survey grid (a few overlapping top-down shots)
   │
   ├─ height: rangefinder + DSM ─▶ H
   ├─ standoff: r = (H/2 + margin)/tan(VFOV/2)
   └─ obstacles: DepthAnything/stereo ─▶ point cloud ─▶ OctoMap
            └─ SAM2 / segmentation ─▶ label trees, wires (no-fly volumes)
   ▼
orbit radius r + obstacle-aware safe volume
```

---

## Stage 3 — 360° Mapping with DFS Exploration & Occlusion Close-Ups

**What it does:** Fly a 360 around the property at radius `r`, building a full 3D map. When a face is blocked (e.g., trees in front of one wall), detect the gap and dive in for a close-up from a better angle. Result: a complete 3D model.

This is the richest stage, and it maps **exactly** onto a well-studied robotics problem: **active 3D reconstruction via Next-Best-View (NBV) planning.** Your "DFS until you've seen everything, take close-ups of what's occluded" *is* frontier-based NBV.

### Algorithm / transform
- **Base orbit:** a cylindrical/boustrophedon coverage path around the AOI at radius `r`, gimbal aimed at the centroid — gets the easy 80%.
- **Live reconstruction:** **Structure-from-Motion** for camera poses + a dense model:
  - *Poses:* **COLMAP** (SfM) or real-time **VIO/SLAM** (ORB-SLAM3).
  - *Dense model:* **3D Gaussian Splatting** (or **DroneSplat**, a 2025 method built specifically for in-the-wild drone imagery), or a textured **mesh** via ODM.
- **Occlusion / coverage gap detection (the "DFS" part):** voxelize the scene; each surface voxel is `seen / unseen / under-observed`. A wall hidden behind trees stays low-confidence → it's a **frontier**. The planner computes, for candidate viewpoints, the **information gain** (how much unseen/under-seen surface they'd reveal) and goes to the highest-gain one next. DFS = keep descending into the most-uncertain region until its gain drops below a threshold, then back out.
- **Close-up trigger:** if a frontier can't be resolved from the orbit radius (occluded), generate a *closer, re-angled* viewpoint that has line-of-sight (checked against the OctoMap) and shoot detail there.
- **Stop condition:** coverage % over a target, or battery budget.

### APIs & what's on the market
- **SfM / poses:** COLMAP, RealityCapture, Agisoft Metashape (commercial), Pix4D.
- **Dense 3D:** 3D Gaussian Splatting (gsplat / Nerfstudio), DroneSplat, NeRF (Nerfstudio), OpenDroneMap (mesh+ortho).
- **NBV / view planning:** frontier-based NBV planners (receding-horizon "NBVP"), "Bag of Views" appearance-based NBV; the two-stage **viewpoint-generation → routing** pattern from the inspection-planning literature.
- **Reference products:** DJI **Terra** / enterprise "oblique" & "smart oblique" capture, **Pix4Dcapture**, **Skydio 3D Scan** — these are commercial autonomous-scan apps that already do orbit + adaptive close-up capture for inspection. Skydio 3D Scan in particular is the closest shipping analog to this stage.

### If executed
```
orbit at r, gimbal → centroid ──▶ stream frames
   │   (COLMAP/SLAM poses + Gaussian-splat/mesh built incrementally)
   ▼
voxel coverage map ── any under-observed surface? ──no──▶ done (coverage ≥ target)
        │ yes
        ▼
rank frontiers by information gain (DFS: deepest-uncertainty first)
        │
        ├─ resolvable from orbit? ─▶ nudge viewpoint, capture
        └─ occluded? ─▶ plan closer line-of-sight pose (OctoMap-checked) ─▶ close-up
        ▼ (loop until coverage target or battery floor)
complete 3D model + posed image set
```

---

## Stage 4 — Interest Field: Highlight Interesting Items & Assign Value to Space

**What it does:** Look over the captured imagery/model for *interesting* things — "noise" (rich detail/texture) and "clean lines" (strong geometry/edges) — then assign a **value to points in 3D space**: a viewpoint is valuable if it sees a lot of high-interest stuff, *and* it's even better when it's near the **optimal focal point** of those things (right distance, well-framed).

### Algorithm / transform
Two sub-steps: **(A) find interest in images**, then **(B) lift it into a 3D value field over candidate viewpoints.**

**A. Per-image interest signals** (your "noise" and "clean lines"):
- **"Clean lines" / geometry:** edge & line detectors — **Canny**, **Hough transform**, **LSD** (Line Segment Detector), or learned wireframe parsers (**HAWP**, **LETR**). Strong, long, coherent lines → high score.
- **"Noise" / detail density:** local high-frequency energy — **Laplacian variance**, gradient-magnitude density, local entropy, or FFT/wavelet energy. Dense fine texture → high score.
- **Visual saliency:** where the eye goes — deep saliency models (**U²-Net**, **TRACER**).
- **Aesthetic quality:** **NIMA** (Neural Image Assessment) scores "would a human like this shot."
- **Semantic interest:** **CLIP** / open-vocab detection to up-weight meaningful subjects ("entrance", "facade", "architectural detail").
- Combine into a per-pixel **interest heatmap** = weighted sum of these signals.

**B. Lift to a 3D value field:**
- **Project** the per-pixel heatmaps onto the Stage-3 model (you have camera poses) → a scalar **interest density** baked onto the surface / into voxels. Hotspots in 3D = the things worth filming.
- **Score a candidate viewpoint `v`:**
  ```
  value(v) = Σ_over_visible_hotspots  interest(p)
                  · framing(v, p)          // angle vs surface normal, in-frame position
                  · focal(dist(v,p))        // peaks at the optimal subject distance
  ```
  - `focal(d)` is a falloff (e.g., Gaussian) peaking at the ideal focal/subject distance → "weighted better if closer to the optimal focal point," exactly as you described.
  - `framing(v,p)` rewards looking at a surface straight-on-ish and keeping the subject well-placed in frame.
- The result is a **value field over viewpoint space** — a function you can then optimize in Stage 5.

### APIs & what's on the market
- **Edges/lines:** OpenCV (`Canny`, `HoughLinesP`, `createLineSegmentDetector`), DeepLSD/HAWP.
- **Saliency/aesthetics:** U²-Net, TRACER, **NIMA** (TF/PyTorch reimplementations widely available).
- **Semantics:** CLIP (OpenCLIP), Grounding DINO, SAM 2 for instance masks.
- **Projection / fusion:** standard in any SfM stack (reproject with known intrinsics+pose); Open3D / PyTorch3D for the geometry.
- **Reference idea:** this "score viewpoints by predicted value" is the same machinery as **information gain** in NBV (Stage 3) — here the "information" is *aesthetic/semantic interest* instead of *unseen surface*. Same math, different objective.

### If executed
```
posed images ──▶ per-image: [Canny/LSD lines] + [Laplacian/entropy texture]
                              + [U²-Net saliency] + [NIMA aesthetics] + [CLIP semantics]
                 ──▶ interest heatmap per image
   │
project heatmaps onto 3D model (poses known) ──▶ 3D interest density (hotspots)
   │
for a grid of candidate viewpoints v:
   value(v) = Σ interest(p)·framing(v,p)·focal(dist(v,p))   over visible hotspots p
   ▼
value field over viewpoint space
```

---

## Stage 5 — Path Optimization & Variety Shots

**What it does:** Given the value field, pick the best places to shoot from, then draw a smooth, safe, flyable path through them — and capture a *variety* of shot types (orbit, reveal, push-in, top-down…) rather than the same look repeated.

### Algorithm / transform
- **Pick viewpoints:** take local maxima of `value(v)` (your "optimized points"). Refine each with **gradient ascent / descent** on the value field (your gradient-descent step): nudge the camera pose to climb to the best nearby framing.
- **Assign shot types (variety):** map each high-value subject to one or two entries from a **shot-grammar library** — *orbit, flyby, reveal (occluder → subject), push-in/dolly, top-down, parallax/dronie*. Diversity is a constraint: don't reuse the same grammar on adjacent subjects.
- **Order them (routing):** visiting the chosen viewpoints efficiently is a **Travelling-Salesman / vehicle-routing** problem → solve with an OR-Tools TSP. (This is the standard "viewpoints → routing" two-stage inspection pattern.)
- **Draw the actual trajectory:** connect ordered viewpoints into a continuous, dynamically-feasible, collision-free path:
  - **Global safe connectors:** **RRT\*** / **A\*** through the OctoMap.
  - **Smoothing/feasibility:** **minimum-snap polynomial trajectories** (Mellinger), B-splines, or trajectory optimization (**CHOMP/TrajOpt**) — minimize a cost of `path length + jerk/snap + obstacle penalty − captured value`. That cost-minimization *is* the gradient-descent path drawing.
  - **Gimbal keyframes:** for each segment, set gimbal aim + camera move to execute the assigned shot.
- **Emit a mission:** waypoints + gimbal/camera keyframes the drone firmware can fly.

### APIs & what's on the market
- **Routing:** Google **OR-Tools** (TSP/VRP).
- **Motion planning:** **OMPL** (RRT\*/PRM), **Nav2**, ArduPilot/PX4 path modes.
- **Smooth trajectories:** `mav_trajectory_generation` (min-snap), Toppra (time-parameterization), CHOMP/TrajOpt (via MoveIt-style stacks).
- **Mission execution:** **DJI Waypoint Mission V2/V3**, **MAVSDK Mission**, MAVLink mission items; gimbal control via the same SDKs.
- **Reference products — this is the shipping state of the art:** **Skydio KeyFrame** (define keyframes, drone flies a smooth spline through them), **DJI MasterShots / QuickShots / ActiveTrack** (automated variety shots), **Litchi** waypoint missions. PRAL's novelty is *auto-choosing* the keyframes from the value field instead of the user placing them.

### If executed
```
value field ──▶ local maxima ──gradient ascent──▶ refined viewpoints
   │
assign shot grammar (orbit / reveal / push-in / top-down…) — enforce variety
   │
OR-Tools TSP ──▶ visit order
   │
RRT*/A* through OctoMap (safe connectors) ──▶ min-snap / TrajOpt smoothing
   │  (cost = length + snap + obstacle − value ; minimized by gradient descent)
   ▼
waypoint + gimbal-keyframe mission ──▶ DJI/MAVSDK ──▶ FLY & CAPTURE
   ▼
Curated Footage Set (clips + poses + shot types + interest tags)
```

---

## The backbone that ties it together

| Concern | Concrete choice |
|---|---|
| **Flight control** | MAVSDK/MAVLink (PX4/ArduPilot) or DJI SDK; RTK GPS |
| **Perception** | YOLO-World / Grounding DINO + SAM 2 (detect/segment), Depth Anything V2 (depth) |
| **3D model** | COLMAP/SLAM poses + 3D Gaussian Splatting (or ODM mesh) — *the shared backbone* |
| **Mapping/obstacles** | OctoMap / Nav2 costmap |
| **Interest** | OpenCV edges/lines + Laplacian/entropy texture + U²-Net saliency + NIMA + CLIP |
| **Planning** | NBV (info gain) for coverage; OR-Tools TSP for order; RRT\*/min-snap for the path |
| **Compute split** | survey/orbit on-drone; heavy 3D + interest + planning on a ground station (round-trip between passes) — *to be confirmed* |

**The one insight worth repeating:** Stages 3, 4, and 5 are the *same algorithm* (score candidate viewpoints, go to the best ones) with three different objectives — *unseen surface* (coverage), then *aesthetic/semantic interest* (value), then *smooth-safe-visiting* (path). Build the viewpoint-scoring + 3D-model core once and all three fall out of it.

---

## Sources

- [A Review on Viewpoints and Path-planning for UAV-based 3D Reconstruction (arXiv)](https://arxiv.org/pdf/2205.03716)
- [A structured review and taxonomy of next-best-view strategies (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S2667393225000171)
- [Bag of Views: Appearance-based Next-Best-View Planning (arXiv)](https://arxiv.org/pdf/2307.05832)
- [DroneSplat: 3D Gaussian Splatting for Robust 3D Reconstruction from In-the-Wild Drone Imagery (CVPR'25)](https://github.com/BITyia/DroneSplat)
- [Drone reconstruction pipeline (COLMAP + NeRF/3DGS)](https://github.com/ch1bo/drone-reconstruction)
- [SAM 2: Segment Anything Model 2 (Ultralytics)](https://docs.ultralytics.com/models/sam-2)
- [Explaining Automatic Image Assessment / NIMA modalities (arXiv)](https://arxiv.org/html/2502.01873v1)
- [PX4 Robotics / Drone Apps & APIs (MAVSDK)](https://docs.px4.io/main/en/robotics/)
- [Four Drone Manufacturers Providing SDKs (RIIS)](https://www.riis.com/blog/four-drone-manufacturers-providing-sdks)
- [Skydio KeyFrame autonomous cinematography (DroneDJ)](https://dronedj.com/2022/01/04/what-is-skydio-keyframe-ai-drone-feature/)
