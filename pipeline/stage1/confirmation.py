"""
Sub-step 1d — Candidate management and AOI confirmation.

Merges OSM priors with vision detections, deduplicates by centroid distance,
and locks the user-selected candidate as the AOI.
"""
import math

from .types import AOI, Candidate, HomeOrigin

MERGE_DISTANCE_M = 5.0  # centroids closer than this are the same building


def merge_candidates(
    prior: list[Candidate],
    vision: list[Candidate],
    merge_dist_m: float = MERGE_DISTANCE_M,
) -> list[Candidate]:
    """
    Merge OSM prior candidates with vision candidates.

    If a vision centroid falls within merge_dist_m of a prior centroid they
    refer to the same building — keep the prior polygon (more precise geometry)
    and discard the vision duplicate. Unmatched vision candidates are appended.
    """
    merged = list(prior)

    for vc in vision:
        matched = any(
            math.hypot(
                vc.centroid_enu[0] - pc.centroid_enu[0],
                vc.centroid_enu[1] - pc.centroid_enu[1],
            ) < merge_dist_m
            for pc in prior
        )
        if not matched:
            merged.append(vc)

    return merged


def closest_to_pin(
    candidates: list[Candidate],
    pin_enu: tuple[float, float],
) -> Candidate:
    """Return the candidate whose centroid is closest to the pin."""
    return min(
        candidates,
        key=lambda c: math.hypot(
            c.centroid_enu[0] - pin_enu[0],
            c.centroid_enu[1] - pin_enu[1],
        ),
    )


def confirm_candidate(candidate: Candidate, home_origin: HomeOrigin) -> AOI:
    """Lock a candidate as the confirmed AOI."""
    return AOI(
        polygon_enu=candidate.polygon_enu,
        centroid_enu=candidate.centroid_enu,
        home_origin=home_origin,
        source=candidate.source,
    )


def confirm_manual(
    polygon_enu: list[tuple[float, float]],
    home_origin: HomeOrigin,
) -> AOI:
    """
    Create an AOI from a manually drawn polygon.
    Used as fallback when no candidates are found (T1.5).
    """
    if len(polygon_enu) < 3:
        raise ValueError("A polygon requires at least 3 points")
    e = sum(p[0] for p in polygon_enu) / len(polygon_enu)
    n = sum(p[1] for p in polygon_enu) / len(polygon_enu)
    return AOI(
        polygon_enu=polygon_enu,
        centroid_enu=(e, n),
        home_origin=home_origin,
        source="manual",
    )
