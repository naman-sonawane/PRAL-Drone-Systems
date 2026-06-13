# Video Post-Processing Pipeline — Execution Spec

> **Status:** Draft v0.2 · **Scope:** Pipeline 2 only (media processing). Footage acquisition is out of scope here.
> **Purpose:** Define exactly how each stage works — algorithm, libraries, parameters, concrete "if executed" sketch — so this document alone is sufficient to implement the full system.
> **Companion:** [`prd/footage-acquisition-execution.md`](./footage-acquisition-execution.md) — Pipeline 1 execution spec.

This spec describes the 8-stage flow that turns raw continuous drone footage into polished, style-specific highlight videos:

```
1. INGEST       2. SEGMENT      3. SCORE        4. RANK
   read meta,      sliding-window  sharpness +     normalize,
   downsample      candidate clips exposure +      hard filter,
   for analysis                    smoothness +    promising_score
                                   composition

5. DIVERSITY    6. STYLE        7. SELECT       8. ASSEMBLE
   fingerprint,    templates —     filter by       moviepy render,
   deduplicate     10 configs      motion type,    color grade,
   curated pool                    order + greedily transitions,
                                   fill duration   export mp4
```

A note that shapes everything below: **stages 3 and 4 do the editorial judgment a human editor would do manually; the rest exist to feed them good inputs and act on their output.** Getting the scoring right is the technical heart of this pipeline, exactly as Stage 6 (Optimize) is the heart of Pipeline 1.

---

## Project Structure

```
video_pipeline/
├── main.py              # CLI entry point — orchestrates all stages
├── config.py            # All tunable constants and thresholds
├── ingest.py            # Stage 1: read metadata, prepare analysis frames
├── segmenter.py         # Stage 2: sliding-window clip segmentation
├── scorer.py            # Stage 3: per-clip quality scoring (4 signals)
├── ranker.py            # Stage 4: normalize, hard-filter, compute promising_score
├── diversity.py         # Stage 5: visual fingerprinting and deduplication
├── styles.py            # Stage 6: 10 style template definitions
├── selector.py          # Stage 7: style-aware clip selection
├── assembler.py         # Stage 8: moviepy rendering and export
├── requirements.txt
├── README.md
└── tests/
    ├── test_scorer.py
    ├── test_ranker.py
    └── test_diversity.py
```

---

## Stage 1 — Ingest & Normalize

**What it does:** Reads the raw video file, extracts technical metadata, and prepares a downscaled analysis copy of frames at regular intervals. The original full-resolution footage is referenced by time range only — never loaded in full — until Stage 8 when specific clips are actually rendered.

### Algorithm / transform

- **Metadata extraction:** Use `ffprobe` (via `ffmpeg-python` or `subprocess`) to read: duration, resolution, frame rate, codec, creation timestamp. Fall back to OpenCV's `VideoCapture.get()` if ffprobe is unavailable. Validate that the file is readable and at least `MIN_VIDEO_DURATION` (default 10s).
- **Frame sampling for analysis:** Extract one frame per second (configurable via `FRAME_SAMPLE_RATE`) using `cv2.VideoCapture`. Downscale each frame to `ANALYSIS_RESOLUTION` (default `640×360`) using `cv2.resize` with `INTER_AREA` (best quality for downscaling). Store as NumPy arrays indexed by timestamp. This is the only in-memory representation during stages 2–7; full-resolution frames are never loaded during analysis.
- **Output artifact:** An `IngestedVideo` dataclass containing: file path, metadata dict, list of `(timestamp_seconds, frame_ndarray)` tuples at analysis resolution.

### APIs & libraries
- `ffmpeg-python` for ffprobe metadata; `subprocess` fallback
- `cv2.VideoCapture`, `cv2.resize(INTER_AREA)` — OpenCV

### If executed
```
input video path
   │
   ├─ ffprobe → {duration, fps, width, height, codec, created_at}
   ├─ validate: duration ≥ MIN_VIDEO_DURATION (10s), file readable
   └─ cv2.VideoCapture → sample 1 frame/sec → cv2.resize(640×360, INTER_AREA)
   ▼
IngestedVideo(path, metadata, [(t0, frame0), (t1, frame1), ...])
```

---

## Stage 2 — Segmentation

**What it does:** Slices the continuous footage timeline into overlapping candidate clips using a sliding window. There are no natural scene cuts in drone footage (no jump cuts, no camera changes), so the segmenter creates its own boundaries.

### Algorithm / transform

- **Sliding window:** Step through the video timeline from `t=0` to `t=duration`, emitting a `CandidateClip` at every step:
  - `WINDOW_SIZE = 4.0` seconds (configurable)
  - `STEP_SIZE = 1.0` second (configurable; overlap = `WINDOW_SIZE - STEP_SIZE = 3.0s`)
  - Final window: discard if remaining footage < `MIN_CLIP_DURATION` (default 2.0s).
  - Exception: styles with `bypass_duration_guards=True` (currently only `timelapse_feel`) skip this discard check, allowing sub-second effective clips after Stage 7 truncation.
- **Why overlap matters:** Without overlap, a great 3-second shot straddling two window boundaries would appear truncated in both. 3-second overlap ensures any continuous moment of `WINDOW_SIZE - STEP_SIZE` seconds is fully captured within at least one window.
- **Frame assignment:** Each clip receives the analysis frames whose timestamps fall within `[start_time, end_time]`. Clips with fewer than `MIN_FRAMES_PER_CLIP` (default 3) valid frames are discarded.
- **Output artifact:** List of `CandidateClip` dataclass instances, each with: `clip_id`, `start_time`, `end_time`, `duration`, `frames` (analysis-resolution ndarrays).

### APIs & libraries
- Pure Python + NumPy. No additional library beyond Stage 1.

### If executed
```
IngestedVideo (duration=D, frames at 1 fps)
   │
   for t in [0, STEP_SIZE, 2×STEP_SIZE, ... ]:
       end = min(t + WINDOW_SIZE, D)
       if (end - t) < MIN_CLIP_DURATION → skip (unless bypass_duration_guards)
       frames = [f for (ts, f) in analysis_frames if t ≤ ts < end]
       if len(frames) ≥ MIN_FRAMES_PER_CLIP → emit CandidateClip(id, t, end, frames)
   ▼
[CandidateClip_0, CandidateClip_1, ..., CandidateClip_N]
N ≈ (duration - WINDOW_SIZE) / STEP_SIZE
```

---

## Stage 3 — Scoring

**What it does:** Evaluates each candidate clip on four independent quality signals using computer vision. This is the editorial judgment layer — it answers "is this clip usable and interesting?" for the properties a human editor would assess visually.

Each scoring function operates on the clip's analysis frames and returns a raw score (not yet normalized). All four are computed independently and stored on the clip.

### Signal 1 — Sharpness (Laplacian variance)

**What it measures:** Focus and detail richness. A blurry or motion-blurred clip fails this regardless of other quality.

**Algorithm:**
- For each frame: convert to grayscale (`cv2.COLOR_BGR2GRAY`), apply `cv2.Laplacian(gray, cv2.CV_64F)`, compute `np.var()` of the result.
- The Laplacian is a second-derivative edge detector: sharp images have crisp edges with large responses and high variance. Blurry images have soft edges and low variance.
- Average the per-frame Laplacian variances across all valid frames. Skip `None` or zero-size frames; if fewer than `MIN_FRAMES_PER_CLIP` valid frames remain, return 0.0.

**Typical values on 640×360 frames:** < 50 = blurry/motion-blur; 50–150 = acceptable; > 150 = sharp. Recalibrate if `ANALYSIS_RESOLUTION` changes.

### Signal 2 — Exposure Quality (histogram analysis)

**What it measures:** Whether footage is well-exposed. Under/overexposed footage loses detail and looks unprofessional.

**Algorithm:**
- For each frame: convert to grayscale, compute a normalized 256-bin brightness histogram via `cv2.calcHist`, then divide by total pixel count to get fractions.
- Three zones:
  - `shadow_fraction` = sum of bins 0–`SHADOW_THRESHOLD` (default 20). Near-black / crushed.
  - `highlight_fraction` = sum of bins `HIGHLIGHT_THRESHOLD` (default 235) to 255. Near-white / blown.
  - `midtone_fraction` = 1.0 − shadow_fraction − highlight_fraction.
- Per-frame score = `midtone_fraction − SHADOW_PENALTY × shadow_fraction − HIGHLIGHT_PENALTY × highlight_fraction`. Both penalties default to 1.5 (extremes penalized more than they reduce midtones).
- Average across all valid frames.

### Signal 3 — Motion Smoothness + Type Classification (Farneback optical flow)

**What it measures (two-in-one):** Whether camera motion is smooth/controlled or shaky/erratic, and *what kind* of motion is present. Motion type becomes the clip's label, used in Stage 7 for style-based filtering.

**Algorithm — smoothness:**
- For each consecutive frame pair: convert both to grayscale, compute dense optical flow via `cv2.calcOpticalFlowFarneback(pyr_scale=0.5, levels=3, winsize=15, iterations=3, poly_n=5, poly_sigma=1.2, flags=0)`.
- Extract magnitude via `cv2.cartToPolar(flow[...,0], flow[...,1])`.
- `smoothness_transition = 1.0 / (1.0 + np.std(magnitude))`. High std (motion varies across frame) → shaky. Low std (all pixels move similarly) → smooth pan or hover.
- `mean_magnitude_transition = np.mean(magnitude)`.
- Clip smoothness = mean of per-transition smoothness values. Clip mean magnitude = mean of per-transition magnitudes.
- Edge case: fewer than 2 frames → return (0.0, "unknown"). Flow computation error on a pair → skip that pair.

**Algorithm — motion type classification:**
- `clip_mean_magnitude < STATIC_THRESHOLD` (default 1.5 px/frame) → `"static"`
- `STATIC_THRESHOLD ≤ clip_mean_magnitude < PAN_THRESHOLD` (default 8.0 px/frame) → `"slow_pan"`
- `clip_mean_magnitude ≥ PAN_THRESHOLD` → `"fast_flythrough"`

### Signal 4 — Composition (edge density + horizon detection)

**What it measures:** Whether structured, interesting visual content is in frame — as opposed to empty sky, blank ground, or a featureless expanse.

> **Note — upgrade path:** This is a deliberately simplified proxy for subject detection. The correct long-term implementation uses a YOLO model fine-tuned on drone architectural imagery, scoring by whether the target building is clearly visible and well-framed. The edge-density approach used here captures the right intuition (buildings have many edges; sky has almost none) without requiring a trained model. Mark the upgrade path explicitly in the code.

**Algorithm:**
- For each frame: convert to grayscale, apply `cv2.GaussianBlur` (kernel `5×5`), apply `cv2.Canny(low=CANNY_LOW_THRESHOLD, high=CANNY_HIGH_THRESHOLD)`.
- `edge_density` = count of edge pixels / total pixels.
- **Horizon penalty:** in the vertical zone centered on `HORIZON_ZONE_CENTER` (default 0.5 = vertical midpoint) spanning `HORIZON_ZONE_HEIGHT` (default 30% of height), apply `cv2.HoughLinesP`. If a roughly horizontal line (angle < 10°) spans > `HORIZON_LINE_FRACTION` (default 40%) of frame width, apply `HORIZON_PENALTY_MULTIPLIER` (default 0.7) to the edge density score. Rationale: a clear bare horizon is technically high-edge but cinematically uninteresting for a building showcase.
- Average adjusted edge density across all valid frames.

### Output artifact
Each `CandidateClip` gains: `sharpness_raw`, `exposure_raw`, `smoothness_raw`, `composition_raw`, `motion_type` (`"static"`, `"slow_pan"`, `"fast_flythrough"`, or `"unknown"`).

### APIs & libraries
- `cv2.Laplacian`, `cv2.calcHist`, `cv2.calcOpticalFlowFarneback`, `cv2.cartToPolar`, `cv2.Canny`, `cv2.GaussianBlur`, `cv2.HoughLinesP` — all OpenCV
- `numpy` for variance, mean, array operations

### If executed
```
CandidateClip (frames: [f0, f1, ..., fn])
   │
   ├─ sharpness: Laplacian(gray(fi)) → var → mean over frames
   ├─ exposure:  calcHist(gray(fi)) → shadow/highlight/midtone fractions → score → mean
   ├─ smoothness: Farneback(fi, fi+1) → cartToPolar → std → 1/(1+std) → mean
   │              + mean(magnitude) → motion_type classification
   └─ composition: GaussianBlur → Canny → edge_density
                   + HoughLinesP → horizon_penalty → adjusted → mean
   ▼
CandidateClip + {sharpness_raw, exposure_raw, smoothness_raw, composition_raw, motion_type}
```

---

## Stage 4 — Ranking

**What it does:** Normalizes raw scores to a common scale, applies hard quality filters, and combines survivors into a single `promising_score` ranking.

### Algorithm / transform

**Step 1 — Hard filters (applied before normalization):**
These are absolute minimum bars. Failing either filter means the clip is discarded entirely — it does not proceed to normalization or scoring. A blurry or shaky clip is not redeemable by good exposure or composition.
- `sharpness_raw < MIN_SHARPNESS` (default 50.0) → discard
- `smoothness_raw < MIN_SMOOTHNESS` (default 0.6) → discard

**Step 2 — Normalization across survivors:**
For each of the four signals:
```
score_norm = (score_raw - min_raw) / (max_raw - min_raw + ε)     ε = 1e-6
```
Maps each signal to [0, 1] relative to the surviving batch. If all surviving clips have the same raw score for a signal (max == min), all get 0.5.

**Step 3 — Weighted combination:**
```
promising_score = (
    WEIGHT_SHARPNESS   × sharpness_norm   +   # default 0.30
    WEIGHT_SMOOTHNESS  × smoothness_norm  +   # default 0.30
    WEIGHT_COMPOSITION × composition_norm +   # default 0.25
    WEIGHT_EXPOSURE    × exposure_norm        # default 0.15
)
```
All weights configurable in `config.py`; validated to sum to 1.0 at startup.

**Step 4 — Sort:** Sort surviving clips descending by `promising_score`.

**Console output (important for demo):** Total clips → survived hard filter → table of top 10 with individual signal values and motion type.

### APIs & libraries
- Pure Python + NumPy.

### If executed
```
[CandidateClip with raw scores]
   │
   ├─ hard filter: discard sharpness_raw < 50.0 OR smoothness_raw < 0.6
   ├─ normalize each signal across survivors: (x - min) / (max - min + ε)
   └─ promising_score = weighted sum
   ▼
ranked list of surviving CandidateClips, descending by promising_score
```

---

## Stage 5 — Diversity Filtering

**What it does:** Prevents the curated pool from being dominated by near-duplicate clips (e.g., 10 consecutive windows all showing the same slow pan from the same angle).

### Algorithm / transform

**Fingerprinting** (computed for each clip, using its middle frame):
- **Color histogram:** convert middle frame to HSV (`cv2.COLOR_BGR2HSV`), compute 3D histogram (`cv2.calcHist`, bins=[8, 8, 8] across H, S, V channels), flatten and L2-normalize. Captures overall color distribution.
- **Perceptual hash:** resize middle frame to `8×8` grayscale, compute mean pixel value, produce a 64-bit integer where each bit = 1 if the corresponding pixel is above mean. Simple aHash, fast to compare.

**Greedy deduplication** (iterate ranked list, highest `promising_score` first):
- For each candidate, compare its fingerprint against every clip already in `curated_pool`:
  - Color similarity: `cv2.compareHist(a.color_hist, b.color_hist, cv2.HISTCMP_CORREL) > COLOR_SIMILARITY_THRESHOLD` (default 0.92)
  - Hash distance: `bin(a.phash ^ b.phash).count('1') < PHASH_DISTANCE_THRESHOLD` (default 8)
  - **Both** conditions must hold to be considered a near-duplicate.
- If not a near-duplicate of anything in the pool → add to pool.
- Stop when `curated_pool` reaches `MAX_POOL_SIZE` (default 40) or list is exhausted.

**Console output:** clips evaluated, duplicates removed, final pool size.

### APIs & libraries
- `cv2.cvtColor`, `cv2.calcHist`, `cv2.compareHist` — OpenCV
- Pure Python for perceptual hash and Hamming distance.

### If executed
```
ranked CandidateClips (best → worst promising_score)
   │
   for each clip in order:
       fingerprint → color_hist (HSV 8³) + phash (64-bit)
       for each existing pool clip:
           if correl > 0.92 AND hamming < 8 → skip (near-duplicate)
       else → add to curated_pool
       stop at MAX_POOL_SIZE = 40
   ▼
curated_pool: up to 40 diverse, high-quality CandidateClips
```

---

## Stage 6 — Style Templates

**What it does:** Defines 10 "recipes" for turning the curated pool into different finished videos. Each `StyleConfig` dataclass specifies all parameters needed for stages 7 and 8.

### `StyleConfig` fields

| Field | Type | Description |
|---|---|---|
| `name` | str | Registry key. |
| `preferred_motion_types` | List[str] | Motion types to prefer in clip selection. |
| `clip_duration_min` | float | Minimum effective clip length (seconds). |
| `clip_duration_max` | float | Maximum effective clip length; longer clips are truncated. |
| `target_total_duration` | float | Target output duration (0 for `hero_shot_mode`). |
| `ordering_strategy` | str | How to order selected clips. |
| `transition_type` | str | `"crossfade"`, `"hard_cut"`, or `"none"`. |
| `transition_duration` | float | Seconds of overlap for crossfades (0 for hard cuts). |
| `color_grade` | Dict[str, float] | `brightness`, `contrast`, `saturation`, `warmth`. |
| `output_suffix` | str | Filename suffix for the rendered mp4. |
| `output_aspect_ratio` | str | `"16:9"` (default) or `"9:16"` (social_vertical). |
| `hero_shot_mode` | bool | If True, select exactly 1 clip (the highest-scored). |
| `bypass_duration_guards` | bool | If True, ignore `MIN_CLIP_DURATION` in Stage 7. |
| `slowmo_top_n` | int | Apply 0.5× slowdown to the top-N clips (cinematic stretch goal). |
| `letterbox` | bool | Add 2.35:1 black bars (cinematic stretch goal). |
| `music_tempo_preference` | Optional[str] | `"fast"`, `"slow"`, or `None`. |
| `score_weight_overrides` | Optional[Dict[str, float]] | Per-style ranking weights for Stage 7 ordering. |

### Ordering strategies

- `"best_first"` — sort descending by style score; best clip leads (establishing shot).
- `"build_to_climax"` — ascending order for the first 80% of clips, highest-scored clip placed last. Creates a ramp-up with a strong finish.
- `"static_first"` — static clips sorted by score first, then all remaining motion types sorted by score. Used by `overview` to open with establishing wide shots.
- `"none"` — no reordering; used only by `hero_shot_mode` (single clip, ordering irrelevant).

### Special cases

**`hero_shot`** — `hero_shot_mode=True`: Stage 7 ignores all duration filters and ordering; it simply returns the single clip with the highest `promising_score`. The `transition_type="none"` means Stage 8 renders one clip with no joins.

**`social_vertical`** — `output_aspect_ratio="9:16"`: Stage 8 crops the full-resolution 16:9 frame to a center-vertical 9:16 strip before resizing. Crop: from `x = (width - height × 9/16) // 2` to `x + height × 9/16`, full height. Output resolution: 1080 × 1920.

**`timelapse_feel`** — `bypass_duration_guards=True` and `clip_duration_max=1.0`: Stage 7 truncates each 4-second segmenter clip to 1 second by adjusting `end_time = start_time + clip_duration_max`. The `bypass_duration_guards` flag suppresses the check that would reject styles where `clip_duration_max < MIN_CLIP_DURATION`.

### The 10 style configs

---

#### `real_estate`
```
preferred_motion_types:  ["static", "slow_pan"]
clip_duration_min:        4.0s
clip_duration_max:        8.0s
target_total_duration:   75.0s
ordering_strategy:        "best_first"
transition_type:          "crossfade"
transition_duration:      1.0s
color_grade:              brightness=1.08, contrast=1.00, saturation=1.05, warmth=+0.06
output_aspect_ratio:      "16:9"
```
Calm pacing, warm tones, crossfades — signals "inviting property." Best-composed shot leads as establishing shot, as professional listing videos open.

---

#### `dynamic`
```
preferred_motion_types:  ["fast_flythrough", "slow_pan"]
clip_duration_min:        1.0s
clip_duration_max:        3.0s
target_total_duration:   38.0s
ordering_strategy:        "build_to_climax"
transition_type:          "hard_cut"
transition_duration:      0.0s
color_grade:              brightness=1.00, contrast=1.15, saturation=1.25, warmth=+0.00
output_aspect_ratio:      "16:9"
music_tempo_preference:   "fast"
```
Energy, pace, decisive cuts. Saturated contrast pops on screens. Beat-synced cuts are a **stretch goal**: if music is provided and `librosa` is available, snap cut points to beat timestamps from `librosa.beat.beat_track()`.

---

#### `cinematic`
```
preferred_motion_types:  ["slow_pan", "static", "fast_flythrough"]   # no preference, best wins
clip_duration_min:        3.0s
clip_duration_max:       10.0s
target_total_duration:   60.0s
ordering_strategy:        "best_first"
transition_type:          "crossfade"
transition_duration:      1.5s
color_grade:              brightness=0.95, contrast=1.10, saturation=0.85, warmth=-0.03
output_aspect_ratio:      "16:9"
slowmo_top_n:             2       # stretch goal
letterbox:                True    # stretch goal
music_tempo_preference:   "slow"
```
Moody, desaturated. The top 2 clips get 0.5× slowdown (stretch goal); letterbox adds 2.35:1 widescreen bars (stretch goal).

---

#### `social_vertical`
```
preferred_motion_types:  ["fast_flythrough", "slow_pan"]
clip_duration_min:        1.0s
clip_duration_max:        4.0s
target_total_duration:   20.0s
ordering_strategy:        "build_to_climax"
transition_type:          "hard_cut"
transition_duration:      0.0s
color_grade:              brightness=1.05, contrast=1.10, saturation=1.30, warmth=+0.02
output_aspect_ratio:      "9:16"   ← special case: center-crop to vertical
```
TikTok/Reels/Shorts format. Very vivid saturation pops on phone screens. Short total duration — attention spans are short. The 9:16 crop is handled in Stage 8.

---

#### `walkthrough`
```
preferred_motion_types:  ["static", "slow_pan"]
clip_duration_min:        6.0s
clip_duration_max:       12.0s
target_total_duration:   90.0s
ordering_strategy:        "best_first"
transition_type:          "crossfade"
transition_duration:      1.2s
color_grade:              brightness=1.00, contrast=1.00, saturation=1.00, warmth=+0.00
output_aspect_ratio:      "16:9"
```
Neutral grade, long clips — designed to feel like a guided property walk. Suitable for embedding on a listing page where visitors browse slowly.

---

#### `timelapse_feel`
```
preferred_motion_types:  ["fast_flythrough"]
clip_duration_min:        0.5s
clip_duration_max:        1.0s
target_total_duration:   25.0s
ordering_strategy:        "build_to_climax"
transition_type:          "hard_cut"
transition_duration:      0.0s
color_grade:              brightness=1.00, contrast=1.05, saturation=0.95, warmth=-0.04
output_aspect_ratio:      "16:9"
bypass_duration_guards:   True    ← special case: clip_duration_max < MIN_CLIP_DURATION
```
Rapid-fire cuts of fast flythrough clips — feels like a hyperlapse even though it's not. Each 4-second segmenter clip is truncated to 1 second at assembly. The cool grade suits the kinetic energy.

---

#### `golden_hour`
```
preferred_motion_types:  ["static", "slow_pan"]
clip_duration_min:        5.0s
clip_duration_max:        9.0s
target_total_duration:   60.0s
ordering_strategy:        "best_first"
transition_type:          "crossfade"
transition_duration:      1.2s
color_grade:              brightness=1.12, contrast=1.05, saturation=1.15, warmth=+0.15
output_aspect_ratio:      "16:9"
score_weight_overrides:   {sharpness: 0.25, smoothness: 0.25, composition: 0.20, exposure: 0.30}
```
Very warm, pushed orange grade. `score_weight_overrides` gives exposure 2× its global weight (0.30 vs 0.15), so clips with well-balanced golden-hour light rise above clips with good composition but flat lighting. The result looks distinctly different from `real_estate` despite similar motion preferences.

---

#### `documentary`
```
preferred_motion_types:  ["static", "slow_pan"]
clip_duration_min:        5.0s
clip_duration_max:        8.0s
target_total_duration:   80.0s
ordering_strategy:        "best_first"
transition_type:          "hard_cut"
transition_duration:      0.0s
color_grade:              brightness=1.00, contrast=0.95, saturation=0.90, warmth=+0.00
output_aspect_ratio:      "16:9"
```
Neutral flat grade — slightly low contrast and desaturated, like a news segment or corporate video. Hard cuts despite slow clips distinguish it clearly from `real_estate` (crossfades). Best suited for factual/informational contexts.

---

#### `hero_shot`
```
preferred_motion_types:  ["slow_pan", "static", "fast_flythrough"]   # no preference
clip_duration_min:        8.0s
clip_duration_max:       15.0s
target_total_duration:    0.0    # irrelevant — single clip
ordering_strategy:        "none"
transition_type:          "none"
transition_duration:      0.0s
color_grade:              brightness=1.05, contrast=1.02, saturation=1.05, warmth=+0.04
output_aspect_ratio:      "16:9"
hero_shot_mode:           True    ← special case: select exactly 1 clip
```
The single highest-scored clip, polished and exported on its own. Suitable as a header image/video or a standalone thumbnail-style preview. No transitions, no music mixing decisions needed — just the best moment.

---

#### `overview`
```
preferred_motion_types:  ["static", "slow_pan", "fast_flythrough"]   # static prioritized by ordering
clip_duration_min:        4.0s
clip_duration_max:        8.0s
target_total_duration:   70.0s
ordering_strategy:        "static_first"
transition_type:          "crossfade"
transition_duration:      1.0s
color_grade:              brightness=1.00, contrast=1.00, saturation=1.00, warmth=+0.00
output_aspect_ratio:      "16:9"
```
Neutral grade, all motion types accepted but static shots go first. Opens with wide establishing coverage, then adds movement. Suited for introductory/overview context where spatial orientation matters.

---

### `AVAILABLE_STYLES` registry

```python
AVAILABLE_STYLES: Dict[str, StyleConfig] = {
    "real_estate":    REAL_ESTATE,
    "dynamic":        DYNAMIC,
    "cinematic":      CINEMATIC,
    "social_vertical": SOCIAL_VERTICAL,
    "walkthrough":    WALKTHROUGH,
    "timelapse_feel": TIMELAPSE_FEEL,
    "golden_hour":    GOLDEN_HOUR,
    "documentary":    DOCUMENTARY,
    "hero_shot":      HERO_SHOT,
    "overview":       OVERVIEW,
}
```

---

## Stage 7 — Clip Selection

**What it does:** For each style, filters the curated pool by motion type preferences, orders by the style's strategy, and greedily selects clips to fill the target duration.

### Algorithm / transform

**Step 1 — Motion type filter:**
Keep only clips whose `motion_type` is in `style.preferred_motion_types`. If survivors < `MIN_CLIPS_FOR_STYLE` (default 3), relax: use the full pool and log a warning.

**Step 2 — Duration filter:**
Discard clips shorter than `style.clip_duration_min` (unless `style.bypass_duration_guards`). Truncate clips longer than `style.clip_duration_max` by adjusting `clip.end_time = clip.start_time + style.clip_duration_max`. This adjusts the time range for Stage 8 only — the source file is unchanged.

**Step 3 — Style score computation:**
If `style.score_weight_overrides` is set, compute a `style_score` for each clip using those weights applied to the already-normalized signal scores (`sharpness_norm`, etc.). Otherwise use `promising_score` directly. This makes `golden_hour` genuinely reorder clips relative to the global ranking.

**Step 4 — Ordering:**
- `"best_first"`: sort descending by style score.
- `"build_to_climax"`: sort ascending for first 80%, place top-scored clip last.
- `"static_first"`: static clips sorted by style score first, then all others by style score.
- `"none"`: no reordering (hero_shot single-clip case).

**Step 5 — Greedy duration fill (skipped for `hero_shot_mode`):**
Initialize `selected = []`, `total = 0.0`. Iterate ordered candidates:
- Add clip if `total + clip.duration ≤ target + DURATION_TOLERANCE` (default 5s leeway).
- Stop when `total ≥ target - DURATION_TOLERANCE`.
- If exhausted before reaching target, use what's available and log a warning.

**For `hero_shot_mode`:** return only the single clip with the highest style score, ignoring all duration logic.

**Console output:** per style — clips after motion filter, after duration filter, selected count and total duration, each clip's start/end/motion_type/score.

### APIs & libraries
- Pure Python.

---

## Stage 8 — Assembly

**What it does:** Renders the final video for each style. Loads full-resolution footage for each selected clip's time range, applies color grading, stitches with transitions, optionally adds music, and exports a `.mp4`.

### Algorithm / transform

**Step 1 — Clip extraction:**
`moviepy.VideoFileClip(source_path).subclip(start_time, end_time)` — full resolution, one per selected clip. This is the only point where full-resolution frames are loaded.

**Step 2 — Color grading via `fl_image`:**
Apply the style's `color_grade` dict through a frame-level function. Operations in order (order matters):
1. **Brightness:** `frame × brightness`, clip to `[0, 255]`.
2. **Contrast:** `(frame - 127.5) × contrast + 127.5`, clip.
3. **Saturation:** convert RGB→HSV, multiply S channel by `saturation`, convert back.
4. **Warmth:** add `warmth × 255` to R channel, subtract from B channel (moviepy uses RGB internally), clip.

Note: moviepy passes frames as RGB, not BGR. Ensure channel ordering is consistent in warmth and saturation steps.

**Step 3 — Resize and crop:**
- Default `"16:9"`: resize to `OUTPUT_RESOLUTION` (1920×1080). If source has different aspect ratio, letterbox (black bars) rather than stretch.
- `"9:16"` (`social_vertical`): first crop a center vertical strip of width `int(height × 9/16)` from the full-resolution frame, then resize to 1080×1920.
- `cinematic` with `letterbox=True`: after resize to 1920×1080, add additional black bars to achieve 2.35:1 (crop to 1920×817 content area padded to 1920×1080).

**Step 4 — Transitions:**
- `"hard_cut"`: `moviepy.concatenate_videoclips(clips, method="compose")`.
- `"crossfade"`: apply `.crossfadein(transition_duration)` to each clip after the first, then `concatenate_videoclips(clips, padding=-transition_duration, method="compose")`.
- `"none"`: single clip, no concatenation needed.

**Step 5 — Audio (optional):**
If `--music` path provided: load `moviepy.AudioFileClip`. Loop if shorter than video (`audio.audio_loop(duration=video.duration)`), trim if longer. Set volume to `MUSIC_VOLUME` (default 0.8). Attach via `video.set_audio(audio)`. If no music provided, output has no audio track.

**Step 6 — Export:**
`video.write_videofile(output_path, codec="libx264", audio_codec="aac", fps=OUTPUT_FPS, threads=4, logger=None)`. Log start/end and final file size.

**Error handling:**
- Clip fails to load → log error, skip, continue with remaining clips.
- More than `MAX_CLIP_LOAD_FAILURES` (20%) of clips fail → abort with error rather than rendering a partial video.
- All clips fail → raise exception, no output file written.
- Wrap full assembly in `try/finally` to close all moviepy file handles.

### APIs & libraries
- `moviepy.VideoFileClip`, `moviepy.AudioFileClip`, `moviepy.concatenate_videoclips`, `moviepy.CompositeVideoClip` — moviepy ≥ 1.0.3
- `cv2.cvtColor` for HSV saturation in color grading (RGB→HSV→RGB)
- `librosa` (optional) for beat-sync stretch goal

### If executed
```
selected_clips (ordered) + StyleConfig + source_path + optional music
   │
   for each clip:
       VideoFileClip(path).subclip(start, end)
       → fl_image(grade_frame)  [brightness → contrast → saturation → warmth]
       → crop/resize to output resolution
   │
   ├─ "none":       single clip, no join
   ├─ "hard_cut":   concatenate_videoclips(clips, method="compose")
   └─ "crossfade":  clips[i].crossfadein(dur) → concatenate with padding=-dur
   │
   ├─ music: AudioFileClip → loop/trim → set_audio(volume=0.8)
   └─ write_videofile → {output_dir}/{style.output_suffix}.mp4
   ▼
finished .mp4 per style
```

---

## CLI — `main.py`

```
python main.py \
    --input footage/E7_raw.mp4 \
    --styles real_estate dynamic \
    --music assets/background.mp3 \
    --output-dir output/
```

**Arguments:**
- `--input` (required): path to raw video file
- `--styles` (required, 1+): style names from the `AVAILABLE_STYLES` registry
- `--music` (optional): path to audio file for background music
- `--output-dir` (optional, default `output/`): directory for rendered mp4 files
- `--config` (optional): path to JSON file overriding any `config.py` values

**Console output per stage:**
1. Ingest: file path, duration, fps, resolution, codec
2. Segmentation: clip count produced
3. Scoring: rolling progress count + summary table of top 10 scores with all signal values
4. Ranking: clips before/after hard filter, reasons for any full-batch failure
5. Diversity: clips evaluated, duplicates removed, pool size
6. Selection (per style): clips available, selected, total duration, clip list
7. Assembly (per style): progress, output path, file size

**Edge cases:**
- Input file not found → clear error message, exit code 1
- All clips fail hard filter → error: "All clips failed quality filter. Check if footage is well-lit and not overly shaky."
- No clips match style's motion types (after relaxation) → warning, fallback to full pool
- Output directory does not exist → create it
- Unknown style name → error listing valid names

---

## `config.py` — Tunable Constants

All numeric thresholds and weights, organized by stage, with inline comments explaining rationale for each default. Key groups (full list in source):

```python
# Stage 1
ANALYSIS_RESOLUTION = (640, 360)    # balance of analysis speed vs accuracy
FRAME_SAMPLE_RATE   = 1.0           # fps for analysis frame extraction
MIN_VIDEO_DURATION  = 10.0          # minimum source duration in seconds

# Stage 2
WINDOW_SIZE         = 4.0           # candidate clip length (seconds)
STEP_SIZE           = 1.0           # window step; overlap = WINDOW_SIZE - STEP_SIZE
MIN_CLIP_DURATION   = 2.0           # discard clips shorter than this
MIN_FRAMES_PER_CLIP = 3             # discard clips with too few analysis frames

# Stage 3 — exposure
SHADOW_THRESHOLD    = 20            # histogram bins 0-20 = crushed shadows
HIGHLIGHT_THRESHOLD = 235           # histogram bins 235-255 = blown highlights
SHADOW_PENALTY      = 1.5
HIGHLIGHT_PENALTY   = 1.5

# Stage 3 — motion
STATIC_THRESHOLD    = 1.5           # px/frame below = static
PAN_THRESHOLD       = 8.0           # px/frame above = fast_flythrough

# Stage 3 — composition
CANNY_LOW_THRESHOLD  = 50
CANNY_HIGH_THRESHOLD = 150
HORIZON_LINE_FRACTION        = 0.4
HORIZON_ZONE_CENTER          = 0.5
HORIZON_ZONE_HEIGHT          = 0.30
HORIZON_PENALTY_MULTIPLIER   = 0.7

# Stage 4 — hard filters (gates, not weights)
MIN_SHARPNESS       = 50.0
MIN_SMOOTHNESS      = 0.6

# Stage 4 — weights (must sum to 1.0)
WEIGHT_SHARPNESS    = 0.30
WEIGHT_SMOOTHNESS   = 0.30
WEIGHT_COMPOSITION  = 0.25
WEIGHT_EXPOSURE     = 0.15

# Stage 5 — diversity
COLOR_SIMILARITY_THRESHOLD = 0.92
PHASH_DISTANCE_THRESHOLD   = 8
MAX_POOL_SIZE              = 40

# Stage 7 — selection
MIN_CLIPS_FOR_STYLE = 3
DURATION_TOLERANCE  = 5.0

# Stage 8 — assembly
OUTPUT_RESOLUTION        = (1920, 1080)
OUTPUT_FPS               = 30
MUSIC_VOLUME             = 0.8
MAX_CLIP_LOAD_FAILURES   = 0.20
```

---

## `requirements.txt`

```
opencv-python>=4.8.0
moviepy>=1.0.3
numpy>=1.24.0
ffmpeg-python>=0.2.0
pytest>=7.0.0
# librosa>=0.10.0   # uncomment for beat-sync stretch goal
```

> **Note:** moviepy requires `ffmpeg` installed on the system PATH. See README for installation instructions.

---

## `tests/`

**`test_scorer.py`** — unit tests using synthetic frames:
- Solid black/white → sharpness ≈ 0 (no edges)
- Gradient frame → sharpness > 0
- Checkerboard → sharpness > gradient (maximum edges)
- All-white frame → exposure low (blown highlights)
- All-black frame → exposure low (crushed shadows)
- Middle-gray frame → exposure > all-white
- Identical consecutive frames → smoothness ≈ 1.0, motion_type = "static"
- Single frame → smoothness = 0.0, motion_type = "unknown"
- Blank frame → composition ≈ 0.0
- Checkerboard → composition > blank

**`test_ranker.py`** — tests normalization math, weight validation, hard filter logic

**`test_diversity.py`** — tests that near-identical clips deduplicate, genuinely different clips both survive

---

## The backbone that ties it together

| Concern | Concrete choice |
|---|---|
| **Frame analysis** | OpenCV — Laplacian, Farneback flow, Canny, HoughLinesP, calcHist |
| **Scoring math** | NumPy |
| **Video rendering** | moviepy (wraps ffmpeg) |
| **Audio / beat-sync** | librosa (optional, stretch goal) |
| **All thresholds** | `config.py` — tune against real footage before demo |
| **Full-res footage** | Never loaded until Stage 8; analysis always runs on 640×360 |

**The one insight worth repeating:** stages 3 and 4 are where "what makes a good clip" is encoded. Every other stage either feeds them or acts on their outputs. If the scoring weights or hard-filter thresholds are wrong, the pipeline produces bad results regardless of how well the rest is implemented. **Calibrate config.py against real E7 footage before the demo.** The defaults are informed starting points, not ground truth.
