"""
Stage 2 — Segmentation

Slices continuous flight footage into overlapping candidate clips using a
sliding window. There are no natural scene cuts in drone footage, so the
segmenter creates its own boundaries. The overlap between consecutive windows
ensures that any great moment that straddles a boundary is fully captured
within at least one window.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from . import config
from .ingest import IngestedVideo

logger = logging.getLogger(__name__)


@dataclass
class CandidateClip:
    """A single candidate clip produced by the sliding window segmenter.

    Attributes:
        clip_id: Sequential integer ID within this video's segmentation run.
        start_time: Clip start in seconds (relative to source video).
        end_time: Clip end in seconds. May be adjusted by Stage 7 to respect
            a style's clip_duration_max.
        duration: Effective duration in seconds (end_time - start_time).
        frames: Analysis-resolution frames whose timestamps fall in [start, end).
            dtype uint8, shape (H, W, 3), BGR. May be empty for clips with
            fewer than MIN_FRAMES_PER_CLIP valid frames (these are discarded).

        --- Populated by scorer.py (Stage 3) ---
        sharpness_raw: Laplacian variance mean. 0.0 if not yet scored.
        exposure_raw: Midtone fraction minus penalized extremes. 0.0 if not scored.
        smoothness_raw: Mean per-transition smoothness in [0, 1]. 0.0 if not scored.
        composition_raw: Adjusted edge density in [0, 1]. 0.0 if not scored.
        motion_type: "static", "slow_pan", "fast_flythrough", or "unknown".

        --- Populated by ranker.py (Stage 4) ---
        sharpness_norm: Sharpness normalized to [0, 1] across surviving clips.
        exposure_norm: Exposure normalized to [0, 1].
        smoothness_norm: Smoothness normalized to [0, 1].
        composition_norm: Composition normalized to [0, 1].
        promising_score: Weighted combination of normalized scores.
        passed_hard_filter: True if this clip survived the hard sharpness/smoothness gates.

        --- Populated by diversity.py (Stage 5) ---
        color_hist: L2-normalized HSV color histogram (64-element float array).
        phash: 64-bit perceptual hash as a Python int.
    """

    clip_id: int
    start_time: float
    end_time: float
    duration: float
    frames: List[np.ndarray] = field(default_factory=list)

    # Stage 3 — raw scores
    sharpness_raw: float = 0.0
    exposure_raw: float = 0.0
    smoothness_raw: float = 0.0
    composition_raw: float = 0.0
    motion_type: str = "unknown"

    # Stage 4 — normalized scores and final rank
    sharpness_norm: float = 0.0
    exposure_norm: float = 0.0
    smoothness_norm: float = 0.0
    composition_norm: float = 0.0
    promising_score: float = 0.0
    passed_hard_filter: bool = False

    # Stage 5 — diversity fingerprint
    color_hist: Optional[np.ndarray] = field(default=None, repr=False)
    phash: int = 0

    def __repr__(self) -> str:
        return (
            f"CandidateClip(id={self.clip_id}, t={self.start_time:.1f}–{self.end_time:.1f}s, "
            f"motion={self.motion_type}, score={self.promising_score:.3f})"
        )


def segment(video: IngestedVideo, bypass_duration_guards: bool = False) -> List[CandidateClip]:
    """Slice a video's analysis frames into overlapping candidate clips.

    Uses a sliding window of config.WINDOW_SIZE seconds stepped by
    config.STEP_SIZE seconds, resulting in (WINDOW_SIZE - STEP_SIZE)
    seconds of overlap between consecutive clips.

    Args:
        video: IngestedVideo from Stage 1 (with analysis_frames populated).
        bypass_duration_guards: If True, skip the MIN_CLIP_DURATION check for
            tail clips. Used for styles like timelapse_feel where effective clip
            durations are set shorter than MIN_CLIP_DURATION by the style config.

    Returns:
        List of CandidateClip instances, each with frames assigned. Clips with
        fewer than config.MIN_FRAMES_PER_CLIP frames are excluded.
    """
    if not video.analysis_frames:
        logger.error("No analysis frames available; cannot segment")
        return []

    clips: List[CandidateClip] = []
    clip_id = 0
    step = config.STEP_SIZE
    window = config.WINDOW_SIZE
    duration = video.duration

    logger.debug(
        "Segmenting %.1fs video | window=%.1fs, step=%.1fs, overlap=%.1fs",
        duration, window, step, window - step,
    )

    t_start = 0.0
    while t_start < duration:
        t_end = min(t_start + window, duration)
        clip_duration = t_end - t_start

        # Discard tail clips that are too short to score meaningfully,
        # unless the caller has explicitly bypassed this guard.
        if not bypass_duration_guards and clip_duration < config.MIN_CLIP_DURATION:
            logger.debug(
                "Discarding tail clip at t=%.1f–%.1f (%.1fs < MIN_CLIP_DURATION %.1fs)",
                t_start, t_end, clip_duration, config.MIN_CLIP_DURATION,
            )
            t_start += step
            continue

        # Collect analysis frames whose timestamps fall within [t_start, t_end)
        clip_frames = [
            frame
            for (ts, frame) in video.analysis_frames
            if t_start <= ts < t_end
        ]

        if len(clip_frames) < config.MIN_FRAMES_PER_CLIP:
            logger.debug(
                "Discarding clip at t=%.1f–%.1f: only %d frames (min %d)",
                t_start, t_end, len(clip_frames), config.MIN_FRAMES_PER_CLIP,
            )
            t_start += step
            continue

        clips.append(
            CandidateClip(
                clip_id=clip_id,
                start_time=t_start,
                end_time=t_end,
                duration=clip_duration,
                frames=clip_frames,
            )
        )
        clip_id += 1
        t_start += step

    logger.info(
        "Segmentation: %d candidate clips from %.1fs of footage "
        "(window=%.1fs, step=%.1fs)",
        len(clips), duration, window, step,
    )
    return clips
