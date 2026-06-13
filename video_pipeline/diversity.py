"""
Stage 5 — Diversity Filtering

Prevents the curated pool from being dominated by near-duplicate clips.
When the drone holds a position for 30 seconds, the sliding window produces
many overlapping clips that are visually identical — all individually good,
but redundant. This stage deduplicates them while keeping variety.

Two fingerprint signals are used in combination:
  - Color histogram: catches clips with the same overall color distribution
    (same angle/lighting conditions at a given position).
  - Perceptual hash (aHash): catches clips with the same spatial structure
    even if the color processing differs slightly.

Both signals must agree for a clip to be considered a near-duplicate.
Using both prevents false positives: two clips of opposite sides of the
building may share similar color histograms (both gray concrete in daylight)
but differ sharply in perceptual hash. Requiring BOTH signals to match is
the correct approach.
"""

import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import config
from .segmenter import CandidateClip

logger = logging.getLogger(__name__)


def build_curated_pool(ranked_clips: List[CandidateClip]) -> List[CandidateClip]:
    """Build a diverse curated pool from the ranked survivor list.

    Iterates ranked_clips in order (highest promising_score first). For each
    clip, computes its visual fingerprint and checks it against clips already
    in the pool. If the clip is a near-duplicate of any pool clip, it is
    skipped. Otherwise, it is added to the pool.

    Stops when the pool reaches MAX_POOL_SIZE or the ranked list is exhausted.

    Args:
        ranked_clips: Clips sorted descending by promising_score (from Stage 4).

    Returns:
        curated_pool: Up to MAX_POOL_SIZE diverse clips, ordered from highest
            to lowest promising_score (the greedy selection order).
    """
    if not ranked_clips:
        logger.warning("Diversity filtering received empty clip list")
        return []

    logger.info(
        "Diversity filtering %d ranked clips (target pool size: %d) ...",
        len(ranked_clips), config.MAX_POOL_SIZE,
    )

    curated_pool: List[CandidateClip] = []
    duplicates_skipped = 0

    for clip in ranked_clips:
        if len(curated_pool) >= config.MAX_POOL_SIZE:
            logger.debug("Pool full at %d clips; stopping", config.MAX_POOL_SIZE)
            break

        # Compute fingerprint for this clip (sets clip.color_hist and clip.phash)
        _fingerprint_clip(clip)

        # Check for near-duplicates in the existing pool
        if _is_near_duplicate(clip, curated_pool):
            duplicates_skipped += 1
            logger.debug(
                "Clip %d [%.1f–%.1fs] skipped: near-duplicate of an existing pool clip",
                clip.clip_id, clip.start_time, clip.end_time,
            )
            continue

        curated_pool.append(clip)
        logger.debug(
            "Pool +clip %d [%.1f–%.1fs] score=%.3f type=%s  (pool size: %d)",
            clip.clip_id, clip.start_time, clip.end_time,
            clip.promising_score, clip.motion_type, len(curated_pool),
        )

    logger.info(
        "Diversity filtering complete: %d clips evaluated, "
        "%d duplicates skipped, %d clips in curated pool",
        len(ranked_clips), duplicates_skipped, len(curated_pool),
    )

    return curated_pool


def _fingerprint_clip(clip: CandidateClip) -> None:
    """Compute and store a visual fingerprint for a clip in-place.

    Uses the middle frame of the clip as the representative frame.
    Sets clip.color_hist (L2-normalized HSV histogram) and clip.phash
    (64-bit perceptual hash as an int).

    If the clip has no valid middle frame, sets fingerprint to sentinel
    values that will never match any other clip (phash=0 with a specific
    all-zero color_hist — the comparison thresholds are set so that an
    all-zero histogram has low correlation with any real frame).

    Args:
        clip: CandidateClip with frames populated.
    """
    if not clip.frames:
        clip.color_hist = np.zeros(512, dtype=np.float32)  # 8*8*8 = 512 bins
        clip.phash = 0
        return

    middle_idx = len(clip.frames) // 2
    frame = clip.frames[middle_idx]

    if frame is None or frame.size == 0:
        clip.color_hist = np.zeros(512, dtype=np.float32)
        clip.phash = 0
        return

    clip.color_hist = _compute_color_histogram(frame)
    clip.phash = _compute_perceptual_hash(frame)


def _compute_color_histogram(frame: np.ndarray) -> np.ndarray:
    """Compute an L2-normalized 3D HSV color histogram for a frame.

    Uses 8 bins per channel (H, S, V) → 512 total bins. HSV is more
    meaningful than BGR for perceptual similarity: H captures hue
    (what color), S captures saturation (how colorful), V captures
    brightness (how bright). Splitting into bins of 8 each gives enough
    resolution to distinguish "blue sky" from "golden sunset" while
    remaining robust to small color shifts.

    Args:
        frame: BGR uint8 ndarray at analysis resolution.

    Returns:
        L2-normalized flat float32 array of length 512 (8×8×8 bins).
        All-zero array if the frame cannot be processed.
    """
    try:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        # H: 0–179, S: 0–255, V: 0–255 in OpenCV's HSV representation
        hist = cv2.calcHist(
            [hsv],
            [0, 1, 2],          # all three channels
            None,               # no mask
            [8, 8, 8],          # 8 bins per channel
            [0, 180, 0, 256, 0, 256],  # ranges for H, S, V
        )
        flat = hist.flatten()

        # L2 normalize so that scale differences don't affect similarity
        norm = np.linalg.norm(flat)
        if norm > 0:
            flat = flat / norm

        return flat.astype(np.float32)

    except cv2.error as exc:
        logger.debug("Color histogram computation failed: %s", exc)
        return np.zeros(512, dtype=np.float32)


def _compute_perceptual_hash(frame: np.ndarray) -> int:
    """Compute a 64-bit average hash (aHash) for a frame.

    Algorithm:
      1. Resize frame to 8×8 pixels (bicubic for quality)
      2. Convert to grayscale
      3. Compute mean pixel value
      4. Each pixel → 1 if above mean, 0 otherwise
      5. Pack 64 bits into a Python int (bit order: row-major)

    This hash captures the spatial structure of the image at a coarse level.
    Two images with the same overall layout (sky above building, building in
    center) will have similar hashes regardless of color temperature or
    minor exposure differences.

    Hamming distance < PHASH_DISTANCE_THRESHOLD (default 8) indicates
    similar spatial structure. A perfectly identical image has distance 0;
    a random hash has expected distance 32 from any other hash.

    Args:
        frame: BGR uint8 ndarray.

    Returns:
        64-bit integer perceptual hash. Returns 0 on failure.
    """
    try:
        # Resize to 8×8 using INTER_CUBIC for quality at very small scales
        small = cv2.resize(frame, (8, 8), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        mean_val = float(np.mean(gray))

        # Build bit string: 1 if pixel >= mean, 0 otherwise
        bits = (gray.flatten() >= mean_val).astype(np.uint8)

        # Pack into a single 64-bit integer (bit 63 = first pixel, bit 0 = last)
        hash_val = 0
        for bit in bits:
            hash_val = (hash_val << 1) | int(bit)

        return hash_val

    except (cv2.error, ValueError) as exc:
        logger.debug("Perceptual hash computation failed: %s", exc)
        return 0


def _is_near_duplicate(
    candidate: CandidateClip, pool: List[CandidateClip]
) -> bool:
    """Check whether a candidate clip is a near-duplicate of any clip in the pool.

    A clip is a near-duplicate if BOTH of the following hold against any
    pool clip:
      - Color histogram correlation > COLOR_SIMILARITY_THRESHOLD (default 0.92)
      - Perceptual hash Hamming distance < PHASH_DISTANCE_THRESHOLD (default 8)

    Requiring both signals prevents false positives from either metric alone.

    Args:
        candidate: The clip being evaluated. Must have color_hist and phash set.
        pool: Current curated pool. All clips must have color_hist and phash set.

    Returns:
        True if the candidate is a near-duplicate of any existing pool clip.
    """
    if candidate.color_hist is None:
        return False  # no fingerprint → cannot be a duplicate → accept

    for pool_clip in pool:
        if pool_clip.color_hist is None:
            continue

        # Signal 1: color histogram correlation
        color_corr = float(
            cv2.compareHist(
                candidate.color_hist,
                pool_clip.color_hist,
                cv2.HISTCMP_CORREL,
            )
        )
        if color_corr <= config.COLOR_SIMILARITY_THRESHOLD:
            continue  # colors differ → not a duplicate

        # Signal 2: perceptual hash Hamming distance
        hamming = _hamming_distance(candidate.phash, pool_clip.phash)
        if hamming >= config.PHASH_DISTANCE_THRESHOLD:
            continue  # structure differs → not a duplicate

        # Both signals agree: near-duplicate
        logger.debug(
            "Near-duplicate: clip %d vs pool clip %d "
            "(color_corr=%.3f, hamming=%d)",
            candidate.clip_id, pool_clip.clip_id, color_corr, hamming,
        )
        return True

    return False


def _hamming_distance(a: int, b: int) -> int:
    """Compute the Hamming distance between two 64-bit integers.

    Counts the number of bit positions that differ. Equivalently, counts
    the number of 1-bits in (a XOR b).

    Args:
        a: First 64-bit integer hash.
        b: Second 64-bit integer hash.

    Returns:
        Integer in [0, 64] — the number of differing bit positions.
    """
    return bin(a ^ b).count("1")
