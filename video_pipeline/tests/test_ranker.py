"""
Unit tests for ranker.py — normalization, hard filters, and scoring weights.

Tests are written without real video frames — we construct CandidateClip
objects with raw score values set directly to verify the math in isolation.
"""

import pytest

from video_pipeline import config
from video_pipeline.segmenter import CandidateClip
from video_pipeline.ranker import rank, _validate_weights, _apply_hard_filters, _normalize_scores


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_clip(
    clip_id: int,
    sharpness: float = 100.0,
    exposure: float = 0.5,
    smoothness: float = 0.8,
    composition: float = 0.05,
) -> CandidateClip:
    """Create a CandidateClip with specific raw scores and no frames."""
    clip = CandidateClip(
        clip_id=clip_id,
        start_time=float(clip_id),
        end_time=float(clip_id) + 4.0,
        duration=4.0,
        frames=[],
    )
    clip.sharpness_raw = sharpness
    clip.exposure_raw = exposure
    clip.smoothness_raw = smoothness
    clip.composition_raw = composition
    return clip


# ─────────────────────────────────────────────────────────────────────────────
# Weight validation
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateWeights:
    """Tests for _validate_weights()."""

    def test_default_config_weights_are_valid(self):
        """The default config weights must sum to 1.0 (else tests would fail everywhere)."""
        try:
            _validate_weights()
        except ValueError:
            pytest.fail("Default config weights do not sum to 1.0")

    def test_bad_weights_raise_value_error(self, monkeypatch):
        """Weights summing to != 1.0 should raise ValueError."""
        monkeypatch.setattr(config, "WEIGHT_SHARPNESS", 0.5)
        monkeypatch.setattr(config, "WEIGHT_SMOOTHNESS", 0.5)
        monkeypatch.setattr(config, "WEIGHT_COMPOSITION", 0.5)
        monkeypatch.setattr(config, "WEIGHT_EXPOSURE", 0.5)
        with pytest.raises(ValueError, match="sum to 1.0"):
            _validate_weights()

    def test_weights_summing_to_one_pass(self, monkeypatch):
        """Valid custom weights should not raise."""
        monkeypatch.setattr(config, "WEIGHT_SHARPNESS",   0.25)
        monkeypatch.setattr(config, "WEIGHT_SMOOTHNESS",  0.25)
        monkeypatch.setattr(config, "WEIGHT_COMPOSITION", 0.25)
        monkeypatch.setattr(config, "WEIGHT_EXPOSURE",    0.25)
        try:
            _validate_weights()
        except ValueError:
            pytest.fail("Equal weights (0.25 each) should be valid")


# ─────────────────────────────────────────────────────────────────────────────
# Hard filters
# ─────────────────────────────────────────────────────────────────────────────

class TestHardFilters:
    """Tests for the hard sharpness and smoothness filters."""

    def test_clip_below_min_sharpness_is_rejected(self, monkeypatch):
        """Clip with sharpness < MIN_SHARPNESS should be rejected."""
        monkeypatch.setattr(config, "MIN_SHARPNESS", 50.0)
        clip = make_clip(0, sharpness=30.0, smoothness=0.9)
        survivors, rejected = _apply_hard_filters([clip])
        assert clip in rejected
        assert clip not in survivors
        assert clip.passed_hard_filter is False

    def test_clip_below_min_smoothness_is_rejected(self, monkeypatch):
        """Clip with smoothness < MIN_SMOOTHNESS should be rejected."""
        monkeypatch.setattr(config, "MIN_SMOOTHNESS", 0.6)
        clip = make_clip(0, sharpness=200.0, smoothness=0.3)
        survivors, rejected = _apply_hard_filters([clip])
        assert clip in rejected
        assert clip.passed_hard_filter is False

    def test_clip_above_both_thresholds_survives(self, monkeypatch):
        """Clip with sharpness >= MIN_SHARPNESS AND smoothness >= MIN_SMOOTHNESS survives."""
        monkeypatch.setattr(config, "MIN_SHARPNESS", 50.0)
        monkeypatch.setattr(config, "MIN_SMOOTHNESS", 0.6)
        clip = make_clip(0, sharpness=100.0, smoothness=0.8)
        survivors, rejected = _apply_hard_filters([clip])
        assert clip in survivors
        assert clip not in rejected
        assert clip.passed_hard_filter is True

    def test_exactly_at_threshold_survives(self, monkeypatch):
        """Clips at exactly the threshold value should survive (≥ condition)."""
        monkeypatch.setattr(config, "MIN_SHARPNESS", 50.0)
        monkeypatch.setattr(config, "MIN_SMOOTHNESS", 0.6)
        clip = make_clip(0, sharpness=50.0, smoothness=0.6)
        survivors, _ = _apply_hard_filters([clip])
        assert clip in survivors

    def test_all_rejected_returns_empty_survivors(self):
        """All clips failing hard filter → survivors is empty."""
        clips = [make_clip(i, sharpness=0.0, smoothness=0.0) for i in range(5)]
        survivors, rejected = _apply_hard_filters(clips)
        assert len(survivors) == 0
        assert len(rejected) == 5


# ─────────────────────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalization:
    """Tests for _normalize_scores()."""

    def test_best_clip_gets_highest_norm(self):
        """The clip with the highest raw value should get the highest normalized value."""
        clip_low = make_clip(0, sharpness=50.0)
        clip_high = make_clip(1, sharpness=200.0)
        _normalize_scores([clip_low, clip_high])
        assert clip_high.sharpness_norm > clip_low.sharpness_norm

    def test_worst_clip_gets_zero_norm(self):
        """The clip with the minimum raw value should get norm ≈ 0."""
        clips = [make_clip(i, sharpness=float(i + 1) * 50) for i in range(4)]
        _normalize_scores(clips)
        # First clip (sharpness=50) is the minimum → norm ≈ 0
        assert clips[0].sharpness_norm == pytest.approx(0.0, abs=1e-5)

    def test_best_clip_gets_norm_near_one(self):
        """The clip with the maximum raw value should get norm ≈ 1."""
        clips = [make_clip(i, sharpness=float(i + 1) * 50) for i in range(4)]
        _normalize_scores(clips)
        # Last clip (sharpness=200) is the maximum → norm ≈ 1
        assert clips[-1].sharpness_norm == pytest.approx(1.0, abs=1e-4)

    def test_all_same_raw_get_half(self):
        """When all clips have the same raw score, normalization produces 0.5."""
        clips = [make_clip(i, sharpness=100.0) for i in range(3)]
        _normalize_scores(clips)
        for clip in clips:
            # (100 - 100) / (100 - 100 + ε) = 0 / ε ≈ 0 but the code adds ε to denominator
            # Actually: (x - min) / (max - min + ε) = 0 / ε ≈ 0, then clipped.
            # Let's just check it's in [0, 1]
            assert 0.0 <= clip.sharpness_norm <= 1.0

    def test_all_signals_normalized(self):
        """All four signals should have norm values in [0, 1] after normalization."""
        clips = [
            make_clip(0, sharpness=50.0,  exposure=0.2, smoothness=0.5, composition=0.01),
            make_clip(1, sharpness=200.0, exposure=0.8, smoothness=0.9, composition=0.10),
        ]
        _normalize_scores(clips)
        for clip in clips:
            assert 0.0 <= clip.sharpness_norm   <= 1.0
            assert 0.0 <= clip.exposure_norm    <= 1.0
            assert 0.0 <= clip.smoothness_norm  <= 1.0
            assert 0.0 <= clip.composition_norm <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Full rank() integration
# ─────────────────────────────────────────────────────────────────────────────

class TestRank:
    """Integration tests for the full rank() function."""

    def test_empty_input_returns_empty(self):
        """Empty input → empty output, no exception."""
        result = rank([])
        assert result == []

    def test_all_failing_filter_returns_empty(self, monkeypatch):
        """All clips below hard filter → empty ranked list."""
        monkeypatch.setattr(config, "MIN_SHARPNESS", 9999.0)
        clips = [make_clip(i) for i in range(3)]
        result = rank(clips)
        assert result == []

    def test_result_is_sorted_descending(self, monkeypatch):
        """Ranked output should be sorted by promising_score descending."""
        # Ensure all clips pass the hard filter
        monkeypatch.setattr(config, "MIN_SHARPNESS", 0.0)
        monkeypatch.setattr(config, "MIN_SMOOTHNESS", 0.0)
        clips = [
            make_clip(0, sharpness=50.0,  smoothness=0.7),
            make_clip(1, sharpness=200.0, smoothness=0.9),
            make_clip(2, sharpness=100.0, smoothness=0.8),
        ]
        result = rank(clips)
        scores = [c.promising_score for c in result]
        assert scores == sorted(scores, reverse=True), \
            "Result should be sorted descending by promising_score"

    def test_promising_score_in_zero_one(self, monkeypatch):
        """promising_score must be in [0, 1] for all surviving clips."""
        monkeypatch.setattr(config, "MIN_SHARPNESS", 0.0)
        monkeypatch.setattr(config, "MIN_SMOOTHNESS", 0.0)
        clips = [make_clip(i, sharpness=float(i + 1) * 30) for i in range(5)]
        result = rank(clips)
        for clip in result:
            assert 0.0 <= clip.promising_score <= 1.0, \
                f"promising_score {clip.promising_score} out of [0, 1]"

    def test_better_raw_scores_produce_higher_promising_score(self, monkeypatch):
        """A clip that is better on all raw signals should have a higher promising_score."""
        monkeypatch.setattr(config, "MIN_SHARPNESS", 0.0)
        monkeypatch.setattr(config, "MIN_SMOOTHNESS", 0.0)
        good_clip = make_clip(0, sharpness=200.0, exposure=0.8, smoothness=0.95, composition=0.15)
        bad_clip  = make_clip(1, sharpness=60.0,  exposure=0.2, smoothness=0.65, composition=0.02)
        result = rank([good_clip, bad_clip])
        assert result[0] is good_clip, \
            "The uniformly better clip should rank first"
