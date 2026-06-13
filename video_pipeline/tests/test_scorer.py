"""
Unit tests for scorer.py — the four quality-signal functions.

All tests use synthetic frames (NumPy arrays) so they run without any video
file on disk. The goal is to verify that the mathematical logic of each
scoring function produces the right relative ordering and edge-case behavior,
independently of any specific threshold values in config.py.

Frame helper conventions:
  - All frames are 360×640, 3-channel BGR, uint8 (matching ANALYSIS_RESOLUTION).
  - "Blank" = solid black (no edges, shadows everywhere).
  - "White" = solid white (no edges, highlights everywhere).
  - "Gray" = solid 50% gray (no edges, good exposure).
  - "Gradient" = left-to-right linear ramp black→white (edges at every column).
  - "Checkerboard" = alternating 20×20 black/white blocks (maximum edges).
  - "Checkerboard" has the highest Laplacian variance of any synthetic frame.
"""

import numpy as np
import pytest

from video_pipeline.scorer import (
    score_sharpness,
    score_exposure,
    score_motion,
    score_composition,
    score_clip,
)
from video_pipeline.segmenter import CandidateClip


# ─────────────────────────────────────────────────────────────────────────────
# Frame factories
# ─────────────────────────────────────────────────────────────────────────────

FRAME_H, FRAME_W = 360, 640


def make_solid(value: int) -> np.ndarray:
    """Create a BGR frame filled with a single grayscale value."""
    return np.full((FRAME_H, FRAME_W, 3), value, dtype=np.uint8)


def make_gradient() -> np.ndarray:
    """Create a BGR frame with a left-to-right linear ramp (black → white)."""
    frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    ramp = np.linspace(0, 255, FRAME_W, dtype=np.uint8)
    frame[:, :, 0] = ramp  # B channel
    frame[:, :, 1] = ramp  # G channel
    frame[:, :, 2] = ramp  # R channel
    return frame


def make_checkerboard(block_size: int = 20) -> np.ndarray:
    """Create a BGR frame with black/white checkerboard blocks.

    This is the 'maximum edges' frame — every block boundary is a sharp edge.
    """
    frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    for y in range(FRAME_H):
        for x in range(FRAME_W):
            if (y // block_size + x // block_size) % 2 == 0:
                frame[y, x, :] = 255
    return frame


def make_horizontal_band(upper_value: int = 200, lower_value: int = 50) -> np.ndarray:
    """Create a frame with a horizontal light/dark split at the midpoint.

    Simulates a sky/ground horizon composition. The horizontal edge at the
    midpoint should trigger the horizon penalty in score_composition.
    """
    frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    mid = FRAME_H // 2
    frame[:mid, :, :] = upper_value   # upper half (sky)
    frame[mid:, :, :] = lower_value   # lower half (ground)
    return frame


def make_identical_sequence(n: int = 5) -> list:
    """Create a list of n identical mid-gray frames for zero-motion testing."""
    frame = make_solid(128)
    return [frame.copy() for _ in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
# Sharpness tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSharpness:
    """Tests for score_sharpness() using Laplacian variance."""

    def test_solid_black_is_zero(self):
        """A uniform black frame has no edges → Laplacian variance = 0."""
        frames = [make_solid(0)]
        score = score_sharpness(frames)
        assert score == pytest.approx(0.0, abs=1e-6), \
            "Solid black frame should have Laplacian variance ≈ 0"

    def test_solid_white_is_zero(self):
        """A uniform white frame has no edges → Laplacian variance = 0."""
        frames = [make_solid(255)]
        score = score_sharpness(frames)
        assert score == pytest.approx(0.0, abs=1e-6), \
            "Solid white frame should have Laplacian variance ≈ 0"

    def test_solid_gray_is_zero(self):
        """A uniform gray frame has no edges → Laplacian variance = 0."""
        frames = [make_solid(128)]
        score = score_sharpness(frames)
        assert score == pytest.approx(0.0, abs=1e-6), \
            "Solid gray frame should have Laplacian variance ≈ 0"

    def test_gradient_is_nonzero(self):
        """A gradient frame has edges at every column → positive variance."""
        frames = [make_gradient()]
        score = score_sharpness(frames)
        assert score > 0.0, \
            "Gradient frame should have positive Laplacian variance"

    def test_checkerboard_exceeds_gradient(self):
        """Checkerboard has more edges than a gradient → higher sharpness score."""
        checker_score = score_sharpness([make_checkerboard()])
        gradient_score = score_sharpness([make_gradient()])
        assert checker_score > gradient_score, \
            "Checkerboard (max edges) should score higher than gradient"

    def test_empty_frames_returns_zero(self):
        """Empty frame list → 0.0, no exception."""
        assert score_sharpness([]) == 0.0

    def test_none_frames_are_skipped(self):
        """None entries in the frame list are silently skipped."""
        frames = [None, make_gradient(), None]
        score = score_sharpness(frames)
        gradient_only = score_sharpness([make_gradient()])
        assert score == pytest.approx(gradient_only, rel=1e-5)

    def test_multiple_frames_averaged(self):
        """Score across multiple frames should be the mean of per-frame scores."""
        black = make_solid(0)
        checker = make_checkerboard()
        score_combined = score_sharpness([black, checker])
        score_checker_only = score_sharpness([checker])
        # Combined should be lower than checker-only (black contributes 0)
        assert score_combined < score_checker_only


# ─────────────────────────────────────────────────────────────────────────────
# Exposure tests
# ─────────────────────────────────────────────────────────────────────────────

class TestExposure:
    """Tests for score_exposure() using brightness histogram analysis."""

    def test_solid_white_penalized(self):
        """All-white frame → all pixels are blown highlights → negative or low score."""
        frames = [make_solid(255)]
        score = score_exposure(frames)
        # All pixels in highlight zone → heavy penalty
        assert score < 0.0, \
            "All-white (blown highlights) should produce a negative exposure score"

    def test_solid_black_penalized(self):
        """All-black frame → all pixels are crushed shadows → negative or low score."""
        frames = [make_solid(0)]
        score = score_exposure(frames)
        assert score < 0.0, \
            "All-black (crushed shadows) should produce a negative exposure score"

    def test_midtone_beats_white(self):
        """Mid-gray frame (good exposure) should score higher than all-white."""
        mid_score = score_exposure([make_solid(128)])
        white_score = score_exposure([make_solid(255)])
        assert mid_score > white_score, \
            "Mid-gray (good exposure) should outscore all-white (blown)"

    def test_midtone_beats_black(self):
        """Mid-gray frame should score higher than all-black."""
        mid_score = score_exposure([make_solid(128)])
        black_score = score_exposure([make_solid(0)])
        assert mid_score > black_score, \
            "Mid-gray (good exposure) should outscore all-black (crushed)"

    def test_midtone_is_positive(self):
        """Pure midtone frame → all pixels in midtone zone → positive score."""
        frames = [make_solid(128)]
        score = score_exposure(frames)
        # midtone_fraction ≈ 1.0, so score ≈ 1.0 - 0 - 0 = 1.0
        assert score > 0.8, \
            "Pure midtone frame should have exposure score close to 1.0"

    def test_empty_frames_returns_zero(self):
        """Empty frame list → 0.0."""
        assert score_exposure([]) == 0.0

    def test_gradient_moderate_score(self):
        """A gradient frame spans all brightness values → moderate exposure score."""
        score = score_exposure([make_gradient()])
        # It has some shadows (left edge), some highlights (right edge),
        # and lots of midtones — expect a positive but not high score
        assert -0.5 < score < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Motion tests
# ─────────────────────────────────────────────────────────────────────────────

class TestMotion:
    """Tests for score_motion() using Farneback optical flow."""

    def test_identical_frames_are_smooth(self):
        """Identical frames = zero motion = maximum smoothness."""
        frames = make_identical_sequence(5)
        smoothness, motion_type = score_motion(frames)
        # std of flow magnitudes = 0 → 1/(1+0) = 1.0
        assert smoothness == pytest.approx(1.0, abs=1e-3), \
            "Identical frames should have smoothness ≈ 1.0"

    def test_identical_frames_are_static(self):
        """Identical frames = zero motion = motion_type 'static'."""
        frames = make_identical_sequence(5)
        _, motion_type = score_motion(frames)
        assert motion_type == "static", \
            "Identical frames should classify as 'static'"

    def test_single_frame_returns_unknown(self):
        """Cannot compute flow from a single frame → (0.0, 'unknown')."""
        smoothness, motion_type = score_motion([make_gradient()])
        assert smoothness == 0.0
        assert motion_type == "unknown"

    def test_empty_frames_returns_unknown(self):
        """Empty list → (0.0, 'unknown')."""
        smoothness, motion_type = score_motion([])
        assert smoothness == 0.0
        assert motion_type == "unknown"

    def test_smoothness_in_valid_range(self):
        """Smoothness score must always be in [0, 1]."""
        rng = np.random.default_rng(42)
        frames = [
            rng.integers(0, 255, (FRAME_H, FRAME_W, 3), dtype=np.uint8)
            for _ in range(4)
        ]
        smoothness, _ = score_motion(frames)
        assert 0.0 <= smoothness <= 1.0, \
            f"Smoothness {smoothness} is outside [0, 1]"

    def test_motion_type_is_valid_string(self):
        """motion_type must be one of the four valid labels."""
        valid_types = {"static", "slow_pan", "fast_flythrough", "unknown"}
        frames = make_identical_sequence(3)
        _, motion_type = score_motion(frames)
        assert motion_type in valid_types, \
            f"motion_type '{motion_type}' is not a recognized label"


# ─────────────────────────────────────────────────────────────────────────────
# Composition tests
# ─────────────────────────────────────────────────────────────────────────────

class TestComposition:
    """Tests for score_composition() using Canny edge density."""

    def test_blank_frame_is_near_zero(self):
        """A solid black frame has no edges → composition ≈ 0."""
        frames = [make_solid(0)]
        score = score_composition(frames)
        assert score < 0.01, \
            "Solid black frame should have near-zero composition score"

    def test_solid_white_is_near_zero(self):
        """Solid white also has no Canny edges (no contrast)."""
        frames = [make_solid(255)]
        score = score_composition(frames)
        assert score < 0.01, \
            "Solid white frame should have near-zero composition score"

    def test_checkerboard_has_high_composition(self):
        """Checkerboard has the most edges of any synthetic frame → high score."""
        checker_score = score_composition([make_checkerboard()])
        blank_score = score_composition([make_solid(0)])
        assert checker_score > blank_score, \
            "Checkerboard should outscore blank frame on composition"

    def test_checkerboard_edges_are_positive(self):
        """Checkerboard edge density should be clearly above zero."""
        score = score_composition([make_checkerboard()])
        assert score > 0.05, \
            "Checkerboard should have a meaningful positive composition score"

    def test_gradient_has_intermediate_score(self):
        """Gradient frame has edges (the left/right ramp) → some composition."""
        score = score_composition([make_gradient()])
        blank_score = score_composition([make_solid(0)])
        assert score > blank_score, \
            "Gradient should have higher composition than blank"

    def test_empty_frames_returns_zero(self):
        """Empty frame list → 0.0."""
        assert score_composition([]) == pytest.approx(0.0, abs=1e-6)

    def test_score_in_valid_range(self):
        """Composition score must be in [0, 1] (edge density is a fraction)."""
        score = score_composition([make_checkerboard()])
        assert 0.0 <= score <= 1.0, \
            f"Composition score {score} is outside [0, 1]"

    def test_horizon_band_penalized(self):
        """A bare horizon frame should score lower than a checkerboard with the
        same number of edge pixels (horizon penalty reduces the score)."""
        # The horizontal band has one strong edge at the midpoint — exactly
        # where the horizon penalty is looking.
        horizon_score = score_composition([make_horizontal_band()])
        checker_score = score_composition([make_checkerboard()])
        assert checker_score > horizon_score, \
            "Checkerboard (rich content) should outscore horizon band (bare horizon)"


# ─────────────────────────────────────────────────────────────────────────────
# Integration: score_clip
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreClip:
    """Integration tests for score_clip() — the full 4-signal pipeline."""

    def test_scores_all_fields(self):
        """score_clip should set all four *_raw fields and motion_type."""
        frames = make_identical_sequence(4)
        clip = CandidateClip(
            clip_id=0, start_time=0.0, end_time=4.0, duration=4.0, frames=frames
        )
        result = score_clip(clip)

        # All raw score fields should be set (non-default 0.0 except blank frames)
        assert isinstance(result.sharpness_raw, float)
        assert isinstance(result.exposure_raw, float)
        assert isinstance(result.smoothness_raw, float)
        assert isinstance(result.composition_raw, float)
        assert result.motion_type in {"static", "slow_pan", "fast_flythrough", "unknown"}

    def test_returns_same_clip(self):
        """score_clip should return the same object (modified in-place)."""
        frames = [make_solid(128)]
        clip = CandidateClip(
            clip_id=1, start_time=0.0, end_time=1.0, duration=1.0, frames=frames
        )
        result = score_clip(clip)
        assert result is clip, "score_clip should return the same clip object"

    def test_empty_clip_gets_zeros(self):
        """A clip with no frames should be scored as all zeros."""
        clip = CandidateClip(
            clip_id=2, start_time=0.0, end_time=4.0, duration=4.0, frames=[]
        )
        result = score_clip(clip)
        assert result.sharpness_raw == 0.0
        assert result.exposure_raw == 0.0
        assert result.smoothness_raw == 0.0
        assert result.composition_raw == 0.0
        assert result.motion_type == "unknown"

    def test_sharp_clip_scores_higher_than_blurry(self):
        """A clip of checkerboard frames should have higher sharpness than solid-gray."""
        checker_clip = CandidateClip(
            clip_id=3, start_time=0.0, end_time=4.0, duration=4.0,
            frames=[make_checkerboard()] * 4,
        )
        blurry_clip = CandidateClip(
            clip_id=4, start_time=0.0, end_time=4.0, duration=4.0,
            frames=[make_solid(128)] * 4,
        )
        score_clip(checker_clip)
        score_clip(blurry_clip)
        assert checker_clip.sharpness_raw > blurry_clip.sharpness_raw
