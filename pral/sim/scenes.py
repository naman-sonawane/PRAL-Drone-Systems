"""Procedural voxel scenes for synthetic (Tier-B) tests.

A :class:`VoxelScene` is a regular 3D occupancy grid in the local ENU frame
anchored so that index ``(0, 0, 0)`` sits at ``origin_enu``. The cell size is
``voxel_size`` meters. Each occupied voxel carries a *label* (ground, building,
tree, pole, wire) so tests can measure obstacle recall against ground truth.

Why a voxel grid? Every downstream Tier-B concern reduces to the same query:
"is the straight line between a camera and a surface point clear?" A regular
occupancy grid makes that a deterministic DDA ray march -- no meshes, no CV.

What the scene exposes (the three ground-truth products the harness needs)
-------------------------------------------------------------------------
* **surface voxels** -- the outward-facing shell voxels of the *building*.
  Coverage truth (Test 9) is "what fraction of these has any camera seen?".
* **labeled occupancy** -- every occupied voxel + its :class:`VoxelLabel`.
  Obstacle-recall truth (Test 7) compares a built occupancy map to the
  ``OBSTACLE`` labels lying in the orbit annulus.
* **occluded-from-orbit truth** -- per building-surface voxel, whether a
  ring of cameras at the orbit radius (aimed at the centroid) can see it.
  A wall hidden behind a tree is occluded; this is the frontier truth for
  Tests 10/11/25.

Determinism: obstacle placement uses ``numpy.random.default_rng(seed)``; the
default seed is ``0``. No wall-clock, no global RNG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


class VoxelLabel(IntEnum):
    """Semantic label of an occupied voxel."""

    EMPTY = 0
    GROUND = 1
    BUILDING = 2
    TREE = 3
    POLE = 4
    WIRE = 5

    @property
    def is_obstacle(self) -> bool:
        """Hazards the drone must not hit on the orbit path (Test 7)."""
        return self in (VoxelLabel.TREE, VoxelLabel.POLE, VoxelLabel.WIRE)


# ---------------------------------------------------------------------------
# Ray marching against the grid (shared by depth + visibility)
# ---------------------------------------------------------------------------


def _voxel_traversal(
    origin: np.ndarray,
    direction: np.ndarray,
    shape: tuple[int, int, int],
    max_t: float,
) -> list[tuple[int, int, int, float]]:
    """Amanatides-Woo voxel DDA in *index* space.

    ``origin`` / ``direction`` are in continuous voxel-index coordinates (i.e.
    already divided by ``voxel_size`` and shifted so the grid corner is 0).
    Yields ``(i, j, k, t_entry)`` for every cell the ray crosses, in order,
    until it leaves the grid or ``t`` exceeds ``max_t``. ``t`` is measured in
    the same units as ``direction`` length (caller normalizes as needed).
    """
    direction = np.asarray(direction, dtype=float)
    n = np.linalg.norm(direction)
    if n < 1e-12:
        return []
    d = direction / n
    max_t_norm = max_t  # caller passes max_t already in matching units

    cells: list[tuple[int, int, int, float]] = []
    pos = np.asarray(origin, dtype=float)
    ijk = np.floor(pos).astype(int)
    step = np.where(d > 0, 1, -1)

    t_max = np.empty(3)
    t_delta = np.empty(3)
    for a in range(3):
        if abs(d[a]) < 1e-12:
            t_max[a] = np.inf
            t_delta[a] = np.inf
        else:
            nxt = ijk[a] + (1 if step[a] > 0 else 0)
            t_max[a] = (nxt - pos[a]) / d[a]
            t_delta[a] = abs(1.0 / d[a])

    t = 0.0
    # Number of cells we could possibly cross is bounded by the grid extent.
    max_steps = 2 * (shape[0] + shape[1] + shape[2]) + 8
    for _ in range(max_steps):
        i, j, k = int(ijk[0]), int(ijk[1]), int(ijk[2])
        if 0 <= i < shape[0] and 0 <= j < shape[1] and 0 <= k < shape[2]:
            cells.append((i, j, k, t))
        elif cells:
            # We were inside and have now exited.
            break
        a = int(np.argmin(t_max))
        t = t_max[a]
        if t > max_t_norm:
            break
        ijk[a] += step[a]
        t_max[a] += t_delta[a]
    return cells


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


@dataclass
class VoxelScene:
    """A procedural building + obstacles on a ground plane, as a voxel grid.

    Use :meth:`make` to construct one; the dataclass fields are the resolved
    grid + ground-truth products.
    """

    voxel_size: float
    origin_enu: np.ndarray  # ENU position of grid corner (i=j=k=0)
    labels: np.ndarray  # int grid [nx, ny, nz] of VoxelLabel values
    building_height: float
    centroid_enu: np.ndarray  # building footprint centroid (E, N, U=0)
    orbit_radius: float
    surface_voxels: np.ndarray = field(default_factory=lambda: np.empty((0, 3)))
    surface_indices: np.ndarray = field(default_factory=lambda: np.empty((0, 3), int))
    occluded_from_orbit: np.ndarray = field(default_factory=lambda: np.empty((0,), bool))

    # ---- geometry helpers -------------------------------------------------

    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(int(s) for s in self.labels.shape)  # type: ignore[return-value]

    def index_to_enu(self, ijk: np.ndarray) -> np.ndarray:
        """Center of voxel ``(i, j, k)`` in ENU meters."""
        ijk = np.asarray(ijk, dtype=float)
        return self.origin_enu + (ijk + 0.5) * self.voxel_size

    def enu_to_index(self, p: np.ndarray) -> np.ndarray:
        """Continuous voxel-index coordinates of ENU point ``p``."""
        p = np.asarray(p, dtype=float)
        return (p - self.origin_enu) / self.voxel_size

    def is_occupied(self, ijk: tuple[int, int, int]) -> bool:
        i, j, k = ijk
        s = self.shape
        if not (0 <= i < s[0] and 0 <= j < s[1] and 0 <= k < s[2]):
            return False
        return self.labels[i, j, k] != VoxelLabel.EMPTY

    def occupied_voxels(self, only_obstacles: bool = False) -> np.ndarray:
        """Indices ``[m, 3]`` of occupied voxels (optionally obstacles only)."""
        if only_obstacles:
            mask = np.isin(
                self.labels,
                [int(VoxelLabel.TREE), int(VoxelLabel.POLE), int(VoxelLabel.WIRE)],
            )
        else:
            mask = self.labels != int(VoxelLabel.EMPTY)
        return np.argwhere(mask)

    def obstacle_voxels_enu(self) -> np.ndarray:
        """ENU centers ``[m, 3]`` of obstacle (tree/pole/wire) voxels."""
        idx = self.occupied_voxels(only_obstacles=True)
        if len(idx) == 0:
            return np.empty((0, 3))
        return np.array([self.index_to_enu(v) for v in idx])

    # ---- ray queries ------------------------------------------------------

    def line_of_sight_clear(
        self,
        cam_enu: np.ndarray,
        target_enu: np.ndarray,
        ignore_indices: set[tuple[int, int, int]] | None = None,
    ) -> bool:
        """True if the segment cam->target hits no occupied voxel (excluding
        ``ignore_indices``, typically the target's own voxel and its neighbors).
        """
        o = self.enu_to_index(cam_enu)
        tgt = self.enu_to_index(target_enu)
        seg = tgt - o
        length = float(np.linalg.norm(seg))
        if length < 1e-9:
            return True
        ignore = ignore_indices or set()
        # Stop just short of the target so we don't count the surface itself.
        max_t = length - 0.5
        for (i, j, k, t) in _voxel_traversal(o, seg, self.shape, max_t):
            if t <= 1e-6:
                continue
            if (i, j, k) in ignore:
                continue
            if self.labels[i, j, k] != int(VoxelLabel.EMPTY):
                return False
        return True

    # ---- construction -----------------------------------------------------

    @classmethod
    def make(
        cls,
        building: str = "box",
        height: float = 30.0,
        width: float = 20.0,
        depth: float = 20.0,
        voxel_size: float = 2.0,
        n_trees: int = 6,
        n_poles: int = 2,
        n_wires: int = 0,
        margin: float = 4.0,
        vfov_deg: float = 53.0,
        block_face: bool = False,
        seed: int = 0,
    ) -> "VoxelScene":
        """Build a procedural scene.

        Parameters
        ----------
        building
            ``"box"`` or ``"L"`` (an L-shaped footprint).
        height, width, depth
            Building dimensions in meters (depth = N extent, width = E extent).
        voxel_size
            Cell size in meters.
        n_trees, n_poles, n_wires
            Obstacle counts, placed in the orbit annulus.
        margin
            Extra framing margin used to compute the orbit radius
            ``r = (H/2 + margin) / tan(vfov/2)``.
        block_face
            If True, deterministically place a tall tree directly on the +N
            face's orbit line so that face is occluded from the orbit (used by
            occlusion / close-up tests 10/11/25).
        seed
            RNG seed for obstacle scatter (default 0).
        """
        rng = np.random.default_rng(seed)
        vs = float(voxel_size)

        # Orbit radius from the framing equation (Stage 2 math).
        r = (height / 2.0 + margin) / np.tan(np.radians(vfov_deg) / 2.0)

        # Footprint centroid at the world origin; ground plane at U=0.
        # Grid spans a square big enough for the building + orbit + obstacle ring.
        half_extent = r + 2.0 * max(width, depth) + 6.0
        origin = np.array([-half_extent, -half_extent, 0.0])
        nx = ny = int(np.ceil(2 * half_extent / vs))
        nz = int(np.ceil((height + 2 * vs) / vs))
        labels = np.zeros((nx, ny, nz), dtype=np.int16)

        centroid = np.array([0.0, 0.0, 0.0])

        def enu_to_idx(p: np.ndarray) -> np.ndarray:
            return np.floor((np.asarray(p, float) - origin) / vs).astype(int)

        # --- ground plane (k = 0 layer) ---
        labels[:, :, 0] = int(VoxelLabel.GROUND)

        # --- building ---
        hw, hd = width / 2.0, depth / 2.0
        kz_top = int(np.ceil(height / vs))

        def fill_box(e0: float, e1: float, n0: float, n1: float, ktop: int) -> None:
            i0, j0, _ = enu_to_idx([e0, n0, 0])
            i1, j1, _ = enu_to_idx([e1, n1, 0])
            i0, i1 = sorted((int(i0), int(i1)))
            j0, j1 = sorted((int(j0), int(j1)))
            for i in range(max(i0, 0), min(i1 + 1, nx)):
                for j in range(max(j0, 0), min(j1 + 1, ny)):
                    for k in range(1, min(ktop + 1, nz)):
                        labels[i, j, k] = int(VoxelLabel.BUILDING)

        if building == "box":
            fill_box(-hw, hw, -hd, hd, kz_top)
        elif building == "L":
            # Full box minus the +E/+N quadrant -> L footprint.
            fill_box(-hw, hw, -hd, hd, kz_top)
            i0, j0, _ = enu_to_idx([0.0, 0.0, 0])
            for i in range(max(int(i0), 0), nx):
                for j in range(max(int(j0), 0), ny):
                    for k in range(1, nz):
                        if labels[i, j, k] == int(VoxelLabel.BUILDING):
                            labels[i, j, k] = int(VoxelLabel.EMPTY)
        else:
            raise ValueError(f"unknown building type: {building!r}")

        # --- obstacles in the orbit annulus ---
        def place_pillar(e: float, n: float, top_h: float, label: VoxelLabel) -> None:
            i, j, _ = enu_to_idx([e, n, 0])
            ktop = int(np.ceil(top_h / vs))
            if 0 <= i < nx and 0 <= j < ny:
                for k in range(1, min(ktop + 1, nz)):
                    if labels[i, j, k] == int(VoxelLabel.EMPTY):
                        labels[i, j, k] = int(label)

        def annulus_point() -> tuple[float, float]:
            ang = rng.uniform(0, 2 * np.pi)
            rad = rng.uniform(r * 0.6, r * 0.95)
            return rad * np.cos(ang), rad * np.sin(ang)

        if block_face:
            # A tall tree dead-on the +N orbit face, between orbit cam and wall.
            place_pillar(0.0, hd + 0.5 * (r - hd), min(height * 1.1, height + vs), VoxelLabel.TREE)

        for _ in range(n_trees):
            e, n = annulus_point()
            place_pillar(e, n, rng.uniform(4.0, 12.0), VoxelLabel.TREE)
        for _ in range(n_poles):
            e, n = annulus_point()
            place_pillar(e, n, rng.uniform(6.0, 14.0), VoxelLabel.POLE)
        for _ in range(n_wires):
            e, n = annulus_point()
            place_pillar(e, n, rng.uniform(8.0, 12.0), VoxelLabel.WIRE)

        scene = cls(
            voxel_size=vs,
            origin_enu=origin,
            labels=labels,
            building_height=float(height),
            centroid_enu=centroid,
            orbit_radius=float(r),
        )
        scene._compute_surface()
        scene._compute_occlusion()
        return scene

    # ---- ground-truth products -------------------------------------------

    def _compute_surface(self) -> None:
        """Outward-facing shell voxels of the *building* (the coverage target).

        A building voxel is on the surface if at least one of its 6 face
        neighbors is not building (empty, ground-adjacent air, or off-grid).
        """
        building = self.labels == int(VoxelLabel.BUILDING)
        s = self.shape
        surf_idx: list[tuple[int, int, int]] = []
        offs = [(-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1)]
        bi = np.argwhere(building)
        for i, j, k in bi:
            exposed = False
            for di, dj, dk in offs:
                ni, nj, nk = i + di, j + dj, k + dk
                if not (0 <= ni < s[0] and 0 <= nj < s[1] and 0 <= nk < s[2]):
                    exposed = True
                    break
                if not building[ni, nj, nk]:
                    exposed = True
                    break
            if exposed:
                surf_idx.append((int(i), int(j), int(k)))
        self.surface_indices = np.array(surf_idx, dtype=int)
        if len(surf_idx):
            self.surface_voxels = np.array([self.index_to_enu(v) for v in surf_idx])
        else:
            self.surface_voxels = np.empty((0, 3))

    def orbit_poses_enu(self, n_views: int = 16, altitude: float | None = None) -> np.ndarray:
        """Camera positions on the orbit ring at the orbit radius.

        Aimed (by convention) at the building centroid raised to mid-height.
        ``altitude`` defaults to mid-building height.
        """
        if altitude is None:
            altitude = self.building_height / 2.0
        angs = np.linspace(0, 2 * np.pi, n_views, endpoint=False)
        return np.array(
            [
                [self.orbit_radius * np.cos(a), self.orbit_radius * np.sin(a), altitude]
                for a in angs
            ]
        )

    def _compute_occlusion(self, n_views: int = 24) -> None:
        """Per surface voxel: is it invisible from *every* orbit viewpoint?

        Marches a ray from each orbit camera to each surface voxel; a voxel is
        ``occluded_from_orbit`` if no orbit camera has clear line of sight.
        """
        if len(self.surface_indices) == 0:
            self.occluded_from_orbit = np.empty((0,), bool)
            return
        cams = self.orbit_poses_enu(n_views=n_views)
        occluded = np.ones(len(self.surface_indices), dtype=bool)
        for s_i, ijk in enumerate(self.surface_indices):
            tgt = self.index_to_enu(ijk)
            ignore = {
                (int(ijk[0]) + di, int(ijk[1]) + dj, int(ijk[2]) + dk)
                for di in (-1, 0, 1)
                for dj in (-1, 0, 1)
                for dk in (-1, 0, 1)
            }
            for cam in cams:
                if self.line_of_sight_clear(cam, tgt, ignore_indices=ignore):
                    occluded[s_i] = False
                    break
        self.occluded_from_orbit = occluded


__all__ = ["VoxelLabel", "VoxelScene"]
