"""
Stage 2 -- Survey + Geometry: Runner.

Orchestrates 2a -> 2b -> 2c -> 2d and returns Stage2Output.
Gate check is enforced before returning; raises AssertionError on failure.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from .height import (
    apply_height_edge_cases,
    dsm_height,
    fuse_heights,
    rangefinder_height,
)
from .obstacle import (
    MockOctoMap,
    build_octomap,
    build_point_cloud,
    extract_no_fly_volumes,
    filter_to_annulus,
    inflate_no_go,
    label_voxels,
)
from .overflight import MockOverflight
from .radius import compute_orbit_radius, compute_vfov
from .types import AOI, Stage2Output

log = logging.getLogger(__name__)

# Default camera intrinsics (1920x1080, ~60-degree HFOV)
DEFAULT_K = np.array(
    [[1000.0, 0.0, 960.0],
     [0.0, 1000.0, 540.0],
     [0.0, 0.0,    1.0]],
    dtype=np.float64,
)
DEFAULT_IMG_HEIGHT = 1080


class Stage2Runner:
    """
    Runs all Stage 2 sub-steps and returns a Stage2Output.

    Parameters
    ----------
    K                : 3x3 camera intrinsics matrix
    image_height     : sensor height in pixels
    stream_url       : stream server URL (used by MockOverflight for nadir frames)
    sam2_checkpoint  : path to SAM 2 model checkpoint
    H_true_mock      : simulated building height fed to MockOverflight rangefinder
    """

    def __init__(
        self,
        K: Optional[np.ndarray] = None,
        image_height: int = DEFAULT_IMG_HEIGHT,
        stream_url: str = "http://localhost:5001",
        sam2_checkpoint: str = "pipeline/sam2.1_hiera_tiny.pt",
        H_true_mock: float = 15.0,
    ) -> None:
        self.K = K if K is not None else DEFAULT_K.copy()
        self.image_height = image_height
        self.stream_url = stream_url
        self.sam2_checkpoint = sam2_checkpoint
        self.H_true_mock = H_true_mock
        self._depth_model = None  # lazy-load if needed

    # ------------------------------------------------------------------
    def run(self, aoi: AOI) -> Stage2Output:
        log.info("Stage 2 started")

        # ---- 2a: Overflight ----
        log.info("  2a: AOI overflight & data capture")
        overflight = MockOverflight(
            aoi=aoi,
            H_true=self.H_true_mock,
            stream_url=self.stream_url,
        )
        rangefinder_readings, nadir_frames = overflight.run()
        log.info(
            f"  2a: {len(rangefinder_readings)} rangefinder readings, "
            f"{len(nadir_frames)} nadir frames"
        )

        # ---- 2b: Height estimation ----
        log.info("  2b: Height estimation")
        H_rf = rangefinder_height(rangefinder_readings, aoi)
        H_dsm_val = dsm_height(nadir_frames, aoi, self.K, self._depth_model)
        H_fused, height_disagreed = fuse_heights(H_rf, H_dsm_val)
        H, height_warning = apply_height_edge_cases(H_fused)
        log.info(
            f"  2b: H_rangefinder={H_rf:.1f} m, H_dsm={H_dsm_val:.1f} m, "
            f"H_fused={H:.1f} m, disagreed={height_disagreed}"
        )

        # ---- 2c: Orbit radius ----
        log.info("  2c: Orbit radius calculation")
        vfov = compute_vfov(self.K, self.image_height)
        r, r_raw, fill_ratio = compute_orbit_radius(H, vfov)
        r_clamped = abs(r - r_raw) > 0.001
        z_orbit = H / 2.0
        log.info(f"  2c: r={r:.1f} m, z_orbit={z_orbit:.1f} m, fill={fill_ratio:.2f}")

        # ---- 2d: Obstacle map ----
        log.info("  2d: Obstacle map construction")
        cloud_full = build_point_cloud(
            nadir_frames, self.K, aoi=aoi, r=r, depth_model=self._depth_model
        )
        cloud_annulus = filter_to_annulus(cloud_full, aoi.centroid_enu, r)
        obstacle_map = build_octomap(cloud_annulus)
        label_voxels(nadir_frames, self.K, obstacle_map, self.sam2_checkpoint)
        if isinstance(obstacle_map, MockOctoMap):
            inflate_no_go(obstacle_map)
        no_fly_vols = extract_no_fly_volumes(obstacle_map)  # type: ignore[arg-type]
        log.info(
            f"  2d: {obstacle_map.size()} occupied voxels, "
            f"{len(no_fly_vols)} no-fly volumes"
        )

        # ---- Gate check ----
        assert H > 0, "Height estimation failed (H == 0)"
        assert 3.0 <= r <= 50.0, f"Orbit radius {r:.1f} m outside safe range [3, 50]"
        assert obstacle_map.size() > 0, "OctoMap empty after construction"
        log.info("Stage 2 gate check: PASSED")

        voxel_labels = dict(obstacle_map.items()) if isinstance(obstacle_map, MockOctoMap) else None

        return Stage2Output(
            H=H,
            r=r,
            z_orbit=z_orbit,
            obstacle_map=obstacle_map,
            no_fly_volumes=no_fly_vols,
            H_rangefinder=H_rf,
            H_dsm=H_dsm_val,
            r_raw=r_raw,
            vfov_rad=vfov,
            fill_ratio=fill_ratio,
            height_disagreed=height_disagreed,
            height_warning=height_warning,
            r_clamped=r_clamped,
            rangefinder_readings=rangefinder_readings,
            cloud_enu=cloud_annulus,
            voxel_labels=voxel_labels,
        )
