"""
Stage 3 — Scoring

Evaluates each candidate clip on four independent quality signals:
  1. Sharpness     — Laplacian variance (focus / motion-blur)
  2. Exposure      — brightness histogram (clipped shadows / highlights)
  3. Smoothness    — Farneback optical flow variance (camera shake)
                     + motion type classification (static/slow_pan/fast_flythrough)
  4. Composition   — Canny edge density + horizon penalty (structured content proxy)

Each function takes a list of analysis-resolution BGR frames and returns a
raw score. Normalization and combination happen in Stage 4 (ranker.py).

NOTE on composition: The edge-density approach is a placeholder for a proper
YOLO-based subject detector. It correctly separates "sky/ground" from "building
with edges" but cannot distinguish architectural detail from dense foliage.
The upgrade path is clearly marked with UPGRADE_PATH comments below.
"""

import logging
from typing import List, Tuple

import cv2
import numpy as np

from . import config
from .segmenter import CandidateClip

logger = logging.getLogger(__name__)


def score_clip(clip: CandidateClip) -> CandidateClip:
    """Compute all four quality signals for a single candidate clip.

    Modifies the clip in-place (sets *_raw fields and motion_type) and also
    returns it, so callers can use either style.

    Args:
        clip: CandidateClip with frames populated (from Stage 2).

    Returns:
        The same CandidateClip with sharpness_raw, exposure_raw,
        smoothness_raw, composition_raw, and motion_type set.
    """
    if not clip.frames:
        logger.warning("Clip %d has no frames; scoring as zeros", clip.clip_id)
        clip.sharpness_raw = 0.0
        clip.exposure_raw = 0.0
        clip.smoothness_raw = 0.0
        clip.composition_raw = 0.0
        clip.motion_type = "unknown"
        return clip

    clip.sharpness_raw = score_sharpness(clip.frames)
    clip.exposure_raw = score_exposure(clip.frames)
    clip.smoothness_raw, clip.motion_type = score_motion(clip.frames)
    clip.composition_raw = score_composition(clip.frames)

    logger.debug(
        "Clip %d [%.1f–%.1fs] sharp=%.1f exp=%.3f smooth=%.3f comp=%.4f type=%s",
        clip.clip_id, clip.start_time, clip.end_time,
        clip.sharpness_raw, clip.exposure_raw,
        clip.smoothness_raw, clip.composition_raw, clip.motion_type,
    )
    return clip


def score_sharpness(frames: List[np.ndarray]) -> float:
    """Compute sharpness score using Laplacian variance.

    A sharp, in-focus frame has crisp edges with high-frequency content,
    producing large Laplacian responses and therefore high variance.
    A blurry or motion-blurred frame has soft edges and low variance.

    The Laplacian is computed on the grayscale version of each frame.
    Using CV_64F (64-bit float) preserves negative values from the
    second derivative, which would be lost with uint8 (clamped to 0).

    Args:
        frames: List of BGR frames at analysis resolution (uint8 ndarrays).
            Invalid frames (None, zero-size, wrong dtype) are skipped.

    Returns:
        Mean Laplacian variance across all valid frames.
        Returns 0.0 if no valid frames remain after filtering.

    Typical values at 640×360:
        < 50    — blurry / motion-blurred (hard filter threshold)
        50–150  — acceptable focus
        > 150   — sharp, well-focused
    """
    variances: List[float] = []

    for frame in frames:
        if frame is None or frame.size == 0:
            continue
        if len(frame.shape) < 2:
            continue

        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # Laplacian with 64-bit float preserves signed second derivatives
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            variances.append(float(np.var(laplacian)))
        except cv2.error as exc:
            logger.debug("Laplacian computation failed on a frame: %s", exc)
            continue

    if not variances:
        return 0.0

    return float(np.mean(variances))


def score_exposure(frames: List[np.ndarray]) -> float:
    """Compute exposure quality from brightness histogram analysis.

    A well-exposed frame has most pixels in the midtone range.
    Crushed shadows (near-black) and blown highlights (near-white) are
    penalized because they indicate lost detail and poor dynamic range.

    Score formula per frame:
        midtone_fraction - SHADOW_PENALTY * shadow_fraction
                         - HIGHLIGHT_PENALTY * highlight_fraction

    Where fractions are defined by the SHADOW_THRESHOLD and HIGHLIGHT_THRESHOLD
    histogram bin boundaries in config.py.

    Args:
        frames: List of BGR frames at analysis resolution.

    Returns:
        Mean exposure score across all valid frames.
        Raw range is approximately [-1.5, 1.0] before normalization.
        Higher = better exposed (more midtones, fewer extremes).
        Returns 0.0 if no valid frames remain.
    """
    scores: List[float] = []

    for frame in frames:
        if frame is None or frame.size == 0:
            continue

        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            total_pixels = float(gray.shape[0] * gray.shape[1])

            # 256-bin histogram, normalized to [0, 1] fractions
            hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
            hist = hist.flatten() / total_pixels

            shadow_fraction = float(np.sum(hist[:config.SHADOW_THRESHOLD]))
            highlight_fraction = float(np.sum(hist[config.HIGHLIGHT_THRESHOLD:]))
            midtone_fraction = 1.0 - shadow_fraction - highlight_fraction

            score = (
                midtone_fraction
                - config.SHADOW_PENALTY * shadow_fraction
                - config.HIGHLIGHT_PENALTY * highlight_fraction
            )
            scores.append(score)
        except cv2.error as exc:
            logger.debug("Histogram computation failed on a frame: %s", exc)
            continue

    if not scores:
        return 0.0

    return float(np.mean(scores))


def score_motion(frames: List[np.ndarray]) -> Tuple[float, str]:
    """Compute motion smoothness and classify motion type using Farneback optical flow.

    Smoothness is measured by the standard deviation of flow magnitudes across
    each frame. When all pixels move similarly (smooth pan, steady hover), the
    flow field is uniform and std is low → smoothness is high.
    When pixels move erratically in different directions (camera shake, wind),
    std is high → smoothness is low.

    Motion type is classified by the mean flow magnitude across all frame pairs:
        < STATIC_THRESHOLD  → "static"    (hover / near-stationary)
        < PAN_THRESHOLD     → "slow_pan"  (controlled glide or pan)
        ≥ PAN_THRESHOLD     → "fast_flythrough"

    Farneback parameters (pyr_scale=0.5, levels=3, winsize=15, iterations=3,
    poly_n=5, poly_sigma=1.2) are standard defaults for moderate-motion footage.
    Increase levels or winsize for footage with very fast camera movement.

    Args:
        frames: List of BGR frames at analysis resolution. Needs at least 2
            frames to compute any flow; returns (0.0, "unknown") with fewer.

    Returns:
        Tuple of (smoothness_score, motion_type_string).
        smoothness_score is in [0, 1] where 1.0 = perfectly steady.
        motion_type is one of "static", "slow_pan", "fast_flythrough", "unknown".
    """
    if len(frames) < 2:
        return 0.0, "unknown"

    smoothness_values: List[float] = []
    mean_magnitudes: List[float] = []

    for i in range(len(frames) - 1):
        frame_a = frames[i]
        frame_b = frames[i + 1]

        if frame_a is None or frame_b is None:
            continue
        if frame_a.size == 0 or frame_b.size == 0:
            continue

        try:
            gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
            gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)

            flow = cv2.calcOpticalFlowFarneback(
                gray_a,
                gray_b,
                None,           # no pre-computed flow
                pyr_scale=0.5,  # each pyramid level scales by 0.5
                levels=3,       # 3 pyramid levels
                winsize=15,     # averaging window size
                iterations=3,   # iterations per pyramid level
                poly_n=5,       # size of pixel neighborhood for polynomial expansion
                poly_sigma=1.2, # std dev of Gaussian for smoothing before expansion
                flags=0,        # no additional flags
            )
        except cv2.error as exc:
            logger.debug("Optical flow computation failed on frame pair %d/%d: %s",
                         i, i + 1, exc)
            continue

        # Convert flow (dx, dy) to magnitude and angle
        magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])

        mean_mag = float(np.mean(magnitude))
        std_mag = float(np.std(magnitude))

        # Smoothness: high when all pixels move uniformly (low std).
        # 1/(1+std) maps [0, ∞) → (0, 1] with diminishing returns for large std.
        smoothness = 1.0 / (1.0 + std_mag)

        smoothness_values.append(smoothness)
        mean_magnitudes.append(mean_mag)

    if not smoothness_values:
        # No valid frame pairs — can happen if all frames were corrupted
        return 0.0, "unknown"

    final_smoothness = float(np.mean(smoothness_values))
    clip_mean_magnitude = float(np.mean(mean_magnitudes))

    # Classify motion type by average displacement per frame-pair
    if clip_mean_magnitude < config.STATIC_THRESHOLD:
        motion_type = "static"
    elif clip_mean_magnitude < config.PAN_THRESHOLD:
        motion_type = "slow_pan"
    else:
        motion_type = "fast_flythrough"

    return final_smoothness, motion_type


def score_composition(frames: List[np.ndarray]) -> float:
    """Compute composition score using edge density as a proxy for structured content.

    Frames with rich architectural detail (building facades, windows, edges,
    leading lines) produce many Canny edges and score high.
    Frames of empty sky, bare ground, or water score low.

    A horizon penalty is applied when a dominant horizontal line is detected
    near the vertical midpoint of the frame — this pattern typically indicates
    a boring sky/ground split rather than interesting architectural content.

    UPGRADE_PATH: Replace this function with a YOLO-based detector fine-tuned
    on drone building imagery. Score a clip by the IoU of the detected building
    bounding box within the frame, optionally combined with a framing quality
    metric (rule-of-thirds alignment, building coverage %). The edge-density
    approach cannot distinguish an architectural wall from a dense hedge, which
    a subject detector would handle correctly.

    Args:
        frames: List of BGR frames at analysis resolution.

    Returns:
        Mean adjusted edge density across all valid frames.
        Range: [0, edge_density_max * HORIZON_PENALTY_MULTIPLIER] before normalization.
        Higher = more structured content in frame.
        Returns 0.0 if no valid frames remain.
    """
    scores: List[float] = []

    for frame in frames:
        if frame is None or frame.size == 0:
            continue

        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Blur first to reduce noise that would inflate the edge count
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)

            # Canny edge detection
            edges = cv2.Canny(
                blurred,
                config.CANNY_LOW_THRESHOLD,
                config.CANNY_HIGH_THRESHOLD,
            )

            h, w = edges.shape
            total_pixels = float(h * w)
            edge_density = float(np.count_nonzero(edges)) / total_pixels

            # Apply horizon penalty if a bare horizon line is detected
            horizon_multiplier = _compute_horizon_penalty(edges, h, w)
            adjusted_score = edge_density * horizon_multiplier
            scores.append(adjusted_score)

        except cv2.error as exc:
            logger.debug("Composition scoring failed on a frame: %s", exc)
            continue

    if not scores:
        return 0.0

    return float(np.mean(scores))


def _compute_horizon_penalty(edges: np.ndarray, h: int, w: int) -> float:
    """Return a penalty multiplier if a bare horizon line is detected in the frame.

    Checks for a dominant horizontal line within the configured horizon zone
    (a vertical band around the frame midpoint). If found, returns
    HORIZON_PENALTY_MULTIPLIER (< 1.0). Otherwise returns 1.0 (no penalty).

    This prevents frames that are mostly empty sky above a bare horizon from
    scoring high on composition just because the horizon edge counts.

    Args:
        edges: Binary edge map from cv2.Canny (uint8, values 0 or 255).
        h: Frame height in pixels.
        w: Frame width in pixels.

    Returns:
        config.HORIZON_PENALTY_MULTIPLIER if a qualifying horizon is detected,
        otherwise 1.0.
    """
    # Define the vertical band to search for horizon lines
    zone_top = int(h * (config.HORIZON_ZONE_CENTER - config.HORIZON_ZONE_HEIGHT / 2))
    zone_bot = int(h * (config.HORIZON_ZONE_CENTER + config.HORIZON_ZONE_HEIGHT / 2))

    # Clamp to valid range
    zone_top = max(0, zone_top)
    zone_bot = min(h, zone_bot)

    if zone_top >= zone_bot:
        return 1.0

    horizon_zone = edges[zone_top:zone_bot, :]

    # Minimum line length to qualify as a horizon (fraction of frame width)
    min_line_length = int(w * config.HORIZON_LINE_FRACTION)

    try:
        lines = cv2.HoughLinesP(
            horizon_zone,
            rho=1,
            theta=np.pi / 180,
            threshold=50,           # minimum votes to accept a line
            minLineLength=min_line_length,
            maxLineGap=20,          # allow small gaps in the detected line
        )
    except cv2.error:
        return 1.0

    if lines is None:
        return 1.0

    # Check whether any detected line is approximately horizontal (< 10° tilt)
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0:
            continue  # vertical line — skip
        angle_degrees = abs(np.degrees(np.arctan2(dy, dx)))
        if angle_degrees < 10.0:
            return config.HORIZON_PENALTY_MULTIPLIER

    return 1.0


def score_all_clips(clips: List[CandidateClip]) -> List[CandidateClip]:
    """Score all clips in a list, logging progress as a rolling count.

    Args:
        clips: List of CandidateClip instances from Stage 2.

    Returns:
        The same list with all clips scored in-place.
    """
    total = len(clips)
    logger.info("Scoring %d candidate clips...", total)

    for i, clip in enumerate(clips):
        score_clip(clip)
        if (i + 1) % 10 == 0 or (i + 1) == total:
            logger.info("  Scored %d / %d clips", i + 1, total)

    return clips
