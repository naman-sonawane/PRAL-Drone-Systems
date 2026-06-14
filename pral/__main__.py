"""Runnable entry point for the PRAL footage-acquisition pipeline.

Drives Stage 1 -> Stage 5 end to end on a procedural daylight scene and prints a
human-readable summary of every artifact produced -- the AOI, orbit geometry,
obstacle map, 3D coverage, value field, the planned mission, the simulated
flight, and the final Curated Footage Set.

Usage
-----
    python -m pral                      # default box building, daylight happy path
    python -m pral --height 40 --trees 6 --shots 4
"""

from __future__ import annotations

import argparse

from pral.core.camera import Camera
from pral.core.schemas import validate_curated_footage_set
from pral.pipeline import run_pipeline
from pral.sim.scenes import VoxelScene


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="pral", description=__doc__)
    p.add_argument("--building", default="box", help="building shape (box | L)")
    p.add_argument("--height", type=float, default=30.0, help="building height (m)")
    p.add_argument("--width", type=float, default=20.0, help="building width (m)")
    p.add_argument("--depth", type=float, default=20.0, help="building depth (m)")
    p.add_argument("--voxel", type=float, default=2.0, help="voxel size (m)")
    p.add_argument("--trees", type=int, default=4, help="number of tree obstacles")
    p.add_argument("--poles", type=int, default=2, help="number of pole obstacles")
    p.add_argument("--orbit-views", type=int, default=24, help="base orbit viewpoints")
    p.add_argument("--coverage", type=float, default=0.90, help="target surface coverage")
    p.add_argument("--shots", type=int, default=3, help="min distinct shot grammars")
    return p.parse_args()


def _rule(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> int:
    args = _parse_args()

    _rule("PRAL Footage Acquisition — end-to-end run")
    cam = Camera(hfov_deg=84.0, vfov_deg=53.0, width=640, height=480)
    print(f"camera     : HFOV 84.0°  VFOV 53.0°  640x480")
    scene = VoxelScene.make(
        building=args.building, height=args.height, width=args.width,
        depth=args.depth, voxel_size=args.voxel, n_trees=args.trees,
        n_poles=args.poles,
    )
    print(f"scene      : {args.building} building  H={args.height}m  "
          f"{args.width}x{args.depth}m  +{args.trees} trees +{args.poles} poles")

    result = run_pipeline(
        scene, cam, n_orbit_views=args.orbit_views,
        target_coverage=args.coverage, n_distinct_shots=args.shots,
    )

    _rule("Stage 1 — Target Selection & Confirmation")
    print(f"home frame : ({result.home.lat:.5f}, {result.home.lon:.5f})")
    print(f"AOI        : '{result.aoi.name}'  {len(result.aoi.polygon_enu)} vertices  "
          f"ceiling={result.aoi.max_altitude:.0f}m")

    _rule("Stage 2 — Survey, Geometry & Obstacle Map")
    print(f"orbit radius r : {result.orbit_radius:.2f} m  (fits building in frame)")
    print(f"obstacle map   : {len(result.obstacle_map.occupied_voxels)} occupied cells")

    _rule("Stage 3 — 360° Mapping (NBV) & Close-Ups")
    print(f"coverage       : {result.coverage * 100:.1f}% of AOI surface")
    print(f"occluded faces resolved : {len(result.closeup_targets)}")
    print(f"close-up viewpoints     : {len(result.closeup_positions)}")

    _rule("Stage 4 — Interest Field & Value Assignment")
    print(f"value field    : {len(result.value_field.samples)} scored viewpoints")
    if result.value_field.samples:
        best = max(result.value_field.samples, key=lambda s: s.value)
        print(f"peak viewpoint : value={best.value:.3f}")

    _rule("Stage 5 — Path Optimization & Variety Shots")
    mission = result.mission
    print(f"mission        : {len(mission.waypoints)} waypoints")
    print(f"shot types     : {sorted({s.value for s in mission.shot_types})}")

    _rule("Flight simulation")
    flight = result.flight
    print(f"completed      : {flight.completed}")
    print(f"collided       : {flight.collided}")
    print(f"min clearance  : {flight.min_clearance:.2f} m")
    print(f"battery used   : {flight.battery_used * 100:.1f}%  "
          f"(remaining {flight.battery_remaining * 100:.1f}%)")

    _rule("Curated Footage Set (the deliverable)")
    footage = result.footage
    print(f"clips          : {len(footage.clips)}")
    print(f"coverage       : {footage.coverage * 100:.1f}%")
    for i, clip in enumerate(footage.clips):
        tags = ", ".join(clip.interest_tags[:3])
        print(f"  clip {i:>2} : {clip.shot_type.value:<10} "
              f"{len(clip.poses)} pose(s)  tags=[{tags}]")
    validate_curated_footage_set(footage.model_dump())
    print("\nschema validation : PASS — artifact is well-formed and consumable")

    _rule("DONE")
    print("Full pipeline ran end-to-end and produced a validated Curated Footage Set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
