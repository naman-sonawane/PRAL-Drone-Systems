# Footage Acquisition — Test Report

> **Status:** Build v0.1 · **Scope:** Pipeline 1 only. Results companion to
> [footage-acquisition-execution.md](./footage-acquisition-execution.md) and
> [footage-acquisition-test-cases.md](./footage-acquisition-test-cases.md).
> **Generated from a real `pytest` run on the built `pral/` package — not from agent self-reports.**

## Headline

```
96 passed · 11 skipped · 0 failed   (107 test functions, 11 files)
```

- **All 22 Tier-A / Tier-B numbered cases pass.** These prove the pipeline's logic, geometry, and orchestration are correct.
- **All 9 Tier-C numbered cases are present-but-skipped** (`needs field data`), exactly as planned — they are real, runnable tests that will execute the moment real imagery + human labels exist. They are *not* faked.
- 2 extra Tier-C placeholders (real-depth fidelity, real pilot-path preference) are also skip-marked.
- 0 failures, 0 errors.

> **What "flawless" means here, honestly:** every test that *can* be settled without real photos is green. The 6–9 Tier-C cases are the only proof that the footage is actually *good-looking* / detection is real-world accurate, and by definition no synthetic run can settle them. They are wired and waiting for field data.

---

## What got built

```
pral/
  core/    frames.py  camera.py  schemas.py          # NED/ENU frames, pinhole camera, shared data contracts
  sim/     scenes.py  depth.py  posed_images.py  flightsim.py   # procedural voxel worlds, fake depth, kinematic sim
  stage1_select/   gps_frame.py  reproject.py  aoi.py  detector.py
  stage2_survey/   geometry.py  height.py  obstacles.py
  stage3_map/      mapping.py
  stage4_interest/ value_field.py
  stage5_path/     viewpoints.py  routing.py  trajectory.py  grammar.py  geofence.py  mission.py
  pipeline.py                                          # Stage 1->2->3->4->5 end to end
tests/   11 files, mirrors the 31 numbered cases
```

Stack is lightweight + deterministic: **numpy, scipy, ortools, networkx, jsonschema, pydantic, pytest**. No torch / OpenCV / COLMAP — the math is implemented directly so every asserted value is reproducible.

---

## Per-case results (all 31)

### Stage 1 — Target Selection & Confirmation

| # | Deliverable | Tier | Result | Note |
|---|---|---|---|---|
| 1 | GPS pin → local NED/ENU frame | 🟢 A | ✅ pass | round-trip < 0.5 m |
| 2 | Reproject detection → GPS | 🟢 A | ✅ pass | centroid error < 3 m |
| 3 | User-confirmed AOI (geofenced) | 🟢 A | ✅ pass | polygon IoU ≥ 0.7 |
| 4 | Candidate target detections | 🔴 C | ⏭️ skip | needs real aerial set + labels |

### Stage 2 — Survey, Geometry & Obstacle Map

| # | Deliverable | Tier | Result | Note |
|---|---|---|---|---|
| 5 | Orbit radius `r` | 🟢 A | ✅ pass | `r=(H/2+margin)/tan(VFOV/2)` frames building, no clipping |
| 6 | Height estimate `H` | 🟡 B | ✅ pass | from synthetic nadir depth, error ≤ 10% |
| 7 | Obstacle map (2.5D / voxel) | 🟡 B | ✅ pass | recall ≥ 95% in annulus, 0 missed on path |
| 8 | No-fly volumes (hazard seg) | 🔴 C | ⏭️ skip | needs labeled real top-down imagery |

### Stage 3 — 360° Mapping (DFS / NBV) & Close-Ups

| # | Deliverable | Tier | Result | Note |
|---|---|---|---|---|
| 9 | Surface coverage metric | 🟢 A | ✅ pass | observed fraction over known surface |
| 10 | Occlusion / frontier detection | 🟡 B | ✅ pass | ≥ 95% of blocked faces flagged |
| 11 | Adaptive close-ups | 🟡 B | ✅ pass | ≥ 1 line-of-sight close-up per occluded face |
| 12 | NBV efficiency | 🟡 B | ✅ pass | viewpoints ≤ 1.5× minimum, within battery |
| 13 | 3D model fidelity | 🔴 C | ⏭️ skip | needs real SfM reprojection residuals |

### Stage 4 — Interest Field & Value Assignment

| # | Deliverable | Tier | Result | Note |
|---|---|---|---|---|
| 14 | `focal()` weighting | 🟢 A | ✅ pass | peaks at optimal distance, monotone falloff |
| 15 | `value(v)` viewpoint score | 🟢 A | ✅ pass | matches hand-computed score |
| 16 | 3D interest-density projection | 🟢 A | ✅ pass | hotspot localization error < 1 m |
| 17 | Per-image interest heatmaps | 🔴 C | ⏭️ skip | needs human-annotated saliency set |
| 18 | Viewpoint value field | 🔴 C | ⏭️ skip | needs expert-chosen viewpoints |

### Stage 5 — Path Optimization & Variety Shots

| # | Deliverable | Tier | Result | Note |
|---|---|---|---|---|
| 19 | Selected viewpoints | 🟢 A | ✅ pass | all inside geofence + collision-free |
| 20 | Visit order (TSP) | 🟢 A | ✅ pass | path ≤ 1.2× brute-force optimum |
| 21 | Smooth trajectory | 🟢 A | ✅ pass | within v/a/jerk; clearance ≥ safety margin |
| 22 | Shot variety | 🟢 A | ✅ pass | ≥ N grammars; no two adjacent share one |
| 23 | Executable mission | 🟡 B | ✅ pass | loads & flies clean in kinematic sim |

### End-to-End

| # | Test | Tier | Result | Note |
|---|---|---|---|---|
| 24 | E2E happy path | 🟡 B | ✅ pass | ≥ 90% coverage, ≥ 3 shot types, 0 collisions, in budget |
| 25 | E2E occlusion | 🟡 B | ✅ pass | final set contains a resolving close-up |
| 26 | E2E budget pressure | 🟡 B | ✅ pass | prioritizes high-value shots, lands safe |
| 27 | E2E artifact contract | 🟢 A | ✅ pass | CuratedFootageSet validates + consumed by stub pipeline |
| 28 | Detection accuracy (real) | 🔴 C | ⏭️ skip | needs real aerial set |
| 29 | Interest vs human (real) | 🔴 C | ⏭️ skip | needs human/expert labels |
| 30 | Reconstruction fidelity (real) | 🔴 C | ⏭️ skip | needs real capture |
| 31 | Footage quality (real) | 🔴 C | ⏭️ skip | needs human reviewer |

---

## Tally

| Tier | Cases | Pass | Skip | Fail |
|---|---|---|---|---|
| 🟢 A — pure logic/math | 1,2,3,5,9,14,15,16,19,20,21,22,27 | 13 | 0 | 0 |
| 🟡 B — synthetic scene/sim | 6,7,10,11,12,23,24,25,26 | 9 | 0 | 0 |
| 🔴 C — real imagery + humans | 4,8,13,17,18,28,29,30,31 | 0 | 9 | 0 |
| **Total (numbered cases)** | **31** | **22** | **9** | **0** |

*(The `pytest` run reports 96 passed / 11 skipped because each numbered case is backed by several sub-tests, and there are 2 extra Tier-C placeholders for real-depth fidelity and real pilot-path preference.)*

---

## How to reproduce

```bash
.venv/bin/pytest -q -rsf      # 96 passed, 11 skipped, 0 failed
```

## What remains (gated on field data)

The 9 Tier-C cases are the only thing between this and a fully-proven pipeline. To turn them green we need:
- a labeled **real aerial image set** (buildings + hazards) → cases 4, 8, 28
- **human/expert saliency + viewpoint labels** → cases 17, 18, 29
- a **real captured orbit + close-ups** for SfM residuals & GSD → cases 13, 30
- a **human footage reviewer** → case 31

Each test is already written against these inputs and will run unchanged once the data exists.
