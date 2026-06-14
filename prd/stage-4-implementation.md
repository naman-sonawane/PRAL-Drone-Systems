# Stage 4 — Interest Field & Value Assignment: Implementation Spec

> Status: Draft v0.1
> Companion docs: footage-acquisition-io.md · footage-acquisition-testing.md · stage-3-implementation.md
> Input: posed image set + 3D model (mesh or Gaussian splat) from Stage 3
> Output: 3D interest-density surface (per-vertex scores) + value field over viewpoint space

---

## Overview

Stage 4 answers: *which parts of this structure are worth looking at, and from where?* It takes the posed image set and 3D model from Stage 3 and produces a continuous interest field over the building surface. That field is the primary input Stage 5 uses to rank and select shots.

There are five sub-steps, each with a clear transform:

```
4a0. SAM 2 foreground masking      each image → binary subject mask (H×W bool)
4a.  Per-image interest scoring    image × mask → float32 interest map, background zeroed (DINO v2)
4b.  Ray-cast to 3D surface        interest maps + poses + mesh → raw per-surface-point contributions
4c.  Accumulate on mesh surface    raw contributions → per-vertex interest scores (0–1, float32)
4d.  Render heat overlay           per-vertex scores + mesh → colorized mesh visualization
```

---

## I/O Summary

| | Field | Type | Source |
|---|---|---|---|
| **In** | `posed_frames` | `List[PosedFrame]` | Stage 3 — full orbit + close-up set |
| **In** | `scene_path` | `str` | Stage 3 — path to 3DGS scene or COLMAP sparse workspace |
| **In** | `model_type` | `str` | Stage 3 — `"3dgs"` or `"colmap"` |
| **In** | `building_mesh` | `open3d.geometry.TriangleMesh` | Extracted from `scene_path` or reconstructed via Poisson |
| **Out** | `interest_scores` | `np.ndarray`, shape `(N_vertices,)`, float32 | Per-vertex interest scores, range 0–1 |
| **Out** | `value_field` | `np.ndarray`, shape `(N_vertices,)`, float32 | Alias of `interest_scores`; consumed by Stage 5 shot optimizer |
| **Out** | `building_mesh_colored` | `open3d.geometry.TriangleMesh` | Mesh with jet-colormap vertex colors applied |

---

## Example Input — M60 Tank Posed Image Set

The `stage4data/M60/` directory contains 313 posed frames from an orbit + close-up pass around an M60 Patton tank in a museum hangar. Two representative frames illustrate what the pipeline processes:

**Frame `00001.jpg` — front face, direct head-on view**

![front face](../stage4data/M60/00001.jpg)

This is the highest-interest viewpoint. DINO v2 attention will peak on:
- The main gun aperture and rear grille (strong edge contrast, complex geometry)
- The identification plates (`1 ATB 4 13A`, `4-404`) — high texture salience
- The track assembly at close range — repetitive texture structure

Expected interest scores for front-face vertices: **0.7–1.0**

---

**Frame `00220.jpg` — turret, elevated angle**

![turret elevated](../stage4data/M60/00220.jpg)

Secondary high-interest zone. DINO v2 attention will peak on:
- The turret dome and weapon mounts (unusual geometry, high curvature)
- The commander's cupola and auxiliary equipment stowed on top
- Barrel foreshortening — distinctive silhouette cue

Expected interest scores for turret-top vertices: **0.6–0.9**

Frames like `00085.jpg` (side hull close-up, weathered plating) represent the medium-interest baseline (~0.3–0.5) that separates the high-value zones from background surfaces.

---

## Sub-step 4a0 — SAM 2 Foreground Masking

### What it does
Runs SAM 2 on each posed image with a center-point prompt to isolate the subject from the background. The resulting binary mask is applied to the DINO attention map in sub-step 4a — pixels outside the mask are zeroed before ray-casting, preventing background clutter (other vehicles, hangar structure, floor) from contributing scores to the subject mesh.

Center-point prompting works reliably when the subject roughly fills the frame center, which holds for orbit passes around a building or vehicle. Close-up frames may shift the subject off-center; if the mask quality degrades, the fallback is to skip masking for that frame (pass all-ones mask) rather than corrupt the scores.

### Tech to install
- `sam2` — Meta's Segment Anything Model 2
  ```
  pip install git+https://github.com/facebookresearch/sam2.git
  ```

### Implementation steps

1. **Load model** (once, before the image loop):
   ```python
   from sam2.sam2_image_predictor import SAM2ImagePredictor
   predictor = SAM2ImagePredictor.from_pretrained("facebook/sam2-hiera-large")
   ```
2. **Generate mask** for each posed image:
   ```python
   def get_subject_mask(image_rgb: np.ndarray, predictor) -> np.ndarray:
       H, W = image_rgb.shape[:2]
       predictor.set_image(image_rgb)
       masks, scores, _ = predictor.predict(
           point_coords=np.array([[W // 2, H // 2]]),
           point_labels=np.array([1]),   # 1 = foreground
           multimask_output=True,
       )
       return masks[np.argmax(scores)]   # (H, W) bool
   ```
3. **Fallback** if SAM 2 is unavailable:
   ```python
   def get_subject_mask_fallback(image_rgb):
       return np.ones(image_rgb.shape[:2], dtype=bool)   # all pixels included
   ```

### Output
Per-image binary mask, shape `(H, W)`, dtype `bool`. True = subject pixel, False = background.

### Acceptance criteria
Subject pixels (tank / building body) are True; floor, other vehicles, and hangar structure are False. Visual inspection on a sample of frames before running the full set.

---

## Sub-step 4a — Per-Image Interest Scoring (DINO v2)

### What it does
Runs DINO v2 on each posed image to produce a per-pixel saliency map. DINO v2's self-supervised attention heads fire strongly on salient geometry — building facades, entrances, strong edge transitions — without requiring any labeled training data. The output is a float32 map, same spatial resolution as the source image, with values in [0, 1].

### Why DINO v2
DINO v2 (self-supervised ViT) produces patch-level attention maps that correlate with geometric salience: facade articulation, entrance canopies, window rhythm, corner features. No manual labels needed. It can be combined with CLIP for semantic steering: run DINO for saliency, then multiply by CLIP cosine similarity scores against prompts such as `"architectural entrance"` or `"interesting facade detail"` to up-weight semantically relevant regions.

### Tech to install
- `torch`, `torchvision` — already installed from Stage 3
- `transformers` — DINO v2 model weights via HuggingFace
  ```
  pip install transformers
  ```
- `openai-clip` — optional semantic multiplier (already installed from Stage 2)

### Implementation steps
1. **Load model:**
   ```python
   from transformers import AutoImageProcessor, AutoModel
   processor = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
   model     = AutoModel.from_pretrained("facebook/dinov2-base").to(device).eval()
   ```
2. **Extract patch attention** for each posed image:
   ```python
   import torch, numpy as np
   from PIL import Image

   def dino_interest_map(image_bgr, processor, model, device):
       img_rgb = image_bgr[:, :, ::-1]
       inputs  = processor(images=Image.fromarray(img_rgb), return_tensors="pt").to(device)
       with torch.no_grad():
           outputs = model(**inputs, output_attentions=True)
       # Use last-layer [CLS] attention over patch tokens
       # outputs.attentions: tuple of (B, heads, N+1, N+1), N = num patches
       attn = outputs.attentions[-1][0]         # (heads, N+1, N+1)
       cls_attn = attn[:, 0, 1:].mean(dim=0)   # mean over heads, drop CLS token: (N,)
       # Reshape to patch grid
       H_patch = inputs["pixel_values"].shape[2] // model.config.patch_size
       W_patch = inputs["pixel_values"].shape[3] // model.config.patch_size
       attn_map = cls_attn.reshape(H_patch, W_patch).cpu().numpy()
       # Upsample to original image resolution
       import cv2
       h, w = image_bgr.shape[:2]
       attn_up = cv2.resize(attn_map, (w, h), interpolation=cv2.INTER_LINEAR)
       # Normalize to [0, 1]
       attn_up = (attn_up - attn_up.min()) / (attn_up.max() - attn_up.min() + 1e-8)
       return attn_up.astype(np.float32)
   ```
3. **(Optional) CLIP semantic multiplier:**
   ```python
   import clip
   clip_model, clip_prep = clip.load("ViT-B/32", device=device)
   prompts = clip.tokenize(["architectural entrance", "interesting facade detail",
                             "plain roof", "featureless wall"]).to(device)
   with torch.no_grad():
       text_feats = clip_model.encode_text(prompts)
       img_feat   = clip_model.encode_image(clip_prep(pil_img).unsqueeze(0).to(device))
   sims = (img_feat @ text_feats.T).softmax(dim=-1)[0].cpu().numpy()
   # sims[0]+sims[1] = positive signal; sims[2]+sims[3] = negative signal
   semantic_weight = float(sims[0] + sims[1])
   attn_map *= semantic_weight
   attn_map = np.clip(attn_map, 0.0, 1.0)
   ```
4. **Apply SAM 2 mask** to zero out background before ray-casting:
   ```python
   mask = get_subject_mask(img_rgb, predictor)   # from sub-step 4a0
   attn_up[~mask] = 0.0
   ```
5. Collect `interest_maps: List[np.ndarray]`, one per posed frame, shape `(H, W)`, float32.

### Output
Per-image float32 interest map, shape `(H, W)` matching source image resolution, values 0–1.

### Acceptance criteria
Attention peaks on manually-identified facade features (entrance, window grouping, cornice) and falls off on featureless roof and sky regions.

---

## Sub-step 4b — Ray-Cast to 3D Surface (Open3D RaycastingScene)

### What it does
For every pixel in every posed image, casts a ray from the camera origin through the pixel using known camera intrinsics and extrinsics. Finds the mesh hit point (triangle index + barycentric coordinates). Maps the pixel's interest score to the corresponding surface location. Produces a raw list of `(triangle_idx, bary_coords, score)` contributions across all pixels and all images.

### Tech to install
- `open3d` — already installed from Stage 2/3
  ```
  pip install open3d
  ```

### Implementation steps
1. **Build raycasting scene from mesh:**
   ```python
   import open3d as o3d
   import open3d.core as o3c

   scene = o3d.t.geometry.RaycastingScene()
   mesh_t = o3d.t.geometry.TriangleMesh.from_legacy(building_mesh)
   _ = scene.add_triangles(mesh_t)
   ```
2. **For each posed frame**, generate a ray tensor from the known pose:
   ```python
   def rays_from_pose(K, R_cam_to_world, camera_pos_enu, H, W):
       """Returns rays tensor of shape (H, W, 6): [origin(3), direction(3)]"""
       ys, xs = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
       # Unproject pixel grid to camera-space directions
       dirs_cam = np.stack([
           (xs - K[0, 2]) / K[0, 0],
           (ys - K[1, 2]) / K[1, 1],
           np.ones((H, W))
       ], axis=-1)                          # (H, W, 3)
       dirs_world = (R_cam_to_world @ dirs_cam.reshape(-1, 3).T).T
       dirs_world /= np.linalg.norm(dirs_world, axis=-1, keepdims=True)
       origins = np.broadcast_to(camera_pos_enu, (H * W, 3))
       rays = np.concatenate([origins, dirs_world], axis=-1).reshape(H, W, 6)
       return o3c.Tensor(rays.astype(np.float32))
   ```
3. **Cast rays and collect hits:**
   ```python
   contributions = []   # list of (triangle_idx, bary_u, bary_v, score)

   for frame, interest_map in zip(posed_frames, interest_maps):
       rays = rays_from_pose(K, frame.R_cam_to_world, frame.camera_pos_enu,
                             frame.image.shape[0], frame.image.shape[1])
       ans  = scene.cast_rays(rays)
       # ans keys: "t_hit", "geometry_ids", "primitive_ids", "primitive_uvs", "primitive_normals"
       hit_mask    = np.isfinite(ans["t_hit"].numpy())           # (H, W) bool
       tri_ids     = ans["primitive_ids"].numpy()[hit_mask]      # (M,) int
       bary_uv     = ans["primitive_uvs"].numpy()[hit_mask]      # (M, 2)
       scores      = interest_map[hit_mask]                      # (M,) float32
       # Incidence angle weight: cos(theta) = dot(ray_dir, -face_normal)
       normals     = ans["primitive_normals"].numpy()[hit_mask]  # (M, 3) — outward face normals
       ray_dirs    = rays.numpy()[hit_mask, 3:6]                 # (M, 3)
       cos_theta   = np.einsum("ij,ij->i", -ray_dirs, normals).clip(0.0, 1.0)
       contributions.append((tri_ids, bary_uv, scores, cos_theta))
   ```

### Output
`contributions`: list of arrays per frame — triangle indices, barycentric coords, interest scores, incidence weights. Raw input for sub-step 4c.

### Acceptance criteria
Hit rate ≥ 90% of pixels that geometrically intersect the mesh bounding box; miss rate attributable only to background/sky pixels.

---

## Sub-step 4c — Accumulate Scores on Mesh Surface

### What it does
For each mesh vertex, gathers all score contributions from rays that hit nearby triangles. Uses barycentric interpolation to distribute each triangle hit's contribution to the triangle's three vertices. Weights each contribution by `cos(angle of incidence)` to prefer head-on views (which provide more reliable feature signal). Computes a weighted average per vertex and normalizes to [0, 1].

### Tech to install
- `numpy` — already installed

### Implementation steps
1. **Extract vertex indices per triangle from mesh:**
   ```python
   triangles = np.asarray(building_mesh.triangles)   # (T, 3) int — vertex indices
   N_verts   = len(building_mesh.vertices)
   ```
2. **Accumulate weighted score sums per vertex:**
   ```python
   score_sum  = np.zeros(N_verts, dtype=np.float64)
   weight_sum = np.zeros(N_verts, dtype=np.float64)

   for (tri_ids, bary_uv, scores, cos_theta) in contributions:
       bary_u = bary_uv[:, 0]
       bary_v = bary_uv[:, 1]
       bary_w = 1.0 - bary_u - bary_v          # third barycentric coord

       v0 = triangles[tri_ids, 0]
       v1 = triangles[tri_ids, 1]
       v2 = triangles[tri_ids, 2]

       w_score = scores * cos_theta            # incidence-weighted score

       np.add.at(score_sum,  v0, bary_w * w_score)
       np.add.at(score_sum,  v1, bary_u * w_score)
       np.add.at(score_sum,  v2, bary_v * w_score)
       np.add.at(weight_sum, v0, bary_w * cos_theta)
       np.add.at(weight_sum, v1, bary_u * cos_theta)
       np.add.at(weight_sum, v2, bary_v * cos_theta)
   ```
3. **Compute weighted average and normalize:**
   ```python
   interest_scores = np.where(
       weight_sum > 0,
       score_sum / weight_sum,
       0.0
   ).astype(np.float32)

   # Normalize to [0, 1]
   s_min, s_max = interest_scores.min(), interest_scores.max()
   if s_max > s_min:
       interest_scores = (interest_scores - s_min) / (s_max - s_min)
   ```
4. Vertices with zero accumulated weight (never hit by any ray) receive score `0.0`.

### Output
`interest_scores`: `np.ndarray`, shape `(N_vertices,)`, float32, values in [0, 1]. This is the **3D interest-density surface**.

### Acceptance criteria (T4.1)
Entrance and facade-detail vertices score ≥ 0.6; roof and rear-face vertices score ≤ 0.3 on a test structure with known interest regions.

---

## Sub-step 4d — Render Heat Overlay

### What it does
Maps per-vertex interest scores through a jet colormap to produce RGB vertex colors, then renders the mesh. The result is a building mesh with hotspots (high-interest regions such as entrances and articulated facades) rendered in red/yellow and low-interest regions (flat roof, back face) in cool blue. Detailed visualization behavior is covered in the companion visualization spec.

### Tech to install
- `open3d` — already installed
- `matplotlib` — colormap lookup
  ```
  pip install matplotlib
  ```

### Implementation steps
1. **Apply jet colormap to vertex scores:**
   ```python
   import matplotlib.cm as cm
   colormap = cm.get_cmap("jet")
   vertex_colors = colormap(interest_scores)[:, :3]   # (N_verts, 3) RGB float64 in [0,1]
   ```
2. **Assign to mesh and render:**
   ```python
   building_mesh_colored = o3d.geometry.TriangleMesh(building_mesh)
   building_mesh_colored.vertex_colors = o3d.utility.Vector3dVector(vertex_colors)
   ```
3. **Visualize** (non-blocking, used during development):
   ```python
   o3d.visualization.draw_geometries(
       [building_mesh_colored],
       window_name="Stage 4 — Interest Heat Overlay",
       width=1280, height=720,
   )
   ```

### Output
`building_mesh_colored`: `open3d.geometry.TriangleMesh` with per-vertex RGB colors encoding interest scores via jet colormap. Entrance/facade hotspots appear red/yellow; roof and back faces appear blue.

---

## Mesh vs. Gaussian Splat Path

Stage 3 may deliver either a triangulated mesh (`model_type="colmap"` + Poisson reconstruction) or a 3D Gaussian Splatting scene (`model_type="3dgs"`).

| | Mesh path | Gaussian splat path |
|---|---|---|
| **4b ray target** | `open3d.t.geometry.RaycastingScene` over triangle mesh | Cast rays against splat centers (approximate: find nearest Gaussian centroid per ray) |
| **4c accumulation** | Per-vertex weighted average via barycentric interpolation | Per-Gaussian weighted average; each Gaussian accumulates from all rays within its effective radius |
| **4d colorization** | Jet-colormap RGB written to mesh vertex colors | Modulate each Gaussian's `features_dc` (base color SH coefficient) by the accumulated interest score; re-render via `gsplat` renderer |
| **Output artifact** | `building_mesh.ply` with `interest_scores.npy` | `splat_colored.ply` with per-Gaussian scores in an auxiliary `.npy` |

The mesh path is the primary path. The splat path is used when `model_type="3dgs"` and a mesh cannot be extracted; in that case sub-step 4b/4c operate on the Gaussian centroid set as a proxy surface.

---

## Data Artifacts

Files written to `{workspace_dir}/stage4/`:

| File | Format | Description |
|---|---|---|
| `building_mesh.ply` | PLY (binary, vertex colors) | Source mesh from Stage 3 reconstruction, used as raycasting target |
| `interest_scores.npy` | NumPy float32, shape `(N_vertices,)` | Per-vertex interest scores, normalized 0–1 — the 3D interest-density surface |
| `building_mesh_colored.ply` | PLY (binary, vertex colors) | Mesh with jet-colormap heat overlay applied; passed to Stage 4 visualization and Stage 5 |

`interest_scores.npy` and `building_mesh.ply` are the two artifacts consumed by Stage 5 (shot optimizer). They must be written before the Stage 4 output contract is returned.

---

## Stage 4 Output Contract

| Field | Type | Description |
|---|---|---|
| `interest_scores` | `np.ndarray (N_vertices,) float32` | Per-vertex interest scores, 0–1 — 3D interest-density surface |
| `value_field` | `np.ndarray (N_vertices,) float32` | Same array as `interest_scores`; aliased name used by Stage 5 |
| `building_mesh` | `o3d.geometry.TriangleMesh` | Source mesh (no vertex colors) |
| `building_mesh_colored` | `o3d.geometry.TriangleMesh` | Mesh with heat-overlay vertex colors |
| `n_vertices` | `int` | Vertex count of mesh |
| `coverage_fraction_hit` | `float` | Fraction of mesh vertices hit by at least one ray |
| `reduced_confidence` | `bool` | Propagated from Stage 3; True if 3DGS quality was below floor |

Gate check before Stage 5:
```python
assert interest_scores.shape[0] == n_vertices, "Score array length mismatch"
assert interest_scores.min() >= 0.0 and interest_scores.max() <= 1.0, "Scores out of range"
assert coverage_fraction_hit >= 0.80, f"Only {coverage_fraction_hit:.1%} of vertices hit — mesh or pose problem"
```
If any assertion fails: flag interest field failure, do not proceed to Stage 5.

---

## Dependencies Summary

| Package | Purpose | Install |
|---|---|---|
| `torch` | DINO v2 + SAM 2 inference backend (from Stage 3) | `pip install torch` |
| `sam2` | SAM 2 foreground masking (4a0) | `pip install git+https://github.com/facebookresearch/sam2.git` |
| `transformers` | DINO v2 model weights and processor | `pip install transformers` |
| `openai-clip` | Optional semantic weight multiplier (from Stage 2) | `pip install openai-clip` |
| `open3d` | RaycastingScene, mesh I/O, visualization (from Stage 2/3) | `pip install open3d` |
| `numpy` | Ray generation, barycentric accumulation, normalization | `pip install numpy` |
| `matplotlib` | Jet colormap for heat overlay | `pip install matplotlib` |
| `gsplat` | Gaussian splat rendering (splat path only, from Stage 3) | `pip install gsplat` |
