"""
Stage 6 — Style Templates

Defines 10 distinct output style configurations as fully explicit StyleConfig
dataclass instances. Every parameter is spelled out on each style — no
shorthand, no inheritance between styles — so adding a new style later
requires only copying an existing block and modifying the relevant fields.

The 10 styles cover the range from calm professional real estate footage to
rapid social media edits, with documentary, cinematic, and specialized styles
in between. See the spec (prd/VIDEO_PIPELINE_SPEC.md, Stage 6) for the full
rationale for each style's parameter choices.

Special cases (handled by assembler.py and selector.py):
  - hero_shot:      hero_shot_mode=True → select only the single best clip
  - social_vertical: output_aspect_ratio="9:16" → center-crop in assembler
  - timelapse_feel: bypass_duration_guards=True → clip_duration_max < MIN_CLIP_DURATION
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class StyleConfig:
    """Complete configuration for one output style.

    Attributes:
        name: Registry key string. Must match the key in AVAILABLE_STYLES.
        preferred_motion_types: Motion type labels (from scorer.py) to prefer
            when filtering the curated pool. Selector relaxes to all types if
            fewer than MIN_CLIPS_FOR_STYLE clips match.
        clip_duration_min: Minimum effective clip duration in seconds.
            Clips shorter than this are discarded in Stage 7 (unless
            bypass_duration_guards is True).
        clip_duration_max: Maximum effective clip duration in seconds. Clips
            longer than this have their end_time truncated in Stage 7.
        target_total_duration: Target total output duration in seconds.
            Greedy selection fills until within DURATION_TOLERANCE of this.
            Set to 0.0 for hero_shot_mode (single clip).
        ordering_strategy: How to order selected clips before assembly.
            "best_first"      — descending by style score; best clip leads.
            "build_to_climax" — ascending for first 80%, best clip last.
            "static_first"    — static clips by score, then all others by score.
            "none"            — no reordering (hero_shot_mode only).
        transition_type: Type of cut between clips.
            "crossfade"  — linear opacity overlap over transition_duration.
            "hard_cut"   — instant cut, no transition.
            "none"       — single clip, no join needed.
        transition_duration: Seconds of overlap for crossfades. 0.0 for hard cuts.
        color_grade: Dict controlling per-frame color adjustment in Stage 8.
            brightness  — scalar multiplier (1.0 = neutral; >1 = brighter)
            contrast    — scalar; applied as (frame - 127.5) * contrast + 127.5
            saturation  — HSV S-channel multiplier (1.0 = neutral)
            warmth      — additive R/B shift (positive = warmer orange tones;
                          adds warmth*255 to R, subtracts from B)
        output_suffix: Filename suffix for the rendered mp4 (e.g. "real_estate"
            → "output/real_estate.mp4").
        output_aspect_ratio: "16:9" (default 1920×1080) or "9:16" (social_vertical:
            1080×1920 via center-crop in assembler).
        hero_shot_mode: If True, selector returns only the single highest-scored
            clip, ignoring all duration and ordering logic.
        bypass_duration_guards: If True, the selector does not enforce
            config.MIN_CLIP_DURATION — allows styles where clip_duration_max is
            less than MIN_CLIP_DURATION (currently only timelapse_feel).
        slowmo_top_n: Number of top-scored clips to apply 0.5× slowdown to.
            0 = disabled. Stretch goal; requires high-fps source footage for
            quality results.
        letterbox: If True, add black bars to achieve 2.35:1 widescreen ratio
            after resize to 1920×1080. Stretch goal for cinematic style.
        music_tempo_preference: Hint for beat-sync stretch goal.
            "fast", "slow", or None. Used only when librosa is available and
            a music track is provided.
        score_weight_overrides: Optional dict overriding the global scoring
            weights (WEIGHT_SHARPNESS etc.) when computing the style-specific
            score for clip ordering within this style. Keys must be a subset of
            {"sharpness", "smoothness", "composition", "exposure"}. Values
            should sum to 1.0. None = use global config weights.
    """

    name: str
    preferred_motion_types: List[str]
    clip_duration_min: float
    clip_duration_max: float
    target_total_duration: float
    ordering_strategy: str
    transition_type: str
    transition_duration: float
    color_grade: Dict[str, float]
    output_suffix: str

    # Optional / special-case fields with sensible defaults
    output_aspect_ratio: str = "16:9"
    hero_shot_mode: bool = False
    bypass_duration_guards: bool = False
    slowmo_top_n: int = 0
    letterbox: bool = False
    music_tempo_preference: Optional[str] = None
    score_weight_overrides: Optional[Dict[str, float]] = field(default=None)


# ─────────────────────────────────────────────────────────────────────────────
# Style 1 — real_estate
# ─────────────────────────────────────────────────────────────────────────────
# Calm pacing, warm tones, crossfades. Signals "inviting property" rather than
# "exciting experience." The highest-scored clip leads as an establishing shot,
# mirroring the opening of a professional listing video.
# ─────────────────────────────────────────────────────────────────────────────

REAL_ESTATE = StyleConfig(
    name="real_estate",
    preferred_motion_types=["static", "slow_pan"],
    clip_duration_min=4.0,
    clip_duration_max=8.0,
    target_total_duration=75.0,
    ordering_strategy="best_first",
    transition_type="crossfade",
    transition_duration=1.0,
    color_grade={
        "brightness": 1.08,     # slight boost — warmer, more inviting feel
        "contrast":   1.00,     # neutral contrast
        "saturation": 1.05,     # very mild saturation — not vivid, just clean
        "warmth":     0.06,     # gentle shift toward warmer orange tones
    },
    output_suffix="real_estate",
    output_aspect_ratio="16:9",
    hero_shot_mode=False,
    bypass_duration_guards=False,
    slowmo_top_n=0,
    letterbox=False,
    music_tempo_preference=None,
    score_weight_overrides=None,
)


# ─────────────────────────────────────────────────────────────────────────────
# Style 2 — dynamic
# ─────────────────────────────────────────────────────────────────────────────
# Energetic, punchy, decisive cuts. High saturation pops on phone screens.
# Builds toward the best clip placed last for a strong finish.
#
# Stretch goal — beat-synced cuts: when music is provided and librosa is
# available, snap cut points to beat timestamps from librosa.beat.beat_track().
# Marked with STRETCH_GOAL_BEAT_SYNC comments in assembler.py.
# ─────────────────────────────────────────────────────────────────────────────

DYNAMIC = StyleConfig(
    name="dynamic",
    preferred_motion_types=["fast_flythrough", "slow_pan"],
    clip_duration_min=1.0,
    clip_duration_max=3.0,
    target_total_duration=38.0,
    ordering_strategy="build_to_climax",
    transition_type="hard_cut",
    transition_duration=0.0,
    color_grade={
        "brightness": 1.00,     # neutral brightness — energy comes from contrast
        "contrast":   1.15,     # punchy contrast
        "saturation": 1.25,     # vivid, energetic colors
        "warmth":     0.00,     # neutral warmth — not trying to feel cozy
    },
    output_suffix="dynamic",
    output_aspect_ratio="16:9",
    hero_shot_mode=False,
    bypass_duration_guards=False,
    slowmo_top_n=0,
    letterbox=False,
    music_tempo_preference="fast",  # hint for beat-sync stretch goal
    score_weight_overrides=None,
)


# ─────────────────────────────────────────────────────────────────────────────
# Style 3 — cinematic
# ─────────────────────────────────────────────────────────────────────────────
# Moody, desaturated, deliberate pacing. Best clips win regardless of motion
# type — a cinematic feel comes from grade and timing, not shot type.
#
# Stretch goals (marked in assembler.py):
#   slowmo_top_n=2  — apply 0.5× slowdown to the top 2 clips via moviepy
#                     (best with high-fps source; degrades at 30fps source)
#   letterbox=True  — add black bars to achieve 2.35:1 widescreen ratio
# ─────────────────────────────────────────────────────────────────────────────

CINEMATIC = StyleConfig(
    name="cinematic",
    preferred_motion_types=["slow_pan", "static", "fast_flythrough"],
    clip_duration_min=3.0,
    clip_duration_max=10.0,
    target_total_duration=60.0,
    ordering_strategy="best_first",
    transition_type="crossfade",
    transition_duration=1.5,
    color_grade={
        "brightness": 0.95,     # slightly darker, moodier
        "contrast":   1.10,     # moderate contrast boost
        "saturation": 0.85,     # desaturated — the hallmark cinematic look
        "warmth":    -0.03,     # slight cool shift
    },
    output_suffix="cinematic",
    output_aspect_ratio="16:9",
    hero_shot_mode=False,
    bypass_duration_guards=False,
    slowmo_top_n=2,             # stretch goal — top 2 clips get 0.5× slowdown
    letterbox=True,             # stretch goal — 2.35:1 widescreen bars
    music_tempo_preference="slow",
    score_weight_overrides=None,
)


# ─────────────────────────────────────────────────────────────────────────────
# Style 4 — social_vertical
# ─────────────────────────────────────────────────────────────────────────────
# TikTok / Reels / Shorts format. 9:16 vertical output via center-crop in
# assembler.py. Very vivid saturation pops on phone screens. Short total
# duration — vertical social content demands fast hooks.
#
# Special case: output_aspect_ratio="9:16" triggers center-crop logic in
# assembler.py: crop from x=(width - height*9/16)//2, full height, resize
# to 1080×1920.
# ─────────────────────────────────────────────────────────────────────────────

SOCIAL_VERTICAL = StyleConfig(
    name="social_vertical",
    preferred_motion_types=["fast_flythrough", "slow_pan"],
    clip_duration_min=1.0,
    clip_duration_max=4.0,
    target_total_duration=20.0,
    ordering_strategy="build_to_climax",
    transition_type="hard_cut",
    transition_duration=0.0,
    color_grade={
        "brightness": 1.05,     # slight boost — phone screens are bright
        "contrast":   1.10,     # moderate contrast
        "saturation": 1.30,     # very vivid — pops on small screens
        "warmth":     0.02,     # just a touch of warmth
    },
    output_suffix="social_vertical",
    output_aspect_ratio="9:16",     # special case: center-crop in assembler
    hero_shot_mode=False,
    bypass_duration_guards=False,
    slowmo_top_n=0,
    letterbox=False,
    music_tempo_preference="fast",
    score_weight_overrides=None,
)


# ─────────────────────────────────────────────────────────────────────────────
# Style 5 — walkthrough
# ─────────────────────────────────────────────────────────────────────────────
# Neutral grade, long clips — designed to feel like a guided property walk.
# Crossfades despite longer clips give a seamless flow. Suitable for embedding
# on a listing page where visitors browse slowly. Most immersive of all styles.
# ─────────────────────────────────────────────────────────────────────────────

WALKTHROUGH = StyleConfig(
    name="walkthrough",
    preferred_motion_types=["static", "slow_pan"],
    clip_duration_min=6.0,
    clip_duration_max=12.0,
    target_total_duration=90.0,
    ordering_strategy="best_first",
    transition_type="crossfade",
    transition_duration=1.2,
    color_grade={
        "brightness": 1.00,     # completely neutral — let the light speak
        "contrast":   1.00,     # neutral contrast
        "saturation": 1.00,     # natural saturation
        "warmth":     0.00,     # neutral warmth
    },
    output_suffix="walkthrough",
    output_aspect_ratio="16:9",
    hero_shot_mode=False,
    bypass_duration_guards=False,
    slowmo_top_n=0,
    letterbox=False,
    music_tempo_preference="slow",
    score_weight_overrides=None,
)


# ─────────────────────────────────────────────────────────────────────────────
# Style 6 — timelapse_feel
# ─────────────────────────────────────────────────────────────────────────────
# Rapid-fire cuts of fast flythrough clips — feels like a hyperlapse even
# though it's not. Each 4-second segmenter clip is truncated to 1 second at
# assembly time by adjusting end_time. The cool grade suits the kinetic energy.
#
# Special case: bypass_duration_guards=True because clip_duration_max=1.0 is
# less than config.MIN_CLIP_DURATION=2.0. The selector skips the normal
# duration minimum check for this style.
# ─────────────────────────────────────────────────────────────────────────────

TIMELAPSE_FEEL = StyleConfig(
    name="timelapse_feel",
    preferred_motion_types=["fast_flythrough"],
    clip_duration_min=0.5,
    clip_duration_max=1.0,
    target_total_duration=25.0,
    ordering_strategy="build_to_climax",
    transition_type="hard_cut",
    transition_duration=0.0,
    color_grade={
        "brightness": 1.00,     # neutral
        "contrast":   1.05,     # slight contrast boost
        "saturation": 0.95,     # very slightly desaturated — keeps it cool, not garish
        "warmth":    -0.04,     # cool shift — kinetic energy reads cooler
    },
    output_suffix="timelapse_feel",
    output_aspect_ratio="16:9",
    hero_shot_mode=False,
    bypass_duration_guards=True,    # special case: clip_duration_max < MIN_CLIP_DURATION
    slowmo_top_n=0,
    letterbox=False,
    music_tempo_preference="fast",
    score_weight_overrides=None,
)


# ─────────────────────────────────────────────────────────────────────────────
# Style 7 — golden_hour
# ─────────────────────────────────────────────────────────────────────────────
# Very warm, pushed orange grade — designed for footage shot near sunrise or
# sunset. score_weight_overrides gives exposure 2× its global weight (0.30 vs
# 0.15), so clips with well-balanced golden-hour light rise above clips with
# good composition but flat or harsh lighting.
#
# Despite similar motion preferences to real_estate, the pushed warmth and
# heavier exposure weighting produce distinctly different output.
# ─────────────────────────────────────────────────────────────────────────────

GOLDEN_HOUR = StyleConfig(
    name="golden_hour",
    preferred_motion_types=["static", "slow_pan"],
    clip_duration_min=5.0,
    clip_duration_max=9.0,
    target_total_duration=60.0,
    ordering_strategy="best_first",
    transition_type="crossfade",
    transition_duration=1.2,
    color_grade={
        "brightness": 1.12,     # noticeably brighter — golden hour glow
        "contrast":   1.05,     # slight contrast to keep it from looking washed
        "saturation": 1.15,     # moderate saturation — the warmth carries the vibe
        "warmth":     0.15,     # strong warm shift — the defining characteristic
    },
    output_suffix="golden_hour",
    output_aspect_ratio="16:9",
    hero_shot_mode=False,
    bypass_duration_guards=False,
    slowmo_top_n=0,
    letterbox=False,
    music_tempo_preference="slow",
    # Exposure gets 2× global weight (0.15→0.30) to prioritize well-lit clips.
    # Sharpness and smoothness each drop slightly; composition drops to 0.20.
    score_weight_overrides={
        "sharpness":   0.25,
        "smoothness":  0.25,
        "composition": 0.20,
        "exposure":    0.30,
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# Style 8 — documentary
# ─────────────────────────────────────────────────────────────────────────────
# Neutral flat grade — slightly low contrast and desaturated, like a news
# segment or corporate video. Hard cuts despite slow clips distinguish it
# clearly from real_estate (crossfades) and walkthrough (neutral grade but
# also crossfades). Best for factual/informational contexts.
# ─────────────────────────────────────────────────────────────────────────────

DOCUMENTARY = StyleConfig(
    name="documentary",
    preferred_motion_types=["static", "slow_pan"],
    clip_duration_min=5.0,
    clip_duration_max=8.0,
    target_total_duration=80.0,
    ordering_strategy="best_first",
    transition_type="hard_cut",
    transition_duration=0.0,
    color_grade={
        "brightness": 1.00,     # neutral
        "contrast":   0.95,     # slightly flat — less dramatic than real_estate
        "saturation": 0.90,     # slightly desaturated — factual, not marketing
        "warmth":     0.00,     # neutral warmth — no emotional color push
    },
    output_suffix="documentary",
    output_aspect_ratio="16:9",
    hero_shot_mode=False,
    bypass_duration_guards=False,
    slowmo_top_n=0,
    letterbox=False,
    music_tempo_preference=None,
    score_weight_overrides=None,
)


# ─────────────────────────────────────────────────────────────────────────────
# Style 9 — hero_shot
# ─────────────────────────────────────────────────────────────────────────────
# The single highest-scored clip, polished and exported on its own. No
# transitions, no greedy duration fill — just the best moment. Suitable as
# a header video, standalone preview, or thumbnail-replacement video.
#
# Special case: hero_shot_mode=True. Selector returns only 1 clip.
# clip_duration_min/max are the bounds for which clips are eligible, not
# an output length constraint (the full clip duration is used as-is).
# ─────────────────────────────────────────────────────────────────────────────

HERO_SHOT = StyleConfig(
    name="hero_shot",
    preferred_motion_types=["slow_pan", "static", "fast_flythrough"],  # no preference
    clip_duration_min=8.0,
    clip_duration_max=15.0,
    target_total_duration=0.0,          # irrelevant — single clip mode
    ordering_strategy="none",
    transition_type="none",
    transition_duration=0.0,
    color_grade={
        "brightness": 1.05,     # gentle brightening
        "contrast":   1.02,     # very subtle contrast
        "saturation": 1.05,     # just barely more vivid
        "warmth":     0.04,     # subtle warmth — complements most lighting
    },
    output_suffix="hero_shot",
    output_aspect_ratio="16:9",
    hero_shot_mode=True,                # special case: select exactly 1 clip
    bypass_duration_guards=False,
    slowmo_top_n=0,
    letterbox=False,
    music_tempo_preference=None,
    score_weight_overrides=None,
)


# ─────────────────────────────────────────────────────────────────────────────
# Style 10 — overview
# ─────────────────────────────────────────────────────────────────────────────
# Neutral grade, all motion types accepted, but static shots go first.
# Opens with wide establishing coverage, then adds movement — useful for
# introductory/overview contexts where spatial orientation matters.
# The "static_first" ordering is what distinguishes this from walkthrough
# (which uses "best_first" on the same motion preferences).
# ─────────────────────────────────────────────────────────────────────────────

OVERVIEW = StyleConfig(
    name="overview",
    preferred_motion_types=["static", "slow_pan", "fast_flythrough"],  # all accepted
    clip_duration_min=4.0,
    clip_duration_max=8.0,
    target_total_duration=70.0,
    ordering_strategy="static_first",
    transition_type="crossfade",
    transition_duration=1.0,
    color_grade={
        "brightness": 1.00,     # neutral — spatial orientation, not atmosphere
        "contrast":   1.00,     # neutral contrast
        "saturation": 1.00,     # natural saturation
        "warmth":     0.00,     # neutral warmth
    },
    output_suffix="overview",
    output_aspect_ratio="16:9",
    hero_shot_mode=False,
    bypass_duration_guards=False,
    slowmo_top_n=0,
    letterbox=False,
    music_tempo_preference=None,
    score_weight_overrides=None,
)


# ─────────────────────────────────────────────────────────────────────────────
# Registry — keyed by name string for CLI lookup
# ─────────────────────────────────────────────────────────────────────────────

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
