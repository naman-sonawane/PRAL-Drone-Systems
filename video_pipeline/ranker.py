"""
Stage 4 — Ranking

Normalizes raw scores from Stage 3 to a common [0, 1] scale, applies hard
quality filters that discard unrecoverable clips, then combines the normalized
scores into a single promising_score for each survivor.

Two concepts are kept strictly separate:
  - Hard filters: binary gates. A clip below MIN_SHARPNESS or MIN_SMOOTHNESS
    is discarded entirely, regardless of how well it scores on other signals.
    Blurry and shaky footage is never redeemable by good composition.
  - Weighted combination: only applied to clips that passed the hard filters.
    Weights are configurable in config.py and must sum to 1.0.
"""

import logging
from typing import List, Tuple

import numpy as np

from . import config
from .segmenter import CandidateClip

logger = logging.getLogger(__name__)

# Small epsilon used to prevent division by zero when all clips have the same
# raw score for a given signal (max == min). Produces 0.5 for all such clips.
_NORM_EPSILON = 1e-6


def rank(clips: List[CandidateClip]) -> List[CandidateClip]:
    """Apply hard filters, normalize scores, compute promising_score, sort.

    This is the main entry point for Stage 4. It modifies clips in-place
    (setting *_norm, promising_score, passed_hard_filter) and returns the
    subset that passed the hard filters, sorted descending by promising_score.

    Args:
        clips: All scored CandidateClips from Stage 3. Expected to have
            sharpness_raw, exposure_raw, smoothness_raw, composition_raw set.

    Returns:
        Filtered and sorted list of CandidateClips. Clips that failed either
        hard filter are excluded entirely. Empty list if nothing survived.

    Raises:
        ValueError: If the configured score weights do not sum to 1.0.
    """
    _validate_weights()

    if not clips:
        logger.warning("Ranking received empty clip list")
        return []

    logger.info("Ranking %d clips (hard filter: sharpness ≥ %.1f, smoothness ≥ %.2f) ...",
                len(clips), config.MIN_SHARPNESS, config.MIN_SMOOTHNESS)

    # Step 1: Hard filters — mark and partition
    survivors, rejected = _apply_hard_filters(clips)

    logger.info(
        "Hard filter: %d / %d clips survived (%.0f%% pass rate); "
        "%d rejected (sharpness or smoothness below threshold)",
        len(survivors), len(clips),
        100 * len(survivors) / len(clips) if clips else 0,
        len(rejected),
    )

    if not survivors:
        logger.warning(
            "All %d clips failed the hard filter. Check footage quality — "
            "likely too blurry (MIN_SHARPNESS=%.1f) or too shaky "
            "(MIN_SMOOTHNESS=%.2f). Try lowering thresholds in config.py.",
            len(clips), config.MIN_SHARPNESS, config.MIN_SMOOTHNESS,
        )
        return []

    # Step 2: Normalize each signal across the surviving batch
    _normalize_scores(survivors)

    # Step 3: Weighted combination → promising_score
    for clip in survivors:
        clip.promising_score = _compute_promising_score(clip)

    # Step 4: Sort descending
    survivors.sort(key=lambda c: c.promising_score, reverse=True)

    # Log top 10 for demo-friendly console output
    _log_top_clips(survivors)

    return survivors


def _validate_weights() -> None:
    """Verify that configured weights sum to 1.0.

    Args: None (reads from config module).

    Raises:
        ValueError: If weights do not sum to 1.0 within a small tolerance.
    """
    total = (
        config.WEIGHT_SHARPNESS
        + config.WEIGHT_SMOOTHNESS
        + config.WEIGHT_COMPOSITION
        + config.WEIGHT_EXPOSURE
    )
    if abs(total - 1.0) > 1e-4:
        raise ValueError(
            f"Score weights in config.py must sum to 1.0, "
            f"but sum is {total:.6f}. "
            f"(sharpness={config.WEIGHT_SHARPNESS}, "
            f"smoothness={config.WEIGHT_SMOOTHNESS}, "
            f"composition={config.WEIGHT_COMPOSITION}, "
            f"exposure={config.WEIGHT_EXPOSURE})"
        )


def _apply_hard_filters(
    clips: List[CandidateClip],
) -> Tuple[List[CandidateClip], List[CandidateClip]]:
    """Partition clips into survivors and rejected based on hard thresholds.

    Sets clip.passed_hard_filter on every clip. Returns two lists:
    (survivors, rejected). Neither the clip list nor individual clips are
    modified beyond setting passed_hard_filter.

    Args:
        clips: All scored clips.

    Returns:
        Tuple of (survivors, rejected) where survivors passed both thresholds.
    """
    survivors: List[CandidateClip] = []
    rejected: List[CandidateClip] = []

    for clip in clips:
        sharp_ok = clip.sharpness_raw >= config.MIN_SHARPNESS
        smooth_ok = clip.smoothness_raw >= config.MIN_SMOOTHNESS

        if sharp_ok and smooth_ok:
            clip.passed_hard_filter = True
            survivors.append(clip)
        else:
            clip.passed_hard_filter = False
            rejected.append(clip)

            reasons = []
            if not sharp_ok:
                reasons.append(
                    f"sharpness {clip.sharpness_raw:.1f} < {config.MIN_SHARPNESS:.1f}"
                )
            if not smooth_ok:
                reasons.append(
                    f"smoothness {clip.smoothness_raw:.3f} < {config.MIN_SMOOTHNESS:.2f}"
                )
            logger.debug(
                "Clip %d [%.1f–%.1fs] rejected: %s",
                clip.clip_id, clip.start_time, clip.end_time,
                " AND ".join(reasons),
            )

    return survivors, rejected


def _normalize_scores(clips: List[CandidateClip]) -> None:
    """Normalize all four raw signals to [0, 1] across the given clip list.

    Normalization is min-max scaling:
        score_norm = (score_raw - min_raw) / (max_raw - min_raw + ε)

    When all clips have the same raw value for a signal (max == min), the
    epsilon in the denominator prevents division by zero; all clips receive 0.5.

    Modifies clips in-place (sets sharpness_norm, exposure_norm,
    smoothness_norm, composition_norm).

    Args:
        clips: Surviving clips whose *_raw fields are already populated.
    """
    for attr, norm_attr in [
        ("sharpness_raw",   "sharpness_norm"),
        ("exposure_raw",    "exposure_norm"),
        ("smoothness_raw",  "smoothness_norm"),
        ("composition_raw", "composition_norm"),
    ]:
        raw_values = [getattr(c, attr) for c in clips]
        min_val = float(min(raw_values))
        max_val = float(max(raw_values))
        span = max_val - min_val + _NORM_EPSILON

        for clip in clips:
            raw = getattr(clip, attr)
            normalized = (raw - min_val) / span
            setattr(clip, norm_attr, float(np.clip(normalized, 0.0, 1.0)))

        logger.debug(
            "Normalized %s: range [%.3f, %.3f]",
            attr, min_val, max_val,
        )


def _compute_promising_score(clip: CandidateClip) -> float:
    """Compute the final weighted promising_score for a single clip.

    Uses the global weights from config.py. Style-specific weight overrides
    are applied in selector.py when computing per-style ordering scores.

    Args:
        clip: A clip whose *_norm fields have been set by _normalize_scores.

    Returns:
        Weighted sum in [0, 1].
    """
    return (
        config.WEIGHT_SHARPNESS   * clip.sharpness_norm
        + config.WEIGHT_SMOOTHNESS  * clip.smoothness_norm
        + config.WEIGHT_COMPOSITION * clip.composition_norm
        + config.WEIGHT_EXPOSURE    * clip.exposure_norm
    )


def _log_top_clips(sorted_clips: List[CandidateClip], n: int = 10) -> None:
    """Print a formatted table of the top-N clips for demo-friendly console output.

    Args:
        sorted_clips: Clips sorted descending by promising_score.
        n: How many top clips to include in the table.
    """
    top = sorted_clips[:n]
    header = (
        f"{'ID':>4}  {'Start':>6}  {'End':>6}  {'Type':<16}  "
        f"{'Sharp':>6}  {'Smooth':>6}  {'Comp':>6}  {'Exp':>6}  {'Score':>6}"
    )
    separator = "-" * len(header)

    lines = [
        f"\nTop {len(top)} clips (of {len(sorted_clips)} survivors):",
        separator,
        header,
        separator,
    ]
    for clip in top:
        lines.append(
            f"{clip.clip_id:>4}  "
            f"{clip.start_time:>5.1f}s  "
            f"{clip.end_time:>5.1f}s  "
            f"{clip.motion_type:<16}  "
            f"{clip.sharpness_raw:>6.1f}  "
            f"{clip.smoothness_raw:>6.3f}  "
            f"{clip.composition_raw:>6.4f}  "
            f"{clip.exposure_raw:>6.3f}  "
            f"{clip.promising_score:>6.3f}"
        )
    lines.append(separator)

    for line in lines:
        logger.info(line)
