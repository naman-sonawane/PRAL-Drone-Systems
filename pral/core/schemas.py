"""Shared data contracts for the footage-acquisition pipeline.

Every stage produces or consumes one of these artifacts. They are defined once
here, as `pydantic` v2 models, so that:

* construction is validated and type-checked in Python (downstream code),
* a stable JSON Schema can be emitted for cross-language / on-the-wire checks.

The pipeline backbone (per the execution spec) is the posed 3D model; the final
deliverable is the **Curated Footage Set** (clips + poses + shot types +
interest tags). :func:`validate_curated_footage_set` validates an arbitrary
JSON-like object against the Curated Footage Set JSON Schema using ``jsonschema``
(Test 27).

Artifacts, in pipeline order
-----------------------------
* :class:`AOI`            -- Stage 1: geofenced polygon + home frame.
* :class:`ObstacleMap`    -- Stage 2: 2.5D / voxel occupancy.
* :class:`Model3D`        -- Stage 3: surface voxels + posed image refs + coverage.
* :class:`ValueField`     -- Stage 4: viewpoint -> value samples.
* :class:`Mission`        -- Stage 5: waypoints + gimbal keyframes.
* :class:`CuratedFootageSet` -- final deliverable.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ShotType(str, Enum):
    """Cinematographic shot grammars (Stage 5 variety library)."""

    ORBIT = "orbit"
    FLYBY = "flyby"
    REVEAL = "reveal"
    PUSH_IN = "push_in"
    TOP_DOWN = "top_down"
    PARALLAX = "parallax"
    DRONIE = "dronie"


# ---------------------------------------------------------------------------
# Common geometry primitives
# ---------------------------------------------------------------------------


class HomeFrame(BaseModel):
    """The geodetic anchor that defines the local ENU/NED frame."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    alt: float = 0.0


class Quaternion(BaseModel):
    """Unit quaternion (w, x, y, z)."""

    model_config = ConfigDict(extra="forbid")

    w: float
    x: float
    y: float
    z: float


class PoseModel(BaseModel):
    """A camera pose: ENU position (meters) + orientation quaternion."""

    model_config = ConfigDict(extra="forbid")

    position: list[float] = Field(min_length=3, max_length=3)
    orientation: Quaternion


# ---------------------------------------------------------------------------
# Stage 1 -- AOI
# ---------------------------------------------------------------------------


class AOI(BaseModel):
    """Geofenced Area of Interest: a polygon in the local ENU frame + home anchor."""

    model_config = ConfigDict(extra="forbid")

    home: HomeFrame
    # Polygon vertices as (east, north) meters in the ENU frame. >= 3 vertices.
    polygon_enu: list[list[float]] = Field(min_length=3)
    max_altitude: float = Field(default=120.0, gt=0.0)
    name: str | None = None

    @field_validator("polygon_enu")
    @classmethod
    def _check_polygon(cls, v: list[list[float]]) -> list[list[float]]:
        for pt in v:
            if len(pt) != 2:
                raise ValueError("each polygon vertex must be [east, north]")
        return v


# ---------------------------------------------------------------------------
# Stage 2 -- ObstacleMap
# ---------------------------------------------------------------------------


class ObstacleMap(BaseModel):
    """2.5D / voxel occupancy of the orbit volume.

    Stored as a regular grid. ``resolution`` is the cell size in meters;
    ``origin_enu`` is the (east, north, up) corner. Either a 2.5D height grid
    (``height_grid``) or a sparse list of occupied voxel indices
    (``occupied_voxels``) may be supplied.
    """

    model_config = ConfigDict(extra="forbid")

    resolution: float = Field(gt=0.0)
    origin_enu: list[float] = Field(min_length=3, max_length=3)
    shape: list[int] = Field(min_length=2, max_length=3)
    # 2.5D: per-cell max height (meters). Sparse 3D: occupied (i, j, k) indices.
    height_grid: list[list[float]] | None = None
    occupied_voxels: list[list[int]] | None = None


# ---------------------------------------------------------------------------
# Stage 3 -- Model3D
# ---------------------------------------------------------------------------


class PosedImageRef(BaseModel):
    """A reference to a captured image plus the pose it was shot from."""

    model_config = ConfigDict(extra="forbid")

    image_id: str
    pose: PoseModel
    uri: str | None = None


class Model3D(BaseModel):
    """Reconstructed scene: surface voxels + posed image refs + coverage fraction."""

    model_config = ConfigDict(extra="forbid")

    # Surface voxel centers in ENU meters.
    surface_voxels: list[list[float]] = Field(default_factory=list)
    voxel_size: float = Field(gt=0.0)
    posed_images: list[PosedImageRef] = Field(default_factory=list)
    coverage: float = Field(ge=0.0, le=1.0)

    @field_validator("surface_voxels")
    @classmethod
    def _check_voxels(cls, v: list[list[float]]) -> list[list[float]]:
        for pt in v:
            if len(pt) != 3:
                raise ValueError("each surface voxel must be [e, n, u]")
        return v


# ---------------------------------------------------------------------------
# Stage 4 -- Viewpoint + ValueField
# ---------------------------------------------------------------------------


class Viewpoint(BaseModel):
    """A candidate camera viewpoint: a pose, optionally with a scalar value."""

    model_config = ConfigDict(extra="forbid")

    pose: PoseModel
    value: float | None = None


class ValueField(BaseModel):
    """A set of viewpoint -> value samples over viewpoint space."""

    model_config = ConfigDict(extra="forbid")

    samples: list[Viewpoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 5 -- Mission
# ---------------------------------------------------------------------------


class Waypoint(BaseModel):
    """A flight waypoint in the ENU frame."""

    model_config = ConfigDict(extra="forbid")

    position: list[float] = Field(min_length=3, max_length=3)
    speed: float | None = Field(default=None, ge=0.0)


class GimbalKeyframe(BaseModel):
    """A gimbal aim keyframe, indexed to the waypoint timeline."""

    model_config = ConfigDict(extra="forbid")

    waypoint_index: int = Field(ge=0)
    # Gimbal orientation as pitch/yaw/roll degrees, or an aim point in ENU.
    pitch_deg: float | None = None
    yaw_deg: float | None = None
    roll_deg: float = 0.0
    aim_enu: list[float] | None = Field(default=None, min_length=3, max_length=3)


class Mission(BaseModel):
    """A flyable mission: ordered waypoints + gimbal keyframes."""

    model_config = ConfigDict(extra="forbid")

    waypoints: list[Waypoint] = Field(min_length=1)
    gimbal_keyframes: list[GimbalKeyframe] = Field(default_factory=list)
    shot_types: list[ShotType] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Final deliverable -- CuratedFootageSet
# ---------------------------------------------------------------------------


class Clip(BaseModel):
    """A single captured clip: media ref + the poses it was flown along +
    its assigned shot type + interest tags."""

    model_config = ConfigDict(extra="forbid")

    clip_id: str
    shot_type: ShotType
    poses: list[PoseModel] = Field(min_length=1)
    interest_tags: list[str] = Field(default_factory=list)
    uri: str | None = None
    start_time_s: float | None = Field(default=None, ge=0.0)
    duration_s: float | None = Field(default=None, gt=0.0)


class CuratedFootageSet(BaseModel):
    """The pipeline's final deliverable: clips + poses + shot types + interest tags."""

    model_config = ConfigDict(extra="forbid")

    aoi_name: str | None = None
    home: HomeFrame
    clips: list[Clip] = Field(min_length=1)
    coverage: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# JSON Schema validation
# ---------------------------------------------------------------------------


def curated_footage_set_schema() -> dict[str, Any]:
    """Return the JSON Schema (draft 2020-12) for a Curated Footage Set."""
    return CuratedFootageSet.model_json_schema()


def validate_curated_footage_set(obj: Any) -> CuratedFootageSet:
    """Validate ``obj`` (a JSON-like dict) against the Curated Footage Set schema.

    Runs ``jsonschema`` validation against the generated JSON Schema *and*
    pydantic validation (which enforces enums, ranges, and ``extra="forbid"``).
    Returns the parsed :class:`CuratedFootageSet` on success; raises
    ``jsonschema.ValidationError`` or ``pydantic.ValidationError`` on failure.
    """
    schema = curated_footage_set_schema()
    jsonschema.validate(instance=obj, schema=schema)
    return CuratedFootageSet.model_validate(obj)


__all__ = [
    "ShotType",
    "HomeFrame",
    "Quaternion",
    "PoseModel",
    "AOI",
    "ObstacleMap",
    "PosedImageRef",
    "Model3D",
    "Viewpoint",
    "ValueField",
    "Waypoint",
    "GimbalKeyframe",
    "Mission",
    "Clip",
    "CuratedFootageSet",
    "curated_footage_set_schema",
    "validate_curated_footage_set",
]
