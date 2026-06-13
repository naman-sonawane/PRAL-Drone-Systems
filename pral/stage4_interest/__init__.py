"""Stage 4 -- Interest Field & Value Assignment.

Stage 3 hands us a posed 3D model (surface voxels + camera poses). Stage 4 turns
that geometry into a **value field over viewpoint space**: a scalar function
``value(v)`` that says how good a candidate camera viewpoint ``v`` is for
cinematography, so Stage 5 can optimize a path through its peaks.

The value of a viewpoint is, per the execution spec::

    value(v) = sum_over_visible_hotspots  interest(p)
                   * framing(v, p)     # angle vs surface normal + in-frame position
                   * focal(dist(v, p)) # peaks at the optimal subject distance

This module owns the *deterministic geometry/math* half of the stage (Tier A):

* :func:`focal`  -- Gaussian distance weighting peaking at an optimal standoff.
* :class:`Hotspot` / :func:`framing` / :func:`viewpoint_value` -- the value score.
* :func:`project_heatmap_to_surface` -- lift a per-pixel interest heatmap onto the
  3D surface using the known camera pose (hotspot localization).
* :func:`build_value_field` -- score a set of candidate viewpoints into a
  :class:`~pral.core.schemas.ValueField` artifact.

The *per-image* interest signal extraction (Canny / Laplacian / entropy / saliency
on real pixels) is the Tier-C half and lives behind the field-data tests; here we
take the heatmap / hotspot interest as given.
"""

from pral.stage4_interest.value_field import (
    FocalParams,
    FramingParams,
    Hotspot,
    build_value_field,
    focal,
    framing,
    project_heatmap_to_surface,
    viewpoint_value,
)

__all__ = [
    "FocalParams",
    "FramingParams",
    "Hotspot",
    "focal",
    "framing",
    "viewpoint_value",
    "project_heatmap_to_surface",
    "build_value_field",
]
