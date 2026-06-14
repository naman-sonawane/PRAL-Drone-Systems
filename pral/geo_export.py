"""Fly a *real* OSM building footprint through the pipeline and geo-locate it.

Loads the Waterloo E7 (Pearl Sullivan Engineering Building) footprint from
``viz/e7_footprint.json`` (fetched from the OpenStreetMap Overpass API), builds
a voxel scene by extruding that polygon, runs Stage 1 -> Stage 5, then converts
every artifact -- orbit ring, planned mission trajectory, viewpoints, close-up
spurs -- back to GPS (lat/lon) so it can be drawn on a real map.

Writes:
    viz/geo_trace.js   ->  window.PRAL_GEO = {...};   (loaded by viz/map.html)
    viz/geo_trace.json

Usage:
    python -m pral.geo_export
"""

from __future__ import annotations

import json
import os

import numpy as np

from pral.core import frames
from pral.core.camera import Camera
from pral.pipeline import run_pipeline
from pral.sim.scenes import VoxelScene

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIZ_DIR = os.path.join(HERE, "viz")
FOOTPRINT = os.path.join(VIZ_DIR, "e7_footprint.json")

# Each mission waypoint is tagged with the "theoretical part" of the flight it
# belongs to, derived from its altitude relative to building height. This is the
# single source of truth the map viz slices the trajectory by; ``min_frac`` is
# the lower altitude bound (as a fraction of building height) for the band.
PHASE_DEFS = [
    {"key": "survey", "label": "SURVEY · top-down", "color": "#a3e635", "min_frac": 0.70},
    {"key": "orbit", "label": "360 ORBIT · sides", "color": "#38bdf8", "min_frac": 0.32},
    {"key": "capture", "label": "CAPTURE · detail", "color": "#fbbf24", "min_frac": 0.0},
]


def classify_phase(altitude_m: float, height_m: float) -> str:
    """Map a waypoint altitude to a flight phase key (survey/orbit/capture)."""
    frac = altitude_m / height_m if height_m else 0.0
    for d in PHASE_DEFS:  # ordered high -> low
        if frac >= d["min_frac"]:
            return d["key"]
    return PHASE_DEFS[-1]["key"]


def _latlon(enu_xy, lat0, lon0):
    """ENU [.,2 or 3] meters -> [[lat, lon], ...] about the home anchor."""
    out = []
    for p in np.asarray(enu_xy, dtype=float):
        g = frames.enu_to_geodetic(p[0], p[1], p[2] if len(p) > 2 else 0.0,
                                   lat0, lon0, 0.0)
        out.append([round(float(g[0]), 7), round(float(g[1]), 7)])
    return out


def build() -> dict:
    fp = json.load(open(FOOTPRINT))
    lat0, lon0 = fp["centroid"]
    height = float(fp["height_m"])

    # footprint polygon (lat/lon) -> local ENU meters about the centroid
    poly_enu = np.array(
        [frames.geodetic_to_enu(lat, lon, 0.0, lat0, lon0, 0.0)[:2]
         for lat, lon in fp["polygon_latlon"]],
        dtype=float,
    )

    scene = VoxelScene.from_polygon(poly_enu, height, voxel_size=5.0,
                                    n_trees=3, n_poles=1)
    r = run_pipeline(scene, Camera(hfov_deg=84.0, vfov_deg=53.0, width=640, height=480),
                     n_orbit_views=24, target_coverage=0.85, n_distinct_shots=3,
                     closeup_standoff=12.0)

    # the from_polygon recenters the footprint centroid to ENU origin, so the
    # GPS anchor (lat0, lon0) is exactly that origin -> conversions line up.
    orbit = scene.orbit_poses_enu(n_views=64, altitude=height * 0.5)
    mission_xy = np.array([w.position for w in r.mission.waypoints], dtype=float)
    shots = [s.value for s in r.mission.shot_types]

    return {
        "name": fp["name"],
        "osm_id": fp["osm_id"],
        "home": [lat0, lon0],
        "height_m": height,
        "footprint": fp["polygon_latlon"],
        "orbit": _latlon(orbit, lat0, lon0),
        "orbit_radius_m": round(float(scene.orbit_radius), 1),
        "trajectory": _latlon(mission_xy, lat0, lon0),
        "trajectory_alt": [round(float(p[2]), 1) for p in mission_xy],
        "phases": [classify_phase(float(p[2]), height) for p in mission_xy],
        "phase_defs": PHASE_DEFS,
        "shots": shots,
        "closeups": [
            {"from": _latlon([cp], lat0, lon0)[0], "to": _latlon([ct], lat0, lon0)[0]}
            for cp, ct in zip(r.closeup_positions, r.closeup_targets)
        ],
        "viewpoints": _latlon([s.pose.position for s in r.value_field.samples],
                              lat0, lon0),
        "meta": {
            "coverage": round(float(r.coverage), 3),
            "n_waypoints": int(len(mission_xy)),
            "n_shots": len(set(shots)),
            "n_closeups": int(len(r.closeup_positions)),
            "battery_used": round(float(r.flight.battery_used), 3),
            "min_clearance": round(float(r.flight.min_clearance), 2),
            "collided": bool(r.flight.collided),
        },
    }


def main() -> int:
    os.makedirs(VIZ_DIR, exist_ok=True)
    geo = build()
    payload = json.dumps(geo, separators=(",", ":"))
    with open(os.path.join(VIZ_DIR, "geo_trace.js"), "w") as f:
        f.write("window.PRAL_GEO = " + payload + ";\n")
    with open(os.path.join(VIZ_DIR, "geo_trace.json"), "w") as f:
        f.write(json.dumps(geo, indent=2))
    m = geo["meta"]
    print(f"wrote viz/geo_trace.js  ({len(payload):,} bytes)")
    print(f"  {geo['name']}")
    print(f"  footprint {len(geo['footprint'])} verts | orbit r={geo['orbit_radius_m']} m | "
          f"trajectory {m['n_waypoints']} waypoints | coverage {m['coverage']*100:.1f}% | "
          f"{m['n_shots']} shot types | clearance {m['min_clearance']} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
