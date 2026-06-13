# Footage Acquisition — Stage I/O & Pitch Artifacts

> **Status:** Draft v0.1 · **Scope:** Pipeline 1 only. Companion to [footage-acquisition.md](./footage-acquisition.md), [footage-acquisition-execution.md](./footage-acquisition-execution.md), and [footage-acquisition-test-cases.md](./footage-acquisition-test-cases.md).
> **Diagram companion:** [footage-acquisition-flowchart.md](./footage-acquisition-flowchart.md).
> **Purpose:** What flows in and out of each stage — *footage* (pixels) **and** *data* (everything else) — and the one artifact we put on screen in the pitch to make that stage legible.

---

## The pitch principle

Only two stages produce meaningful *video* (3 and 5); the rest transform data or shoot a handful of stills. So the pitch can't be "watch the drone fly" — it has to **make the invisible stages visible**: overlays for perception, graphs and fields for the math, the 3D model for reconstruction, and only at the very end, the beauty reel.

The demo *is* the pipeline diagram coming alive one box at a time. Each stage's row below names the single most compelling thing we'd render on stage to prove that stage works — that's the heuristic that decides what the artifact is *for*.

---

## Stage 1 — Target Selection & Confirmation

| | |
|---|---|
| **Footage in** | 1 nadir (straight-down) overview still captured during ascent |
| **Data in** | User pin (lat/lon) or drawn boundary; building-footprint priors (OSM / Google Open Buildings) |
| **Footage out** | The same still, annotated with detection boxes + SAM-2 masks |
| **Data out** | Home point, geofence radius, confirmed **AOI polygon** (reprojected to GPS) |
| **🎤 Pitch visual** | **Map with the dropped pin → user taps → AOI mask snaps onto the building.** The "point at it and we lock on" moment. *Overlay footage.* |

---

## Stage 2 — Survey, Geometry & Obstacle Map

| | |
|---|---|
| **Footage in** | ~5–15 overlapping nadir stills (lawnmower grid); optional downward rangefinder/LiDAR depth |
| **Data in** | AOI polygon, camera intrinsics (VFOV/HFOV) |
| **Footage out** | *None for humans* — frames are consumed to derive geometry |
| **Data out** | Height `H`, orbit radius `r`, DSM, per-frame depth maps, **OctoMap** occupancy grid, no-fly volumes |
| **🎤 Pitch visual** | **3D obstacle map with the computed orbit ring drawn around the building**, trees/wires/poles flagged red, and the one-line `r = (H/2 + margin)/tan(VFOV/2)` animating to a number. *Graph / 3D viz, not footage.* |

---

## Stage 3 — 360° Mapping (DFS / NBV) & Close-Ups

| | |
|---|---|
| **Footage in** | *Generated here* — this stage flies the orbit |
| **Data in** | Orbit radius `r`, OctoMap, AOI |
| **Footage out** | Continuous orbit frame stream + N adaptive close-up clips (recon-grade, not beauty) |
| **Data out** | **Posed image set**, **3D model** (Gaussian splat / mesh), voxel coverage map, coverage % |
| **🎤 Pitch visual** | **The 3D reconstruction rotating**, with a coverage heatmap (green = seen, red = occluded) and the **DFS dive-in animation**: drone leaves the orbit ring to resolve a tree-blocked wall. The "it explores like a pilot would" moment. *3D viz + overlay.* |

---

## Stage 4 — Interest Field & Value Assignment

| | |
|---|---|
| **Footage in** | The posed image set from Stage 3 (re-read, not re-flown) |
| **Data in** | Camera poses, 3D model |
| **Footage out** | Per-image **interest heatmaps** (derived imagery) |
| **Data out** | 3D interest-density surface (hotspots); **value field** over viewpoint space |
| **🎤 Pitch visual** | **Building lit up with a heat overlay** (facade / entrance / strong rooflines glowing), then the **value field as a 3D cloud of scored camera positions** — bright blobs where a great shot lives. *Heatmap overlay + 3D scalar field.* This is the "it has taste" slide. |

---

## Stage 5 — Path Optimization & Variety Shots

| | |
|---|---|
| **Footage in** | None as input — consumes the value field (data, not pixels) |
| **Data in** | Value field, OctoMap, geofence |
| **Footage out** | Final beauty clips (orbit / reveal / push-in / top-down …), variety-enforced |
| **Data out** | **Curated Footage Set** (clips + poses + shot tags + interest tags + quality score); executable mission |
| **🎤 Pitch visual** | **The smooth optimized trajectory drawn through the value field** (a line threading the bright blobs), shot-type labels popping on each segment → cut to the **final beauty reel**. *Trajectory graph → real footage.* The payoff. |

---

## One-glance pitch table

```
STAGE   PITCH ARTIFACT                          TYPE
S1      pin → AOI mask snaps on                 overlay footage
S2      3D obstacle map + orbit ring + formula  3D viz / graph
S3      rotating 3D model + coverage heatmap    3D viz + overlay
S4      interest heatmap + value-field cloud    heatmap + scalar field
S5      trajectory through field → beauty reel  graph → footage
```

**Arc of the demo:** lock-on → geometry → exploration → taste → payoff.

Each slide reveals one box of the pipeline diagram; the only "pretty footage" is the last beat, which lands harder because the audience has seen everything that earned it.

---

## Footage vs. data, at a glance

| Stage | Flies? | Footage produced | Primary product |
|---|---|---|---|
| S1 | brief ascent | 1 annotated still | AOI polygon (data) |
| S2 | nadir grid | none (stills consumed) | geometry + OctoMap (data) |
| S3 | **orbit + close-ups** | recon stream + close-ups | posed images + 3D model |
| S4 | no flight | interest heatmaps (derived) | value field (data) |
| S5 | **final mission** | **beauty clips** | **Curated Footage Set** |

**The thing to notice:** only Stages 3 and 5 shoot meaningful imagery, and for opposite reasons — S3's footage is *throwaway recon* whose real product is the 3D model; S5's footage is *the product*. Stage 4 flies nothing at all. That's the "see broadly and cheaply, spend effort only where it pays" principle showing up literally as *where the camera actually rolls* — and it's why the pitch leans on overlays and graphs for the middle, not video.
