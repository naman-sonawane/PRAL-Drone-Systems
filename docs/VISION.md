# PRAL Drone System — Vision Document

> **Status:** Draft v0.1 · **Last updated:** 2026-06-13
> **One-line:** Point a drone at a building or location and it autonomously captures, curates, and edits that footage into marketing-ready media — with minimal human input.

---

## 1. The Problem

Capturing high-quality aerial footage of a property, venue, or location today requires:

- A **skilled pilot** who knows where to fly and which angles read well on camera.
- A **manual scouting pass** to figure out what's actually worth filming.
- A **video editor** to turn raw clips into something usable (a listing reel, a social cut, a hero shot).

This is slow, expensive, and inconsistent. The pilot's instincts don't transfer; the editor starts from scratch every time. For anyone who needs *volume* — real estate agencies, event venues, construction progress tracking, tourism boards — the cost per finished asset is the bottleneck.

**PRAL's bet:** the two hard parts — *deciding what to shoot* and *assembling the result* — can be automated. A human says "film this," and the system handles the rest, surfacing a few polished options to choose from.

---

## 2. Vision

A user selects a target (a building, a landmark, a plot of land). The drone takes off, figures out for itself what's worth filming and from where, captures it, and hands back a small set of edited, marketing-ready media previews. The user picks the one they like — or tweaks it — and ships it.

No pilot expertise. No manual scouting. No editor in the loop for the first draft.

---

## 3. System Overview

PRAL is two decoupled pipelines connected by a single hand-off artifact: a **curated footage set**.

```
┌─────────────────────────────────────────────┐     ┌──────────────────────────────┐
│        PIPELINE 1: FOOTAGE ACQUISITION        │     │  PIPELINE 2: MEDIA PROCESSING │
│                                               │     │                              │
│  target → survey → plan → sample → analyze →  │ ──▶ │  assemble → preview → select │
│  optimize → final trajectory → capture        │     │  → edit → export             │
│                                               │     │                              │
│              (produces raw, curated clips)    │     │   (produces finished media)  │
└─────────────────────────────────────────────┘     └──────────────────────────────┘
                          │                                        ▲
                          └────────── Curated Footage Set ─────────┘
                                      (the hand-off contract)
```

**Why two pipelines, not one?** They run on different time horizons and different hardware. Acquisition is real-time, on-drone, flight-critical, and physics-constrained. Processing is offline, server-side, iterative, and forgiving. Decoupling them means the editing layer can be re-run, re-templated, or improved without ever touching the flight stack — and the flight stack can be tested without rendering a single video.

The **Curated Footage Set** is the contract between them: a bundle of clips plus metadata (camera pose, timestamp, detected points of interest, quality scores). As long as acquisition produces a valid set, processing doesn't care how it was captured.

---

## 4. Pipeline 1 — Footage Acquisition

The goal of this pipeline is **not** to film everything. It's to spend a limited flight budget (battery, time) on the footage most likely to be valuable, and to do it autonomously. It works in two coarse-to-fine passes: a cheap survey pass to understand the scene, then an optimized production pass to capture it well.

### Stage 1 — Target Selection
The user designates what to film: a dropped pin, a drawn boundary, or an address. This defines the **area of interest (AOI)** and a safe operating boundary. *Input: human intent. Output: geofenced target.*

### Stage 2 — Survey Ascent
The drone climbs to the highest safe/allowed altitude over the AOI and captures a wide overview — effectively a top-down map of the scene. This is the cheapest way to "see everything at once" before committing to any detailed flying. *Output: overview imagery + coarse 3D/extent of the AOI.*

### Stage 3 — Coarse Trajectory Planning (Sampling)
The overview is processed to propose **sampling trajectories** — flight paths designed to grab a little footage from as many distinct vantage points as possible. The objective here is *coverage*, not beauty: maximize the diversity of what we observe so the next stage has something to reason about. *Output: a set of candidate sampling paths.*

### Stage 4 — Sample Capture
The drone flies the sampling trajectories and collects short clips across the AOI. Think of this as reconnaissance: broad, shallow, fast. *Output: sample footage tagged with camera pose.*

### Stage 5 — Scene Analysis (Points of Interest)
The sample footage is run through a detector that finds **distinctive or interesting things** — architectural features, the entrance, water, greenery, a striking facade, leading lines, contrast. Each hit becomes a **point of interest (POI)** with a location and a salience score. *Output: a scored map of POIs.*

### Stage 6 — Value Optimization
Given the POIs, an optimizer designs the *production* shot list: which subjects to feature, and from what angles. It maximizes a **footage-value objective** subject to **cinematography best practices** (good angles, framing, avoiding harsh sun, orbit/reveal/flyover shot grammar) and flight constraints (battery, no-fly zones, line of sight). This is where the system encodes "what a good pilot would do." *Output: an optimized, prioritized shot list.*

### Stage 7 — Final Trajectory Generation
The shot list is compiled into a single smooth, flyable, collision-free trajectory — the actual flight plan the drone will execute. *Output: the production flight path.*

### Stage 8 — Production Capture
The drone flies the final trajectory and captures the real footage. The result is the **Curated Footage Set** — the hand-off to Pipeline 2. *Output: raw clips + rich metadata.*

> **Design principle:** every stage narrows. Survey sees everything cheaply → sampling observes broadly → analysis finds what matters → optimization decides what's worth the battery → production captures it well. Each stage spends more effort on less area.

---

## 5. Pipeline 2 — Media Processing

This pipeline turns the curated footage set into finished media the user can actually use. It runs server-side and is fully re-runnable.

### Stage 1 — Ingest & Index
The footage set is uploaded and indexed by its metadata (POIs, shot type, quality score, timestamp). Bad clips are filtered early.

### Stage 2 — Assembly
Clips are assembled into a small number of **common, acceptable output forms** — opinionated templates such as:
- **Listing Reel** (~30–60s, paced, music-ready)
- **Social Vertical** (9:16, short, hook-first)
- **Hero Shot** (single best continuous reveal)
- **Overview Cut** (wide establishing → details)

Assembly uses the metadata to pick clips, order them, and time the cuts.

### Stage 3 — Previews
The system renders **multiple previews** — one per template, possibly several variations — so the user sees real options, not a blank timeline.

### Stage 4 — Selection & Editing
The user browses previews, picks a direction, and makes light edits (swap a clip, change music, retime, recolor). The first draft is good enough to ship; editing is refinement, not authoring.

### Stage 5 — Export
The chosen cut is exported in the target format(s) and delivered.

---

## 6. The Hand-off Contract: Curated Footage Set

The single artifact that connects the two pipelines. Defining it well is what lets the two halves evolve independently.

| Field | Description |
|---|---|
| `clips[]` | The raw video segments captured in production. |
| `clip.pose` | Camera position + orientation over time (for each clip). |
| `clip.shot_type` | orbit / reveal / flyover / hero / establishing. |
| `clip.pois[]` | Points of interest featured in the clip. |
| `clip.quality` | Stability, exposure, focus, framing scores. |
| `aoi` | The target geometry and overview map. |
| `timestamp` | Capture time (for lighting/recency). |

---

## 7. Scope for v1 (Clean Version)

To keep the first build honest, v1 is the **happy path, end to end**:

**In scope**
- Single target, single flight, daylight, good weather.
- The full coarse-to-fine acquisition flow (Stages 1–8).
- A fixed set of 3–4 output templates with multi-preview selection.
- Light, in-browser editing.

**Explicitly out of scope (for now)**
- Multi-drone or multi-flight stitching.
- Live/streaming processing during flight.
- Fully custom timeline editing.
- Adverse conditions (night, wind, rain), dynamic obstacles beyond basic avoidance.
- Regulatory automation (BVLOS, airspace authorization) — assume operator handles compliance.

---

## 8. Open Questions

1. **Where does optimization run** — on-drone (real-time, limited compute) or round-tripped to a ground station between the sampling and production passes?
2. **What exactly is "footage value"?** We need a concrete objective function (POI salience × angle quality × shot diversity × coverage?) — this is the technical heart of the system and deserves its own spec.
3. **How much flight does the survey + sampling pass cost** relative to the battery budget? If recon eats half the battery, production suffers.
4. **What does "PRAL" stand for?** Lock the name/acronym.
5. **Latency expectation** — is this "land and get media in minutes," or "results next day"?

---

## 9. Glossary

- **AOI** — Area of Interest; the geofenced target region.
- **POI** — Point of Interest; a distinctive feature worth featuring.
- **Survey pass** — the high-altitude overview capture (Stage 2).
- **Sampling pass** — broad, shallow reconnaissance footage (Stage 4).
- **Production pass** — the final, optimized capture (Stage 8).
- **Curated Footage Set** — the metadata-rich bundle handed from acquisition to processing.
