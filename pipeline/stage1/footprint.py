"""
Sub-step 1b — Prior footprint lookup.

Queries OSM Overpass for building polygons near the user's pin.
No flying required — runs before takeoff.
"""
import math

import requests

from .coordinate import centroid_enu, polygon_latlon_to_enu
from .types import Candidate, HomeOrigin

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def query_osm_footprints(
    lat: float,
    lon: float,
    radius_m: float = 100.0,
    timeout: float = 10.0,
) -> list[Candidate]:
    """
    Fetch building footprints from OSM within radius_m of (lat, lon).
    Returns candidates in ENU relative to (lat, lon) as origin.
    Acceptance criteria: ≥80% IoU overlap with ground truth, response within 2 s (T1.2).
    """
    query = f"""
[out:json][timeout:{int(timeout)}];
way["building"](around:{radius_m},{lat},{lon});
out geom;
"""
    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=timeout,
        headers={"User-Agent": "PRAL-Drone-Systems/1.0"},
    )
    response.raise_for_status()
    data = response.json()

    origin = HomeOrigin(lat=lat, lon=lon, alt=0.0)
    candidates: list[Candidate] = []

    for element in data.get("elements", []):
        if element.get("type") != "way":
            continue
        geometry = element.get("geometry", [])
        if len(geometry) < 3:
            continue

        ring = [(node["lat"], node["lon"]) for node in geometry]
        polygon = polygon_latlon_to_enu(ring, origin)
        center = centroid_enu(polygon)

        candidates.append(
            Candidate(
                id=f"osm-{element['id']}",
                source="osm",
                polygon_enu=polygon,
                centroid_enu=center,
                confidence=1.0,
            )
        )

    return candidates


def filter_by_distance(
    candidates: list[Candidate],
    pin_enu: tuple[float, float],
    max_dist_m: float = 50.0,
) -> list[Candidate]:
    """Discard candidates whose centroid is farther than max_dist_m from the pin."""
    result = []
    for c in candidates:
        dist = math.hypot(
            c.centroid_enu[0] - pin_enu[0],
            c.centroid_enu[1] - pin_enu[1],
        )
        if dist <= max_dist_m:
            result.append(c)
    return result
