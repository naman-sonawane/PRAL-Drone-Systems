"""Export a full pipeline run as a visualization trace.

Runs Stage 1 -> Stage 5 end to end and serializes every stage's input ->
output, plus the 3D geometry (building, obstacles, orbit, viewpoints, value
field, mission path, close-ups), into a single JS file the web dashboard
(``viz/index.html``) replays as if it were happening live.

Writes:
    viz/trace.js     ->  window.PRAL_TRACE = {...};   (loaded by the page; no fetch/CORS)
    viz/trace.json   ->  the same payload, for inspection

Usage:
    python -m pral.viz_export
"""

from __future__ import annotations

import json
import os

import numpy as np

from pral.core.camera import Camera
from pral.pipeline import run_pipeline
from pral.sim.scenes import VoxelScene

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIZ_DIR = os.path.join(HERE, "viz")


def _downsample(arr: np.ndarray, n: int) -> np.ndarray:
    arr = np.asarray(arr, dtype=float)
    if len(arr) <= n:
        return arr
    idx = np.linspace(0, len(arr) - 1, n).astype(int)
    return arr[idx]


def _f(arr) -> list:
    """Round to 2 dp and JSON-listify."""
    return np.round(np.asarray(arr, dtype=float), 2).tolist()


def build_trace() -> dict:
    cam = Camera(hfov_deg=84.0, vfov_deg=53.0, width=640, height=480)
    scene = VoxelScene.make(
        building="box", height=30.0, width=20.0, depth=20.0,
        voxel_size=2.0, n_trees=4, n_poles=2,
    )
    r = run_pipeline(scene, cam, n_orbit_views=24, target_coverage=0.90,
                     n_distinct_shots=3)

    centroid = np.asarray(scene.centroid_enu, dtype=float)

    # --- geometry ---------------------------------------------------------
    building = _downsample(r.model.surface_voxels, 500)

    obstacles_attr = scene.obstacle_voxels_enu
    obstacles = obstacles_attr() if callable(obstacles_attr) else obstacles_attr
    obstacles = _downsample(np.asarray(obstacles, dtype=float), 250)

    # orbit ring (analytic, at building mid-height) for the base 360 path
    rr = float(r.orbit_radius)
    zmid = float(scene.building_height) * 0.5
    ang = np.linspace(0, 2 * np.pi, 48, endpoint=True)
    orbit_ring = np.stack(
        [centroid[0] + rr * np.cos(ang), centroid[1] + rr * np.sin(ang),
         np.full_like(ang, zmid)], axis=1)

    # value-field viewpoints (position + normalized value for the heatmap)
    samples = r.value_field.samples
    vpos = np.array([s.pose.position for s in samples], dtype=float)
    vval = np.array([s.value for s in samples], dtype=float)
    vmax = float(vval.max()) if len(vval) else 1.0
    vnorm = (vval / vmax) if vmax > 0 else vval
    viewpoints = [{"p": _f(p), "v": round(float(v), 3)}
                  for p, v in zip(vpos, vnorm)]

    # mission path + shot types (ordered)
    wp = np.array([w.position for w in r.mission.waypoints], dtype=float)
    shots = [s.value for s in r.mission.shot_types]

    closeups = [{"p": _f(p), "t": _f(t)}
                for p, t in zip(r.closeup_positions, r.closeup_targets)]

    clips = [{"shot": c.shot_type.value,
              "tags": list(c.interest_tags)[:3]}
             for c in r.footage.clips]

    flight = r.flight

    # --- per-stage input -> output narrative ------------------------------
    stages = [
        {
            "n": 1, "name": "Target Selection",
            "input": {"map pin (lat, lon)": [round(r.home.lat, 5), round(r.home.lon, 5)]},
            "output": {"AOI": r.aoi.name,
                       "geofence vertices": len(r.aoi.polygon_enu),
                       "ceiling (m)": round(r.aoi.max_altitude, 0)},
            "log": ["set home frame from GPS pin",
                    "queried building footprints",
                    "open-vocab detection -> candidates",
                    f"user confirmed AOI '{r.aoi.name}' (geofence locked)"],
        },
        {
            "n": 2, "name": "Survey & Geometry",
            "input": {"AOI": r.aoi.name, "camera VFOV (deg)": 53.0},
            "output": {"orbit radius r (m)": round(rr, 2),
                       "building height H (m)": round(float(scene.building_height), 1),
                       "obstacle cells": int(len(r.obstacle_map.occupied_voxels))},
            "log": ["nadir survey grid captured",
                    f"height estimate H = {scene.building_height:.0f} m",
                    f"standoff r = (H/2+margin)/tan(VFOV/2) = {rr:.1f} m",
                    "obstacle map built (trees + poles flagged no-fly)"],
        },
        {
            "n": 3, "name": "360° Mapping (NBV)",
            "input": {"orbit radius (m)": round(rr, 2), "obstacle map": "loaded"},
            "output": {"coverage": f"{r.coverage * 100:.1f}%",
                       "occluded faces resolved": len(closeups),
                       "viewpoints": len(samples)},
            "log": ["flying base 360 orbit, gimbal -> centroid",
                    "incremental 3D reconstruction (SfM poses)",
                    "voxel coverage map updating...",
                    f"{len(closeups)} occluded faces -> line-of-sight close-ups",
                    f"coverage target reached: {r.coverage * 100:.1f}%"],
        },
        {
            "n": 4, "name": "Interest Field",
            "input": {"3D model": "posed", "signals": "lines + texture + saliency"},
            "output": {"scored viewpoints": len(samples),
                       "peak value": round(vmax, 1)},
            "log": ["per-image interest heatmaps (Canny + Laplacian + saliency)",
                    "projecting heatmaps onto 3D surface...",
                    "value(v) = Σ interest·framing·focal over visible hotspots",
                    f"value field built — peak {vmax:.1f}"],
        },
        {
            "n": 5, "name": "Path & Variety Shots",
            "input": {"value field": f"{len(samples)} viewpoints",
                      "obstacle map": "loaded"},
            "output": {"waypoints": len(wp),
                       "distinct shot types": len(set(shots)),
                       "clips": len(clips)},
            "log": ["local maxima -> refined viewpoints (gradient ascent)",
                    "assigning shot grammar (variety enforced)",
                    "OR-Tools TSP -> visit order",
                    "RRT* + min-snap smoothing through OctoMap",
                    "mission emitted — flying & capturing"],
        },
    ]

    return {
        "meta": {
            "coverage": round(r.coverage, 3),
            "orbit_radius": round(rr, 2),
            "building_height": round(float(scene.building_height), 1),
            "voxel_size": float(r.model.voxel_size),
            "n_waypoints": int(len(wp)),
            "n_clips": len(clips),
            "shot_types": sorted(set(shots)),
            "battery_used": round(float(flight.battery_used), 3),
            "battery_remaining": round(float(flight.battery_remaining), 3),
            "min_clearance": round(float(flight.min_clearance), 2),
            "collided": bool(flight.collided),
            "completed": bool(flight.completed),
            "n_occluded": len(closeups),
        },
        "centroid": _f(centroid),
        "aoi_polygon": _f(np.vstack([r.aoi.polygon_enu, r.aoi.polygon_enu[:1]])),
        "building": _f(building),
        "obstacles": _f(obstacles),
        "orbit_ring": _f(orbit_ring),
        "viewpoints": viewpoints,
        "closeups": closeups,
        "mission": {"waypoints": _f(wp), "shots": shots},
        "clips": clips,
        "stages": stages,
    }


def main() -> int:
    os.makedirs(VIZ_DIR, exist_ok=True)
    trace = build_trace()
    payload = json.dumps(trace, separators=(",", ":"))
    with open(os.path.join(VIZ_DIR, "trace.js"), "w") as f:
        f.write("window.PRAL_TRACE = " + payload + ";\n")
    with open(os.path.join(VIZ_DIR, "trace.json"), "w") as f:
        f.write(json.dumps(trace, indent=2))
    print(f"wrote viz/trace.js  ({len(payload):,} bytes)")
    print(f"  coverage={trace['meta']['coverage']*100:.1f}%  "
          f"waypoints={trace['meta']['n_waypoints']}  "
          f"clips={trace['meta']['n_clips']}  "
          f"shots={len(trace['meta']['shot_types'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
