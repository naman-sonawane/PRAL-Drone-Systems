"""Test 27 (Tier A) -- E2E artifact contract.

A well-formed Curated Footage Set must validate against the schema; a malformed
one must be rejected. This proves the final-deliverable contract is enforceable
and consumable by a (stubbed) downstream processing pipeline.
"""

import jsonschema
import pytest
from pydantic import ValidationError

from pral.core.schemas import (
    CuratedFootageSet,
    curated_footage_set_schema,
    validate_curated_footage_set,
)


def _wellformed() -> dict:
    """A minimal, valid Curated Footage Set as a JSON-like dict."""
    return {
        "aoi_name": "test-building",
        "home": {"lat": 37.4275, "lon": -122.1697, "alt": 12.0},
        "coverage": 0.93,
        "clips": [
            {
                "clip_id": "clip-0001",
                "shot_type": "orbit",
                "poses": [
                    {
                        "position": [10.0, -5.0, 30.0],
                        "orientation": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
                    },
                    {
                        "position": [12.0, -3.0, 30.0],
                        "orientation": {"w": 0.92388, "x": 0.0, "y": 0.0, "z": 0.38268},
                    },
                ],
                "interest_tags": ["facade", "entrance"],
                "uri": "s3://footage/clip-0001.mp4",
                "start_time_s": 0.0,
                "duration_s": 8.5,
            },
            {
                "clip_id": "clip-0002",
                "shot_type": "push_in",
                "poses": [
                    {
                        "position": [20.0, 0.0, 15.0],
                        "orientation": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
                    }
                ],
                "interest_tags": ["architectural_detail"],
            },
        ],
    }


def test_schema_is_self_contained():
    """The emitted JSON Schema must be a valid schema document."""
    schema = curated_footage_set_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False


def test_wellformed_validates():
    obj = _wellformed()
    result = validate_curated_footage_set(obj)
    assert isinstance(result, CuratedFootageSet)
    assert result.coverage == pytest.approx(0.93)
    assert len(result.clips) == 2
    assert result.clips[0].shot_type.value == "orbit"
    assert result.clips[0].interest_tags == ["facade", "entrance"]


def test_wellformed_passes_jsonschema_directly():
    schema = curated_footage_set_schema()
    jsonschema.validate(instance=_wellformed(), schema=schema)  # must not raise


def test_missing_required_field_rejected():
    obj = _wellformed()
    del obj["home"]
    with pytest.raises(jsonschema.ValidationError):
        validate_curated_footage_set(obj)


def test_empty_clips_rejected():
    obj = _wellformed()
    obj["clips"] = []
    with pytest.raises(jsonschema.ValidationError):
        validate_curated_footage_set(obj)


def test_bad_shot_type_rejected():
    obj = _wellformed()
    obj["clips"][0]["shot_type"] = "barrel_roll"  # not in ShotType enum
    with pytest.raises(jsonschema.ValidationError):
        validate_curated_footage_set(obj)


def test_coverage_out_of_range_rejected():
    obj = _wellformed()
    obj["coverage"] = 1.5  # > 1.0
    with pytest.raises(jsonschema.ValidationError):
        validate_curated_footage_set(obj)


def test_unknown_extra_field_rejected():
    obj = _wellformed()
    obj["mystery_field"] = 42  # additionalProperties: false
    with pytest.raises(jsonschema.ValidationError):
        validate_curated_footage_set(obj)


def test_malformed_pose_rejected():
    obj = _wellformed()
    obj["clips"][0]["poses"][0]["position"] = [1.0, 2.0]  # needs 3 components
    with pytest.raises(jsonschema.ValidationError):
        validate_curated_footage_set(obj)


def test_pydantic_also_rejects_bad_object():
    """Even bypassing jsonschema, pydantic enforces the contract."""
    obj = _wellformed()
    obj["clips"][0]["shot_type"] = "barrel_roll"
    with pytest.raises(ValidationError):
        CuratedFootageSet.model_validate(obj)
