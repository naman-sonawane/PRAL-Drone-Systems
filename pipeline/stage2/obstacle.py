"""
Sub-step 2d -- Obstacle Map Construction.

Builds a 3D occupancy map (OctoMap or MockOctoMap) filtered to the orbit
annulus [r*0.7, r*1.5], then labels voxels with SAM 2 + CLIP.

All heavy packages are optional; the mock path keeps the pipeline runnable
without a GPU or extra installs.
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .height import pose_to_Rt, unproject
from .types import AOI, NadirFrame

log = logging.getLogger(__name__)

VOXEL_SIZE = 0.25   # meters
LABEL_NO_GO = 1
LABEL_TRAVERSABLE = 2

_NO_GO_TEXTS = ["tree", "vegetation", "bush", "utility pole", "wire", "fence"]
_TRAV_TEXTS = ["building wall", "concrete", "brick facade", "roof", "pavement"]


# ---------------------------------------------------------------------------
# Mock OctoMap
# ---------------------------------------------------------------------------

class MockOctoMap:
    """
    Minimal 3D occupancy grid backed by a dict when octomap-python is absent.
    Key: (ix, iy, iz) integer voxel indices at VOXEL_SIZE resolution.
    Value: 0 (unlabeled occupied) | LABEL_NO_GO | LABEL_TRAVERSABLE
    """

    def __init__(self, resolution: float = VOXEL_SIZE) -> None:
        self.resolution = resolution
        self._nodes: Dict[Tuple[int, int, int], int] = {}

    def _key(self, pt: np.ndarray) -> Tuple[int, int, int]:
        return (
            int(np.floor(pt[0] / self.resolution)),
            int(np.floor(pt[1] / self.resolution)),
            int(np.floor(pt[2] / self.resolution)),
        )

    def update_node(self, pt: np.ndarray, occupied: bool) -> None:
        if occupied:
            self._nodes.setdefault(self._key(pt), 0)

    def set_label(self, pt: np.ndarray, label: int) -> None:
        k = self._key(pt)
        if k in self._nodes:
            self._nodes[k] = label

    def size(self) -> int:
        return len(self._nodes)

    def items(self):
        return self._nodes.items()


def _try_real_octomap():
    try:
        import octomap
        return octomap
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Point cloud from depth
# ---------------------------------------------------------------------------

def _mock_depth_for_obstacle(
    frame: NadirFrame,
    aoi: AOI,
    r: float,
) -> np.ndarray:
    """
    Synthetic depth: distribute points around the orbit annulus.
    Building walls (inner annulus) are closer; outer zone is further away.
    """
    h, w = frame.image.shape[:2]
    drone_z = frame.drone_pos_enu[2]
    rng = np.random.default_rng(int(abs(frame.timestamp * 1000)) % (2**31))
    # Base: ground-distance depth
    depth = np.full((h, w), float(drone_z), dtype=np.float32)
    # Horizontal strips represent walls at different ranges
    for row_band in range(4):
        r0 = row_band * (h // 4)
        r1 = r0 + h // 4
        wall_dist = r * (0.7 + row_band * 0.2)
        depth[r0:r1, :] = (wall_dist + rng.normal(0, 0.5, (h // 4, w))).astype(np.float32)
    return depth


def build_point_cloud(
    frames: List[NadirFrame],
    K: np.ndarray,
    aoi: Optional[AOI] = None,
    r: float = 10.0,
    depth_model=None,
) -> np.ndarray:
    """
    Merge depth-back-projected point clouds from all nadir frames into ENU.
    Uses Depth Anything V2 when available; falls back to mock depth.
    """
    all_pts: List[np.ndarray] = []

    for frame in frames:
        if depth_model is not None:
            try:
                import cv2
                rgb = cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB)
                depth = depth_model.infer_image(rgb)
            except Exception as exc:
                log.warning(f"Depth model failed: {exc} -- using mock depth")
                depth = _mock_depth_for_obstacle(frame, aoi, r) if aoi else np.zeros(
                    (frame.image.shape[0], frame.image.shape[1]), dtype=np.float32
                )
        else:
            depth = _mock_depth_for_obstacle(frame, aoi, r) if aoi else np.zeros(
                (frame.image.shape[0], frame.image.shape[1]), dtype=np.float32
            )

        # Subsample depth map (every 8th pixel) to keep point count manageable
        depth_sub = depth[::8, ::8]
        pts_cam = unproject(depth_sub, K)
        R, t = pose_to_Rt(frame)
        pts_enu = (R @ pts_cam.T).T + t
        all_pts.append(pts_enu.astype(np.float32))

    if not all_pts:
        return np.zeros((0, 3), dtype=np.float32)

    cloud = np.vstack(all_pts)
    return cloud[np.isfinite(cloud).all(axis=1)]


# ---------------------------------------------------------------------------
# Annulus filter
# ---------------------------------------------------------------------------

def filter_to_annulus(
    cloud: np.ndarray,
    aoi_centroid_enu: Tuple[float, float],
    r: float,
) -> np.ndarray:
    """Keep only points inside the orbit annulus [r*0.7, r*1.5] and z > -1 m."""
    if cloud.shape[0] == 0:
        return cloud
    cx, cy = aoi_centroid_enu
    dist_2d = np.linalg.norm(cloud[:, :2] - np.array([cx, cy]), axis=1)
    mask = (dist_2d > r * 0.7) & (dist_2d < r * 1.5) & (cloud[:, 2] > -1.0)
    return cloud[mask]


# ---------------------------------------------------------------------------
# OctoMap insertion
# ---------------------------------------------------------------------------

def build_octomap(cloud: np.ndarray) -> MockOctoMap:
    """Insert cloud into an OctoMap (real if installed, else MockOctoMap)."""
    octomap_mod = _try_real_octomap()
    if octomap_mod is not None:
        tree = octomap_mod.OcTree(VOXEL_SIZE)
        for pt in cloud:
            tree.updateNode(pt.tolist(), True)
        tree.updateInnerOccupancy()
        return tree  # type: ignore[return-value]

    tree = MockOctoMap(VOXEL_SIZE)
    for pt in cloud:
        tree.update_node(pt, True)
    return tree


# ---------------------------------------------------------------------------
# Semantic labeling: SAM 2 + CLIP, with no-go fallback
# ---------------------------------------------------------------------------

def _try_load_clip():
    try:
        import clip
        import torch
        model, preprocess = clip.load("ViT-B/32")
        return model, preprocess, torch, clip
    except Exception:
        return None, None, None, None


def _try_load_sam2(checkpoint: str):
    try:
        import torch
        from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
        from sam2.build_sam import build_sam2

        device = "cuda" if torch.cuda.is_available() else "cpu"
        sam2 = build_sam2("sam2.1_hiera_tiny.yaml", checkpoint, device=device)
        return SAM2AutomaticMaskGenerator(sam2)
    except Exception:
        return None


def label_voxels(
    frames: List[NadirFrame],
    K: np.ndarray,
    tree: MockOctoMap,
    sam2_checkpoint: str = "pipeline/sam2.1_hiera_tiny.pt",
) -> None:
    """
    Label occupied voxels using SAM 2 masks + CLIP zero-shot classification.
    Falls back to marking all voxels no-go when models are unavailable.
    """
    clip_model, clip_preprocess, torch_mod, clip_mod = _try_load_clip()
    mask_gen = _try_load_sam2(sam2_checkpoint)

    if clip_model is None or mask_gen is None:
        log.warning("CLIP/SAM 2 unavailable -- all voxels marked no-go (safe default)")
        _default_all_no_go(tree)
        return

    no_go_tok = clip_mod.tokenize(_NO_GO_TEXTS)
    trav_tok = clip_mod.tokenize(_TRAV_TEXTS)
    fx, fy = K[0, 0], K[1, 1]
    cx_k, cy_k = K[0, 2], K[1, 2]

    for frame in frames:
        rgb = frame.image[:, :, ::-1]  # BGR -> RGB
        masks = mask_gen.generate(rgb)
        R, t = pose_to_Rt(frame)

        for mask_data in masks:
            x, y, bw, bh = (int(v) for v in mask_data["bbox"])
            crop = frame.image[y: y + bh, x: x + bw]
            if crop.size == 0:
                continue

            from PIL import Image as PILImage

            img_pil = PILImage.fromarray(crop[:, :, ::-1])
            img_t = clip_preprocess(img_pil).unsqueeze(0)
            with torch_mod.no_grad():
                logits_ng, _ = clip_model(img_t, no_go_tok)
                logits_tr, _ = clip_model(img_t, trav_tok)
            label = LABEL_NO_GO if logits_ng.max() > logits_tr.max() else LABEL_TRAVERSABLE

            seg = mask_data["segmentation"]  # HxW bool
            ys_px, xs_px = np.where(seg)
            for px, py in zip(xs_px[::10], ys_px[::10]):
                ray_cam = np.array([(px - cx_k) / fx, (py - cy_k) / fy, 1.0])
                ray_enu = R @ ray_cam
                if abs(ray_enu[2]) < 1e-6:
                    continue
                t_hit = -frame.drone_pos_enu[2] / ray_enu[2]
                hit = np.array(frame.drone_pos_enu) + t_hit * ray_enu
                if isinstance(tree, MockOctoMap):
                    tree.set_label(hit, label)


def _default_all_no_go(tree: MockOctoMap) -> None:
    """Mark all unlabeled occupied voxels as no-go."""
    if isinstance(tree, MockOctoMap):
        for k in tree._nodes:
            if tree._nodes[k] == 0:
                tree._nodes[k] = LABEL_NO_GO


# ---------------------------------------------------------------------------
# No-go inflation
# ---------------------------------------------------------------------------

def inflate_no_go(tree: MockOctoMap, inflation_m: float = 1.0) -> None:
    """Add safety buffer around all no-go voxels (1 m = 4 voxels at 25 cm)."""
    if not isinstance(tree, MockOctoMap):
        return
    n_vox = max(1, int(inflation_m / tree.resolution))
    seeds = [k for k, v in tree._nodes.items() if v == LABEL_NO_GO]
    for ix, iy, iz in seeds:
        for dx in range(-n_vox, n_vox + 1):
            for dy in range(-n_vox, n_vox + 1):
                for dz in range(-n_vox, n_vox + 1):
                    nb = (ix + dx, iy + dy, iz + dz)
                    if nb not in tree._nodes:
                        tree._nodes[nb] = LABEL_NO_GO


# ---------------------------------------------------------------------------
# No-fly volume extraction
# ---------------------------------------------------------------------------

def extract_no_fly_volumes(
    tree: MockOctoMap,
) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    """
    BFS-cluster contiguous no-go voxels. Returns AABB tuples
    ((min_e, min_n, min_u), (max_e, max_n, max_u)) per cluster.
    """
    if not isinstance(tree, MockOctoMap):
        return []

    no_go = {k for k, v in tree._nodes.items() if v == LABEL_NO_GO}
    visited: set = set()
    volumes = []
    _NEIGHBORS = [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]

    for start in no_go:
        if start in visited:
            continue
        component = []
        q: deque = deque([start])
        while q:
            cur = q.popleft()
            if cur in visited:
                continue
            visited.add(cur)
            component.append(cur)
            for dx, dy, dz in _NEIGHBORS:
                nb = (cur[0]+dx, cur[1]+dy, cur[2]+dz)
                if nb in no_go and nb not in visited:
                    q.append(nb)

        rs = tree.resolution
        xs = [k[0] * rs for k in component]
        ys = [k[1] * rs for k in component]
        zs = [k[2] * rs for k in component]
        volumes.append((
            (min(xs), min(ys), min(zs)),
            (max(xs) + rs, max(ys) + rs, max(zs) + rs),
        ))

    return volumes
