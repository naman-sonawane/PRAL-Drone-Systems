"""
Sub-step 2c -- Orbit Radius Calculation.

r = (H/2 + margin) / tan(VFOV/2)
Targets 60-85% vertical frame fill. Clamped to [3.0, 50.0] m.
"""
from __future__ import annotations

import logging
from typing import Tuple

import numpy as np

log = logging.getLogger(__name__)

R_MIN = 3.0
R_MAX = 50.0
MARGIN_M = 3.0   # lateral clearance beyond building footprint edge


def compute_vfov(K: np.ndarray, image_height_px: int) -> float:
    """Derive vertical FOV in radians from camera intrinsics."""
    fy = K[1, 1]
    return float(2.0 * np.arctan(image_height_px / (2.0 * fy)))


def compute_orbit_radius(
    H: float,
    vfov_rad: float,
    margin: float = MARGIN_M,
) -> Tuple[float, float, float]:
    """
    Compute orbit radius so the building fills 60-85% of vertical FOV.

    Returns
    -------
    r_clamped : float  -- safe orbit radius (meters)
    r_raw     : float  -- unclamped value before clip
    fill_ratio: float  -- fraction of VFOV half-angle occupied by building half-height
    """
    r_raw = (H / 2.0 + margin) / np.tan(vfov_rad / 2.0)
    r = float(np.clip(r_raw, R_MIN, R_MAX))

    if abs(r - r_raw) > 0.001:
        log.warning(f"Orbit radius clamped from {r_raw:.1f} m to {r:.1f} m")

    # Verify framing: expand by 10% once if building clips top of frame
    theta_top = np.arctan((H / 2.0) / max(r, 0.01))
    fill_ratio = float(theta_top / (vfov_rad / 2.0))
    if fill_ratio > 0.85:
        r = float(np.clip(r * 1.10, R_MIN, R_MAX))
        theta_top = np.arctan((H / 2.0) / max(r, 0.01))
        fill_ratio = float(theta_top / (vfov_rad / 2.0))
        log.info(f"Orbit radius expanded to {r:.1f} m (fill ratio {fill_ratio:.2f})")

    return r, r_raw, fill_ratio
