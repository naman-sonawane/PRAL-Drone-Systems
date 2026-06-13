"""
Central configuration for the PRAL video post-processing pipeline.

All numeric thresholds, weights, and constants live here. Tune these against
real footage before the demo. Changing a value here affects the entire pipeline
without touching any other module.
"""

from typing import Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Ingest
# ─────────────────────────────────────────────────────────────────────────────

ANALYSIS_RESOLUTION: Tuple[int, int] = (640, 360)
"""Width × height for analysis frames. Full-res footage is never loaded until Stage 8.
Lower = faster analysis with less accurate sharpness/composition. 640×360 is the right
balance for a 4-core laptop running the demo."""

FRAME_SAMPLE_RATE: float = 1.0
"""Frames per second to extract for analysis. At 4-second windows this gives ~4 frames
per candidate clip. Increasing this improves motion scoring accuracy at the cost of
RAM and processing time."""

MIN_VIDEO_DURATION: float = 10.0
"""Minimum acceptable source video duration in seconds. Shorter files are rejected
before segmentation — not enough footage to form meaningful clips."""


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Segmentation
# ─────────────────────────────────────────────────────────────────────────────

WINDOW_SIZE: float = 4.0
"""Candidate clip duration in seconds. Chosen to be long enough to capture smooth
motion and assess quality but short enough to differentiate distinct moments."""

STEP_SIZE: float = 1.0
"""Sliding window step in seconds. Overlap = WINDOW_SIZE - STEP_SIZE = 3 seconds.
A 3-second overlap ensures any great 3-second moment falls fully within at least
one window, even if it straddles two boundaries."""

MIN_CLIP_DURATION: float = 2.0
"""Discard clips shorter than this from the sliding window output. Applies to the
tail of the video where a full WINDOW_SIZE of footage is unavailable.
Styles with bypass_duration_guards=True (timelapse_feel) ignore this check."""

MIN_FRAMES_PER_CLIP: int = 3
"""Minimum number of analysis frames required to score a clip meaningfully.
With FRAME_SAMPLE_RATE=1.0, this corresponds to clips of at least 3 seconds."""


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Sharpness (Laplacian variance)
# ─────────────────────────────────────────────────────────────────────────────
# These thresholds are calibrated for 640×360 frames. If ANALYSIS_RESOLUTION
# changes substantially, recalibrate: run the pipeline on known-sharp and
# known-blurry footage and observe where scores cluster.
#
# Typical values at 640×360:
#   < 50   — blurry / heavy motion blur
#   50–150 — acceptable / in focus
#   > 150  — sharp / detailed
#
# (No threshold constants needed here; MIN_SHARPNESS in Stage 4 is the gate.)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Exposure (brightness histogram)
# ─────────────────────────────────────────────────────────────────────────────

SHADOW_THRESHOLD: int = 20
"""Histogram bins 0–SHADOW_THRESHOLD are classified as crushed shadows.
Pixels this dark have lost all shadow detail. Default 20 out of 255."""

HIGHLIGHT_THRESHOLD: int = 235
"""Histogram bins HIGHLIGHT_THRESHOLD–255 are classified as blown highlights.
Pixels this bright have lost all highlight detail. Default 235 out of 255."""

SHADOW_PENALTY: float = 1.5
"""Multiplier on shadow_fraction before subtracting from the midtone score.
> 1.0 means crushed shadows are penalized more than just their absence from midtones.
Outdoor drone footage often has some shadow clipping; 1.5 is a reasonable penalty."""

HIGHLIGHT_PENALTY: float = 1.5
"""Multiplier on highlight_fraction before subtracting from the midtone score.
Identical reasoning to SHADOW_PENALTY. Tune lower (e.g. 1.2) if the target
footage is typically shot into bright sky."""


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Motion smoothness + type (Farneback optical flow)
# ─────────────────────────────────────────────────────────────────────────────

STATIC_THRESHOLD: float = 1.5
"""Mean flow magnitude (px/frame at analysis resolution) below which a clip is
classified as 'static'. At ANALYSIS_RESOLUTION 640×360 and FRAME_SAMPLE_RATE 1fps,
a mean of 1.5px displacement per second = essentially hovering."""

PAN_THRESHOLD: float = 8.0
"""Mean flow magnitude at or above which a clip is 'fast_flythrough'.
Between STATIC_THRESHOLD and PAN_THRESHOLD = 'slow_pan'.
8px/frame at 640×360 = ~1.25% of frame width per second — clearly moving."""


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Composition (Canny edge density + horizon detection)
# ─────────────────────────────────────────────────────────────────────────────

CANNY_LOW_THRESHOLD: int = 50
"""Lower hysteresis threshold for Canny edge detection. Edges below this are
discarded. 50 is a standard starting point; lower values catch weaker edges."""

CANNY_HIGH_THRESHOLD: int = 150
"""Upper hysteresis threshold for Canny edge detection. Only edges above this
are certain edges; edges between low and high are included if connected to
a certain edge. Standard 3:1 ratio to CANNY_LOW_THRESHOLD."""

HORIZON_LINE_FRACTION: float = 0.4
"""A detected line must span at least this fraction of frame width to count as
a horizon. Prevents short horizontal edges (window sills, balconies) from
triggering the horizon penalty."""

HORIZON_ZONE_CENTER: float = 0.5
"""Vertical position (0=top, 1=bottom) of the center of the horizon detection
zone. 0.5 = vertical midpoint. Shift toward 0.4 if drone footage tends to keep
horizons in the upper half."""

HORIZON_ZONE_HEIGHT: float = 0.30
"""Fraction of frame height that defines the horizon detection zone, centered
on HORIZON_ZONE_CENTER. 0.30 = middle 30% of the frame's height."""

HORIZON_PENALTY_MULTIPLIER: float = 0.7
"""Composition score multiplier applied when a bare horizon is detected. 0.7
reduces the score by 30%. A clear sky/ground split with nothing else in frame
is technically high-edge but cinematically uninteresting for a building showcase."""


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — Hard Filters (gates, not weights)
# ─────────────────────────────────────────────────────────────────────────────

MIN_SHARPNESS: float = 50.0
"""Clips with sharpness_raw below this are discarded entirely before scoring.
A blurry clip is not redeemable by good composition or exposure. Set to 0.0
to disable this filter (useful for debugging with intentionally blurry test footage)."""

MIN_SMOOTHNESS: float = 0.6
"""Clips with smoothness_raw below this are discarded entirely before scoring.
Shaky footage is not redeemable by anything else. Set to 0.0 to disable.
0.6 on the [0,1] smoothness scale corresponds to meaningful camera shake."""


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — Scoring Weights
# These four must sum to exactly 1.0; validated at startup in main.py.
# ─────────────────────────────────────────────────────────────────────────────

WEIGHT_SHARPNESS: float = 0.30
"""Sharpness contributes 30% of the promising_score. Equal with smoothness —
both are fundamental requirements for professional footage."""

WEIGHT_SMOOTHNESS: float = 0.30
"""Smoothness contributes 30%. Drone footage lives or dies on whether movement
looks controlled. Equal weight to sharpness reflects this."""

WEIGHT_COMPOSITION: float = 0.25
"""Composition contributes 25%. Important but uses a simplified proxy (edge
density), so slightly lower weight than sharpness/smoothness which are more
directly measurable. Increase once YOLO-based detection is integrated."""

WEIGHT_EXPOSURE: float = 0.15
"""Exposure contributes 15%. Outdoor drone footage in daylight generally has
reasonable exposure; this is a tiebreaker rather than a primary filter."""


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5 — Diversity Filtering
# ─────────────────────────────────────────────────────────────────────────────

COLOR_SIMILARITY_THRESHOLD: float = 0.92
"""cv2.HISTCMP_CORREL above this value between two clips' HSV color histograms
indicates visually similar color content. 0.92 is intentionally strict — only
very similar clips are deduplicated. Lower this if the pool still lacks variety."""

PHASH_DISTANCE_THRESHOLD: int = 8
"""Hamming distance between two clips' 64-bit perceptual hashes below this
indicates similar visual structure. Both color AND hash similarity must hold
for deduplication, preventing false positives from one metric alone."""

MAX_POOL_SIZE: int = 40
"""Maximum number of clips in the curated pool. 40 gives more than enough
candidates for the longest style (walkthrough at 90s with 6s clips = 15 clips
needed), while keeping Stage 7 selection fast."""


# ─────────────────────────────────────────────────────────────────────────────
# Stage 7 — Selection
# ─────────────────────────────────────────────────────────────────────────────

MIN_CLIPS_FOR_STYLE: int = 3
"""If fewer than this many clips survive the motion-type filter for a given style,
relax the filter to the full pool. Prevents styles from producing empty output
when the drone didn't happen to capture enough of the preferred motion type."""

DURATION_TOLERANCE: float = 5.0
"""Seconds of slack around target_total_duration for greedy clip selection.
A clip is added if total_duration + clip.duration <= target + DURATION_TOLERANCE.
Selection stops when total_duration >= target - DURATION_TOLERANCE."""


# ─────────────────────────────────────────────────────────────────────────────
# Stage 8 — Assembly
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_RESOLUTION: Tuple[int, int] = (1920, 1080)
"""Default output resolution (width × height) for 16:9 styles.
social_vertical uses 1080×1920 instead, computed in assembler.py."""

OUTPUT_FPS: int = 30
"""Output video frame rate. 30fps is standard for web/social delivery.
Use 24 for a more cinematic feel (and smaller file size)."""

MUSIC_VOLUME: float = 0.8
"""Volume multiplier for the background music track (range: 0.0–1.0).
0.8 leaves headroom; pure drone footage has no dialogue to compete with."""

MAX_CLIP_LOAD_FAILURES: float = 0.20
"""Maximum fraction of selected clips allowed to fail loading before aborting.
If more than 20% of clips can't be loaded, the render is aborted rather than
producing a video with large gaps. Set to 1.0 to always render what's available."""
