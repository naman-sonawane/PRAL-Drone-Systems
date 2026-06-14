# Footage Acquisition — Testing & QA PRD

> **Branch:** footage-ac · **Companion doc:** [footage-acquisition-execution.md](./footage-acquisition-execution.md)

---

## Stage 1 — GPS Target Selection & Confirmation

### Execution Reference
User drops a pin → drone ascends → YOLO-World/Grounding DINO detects candidates → SAM 2 masks → reproject to GPS → user taps to confirm AOI.

### Test Procedure

**T1.1 — Pin-to-NED frame conversion**
- Input: known lat/lon coordinate
- Run: coordinate transform to NED/ENU
- Expect: reprojected back to lat/lon within ±0.5m of input

**T1.2 — Building footprint lookup**
- Input: lat/lon of a known building (ground truth footprint available)
- Run: OSM / Google Open Buildings query
- Expect: at least one returned footprint overlaps ground truth by ≥80% IoU within 2s

**T1.3 — Onboard candidate detection**
- Input: nadir frame from a controlled test flight over a known structure
- Run: YOLO-World("building") → SAM 2 mask → reproject to GPS
- Expect: bounding box center lands within ±3m of the building's known centroid; mask IoU vs ground truth ≥0.75

**T1.4 — User confirmation round-trip**
- Input: presented candidate list (≥2 candidates on screen)
- Run: user taps correct candidate
- Expect: AOI polygon locked matches the tapped candidate's footprint; all other candidates cleared

**T1.5 — Rejection / retry**
- Input: no valid candidates detected (empty field, bad GPS)
- Expect: graceful fallback UI prompt, no crash, drone hovers safely

---

## Stage 2 — Top-Down Survey, Geometry & Obstacle Map

### Execution Reference
Centers over AOI → measures height via rangefinder + DSM → computes orbit radius `r = (H/2 + margin) / tan(VFOV/2)` → builds 2.5D OctoMap with semantic no-fly labels.

### Test Procedure

**T2.1 — Height estimation accuracy**
- Input: structure of known height (e.g. a measured test building)
- Run: rangefinder + DSM pipeline
- Expect: estimated H within ±10% of ground truth

**T2.2 — Orbit radius formula**
- Input: H from T2.1, known VFOV from camera spec, defined margin
- Run: compute `r`
- Expect: at computed radius, building occupies 60–85% of vertical frame (not clipped, not tiny)

**T2.3 — Obstacle detection**
- Input: test area with known obstacle positions (measured trees, poles)
- Run: Depth Anything V2 → point cloud → OctoMap
- Expect: all obstacles >1m tall within the orbit annulus appear in OctoMap; false-negative rate <5%

**T2.4 — Semantic labeling**
- Input: scene with trees and a wall
- Run: SAM 2 / segmentation → label classes
- Expect: trees labeled as no-go, building wall labeled as traversable; confusion rate <10%

**T2.5 — Degenerate geometry**
- Input: flat structure (H < 2m), very tall structure (H > 20m)
- Expect: `r` stays within drone's safe operating range; pipeline clamps and warns rather than generating an unsafe orbit

---

## Stage 3 — 360° Mapping with DFS / Next-Best-View

### Execution Reference
Orbit at radius `r` → COLMAP/SLAM poses + incremental Gaussian Splatting → voxel coverage map → frontier detection → information-gain ranking → close-up capture of occluded surfaces → stop at coverage target or battery floor.

### Test Procedure

**T3.1 — Pose accuracy**
- Input: flight over a structure with surveyed GCPs (ground control points)
- Run: COLMAP SfM on captured frames
- Expect: reprojection error <1px mean; camera positions within ±0.2m of RTK GPS log

**T3.2 — Coverage completeness**
- Input: cubic test structure (all faces visible from orbit)
- Run: full orbit → voxel coverage map
- Expect: ≥95% of exposed surface voxels marked "seen" after one orbit

**T3.3 — Occlusion / frontier detection**
- Input: structure with a face partially hidden behind a known obstacle
- Run: voxel coverage check after base orbit
- Expect: occluded face voxels correctly flagged as frontier; information gain for close-up viewpoint is highest-ranked

**T3.4 — Close-up viewpoint validity**
- Input: frontier from T3.3
- Run: generate close-up pose → OctoMap collision check
- Expect: generated pose has line-of-sight to frontier; no OctoMap collision along path to that pose

**T3.5 — Stop condition**
- Input: battery floor set to 30%; coverage target set to 90%
- Run: full DFS loop
- Expect: mission stops at whichever threshold is hit first; never flies below battery floor

**T3.6 — Model quality**
- Input: complete posed image set from T3.2
- Run: 3D Gaussian Splatting
- Expect: novel-view renders of held-out camera poses achieve PSNR ≥25dB / SSIM ≥0.85

---

## Stage 4 — Interest Field

### Execution Reference
Per-image: Canny/LSD + Laplacian/entropy + U²-Net saliency + NIMA + CLIP → interest heatmap → project onto 3D model via known poses → score candidate viewpoints by `Σ interest(p) · framing(v,p) · focal(dist(v,p))`.

### Test Procedure

**T4.1 — Per-signal sanity checks**
- Input: synthetic images with known ground truth (e.g. image A has strong edges, image B has dense texture, image C has a salient center subject)
- Run: each signal independently
- Expect: Canny/LSD scores highest on A; Laplacian scores highest on B; U²-Net saliency peaks center on C

**T4.2 — Heatmap projection correctness**
- Input: a single image with a known high-interest region (e.g. a red door) + its camera pose + the 3D model
- Run: back-project heatmap onto surface
- Expect: the 3D surface region corresponding to the door has the highest interest density; positional error <0.3m

**T4.3 — Viewpoint scoring monotonicity**
- Input: three candidate viewpoints at increasing distance from a known hotspot
- Run: compute `value(v)` for each
- Expect: scores peak at the ideal focal distance and decay on both sides (closer and farther)

**T4.4 — Framing penalty**
- Input: two viewpoints equidistant from a hotspot; one face-on, one at 75° grazing angle
- Run: compute `framing(v, p)` for each
- Expect: face-on viewpoint scores at least 2× higher than grazing

**T4.5 — Multi-hotspot aggregation**
- Input: viewpoint that sees three hotspots vs one that sees one hotspot perfectly
- Expect: if cumulative interest is higher, multi-hotspot view wins; verifies the Σ aggregation is working

---

## Stage 5 — Path Optimization & Variety Shots

### Execution Reference
Local maxima of value field → gradient ascent refinement → shot grammar assignment with variety constraint → OR-Tools TSP ordering → RRT*/A* safe connectors → min-snap smoothing → waypoint + gimbal keyframe mission → fly.

### Test Procedure

**T5.1 — Viewpoint refinement**
- Input: a coarse viewpoint near (but not at) a local maximum of the value field
- Run: gradient ascent
- Expect: refined viewpoint has strictly higher `value(v)` than the initial; converges within 20 iterations

**T5.2 — Shot grammar variety**
- Input: 6 high-value viewpoints
- Run: assign shot grammar
- Expect: no single shot type (orbit, reveal, push-in, top-down, etc.) appears more than twice in a sequence of 6; distribution passes a basic entropy check

**T5.3 — TSP routing efficiency**
- Input: 8 viewpoints with known pairwise distances
- Run: OR-Tools TSP
- Expect: output route is within 110% of optimal (known from brute force at this scale); completes in <5s

**T5.4 — Collision-free path**
- Input: ordered viewpoints + OctoMap with 3 known obstacles between them
- Run: RRT*/A* connector
- Expect: generated path clears all obstacles by ≥1m safety margin; path exists within 2s planning budget

**T5.5 — Trajectory smoothness**
- Input: RRT* waypoints from T5.4
- Run: min-snap optimization
- Expect: max jerk stays within drone's physical limits; no velocity discontinuities at waypoints; total path length does not increase by more than 15% vs the RRT* path

**T5.6 — Mission output validity**
- Input: completed trajectory
- Run: emit DJI/MAVSDK mission format
- Expect: all waypoints within geofence; gimbal angles within hardware limits; mission passes DJI/MAVSDK pre-flight validation without errors

**T5.7 — End-to-end execution**
- Input: full generated mission on a test structure
- Run: fly and capture
- Expect: ≥80% of planned shots are captured within ±0.5m and ±5° of target pose; all clips correctly tagged with pose + shot type metadata

---

## Overall Pipeline QA & Failure Points

### Stage Transition Contracts

Each stage has a hard contract — if the output doesn't meet it, the next stage must not proceed.

| Transition | Contract | Failure behavior |
|---|---|---|
| **1 → 2** | AOI polygon locked with ≥1 confirmed candidate | Abort: return to stage 1, re-prompt user |
| **2 → 3** | Height H estimated; orbit radius `r` in [3m, 50m]; OctoMap populated | Abort: flag geometry failure, land safely |
| **3 → 4** | Coverage ≥ target % OR battery floor hit; ≥N posed frames; 3D model renders with PSNR ≥ threshold | Warn if below quality floor; proceed with reduced confidence flag |
| **4 → 5** | Value field computed; ≥K viewpoints with value above minimum threshold | Abort if no viable viewpoints found; surface to operator |
| **5 → fly** | Mission passes pre-flight validation; all waypoints in geofence; battery ≥ required for mission | Hard abort; do not arm |

---

### Cross-Pipeline Failure Modes

**F1 — GPS drift / pose corruption**
- Where it breaks: Stage 1 (false AOI lock), Stage 3 (bad reconstruction), Stage 5 (waypoints land in wrong physical location)
- Detection: cross-check COLMAP poses against RTK GPS log; flag if disagreement >1m
- Mitigation: fuse RTK GPS + VIO; reject frames with pose confidence below threshold

**F2 — 3D model quality collapse**
- Where it breaks: Stage 3 → 4 boundary; if the model is sparse/broken, heatmap projection in Stage 4 is meaningless
- Detection: PSNR/SSIM check on held-out frames; point cloud density check
- Mitigation: trigger additional survey passes before proceeding; degrade gracefully to 2D-only interest scoring

**F3 — OctoMap stale or incomplete**
- Where it breaks: Stage 3 (bad close-up routing), Stage 5 (collision in connectors)
- Detection: check map timestamp vs flight time; flag voxels with low update count
- Mitigation: conservative buffer inflation on uncertain voxels; refuse to plan paths through low-confidence map regions

**F4 — Battery budget violation**
- Where it breaks: any stage if mission runs long
- Detection: continuous battery monitor; project remaining flight time against remaining mission budget
- Mitigation: stage-aware abort — complete current capture, return home. Stage 3 is the biggest risk (open-ended DFS loop)

**F5 — Interest field starvation**
- Where it breaks: Stage 4 → 5 if scene is genuinely texture-poor / featureless
- Detection: mean value across all candidate viewpoints below floor threshold
- Mitigation: fall back to geometry-only scoring (face-on, optimal distance, no interest weighting); flag output as "low confidence — manual review recommended"

**F6 — Shot grammar deadlock**
- Where it breaks: Stage 5 variety constraint conflicts with physical reachability (e.g. only one approach corridor)
- Detection: TSP + grammar assignment returns infeasible
- Mitigation: relax variety constraint progressively (allow one repeat before allowing two); always guarantee a valid mission exists

---

### Regression Test Suite (Run on Every Build)

| ID | Scope | Fixture | Pass criteria |
|---|---|---|---|
| R1 | S1 | Synthetic nadir frame, known building | Detection + reproject within ±3m |
| R2 | S2 | Known-height test structure | H ±10%, r in valid range |
| R3 | S3 | Controlled outdoor structure, no occlusion | Coverage ≥95%, pose error <1px |
| R4 | S3 | Same + partial occlusion | Frontier detected, close-up pose valid |
| R5 | S4 | Synthetic image set with known interest GT | Heatmap projection positional error <0.3m |
| R6 | S5 | 8-viewpoint TSP fixture | Route ≤110% optimal, no collision |
| R7 | E2E | Full pipeline on test structure | ≥80% shots captured within pose tolerance |
