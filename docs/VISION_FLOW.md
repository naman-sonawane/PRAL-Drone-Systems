# PRAL - Vision Flowchart

A simple view of how PRAL goes from "film this" to finished media.
See [VISION.md](./VISION.md) for the full write-up.

---

## The Big Picture

```mermaid
flowchart LR
    User([User picks a target]) --> P1
    P1[Pipeline 1<br/>Footage Acquisition] -->|Curated Footage Set| P2[Pipeline 2<br/>Media Processing]
    P2 --> Done([User picks a finished video])
```

---

## Pipeline 1 - Footage Acquisition

The drone figures out what's worth filming, then films it well.

```mermaid
flowchart TD
    A[1. Select target<br/>building or location] --> B[2. Fly high<br/>survey the whole area]
    B --> C[3. Plan sampling paths<br/>for broad coverage]
    C --> D[4. Capture sample footage<br/>a little from everywhere]
    D --> E[5. Find points of interest<br/>distinctive / interesting things]
    E --> F[6. Optimize for value<br/>best subjects + best angles]
    F --> G[7. Draw final trajectory]
    G --> H[8. Capture real footage]
    H --> Out([Curated Footage Set])
```

**The idea:** each step narrows down. See everything cheap → sample broadly → find what matters → spend the battery only on the good shots.

---

## Pipeline 2 - Media Processing

The footage becomes marketing-ready media.

```mermaid
flowchart TD
    In([Curated Footage Set]) --> A[Assemble into templates<br/>reel · vertical · hero · overview]
    A --> B[Render multiple previews]
    B --> C[User picks one + light edits]
    C --> D([Export finished media])
```
