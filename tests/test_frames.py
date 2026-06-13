"""Test 1 (Tier A) -- GPS pin -> local ENU/NED frame, round-trip < 0.5 m."""

import numpy as np

from pral.core.frames import (
    enu_to_geodetic,
    enu_to_ned,
    geodetic_to_enu,
    geodetic_to_ecef,
    ecef_to_geodetic,
    ned_to_enu,
)

HOME = (37.4275, -122.1697, 12.0)  # Stanford-ish


def test_home_maps_to_origin():
    enu = geodetic_to_enu(*HOME, *HOME)
    assert np.linalg.norm(enu) < 1e-6


def test_known_offsets_directions():
    # A point slightly north should have +north, ~0 east.
    enu = geodetic_to_enu(HOME[0] + 0.001, HOME[1], HOME[2], *HOME)
    assert enu[1] > 100.0  # ~111 m per 0.001 deg lat
    assert abs(enu[0]) < 1.0
    # A point slightly east should have +east.
    enu_e = geodetic_to_enu(HOME[0], HOME[1] + 0.001, HOME[2], *HOME)
    assert enu_e[0] > 50.0
    assert abs(enu_e[1]) < 1.0


def test_roundtrip_accuracy_within_few_km():
    rng = np.random.default_rng(0)
    max_err = 0.0
    for _ in range(200):
        # +/- ~3 km spread.
        dlat = rng.uniform(-0.03, 0.03)
        dlon = rng.uniform(-0.03, 0.03)
        dalt = rng.uniform(-100, 200)
        lat, lon, alt = HOME[0] + dlat, HOME[1] + dlon, HOME[2] + dalt
        enu = geodetic_to_enu(lat, lon, alt, *HOME)
        back = enu_to_geodetic(enu[0], enu[1], enu[2], *HOME)
        # Compare in meters via ECEF distance.
        p_true = geodetic_to_ecef(lat, lon, alt)
        p_back = geodetic_to_ecef(back[0], back[1], back[2])
        err = np.linalg.norm(p_true - p_back)
        max_err = max(max_err, err)
    assert max_err < 0.5, f"max round-trip error {max_err:.4f} m exceeds 0.5 m"


def test_ecef_geodetic_roundtrip():
    p = geodetic_to_ecef(*HOME)
    back = ecef_to_geodetic(*p)
    assert abs(back[0] - HOME[0]) < 1e-7
    assert abs(back[1] - HOME[1]) < 1e-7
    assert abs(back[2] - HOME[2]) < 1e-3


def test_ned_is_enu_remap():
    enu = np.array([3.0, 5.0, 7.0])  # E, N, U
    ned = enu_to_ned(enu)
    assert np.allclose(ned, [5.0, 3.0, -7.0])  # N, E, D
    assert np.allclose(ned_to_enu(ned), enu)
