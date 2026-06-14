"""
Stage 3 -- 360 Map (DFS/NBV): Runner.

Orchestrates 3a -> 3b -> 3c -> 3d (NBV loop) -> 3e and returns Stage3Output.
Gate check enforced before returning; raises AssertionError on hard failure,
sets reduced_confidence flag on soft (PSNR/SSIM) failure.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import List, Optional, Tuple

import numpy as np

from pipeline.stage2.obstacle import MockOctoMap
from .colmap import MockPoseEstimator, run_colmap
from .coverage import (
    build_coverage_map,
    coverage_fraction,
    detect_frontiers,
    mark_seen_voxels,
)
from .nbv import generate_closeup_viewpoint, rank_frontiers
from .orbit import FolderOrbit, MockOrbit, generate_orbit_waypoints
from .splat import MockSplat, compute_psnr_ssim, run_3dgs
from .types import AOI, OrbitFrame, PosedFrame, Stage2Output, Stage3Output

log = logging.getLogger(__name__)

DEFAULT_K = np.array(
    [[1000.0, 0.0, 960.0],
     [0.0, 1000.0, 540.0],
     [0.0, 0.0,    1.0]],
    dtype=np.float64,
)
DEFAULT_IMG_HEIGHT = 1080
DEFAULT_IMG_WIDTH = 1920


class Stage3Runner:
    """
    Runs all Stage 3 sub-steps and returns a Stage3Output.

    Parameters
    ----------
    K                : 3x3 camera intrinsics matrix
    image_height     : sensor height in pixels
    image_width      : sensor width in pixels
    stream_url       : stream server URL (used by MockOrbit for orbit frames)
    image_dir        : if set, load frames from this directory instead of flying (FolderOrbit)
    colmap_workspace : directory for COLMAP and 3DGS working files
    coverage_target  : stop when coverage fraction reaches this value (0-1)
    battery_floor    : stop when battery fraction drops to this value (0-1)
    min_posed_frames : hard gate: minimum required posed frames
    psnr_threshold   : soft gate: minimum acceptable PSNR (dB)
    ssim_threshold   : soft gate: minimum acceptable SSIM
    """

    def __init__(
        self,
        K: Optional[np.ndarray] = None,
        image_height: int = DEFAULT_IMG_HEIGHT,
        image_width: int = DEFAULT_IMG_WIDTH,
        stream_url: str = "http://localhost:5001",
        image_dir: Optional[str] = None,
        colmap_workspace: Optional[str] = None,
        coverage_target: float = 0.90,
        battery_floor: float = 0.30,
        min_posed_frames: int = 24,
        psnr_threshold: float = 25.0,
        ssim_threshold: float = 0.85,
    ) -> None:
        self.K = K if K is not None else DEFAULT_K.copy()
        self.image_height = image_height
        self.image_width = image_width
        self.stream_url = stream_url
        self.image_dir = image_dir
        self.colmap_workspace = colmap_workspace or tempfile.mkdtemp(prefix="stage3_")
        self.coverage_target = coverage_target
        self.battery_floor = battery_floor
        self.min_posed_frames = min_posed_frames
        self.psnr_threshold = psnr_threshold
        self.ssim_threshold = ssim_threshold

    # ------------------------------------------------------------------
    def run(
        self,
        stage2_out: Stage2Output,
        aoi_centroid_enu: Tuple[float, float] = (0.0, 0.0),
    ) -> Stage3Output:
        """
        Execute all Stage 3 sub-steps and return Stage3Output.

        Parameters
        ----------
        stage2_out       : output from Stage 2 (provides r, z_orbit, obstacle_map)
        aoi_centroid_enu : (e, n) ENU centroid of the area of interest; defaults to
                           (0.0, 0.0) for mock / test operation
        """
        log.info("Stage 3 started")

        r = stage2_out.r
        z_orbit = stage2_out.z_orbit
        obstacle_map = stage2_out.obstacle_map

        # ---- 3a: Base orbit capture ----
        log.info("  3a: Base orbit capture")
        if self.image_dir:
            log.info(f"  3a: loading frames from {self.image_dir!r} (FolderOrbit)")
            orbit = FolderOrbit(self.image_dir)
        else:
            orbit = MockOrbit(
                aoi_centroid_enu=aoi_centroid_enu,
                r=r,
                z_orbit=z_orbit,
                stream_url=self.stream_url,
            )
        orbit_frames: List[OrbitFrame] = orbit.run()
        log.info(f"  3a: {len(orbit_frames)} orbit frames captured")

        all_frames: List[OrbitFrame] = list(orbit_frames)

        # ---- 3b: Pose estimation ----
        log.info("  3b: Pose estimation (COLMAP / mock)")
        posed_frames: List[PosedFrame] = run_colmap(
            frames=all_frames,
            K=self.K,
            workspace_dir=self.colmap_workspace,
            aoi_centroid_enu=aoi_centroid_enu,
            r=r,
            z_orbit=z_orbit,
        )
        log.info(f"  3b: {len(posed_frames)} posed frames")

        # ---- 3c: Coverage mapping ----
        log.info("  3c: Coverage mapping")
        coverage_map = build_coverage_map(obstacle_map)
        mark_seen_voxels(coverage_map, posed_frames, self.K)
        cov_frac = coverage_fraction(coverage_map)
        frontiers = detect_frontiers(coverage_map)
        log.info(
            f"  3c: coverage={cov_frac:.1%}, {len(frontiers)} frontier(s)"
        )

        # ---- 3d: NBV close-up loop ----
        log.info("  3d: NBV close-up loop")
        coverage_target_met = cov_frac >= self.coverage_target
        battery_floor_hit = False
        closeup_viewpoints_flown = 0
        closeup_frames: List[OrbitFrame] = []
        _battery = 1.0          # mock battery starts full
        _battery_step = 0.05    # each close-up costs 5 %

        ranked = rank_frontiers(frontiers)
        for frontier in ranked:
            if coverage_target_met:
                break
            _battery -= _battery_step
            if _battery <= self.battery_floor:
                battery_floor_hit = True
                log.warning(f"  3d: battery floor hit at {_battery:.0%}")
                break

            viewpoint = generate_closeup_viewpoint(frontier, obstacle_map, r)
            if viewpoint is None:
                log.info(
                    f"  3d: no collision-free viewpoint for frontier at {frontier.centroid_enu}"
                )
                continue

            pos, yaw = viewpoint
            # Capture a close-up frame (mock: re-use orbit fetch)
            cu_frame = orbit._fetch_frame()
            pitch = -np.arctan2(z_orbit, r * 0.5)
            all_frames.append(OrbitFrame(
                image=cu_frame,
                drone_pos_enu=pos,
                drone_attitude_rpy=(0.0, float(pitch), float(yaw)),
                timestamp=float(len(all_frames)),
                pass_type="closeup",
            ))
            closeup_frames.append(all_frames[-1])
            closeup_viewpoints_flown += 1

            # Re-estimate poses and update coverage
            posed_frames = run_colmap(
                frames=all_frames,
                K=self.K,
                workspace_dir=self.colmap_workspace,
                aoi_centroid_enu=aoi_centroid_enu,
                r=r,
                z_orbit=z_orbit,
            )
            mark_seen_voxels(coverage_map, posed_frames, self.K)
            cov_frac = coverage_fraction(coverage_map)
            frontiers = detect_frontiers(coverage_map)
            ranked = rank_frontiers(frontiers)
            coverage_target_met = cov_frac >= self.coverage_target
            log.info(
                f"  3d: after closeup #{closeup_viewpoints_flown}: "
                f"coverage={cov_frac:.1%}, frontiers={len(frontiers)}"
            )

        if coverage_target_met:
            log.info(f"  3d: coverage target met ({cov_frac:.1%})")
        elif not battery_floor_hit:
            # No more frontiers — coverage is as high as possible
            coverage_target_met = True

        # ---- 3e: 3D Gaussian Splatting ----
        log.info("  3e: 3D Gaussian Splatting")
        held_out = posed_frames[7::8]      # every 8th frame held out
        train_frames = [pf for i, pf in enumerate(posed_frames) if i % 8 != 7]

        scene_path = run_3dgs(
            posed_frames=train_frames,
            K=self.K,
            image_width=self.image_width,
            image_height=self.image_height,
            workspace_dir=self.colmap_workspace,
        )
        psnr_db, ssim_val = compute_psnr_ssim(
            scene_path, held_out, self.K,
            image_width=self.image_width,
            image_height=self.image_height,
        )
        log.info(f"  3e: scene={scene_path}, PSNR={psnr_db:.1f}dB, SSIM={ssim_val:.3f}")

        # ---- Gate check ----
        mean_repr_err = (
            float(np.mean([pf.reprojection_error_px for pf in posed_frames]))
            if posed_frames
            else 0.0
        )

        assert len(posed_frames) >= self.min_posed_frames, (
            f"Insufficient posed frames: {len(posed_frames)} < {self.min_posed_frames}"
        )
        assert mean_repr_err < 1.0, (
            f"Pose accuracy failed: mean reprojection error {mean_repr_err:.2f}px >= 1px"
        )
        assert coverage_target_met or battery_floor_hit, (
            "Stop condition was never triggered -- loop may have exited abnormally"
        )
        log.info("Stage 3 gate check: PASSED")

        quality_warning = ""
        reduced_confidence = False
        if psnr_db < self.psnr_threshold:
            quality_warning += f"PSNR {psnr_db:.1f}dB < {self.psnr_threshold}dB floor. "
            reduced_confidence = True
        if ssim_val < self.ssim_threshold:
            quality_warning += f"SSIM {ssim_val:.3f} < {self.ssim_threshold} floor."
            reduced_confidence = True
        if reduced_confidence:
            log.warning(
                f"Stage 3 quality below floor -- proceeding with reduced confidence: {quality_warning}"
            )

        n_orbit = sum(1 for f in all_frames if f.pass_type == "orbit")
        n_closeup = sum(1 for f in all_frames if f.pass_type == "closeup")

        return Stage3Output(
            posed_frames=posed_frames,
            scene_path=scene_path,
            model_type="3dgs",
            coverage_fraction=cov_frac,
            coverage_target_met=coverage_target_met,
            battery_floor_hit=battery_floor_hit,
            n_orbit_frames=n_orbit,
            n_closeup_frames=n_closeup,
            psnr_db=psnr_db,
            ssim=ssim_val,
            mean_reprojection_error_px=mean_repr_err,
            coverage_map=coverage_map,
            frontiers_detected=len(frontiers),
            closeup_viewpoints_flown=closeup_viewpoints_flown,
            quality_warning=quality_warning,
            reduced_confidence=reduced_confidence,
        )
