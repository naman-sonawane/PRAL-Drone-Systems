"""
Stage 7 — Clip Selection

For each style, filters the curated pool by the style's motion type preferences,
orders clips according to the style's ordering strategy, and greedily selects
clips until the target duration is filled.

Key design decisions:
  - Motion type filter can be relaxed to the full pool if too few clips match.
    This prevents styles from silently producing empty output on footage that
    doesn't have the "right" kind of movement.
  - hero_shot_mode bypasses all duration logic and returns exactly 1 clip.
  - timelapse_feel uses bypass_duration_guards to allow clip_duration_max < MIN_CLIP_DURATION.
  - golden_hour uses score_weight_overrides to re-weight signals at selection time,
    reordering clips differently from the global promising_score rank.
"""

import logging
from typing import List, Optional

import numpy as np

from . import config
from .segmenter import CandidateClip
from .styles import StyleConfig

logger = logging.getLogger(__name__)


def select_clips(
    pool: List[CandidateClip], style: StyleConfig
) -> List[CandidateClip]:
    """Select clips from the curated pool for a given style.

    Steps:
      1. Filter by preferred motion types (relax if too few match).
      2. Filter by clip duration bounds (skip if bypass_duration_guards).
      3. Truncate clips longer than style.clip_duration_max.
      4. Compute style-specific scores (using weight overrides if configured).
      5. Order by style.ordering_strategy.
      6. Greedily fill to style.target_total_duration.

    hero_shot_mode: if set on the style, skip steps 5-6 and return the single
    highest-scored clip that matches the duration bounds.

    Args:
        pool: Curated pool of diverse, high-quality CandidateClips (Stage 5).
        style: StyleConfig defining preferences and parameters.

    Returns:
        Ordered list of CandidateClips selected for this style's video.
        May be empty if no clips survive filtering.
    """
    logger.info("Selecting clips for style '%s' ...", style.name)

    if not pool:
        logger.warning("Empty pool for style '%s'; no clips to select", style.name)
        return []

    # Step 1: Motion type filter
    candidates = _filter_by_motion_type(pool, style)

    # Step 2 & 3: Duration filter and truncation
    candidates = _filter_and_truncate_durations(candidates, style)

    if not candidates:
        logger.warning(
            "Style '%s': no clips remain after filtering; "
            "check motion type preferences and duration bounds",
            style.name,
        )
        return []

    # Step 4: Compute style-specific score for ordering
    _compute_style_scores(candidates, style)

    # Special case: hero_shot_mode — return only the single best clip
    if style.hero_shot_mode:
        return _select_hero_shot(candidates, style)

    # Step 5: Order by strategy
    ordered = _apply_ordering_strategy(candidates, style)

    # Step 6: Greedy duration fill
    selected = _greedy_fill(ordered, style)

    _log_selection(selected, style)
    return selected


def _filter_by_motion_type(
    pool: List[CandidateClip], style: StyleConfig
) -> List[CandidateClip]:
    """Filter pool to clips whose motion_type is in style.preferred_motion_types.

    If fewer than MIN_CLIPS_FOR_STYLE clips match, relaxes to the full pool
    and logs a warning. This handles footage that doesn't have enough of the
    "right" motion type for the style.

    Args:
        pool: Full curated pool.
        style: Style config with preferred_motion_types.

    Returns:
        Filtered (or full, if relaxed) list of clips.
    """
    preferred = set(style.preferred_motion_types)
    filtered = [c for c in pool if c.motion_type in preferred]

    if len(filtered) >= config.MIN_CLIPS_FOR_STYLE:
        logger.info(
            "Style '%s': %d / %d pool clips match preferred motion types %s",
            style.name, len(filtered), len(pool), sorted(preferred),
        )
        return filtered
    else:
        logger.warning(
            "Style '%s': only %d clips match preferred motion types %s "
            "(minimum %d required). Using full pool of %d clips.",
            style.name, len(filtered), sorted(preferred),
            config.MIN_CLIPS_FOR_STYLE, len(pool),
        )
        return list(pool)


def _filter_and_truncate_durations(
    clips: List[CandidateClip], style: StyleConfig
) -> List[CandidateClip]:
    """Discard clips shorter than style.clip_duration_min; truncate longer ones.

    Truncation adjusts clip.end_time (and clip.duration) so that Stage 8
    only renders the first clip_duration_max seconds. The source file and
    analysis frames are not modified.

    The bypass_duration_guards flag suppresses the minimum-duration check,
    which is necessary for timelapse_feel where clip_duration_max=1.0 is
    below the global MIN_CLIP_DURATION=2.0.

    Args:
        clips: Clips after motion type filtering.
        style: Style config with duration bounds and bypass flag.

    Returns:
        Clips that passed the minimum duration check (if applicable),
        with end_time adjusted for those exceeding the maximum.
    """
    result: List[CandidateClip] = []

    for clip in clips:
        effective_duration = clip.end_time - clip.start_time

        # Minimum duration check (skip if bypassed)
        if not style.bypass_duration_guards:
            if effective_duration < style.clip_duration_min:
                logger.debug(
                    "Style '%s': clip %d (%.1fs) below clip_duration_min %.1fs; skipping",
                    style.name, clip.clip_id, effective_duration, style.clip_duration_min,
                )
                continue

        # Truncate clips that exceed the maximum duration.
        # We work with a temporary effective end_time on the clip object.
        # This is safe because selector.py is called per-style; the original
        # end_time isn't overwritten across styles.
        if effective_duration > style.clip_duration_max:
            clip.end_time = clip.start_time + style.clip_duration_max
            clip.duration = style.clip_duration_max

        result.append(clip)

    logger.info(
        "Style '%s': %d clips after duration filter "
        "(min=%.1fs, max=%.1fs, bypass=%s)",
        style.name, len(result),
        style.clip_duration_min, style.clip_duration_max,
        style.bypass_duration_guards,
    )
    return result


def _compute_style_scores(clips: List[CandidateClip], style: StyleConfig) -> None:
    """Compute a style-specific ordering score for each clip.

    If the style has score_weight_overrides, compute a weighted sum using
    those weights applied to the already-normalized signal scores. Store
    the result in a temporary attribute _style_score (not a dataclass field).

    If no overrides, _style_score = clip.promising_score (global ranking).

    This allows golden_hour (which boosts exposure weight) to genuinely
    reorder clips relative to the global rank without affecting other styles.

    Args:
        clips: Clips to score.
        style: Style config, possibly with score_weight_overrides.
    """
    overrides = style.score_weight_overrides

    for clip in clips:
        if overrides is not None:
            score = (
                overrides.get("sharpness",   0.0) * clip.sharpness_norm
                + overrides.get("smoothness",  0.0) * clip.smoothness_norm
                + overrides.get("composition", 0.0) * clip.composition_norm
                + overrides.get("exposure",    0.0) * clip.exposure_norm
            )
        else:
            score = clip.promising_score

        # Store on the object at runtime without polluting the dataclass schema
        clip._style_score = score  # type: ignore[attr-defined]


def _apply_ordering_strategy(
    clips: List[CandidateClip], style: StyleConfig
) -> List[CandidateClip]:
    """Order clips according to style.ordering_strategy.

    Strategies:
      "best_first":      descending by _style_score; best clip leads.
      "build_to_climax": ascending for first 80%, best clip placed last.
      "static_first":    all static clips (by score desc), then all others (by score desc).
      "none":            return as-is (used for hero_shot_mode).

    Args:
        clips: Clips with _style_score set by _compute_style_scores.
        style: Style config with ordering_strategy.

    Returns:
        Reordered list of clips.
    """
    strategy = style.ordering_strategy

    def style_score(c: CandidateClip) -> float:
        return getattr(c, "_style_score", c.promising_score)

    if strategy == "best_first":
        return sorted(clips, key=style_score, reverse=True)

    elif strategy == "build_to_climax":
        # Sort ascending; move the single best clip to the end
        ascending = sorted(clips, key=style_score, reverse=False)
        if not ascending:
            return ascending
        # Find the overall best clip (highest score)
        best_idx = max(range(len(ascending)), key=lambda i: style_score(ascending[i]))
        best_clip = ascending.pop(best_idx)
        ascending.append(best_clip)
        return ascending

    elif strategy == "static_first":
        static_clips = sorted(
            [c for c in clips if c.motion_type == "static"],
            key=style_score, reverse=True,
        )
        other_clips = sorted(
            [c for c in clips if c.motion_type != "static"],
            key=style_score, reverse=True,
        )
        return static_clips + other_clips

    elif strategy == "none":
        return list(clips)

    else:
        logger.warning(
            "Unknown ordering strategy '%s' for style '%s'; defaulting to best_first",
            strategy, style.name,
        )
        return sorted(clips, key=style_score, reverse=True)


def _select_hero_shot(
    candidates: List[CandidateClip], style: StyleConfig
) -> List[CandidateClip]:
    """Select exactly one clip for hero_shot_mode: the highest style-scored clip.

    Args:
        candidates: Clips that survived motion type and duration filters.
        style: Style config (used only for logging).

    Returns:
        Single-element list containing the highest-scored clip.
        Empty list if candidates is empty.
    """
    if not candidates:
        return []

    def style_score(c: CandidateClip) -> float:
        return getattr(c, "_style_score", c.promising_score)

    best = max(candidates, key=style_score)
    logger.info(
        "Style '%s' (hero_shot): selected clip %d [%.1f–%.1fs] "
        "score=%.3f type=%s",
        style.name, best.clip_id, best.start_time, best.end_time,
        style_score(best), best.motion_type,
    )
    return [best]


def _greedy_fill(
    ordered: List[CandidateClip], style: StyleConfig
) -> List[CandidateClip]:
    """Greedily select clips from the ordered list until the target duration is met.

    Adds a clip to the selection if:
        total_duration + clip.duration <= style.target_total_duration + DURATION_TOLERANCE

    Stops when:
        total_duration >= style.target_total_duration - DURATION_TOLERANCE
        OR the ordered list is exhausted.

    Args:
        ordered: Clips in the desired output order.
        style: Style config with target_total_duration.

    Returns:
        Selected clips in the order they should appear in the final video.
    """
    selected: List[CandidateClip] = []
    total_duration = 0.0
    target = style.target_total_duration
    tolerance = config.DURATION_TOLERANCE

    for clip in ordered:
        # Stop if we've already hit the target (within tolerance)
        if total_duration >= target - tolerance:
            break

        # Accept this clip if it fits within the budget (with tolerance)
        if total_duration + clip.duration <= target + tolerance:
            selected.append(clip)
            total_duration += clip.duration
            logger.debug(
                "  +clip %d [%.1f–%.1fs, %.1fs] → total=%.1fs",
                clip.clip_id, clip.start_time, clip.end_time,
                clip.duration, total_duration,
            )

    if not selected:
        logger.warning(
            "Style '%s': greedy fill produced 0 clips (target %.1fs, "
            "%d ordered candidates available)",
            style.name, target, len(ordered),
        )
    elif total_duration < target - tolerance:
        logger.warning(
            "Style '%s': only %.1fs selected (target %.1fs); "
            "not enough footage in curated pool",
            style.name, total_duration, target,
        )

    return selected


def _log_selection(selected: List[CandidateClip], style: StyleConfig) -> None:
    """Log a summary of the selected clips for the style.

    Args:
        selected: Final ordered list of selected clips.
        style: Style config (for logging context).
    """
    total = sum(c.duration for c in selected)
    logger.info(
        "Style '%s': selected %d clips, total duration %.1fs "
        "(target %.1fs)",
        style.name, len(selected), total, style.target_total_duration,
    )
    for i, clip in enumerate(selected, 1):
        def _ss(c: CandidateClip) -> float:
            return getattr(c, "_style_score", c.promising_score)
        logger.info(
            "  [%2d] clip %d  %.1f–%.1fs  (%.1fs)  %s  score=%.3f",
            i, clip.clip_id, clip.start_time, clip.end_time,
            clip.duration, clip.motion_type, _ss(clip),
        )
