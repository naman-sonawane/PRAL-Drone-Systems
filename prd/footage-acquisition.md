# Footage Acquisition — Vision (Working Draft)

> **Status:** Outline v0.1 · **Scope:** Pipeline 1 only (acquisition).
> **Purpose:** Capture what we have today so we can make it specific, stage by stage.

---

## What this is

The footage acquisition pipeline is the half of PRAL that **flies**. A user points at a target; this pipeline autonomously decides what's worth filming, from where, and then captures it. Its only output is a bundle of good raw clips (the *Curated Footage Set*) that gets handed to the processing half later.

The whole thing is one idea repeated: **see broadly and cheaply first, then spend effort only where it pays off.** Every stage looks at more detail over less area than the one before it.

---

## The flow we have right now

```
SELECT  →  SURVEY  →  SAMPLE-PLAN  →  SAMPLE  →  ANALYZE  →  OPTIMIZE  →  FINAL-PLAN  →  CAPTURE
 target     fly high    coverage      recon     find POIs    score &      draw the      shoot the
                        paths        footage                 pick shots    flight path   real footage
```

Three phases inside the pipeline:

1. **Understand the scene** (Select → Survey → Sample-Plan → Sample → Analyze)
2. **Decide what's worth filming** (Optimize)
3. **Capture it well** (Final-Plan → Capture)

---

## The stages, as we understand them today

### 1. Select target
The user designates *what* to film — a building, a landmark, a plot. This sets the area we care about and a boundary the drone stays inside.
- **Have:** the concept (pin / boundary / address → area of interest).
- **Fuzzy:** how the user draws it, what defines the safe boundary.

### 2. Survey (fly high)
The drone climbs as high as allowed and captures a wide overview — the cheapest way to see the whole scene at once before committing to any detailed flying.
- **Have:** the intent (one high pass → overview of the area).
- **Fuzzy:** what "as high as possible" means, what the overview actually is (single image? map? rough 3D?).

### 3. Sample-plan (coverage paths)
From the overview, plan flight paths that will grab a little footage from as many different vantage points as possible. Goal here is **coverage, not beauty** — we just want to observe the area from many angles.
- **Have:** the intent (overview → candidate sampling paths).
- **Fuzzy:** how paths are generated, how "coverage" is measured.

### 4. Sample (recon footage)
Fly the sampling paths and collect short clips from around the area. Broad, shallow, fast — reconnaissance, not the final product.
- **Have:** the intent (fly paths → tagged sample clips).
- **Fuzzy:** how much to sample, how it's tagged.

### 5. Analyze (find points of interest)
Run the sample footage through a detector that finds **distinctive or interesting things** — a striking facade, the entrance, water, greenery, strong lines. Each becomes a point of interest with a location and a "how interesting" score.
- **Have:** the intent (sample footage → scored points of interest).
- **Fuzzy:** what counts as "interesting," how we score it.

### 6. Optimize (decide the shots)
Given the points of interest, decide the real shot list: which subjects to feature and from what angles. Maximize **footage value** while respecting **good-cinematography rules** (nice angles, framing, shot variety) and flight limits (battery, boundaries).
- **Have:** the intent (POIs → prioritized shot list) and the key idea that this is where "what a good pilot would do" lives.
- **Fuzzy:** the actual value function, the angle/best-practice rules. *This is the heart of the system and the thing we'll specify most carefully.*

### 7. Final-plan (draw the trajectory)
Turn the shot list into one smooth, flyable path the drone can actually execute.
- **Have:** the intent (shot list → flight path).
- **Fuzzy:** how shots become a continuous, safe trajectory.

### 8. Capture (shoot for real)
Fly the final path and capture the actual footage. The result is the Curated Footage Set — the hand-off out of this pipeline.
- **Have:** the intent (fly path → raw clips + metadata).
- **Fuzzy:** what metadata travels with each clip.

---

## What leaves this pipeline

A **Curated Footage Set**: the raw clips plus enough metadata (where the camera was, what each clip features, a rough quality score) that the processing half can assemble media without re-deriving anything. This is the only thing acquisition owes the rest of the system.

---

## What we're confident about vs. what's open

**Confident (the skeleton):**
- The two-pass, coarse-to-fine shape (survey/sample to understand, then optimize and capture).
- The 8 stages and their order.
- That the value/angle optimization (Stage 6) is the core differentiator.
- That the pipeline's only output is the Curated Footage Set.

**Still open (where we get specific next):**
- **Stage 6's "footage value"** — the actual objective. (Top priority.)
- What each stage's input/output *artifact* concretely looks like.
- Platform & compute assumptions (sim vs. real drone, on-board vs. ground station) — deliberately deferred.
- How much flight budget the understand-phase is allowed to spend before capture.

---

## Where we go from here

We tighten this one stage at a time, turning each "fuzzy" note above into a concrete input → behavior → output spec — starting with **Stage 6 (Optimize)**, since everything upstream exists to feed it and everything downstream exists to execute its decisions.
