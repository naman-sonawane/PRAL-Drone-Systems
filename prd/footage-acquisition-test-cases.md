# Footage Acquisition — Test Cases

> **Status:** Draft v0.1 · **Scope:** Pipeline 1 only. Companion to [footage-acquisition.md](./footage-acquisition.md) and [footage-acquisition-execution.md](./footage-acquisition-execution.md).
> **Purpose:** Define the tangible, measurable things the code must deliver at each stage — what passes, what fails, and what data each test needs.

---

## How to read this

Each stage lists: **Deliverable** (the artifact the code must output) → **KPI** (the measurable target) → **Test** (how we prove it). Every test is tagged with the data it needs:

- **🟢 Tier A — Pure logic/math/geometry.** Deterministic unit tests on synthetic fixtures (numbers, poses, polygons, grids). **No images at all.** Buildable today.
- **🟡 Tier B — Synthetic scene / sim / fake depth.** Needs a procedural 3D scene, a fake depth map, or a flight simulator (renders synthetic frames). **No real photos.**
- **🔴 Tier C — Real imagery + human labels.** Verifies real-world fidelity or human taste; synthetic data would defeat the test.

**Coverage:** ~25 of 31 tests (≈80%) need no real photos. Those prove the pipeline's *logic, geometry, and orchestration* are correct. The 6 Tier-C tests are the only ones that prove the footage is actually *good-looking* — only real imagery can settle that.

Thresholds below are **starting targets** — tune as we learn.

---

## Stage 1 — Target Selection & Confirmation

| # | Deliverable | KPI | Test | Tier |
|---|---|---|---|---|
| 1 | GPS pin → local NED/ENU frame | Conversion error < 0.5 m vs ground truth | Feed known (lat,lon) pairs, assert metric coords match surveyed points | 🟢 A |
| 2 | Reproject detection → GPS | Centroid GPS error < 3 m | Synthetic camera pose + known 3D point → pixel → GPS round-trip | 🟢 A |
| 3 | User-confirmed AOI (geofenced) | Confirmed mask IoU ≥ 0.7 with true footprint | Polygon IoU against ground-truth footprint | 🟢 A |
| 4 | Candidate target detections | Recall ≥ 90% of visible buildings; ≤ 1 false positive/scene | Run detector on labeled aerial set, compute recall/precision | 🔴 C |

**Gate:** a valid, geofenced AOI exists and is locked.

---

## Stage 2 — Survey, Geometry & Obstacle Map

| # | Deliverable | KPI | Test | Tier |
|---|---|---|---|---|
| 5 | Orbit radius `r` | Building fits frame with margin, no clipping | Given `H`, `VFOV`, assert `r=(H/2+margin)/tan(VFOV/2)` frames building | 🟢 A |
| 6 | Height estimate `H` | Error ≤ 10% of true height | Estimate from a **fake** depth map / synthetic DSM | 🟡 B |
| 7 | Obstacle map (OctoMap / 2.5D) | Recall ≥ 95% of obstacles in orbit annulus; 0 missed wires/poles on path | Compare occupancy grid to labeled **synthetic** point cloud | 🟡 B |
| 8 | No-fly volumes (trees/wires/people) | Segmentation IoU ≥ 0.6 on hazard classes | Eval against labeled top-down imagery | 🔴 C |

**Gate:** `r` chosen, obstacle map covers the planned orbit, no unmapped volume on the path.

---

## Stage 3 — 360° Mapping (DFS / NBV) & Close-Ups

| # | Deliverable | KPI | Test | Tier |
|---|---|---|---|---|
| 9 | Surface coverage metric | Coverage ≥ 90% of AOI surface | Compute observed fraction over a **synthetic** known surface | 🟢 A |
| 10 | Occlusion / frontier detection | Detects ≥ 95% of occluded faces | Procedural voxel scene with known blocked walls; assert each flagged | 🟡 B |
| 11 | Adaptive close-ups | ≥1 line-of-sight close-up per occluded face at target GSD | Synthetic frontier → assert a LoS close-up viewpoint is generated | 🟡 B |
| 12 | NBV efficiency | Viewpoints ≤ 1.5× theoretical minimum; within battery budget | Sim run, count viewpoints vs lawnmower baseline | 🟡 B |
| 13 | 3D model fidelity | Reprojection error < 2 px | Real SfM residuals on captured imagery | 🔴 C |

**Gate:** coverage ≥ target with no unresolved reachable occlusion, within flight budget.

---

## Stage 4 — Interest Field & Value Assignment

| # | Deliverable | KPI | Test | Tier |
|---|---|---|---|---|
| 14 | `focal()` weighting | Peaks at configured optimal distance, monotone falloff both sides | Sweep distance, assert curve shape | 🟢 A |
| 15 | `value(v)` viewpoint score | Matches hand-computed score on fixtures | Synthetic hotspots/framing/focal → assert expected value | 🟢 A |
| 16 | 3D interest-density projection | Hotspot localization error < 1 m | **Fake** heatmap + known pose → assert projects to correct surface point | 🟢 A |
| 17 | Per-image interest heatmaps | Correlation ≥ 0.6 with human labels | Compare heatmap to human-annotated saliency set | 🔴 C |
| 18 | Viewpoint value field | Top-10 overlap ≥ 70% with expert-chosen viewpoints | Compare value-field top-K to pilot's picks | 🔴 C |

**Gate:** a value field exists, peaks are spatially sane, and correlate with human judgment.

---

## Stage 5 — Path Optimization & Variety Shots

| # | Deliverable | KPI | Test | Tier |
|---|---|---|---|---|
| 19 | Selected viewpoints | All inside geofence + collision-free | Assert every viewpoint passes geofence + OctoMap clearance | 🟢 A |
| 20 | Visit order (TSP) | Path length ≤ 1.2× optimal | Compare OR-Tools result to brute-force optimum on small sets | 🟢 A |
| 21 | Smooth trajectory | Within vmax/amax/jerk; min clearance ≥ safety margin everywhere | Simulate, assert kinodynamic limits + clearance never violated | 🟢 A |
| 22 | Shot variety | ≥ N distinct grammars; no two adjacent subjects share one | Assert diversity constraint on emitted shot list | 🟢 A |
| 23 | Executable mission | Loads & flies in sim without errors | Load into MAVSDK/DJI sim, assert clean execution | 🟡 B |

**Gate:** a collision-free, feasible, variety-covering mission flies end-to-end in sim.

---

## End-to-End Tests

| # | Test | Criteria | Tier |
|---|---|---|---|
| 24 | **E2E happy path** | One target, sim, daylight → Curated Footage Set with ≥90% coverage, ≥3 shot types, 0 collisions, within battery | 🟡 B |
| 25 | **E2E occlusion** | Tree-blocked face → final set contains a resolving close-up of that face | 🟡 B |
| 26 | **E2E budget pressure** | Reduced battery → prioritizes highest-value shots, lands safely, no crash | 🟡 B |
| 27 | **E2E artifact contract** | Curated Footage Set validates against schema (clips + poses + shot types + interest tags); consumable by stubbed processing pipeline | 🟢 A |
| 28 | **Detection accuracy (real)** | Building/hazard detection meets recall/precision on real aerial set | 🔴 C |
| 29 | **Interest vs human (real)** | Heatmap + viewpoint picks correlate with human/expert labels | 🔴 C |
| 30 | **Reconstruction fidelity (real)** | SfM reprojection + close-up GSD meet targets on real capture | 🔴 C |
| 31 | **Footage quality (real)** | Final clips judged acceptable by a human reviewer | 🔴 C |

---

## Summary

| Tier | Count | Needs | Buildable when |
|---|---|---|---|
| 🟢 A — pure logic/math | ~14 | Synthetic fixtures only | Now |
| 🟡 B — synthetic scene / sim | ~11 | Procedural 3D / fake depth / flight sim | Once sim harness exists |
| 🔴 C — real imagery + humans | ~6 | Real photos + human/expert labels | Needs field data |

**~80% of tests need no real photos.** They guarantee correctness of logic, geometry, and orchestration — not that the footage looks good. The Tier-C tests are the only proof of footage *quality*, and require real-world data.
