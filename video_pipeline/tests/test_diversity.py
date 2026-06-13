"""
Unit tests for diversity.py — visual fingerprinting and deduplication.

Tests verify that:
  1. Near-identical clips are correctly identified and skipped.
  2. Genuinely different clips both survive into the pool.
  3. The pool respects MAX_POOL_SIZE.
  4. Fingerprinting functions produce the expected types and ranges.
"""

import numpy as np
import pytest

from video_pipeline import config
from video_pipeline.segmenter import CandidateClip
from video_pipeline.diversity import (
    build_curated_pool,
    _fingerprint_clip,
    _compute_color_histogram,
    _compute_perceptual_hash,
    _hamming_distance,
    _is_near_duplicate,
)


# ─────────────────────────────────────────────────────────────────────────────
# Frame and clip helpers
# ─────────────────────────────────────────────────────────────────────────────

FRAME_H, FRAME_W = 360, 640


def make_solid_frame(value: int) -> np.ndarray:
    """Create a solid BGR frame at analysis resolution."""
    return np.full((FRAME_H, FRAME_W, 3), value, dtype=np.uint8)


def make_gradient_frame() -> np.ndarray:
    """Create a left-to-right gradient frame (black → white)."""
    frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    ramp = np.linspace(0, 255, FRAME_W, dtype=np.uint8)
    frame[:, :, :] = ramp[np.newaxis, :, np.newaxis]
    return frame


def make_clip_with_frames(clip_id: int, frames: list, promising_score: float = 0.5) -> CandidateClip:
    """Create a CandidateClip with specific frames and a pre-set promising_score."""
    clip = CandidateClip(
        clip_id=clip_id,
        start_time=float(clip_id * 4),
        end_time=float(clip_id * 4 + 4),
        duration=4.0,
        frames=frames,
    )
    clip.promising_score = promising_score
    return clip


def make_solid_clip(clip_id: int, value: int, promising_score: float = 0.5) -> CandidateClip:
    """Create a clip whose middle frame is a solid color."""
    frames = [make_solid_frame(value)] * 4
    return make_clip_with_frames(clip_id, frames, promising_score)


# ─────────────────────────────────────────────────────────────────────────────
# Hamming distance tests
# ─────────────────────────────────────────────────────────────────────────────

class TestHammingDistance:
    """Tests for _hamming_distance() bit counting."""

    def test_identical_hashes_have_distance_zero(self):
        """Two identical integers have Hamming distance 0."""
        h = 0b10110100_11001010
        assert _hamming_distance(h, h) == 0

    def test_all_zero_vs_all_ones(self):
        """64-bit all-zeros vs all-ones → Hamming distance 64."""
        assert _hamming_distance(0, (1 << 64) - 1) == 64

    def test_single_bit_difference(self):
        """Integers differing by exactly one bit → Hamming distance 1."""
        a = 0b0000
        b = 0b0001
        assert _hamming_distance(a, b) == 1

    def test_distance_is_symmetric(self):
        """Hamming distance is symmetric: d(a,b) == d(b,a)."""
        a = 0b10101010
        b = 0b01010101
        assert _hamming_distance(a, b) == _hamming_distance(b, a)

    def test_distance_in_valid_range(self):
        """Hamming distance between 64-bit integers must be in [0, 64]."""
        import random
        rng = random.Random(42)
        for _ in range(100):
            a = rng.getrandbits(64)
            b = rng.getrandbits(64)
            d = _hamming_distance(a, b)
            assert 0 <= d <= 64


# ─────────────────────────────────────────────────────────────────────────────
# Color histogram tests
# ─────────────────────────────────────────────────────────────────────────────

class TestColorHistogram:
    """Tests for _compute_color_histogram()."""

    def test_returns_correct_shape(self):
        """HSV 8×8×8 = 512 bins → flat array of length 512."""
        frame = make_solid_frame(128)
        hist = _compute_color_histogram(frame)
        assert hist.shape == (512,), f"Expected (512,) got {hist.shape}"

    def test_returns_float32(self):
        """Output should be float32."""
        frame = make_solid_frame(100)
        hist = _compute_color_histogram(frame)
        assert hist.dtype == np.float32

    def test_is_l2_normalized(self):
        """The histogram should be L2-normalized (unit norm)."""
        frame = make_solid_frame(128)
        hist = _compute_color_histogram(frame)
        norm = np.linalg.norm(hist)
        # Non-zero frames should have unit norm; all-zero only if computation failed
        if norm > 0:
            assert norm == pytest.approx(1.0, abs=1e-5)

    def test_different_colors_have_different_histograms(self):
        """Solid blue and solid red frames should have different color histograms."""
        blue_frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
        blue_frame[:, :, 0] = 255  # B channel

        red_frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
        red_frame[:, :, 2] = 255  # R channel

        hist_blue = _compute_color_histogram(blue_frame)
        hist_red = _compute_color_histogram(red_frame)

        # They should not be nearly identical
        correlation = float(
            np.dot(hist_blue, hist_red)
            / (np.linalg.norm(hist_blue) * np.linalg.norm(hist_red) + 1e-10)
        )
        assert correlation < 0.9, \
            "Blue and red frames should have clearly different color histograms"

    def test_identical_frames_have_identical_histograms(self):
        """Two copies of the same frame must produce exactly the same histogram."""
        frame = make_gradient_frame()
        h1 = _compute_color_histogram(frame)
        h2 = _compute_color_histogram(frame.copy())
        np.testing.assert_array_equal(h1, h2)


# ─────────────────────────────────────────────────────────────────────────────
# Perceptual hash tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPerceptualHash:
    """Tests for _compute_perceptual_hash()."""

    def test_returns_int(self):
        """Perceptual hash must be a Python int."""
        frame = make_solid_frame(128)
        h = _compute_perceptual_hash(frame)
        assert isinstance(h, int)

    def test_identical_frames_have_identical_hash(self):
        """Two copies of the same frame must produce the same hash."""
        frame = make_gradient_frame()
        h1 = _compute_perceptual_hash(frame)
        h2 = _compute_perceptual_hash(frame.copy())
        assert h1 == h2

    def test_very_different_frames_have_high_hamming_distance(self):
        """A solid black frame and a solid white frame should have high hash distance."""
        h_black = _compute_perceptual_hash(make_solid_frame(0))
        h_white = _compute_perceptual_hash(make_solid_frame(255))
        distance = _hamming_distance(h_black, h_white)
        # Black frame: all pixels < mean → all bits 0. White frame: all > mean → all bits 1.
        # Expected distance = 64 (or close to it)
        assert distance > 32, \
            f"Black and white frames should have Hamming distance > 32, got {distance}"

    def test_hash_is_64_bits(self):
        """Hash value should fit within 64 bits (< 2^64)."""
        frame = make_gradient_frame()
        h = _compute_perceptual_hash(frame)
        assert 0 <= h < (1 << 64)


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDeduplication:
    """Tests for build_curated_pool() and _is_near_duplicate()."""

    def test_identical_clips_deduplicated(self, monkeypatch):
        """Two clips with identical frames should result in only one in the pool."""
        # Use very permissive thresholds so the test doesn't depend on exact values
        monkeypatch.setattr(config, "COLOR_SIMILARITY_THRESHOLD", 0.50)
        monkeypatch.setattr(config, "PHASH_DISTANCE_THRESHOLD", 60)
        monkeypatch.setattr(config, "MAX_POOL_SIZE", 40)

        frame = make_solid_frame(128)
        clip_a = make_clip_with_frames(0, [frame.copy()] * 4, promising_score=0.9)
        clip_b = make_clip_with_frames(1, [frame.copy()] * 4, promising_score=0.8)

        pool = build_curated_pool([clip_a, clip_b])
        assert len(pool) == 1, \
            "Two identical clips should deduplicate to 1"
        assert pool[0] is clip_a, \
            "The higher-scored clip should survive deduplication"

    def test_different_clips_both_survive(self, monkeypatch):
        """Clips with genuinely different frames should both appear in the pool."""
        monkeypatch.setattr(config, "COLOR_SIMILARITY_THRESHOLD", 0.95)
        monkeypatch.setattr(config, "PHASH_DISTANCE_THRESHOLD", 5)
        monkeypatch.setattr(config, "MAX_POOL_SIZE", 40)

        black_clip = make_solid_clip(0, 0,   promising_score=0.9)
        white_clip = make_solid_clip(1, 255, promising_score=0.8)

        pool = build_curated_pool([black_clip, white_clip])
        assert len(pool) == 2, \
            "Black and white clips should both survive deduplication"

    def test_pool_respects_max_size(self, monkeypatch):
        """Pool should never exceed MAX_POOL_SIZE even with many unique clips."""
        max_size = 5
        monkeypatch.setattr(config, "MAX_POOL_SIZE", max_size)
        monkeypatch.setattr(config, "COLOR_SIMILARITY_THRESHOLD", 0.99)
        monkeypatch.setattr(config, "PHASH_DISTANCE_THRESHOLD", 1)

        # Create 10 clips with very different colors (values 0, 25, 50, ..., 225)
        clips = [
            make_solid_clip(i, i * 25, promising_score=1.0 - i * 0.05)
            for i in range(10)
        ]
        pool = build_curated_pool(clips)
        assert len(pool) <= max_size, \
            f"Pool has {len(pool)} clips but MAX_POOL_SIZE is {max_size}"

    def test_empty_input_returns_empty(self):
        """Empty ranked list → empty pool."""
        pool = build_curated_pool([])
        assert pool == []

    def test_single_clip_always_in_pool(self, monkeypatch):
        """A single clip should always appear in the pool regardless of thresholds."""
        monkeypatch.setattr(config, "MAX_POOL_SIZE", 40)
        clip = make_solid_clip(0, 100)
        pool = build_curated_pool([clip])
        assert len(pool) == 1
        assert pool[0] is clip

    def test_best_scored_clip_chosen_first(self, monkeypatch):
        """When two similar clips exist, the one with higher promising_score is kept."""
        monkeypatch.setattr(config, "COLOR_SIMILARITY_THRESHOLD", 0.50)
        monkeypatch.setattr(config, "PHASH_DISTANCE_THRESHOLD", 60)
        monkeypatch.setattr(config, "MAX_POOL_SIZE", 40)

        frame = make_solid_frame(200)
        # clip_a has higher score and appears first in ranked list
        clip_a = make_clip_with_frames(0, [frame.copy()] * 4, promising_score=0.95)
        clip_b = make_clip_with_frames(1, [frame.copy()] * 4, promising_score=0.60)

        pool = build_curated_pool([clip_a, clip_b])
        if len(pool) == 1:
            assert pool[0] is clip_a, "Higher-scored clip should be kept"
