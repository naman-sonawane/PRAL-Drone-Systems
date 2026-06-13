# Footage Acquisition — Pipeline Flowchart

> **Status:** Draft v0.1 · **Scope:** Pipeline 1 only. Diagram companion to [footage-acquisition-pitch-artifacts.md](./footage-acquisition-pitch-artifacts.md).
> **Purpose:** The 5-stage acquisition pipeline as Mermaid diagrams — the high-level flow, the footage-vs-data tracks, and the pitch arc.

---

## 1. High-level pipeline flow

Red = the drone is flying. Blue = pure compute (no flight). Yellow = footage artifact.

```mermaid
flowchart TD
    pin([User pin / boundary]):::data

    pin --> S1
    S1 --> S2 --> S3 --> S4 --> S5
    S5 --> CFS[["Curated Footage Set
(hand-off to processing)"]]:::footage

    S1["<b>Stage 1 — Select &amp; Confirm</b>
fly: brief ascent
out: AOI polygon"]:::fly
    S2["<b>Stage 2 — Survey, Geometry, Obstacles</b>
fly: nadir grid
out: H, r, OctoMap"]:::fly
    S3["<b>Stage 3 — 360 Mapping (NBV / DFS)</b>
fly: orbit + close-ups
out: posed images + 3D model"]:::fly
    S4["<b>Stage 4 — Interest Field &amp; Value</b>
NO FLIGHT
out: heatmaps + value field"]:::compute
    S5["<b>Stage 5 — Path Opt &amp; Variety Shots</b>
fly: final mission
out: beauty clips"]:::fly

    classDef fly fill:#ffe2e2,stroke:#d33,stroke-width:2px,color:#000;
    classDef compute fill:#e2ecff,stroke:#36c,stroke-width:2px,color:#000;
    classDef footage fill:#fff7d6,stroke:#caa400,stroke-width:2px,color:#000;
    classDef data fill:#ffffff,stroke:#999,stroke-dasharray:3 3,color:#000;
```

---

## 2. Footage vs. data through the pipeline

Top track = pixels (footage). Bottom track = derived data. Note how footage is *spent* in S2/S4 and only *produced for keeps* in S5.

```mermaid
flowchart LR
    subgraph S1g["S1 · Select"]
        direction TB
        f1[/"nadir still
+ priors"/]:::footage --> d1[["AOI polygon"]]:::data
    end
    subgraph S2g["S2 · Survey"]
        direction TB
        f2[/"nadir grid stills"/]:::footage --> d2[["H, r, DSM,
OctoMap, no-fly"]]:::data
    end
    subgraph S3g["S3 · 360 Map"]
        direction TB
        f3[/"orbit stream
+ close-ups"/]:::footage --> d3[["posed images,
3D model, coverage%"]]:::data
    end
    subgraph S4g["S4 · Interest"]
        direction TB
        f4[/"interest
heatmaps"/]:::footage --> d4[["3D hotspots,
value field"]]:::data
    end
    subgraph S5g["S5 · Path + Shots"]
        direction TB
        f5[/"BEAUTY CLIPS"/]:::beauty --> d5[["mission +
shot/interest tags"]]:::data
    end

    S1g --> S2g --> S3g --> S4g --> S5g
    S5g --> CFS[["Curated Footage Set"]]:::beauty

    classDef footage fill:#fff7d6,stroke:#caa400,color:#000;
    classDef beauty fill:#ffd6a5,stroke:#d97700,stroke-width:2px,color:#000;
    classDef data fill:#ffffff,stroke:#999,stroke-dasharray:3 3,color:#000;
```

---

## 3. The pitch arc — what we show, stage by stage

```mermaid
flowchart LR
    P1["<b>S1 · Lock-on</b>
pin → AOI mask snaps on
<i>overlay footage</i>"]
    P2["<b>S2 · Geometry</b>
3D obstacle map + orbit ring + formula
<i>3D viz / graph</i>"]
    P3["<b>S3 · Exploration</b>
rotating 3D model + coverage heatmap
+ DFS dive-in
<i>3D viz + overlay</i>"]
    P4["<b>S4 · Taste</b>
interest heatmap + value-field cloud
<i>heatmap + scalar field</i>"]
    P5["<b>S5 · Payoff</b>
trajectory through field → beauty reel
<i>graph → footage</i>"]

    P1 --> P2 --> P3 --> P4 --> P5

    classDef arc fill:#f0f0ff,stroke:#558,color:#000;
    class P1,P2,P3,P4,P5 arc;
```

**Each slide reveals one box of the pipeline; the only pretty footage is the last beat — which lands harder because the audience has seen everything that earned it.**
