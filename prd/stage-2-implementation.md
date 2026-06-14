# Stage 2 — Survey + Geometry: Implementation Spec

> Companion docs: footage-acquisition-io.md · footage-acquisition-testing.md · stage-1-implementation.md
> Input: AOI — confirmed building footprint in ENU coordinates
> Output: Building height `H`, orbit radius `r`, obstacle map (OctoMap + semantic no-fly volumes)

---

## Overview

Stage 2 answers: *how tall is this structure, how far should we orbit it, and what's in the way?* No creative decisions are made here — this is pure geometry and environment sensing. The drone makes one structured overflight of the AOI and comes back with three numbers/objects that all downstream stages depend on.

There are four sub-steps, each with a clear transform:

```
2a. AOI overflight & data capture     ascend + translate → depth frames + rangefinder readings
2b. Height estimation                 rangefinder + DSM fusion → H (meters, AGL)
2c. Orbit radius calculation          H + VFOV → r (meters)
2d. Obstacle map construction         depth frames + semantic seg → OctoMap + no-fly labels
```

---

## Sub-step 2a — AOI Overflight & Data Capture

### What it does
The drone ascends to a fixed survey altitude above the AOI centroid, then makes a slow translating pass across the confirmed footprint polygon. During this pass it collects: (1) continuous downward rangefinder readings for direct height measurement, and (2) a set of nadir frames that will be used for both DSM height estimation and depth-based obstacle mapping.

### Tech to install
- Drone SDK (DJI MSDK / MAVSDK) — flight commands, gimbal control, camera trigger
- `pymap3d` — already installed from Stage 1
- `numpy` — trajectory computation
  ```
  pip install numpy
  ```

### Implementation steps

1. **Compute survey altitude.** Set `h_survey = aoi_bbox_diagonal * 0.8` with a floor of 30 m and ceiling of 80 m AGL. This ensures the entire footprint fits in a nadir frame at survey altitude.
2. **Fly to survey position.** Command drone to `aoi_centroid_enu` at `h_survey`. Wait for position settled (velocity < 0.2 m/s).
3. **Point gimbal nadir.** Pitch = −90°, yaw locked to heading = 0° (North).
4. **Begin rangefinder logging.** Sample downward-facing rangefinder at 10 Hz. Record `(timestamp, range_m, drone_pos_enu)` for each reading.
5. **Translate across footprint.** Generate a simple lawnmower path covering the AOI bounding box at `h_survey`. Fly at 2 m/s. Trigger camera every 2 m of travel (≥60% overlap between frames).
6. **Record each frame.** For every captured frame, store `(image, drone_pos_enu, drone_attitude_rpy, timestamp)` — the posed image set used by 2b and 2d.
7. **Return to centroid.** After overflight, hover at `aoi_centroid_enu` at `h_survey` awaiting next sub-step.

### Acceptance criteria
Overflight completes without leaving the AOI bounding box + 20 m buffer. Rangefinder log contains ≥10 readings over the AOI footprint interior. Frame set contains ≥3 nadir frames with ≥60% overlap.

---

## Sub-step 2b — Height Estimation

### What it does
Estimates the building's height `H` using two independent methods and fuses them. Primary: direct rangefinder — when the drone flies over the building roof, the rangefinder reads a shorter distance than the surrounding ground; the delta is the building height. Secondary: DSM from nadir frames — a monocular depth network gives a surface elevation map; building height is peak minus ground median. The two are compared and fused; rangefinder wins on disagreement.

### Tech to install
- `depth-anything-v2` — monocular metric depth estimation for DSM
  ```
  # The PyPI package is a stub only — use the git install:
  pip install git+https://github.com/DepthAnything/Depth-Anything-V2.git
  pip install torch torchvision
  pip install huggingface_hub   # for weight download
  ```
  **Model weights** — download into `pipeline/stage2/`:

  | Variant | HF repo | File | Size | Use when |
  |---|---|---|---|---|
  | `vits` (Small) | `depth-anything/Depth-Anything-V2-Small` | `depth_anything_v2_vits.pth` | ~99 MB | CPU / MPS (Apple Silicon) |
  | `vitl` (Large) | `depth-anything/Depth-Anything-V2-Large` | `depth_anything_v2_vitl.pth` | ~1.3 GB | CUDA only |

  ```bash
  huggingface-cli download depth-anything/Depth-Anything-V2-Small \
      depth_anything_v2_vits.pth --local-dir pipeline/stage2/
  ```

  **Device selection:**
  ```python
  device = (torch.device("cuda") if torch.cuda.is_available()
            else torch.device("mps") if torch.backends.mps.is_available()
            else torch.device("cpu"))
  ```
  Use `vits` on CPU/MPS; `vitl` requires CUDA for real-time inference.

  **Corrected constructor** (`features` and `out_channels` are required):
  ```python
  # vits
  model = DepthAnythingV2(encoder="vits", features=64,
                          out_channels=[48, 96, 192, 384], max_depth=80)
  # vitl
  model = DepthAnythingV2(encoder="vitl", features=256,
                          out_channels=[256, 512, 1024, 1024], max_depth=80)
  model.load_state_dict(torch.load("pipeline/stage2/depth_anything_v2_vits.pth",
                                    map_location=device))
  model = model.to(device).eval()
  depth_map = model.infer_image(rgb_hwc_uint8)  # float32 ndarray, metric meters
  ```
- `open3d` — point cloud construction and ground plane fitting
  ```
  pip install open3d
  ```
- `scipy` — percentile stats for ground/roof height separation
  ```
  pip install scipy
  ```

### Implementation steps

**Method A — Rangefinder delta**
1. From the rangefinder log, compute surface elevation for each reading:
   ```python
   # drone Z in ENU minus measured distance to surface below = surface elevation
   agl[i] = drone_pos_enu[i][2] - range_m[i]
   ```
2. Classify each reading by whether the drone was over the AOI footprint or outside it using a 2D point-in-polygon check against `aoi_polygon_enu`.
3. Compute robust ground and roof levels:
   ```python
   h_ground = np.percentile(agl[outside_aoi], 10)   # 10th pct discards outliers
   h_roof   = np.percentile(agl[inside_aoi],  90)   # 90th pct discards outliers
   H_rangefinder = h_roof - h_ground
   ```

**Method B — DSM from depth network**
```python
from depth_anything_v2.dpt import DepthAnythingV2
model = DepthAnythingV2(encoder='vitl', max_depth=80)
model.load_state_dict(torch.load('depth_anything_v2_vitl.pth'))
model.eval()

depth_map = model.infer_image(nadir_frame)  # metric depth in meters
```
1. Run on 3–5 frames from the center of the overflight (most nadir, least oblique).
2. For each frame, back-project the depth map to a 3D point cloud using camera intrinsics `K` and the drone's pose:
   ```python
   pts_cam = unproject(depth_map, K)                         # (N,3) in camera frame
   pts_enu = (R_drone @ pts_cam.T).T + drone_pos_enu         # rotate+translate to ENU
   ```
3. Merge point clouds via `open3d.geometry.PointCloud`.
4. Fit a ground plane to the merged cloud using RANSAC:
   ```python
   plane_model, inliers = cloud.segment_plane(distance_threshold=0.3,
                                               ransac_n=3,
                                               num_iterations=1000)
   ```
5. Measure the vertical distance from the ground plane to the highest point inside the AOI footprint projection: `H_dsm`.

**Fusion**
```python
if abs(H_rangefinder - H_dsm) < 0.1 * max(H_rangefinder, H_dsm):
    H = (H_rangefinder + H_dsm) / 2   # agree within 10%: average
else:
    H = H_rangefinder                  # rangefinder is ground truth; trust over depth net
    log.warn(f"DSM height {H_dsm:.1f}m disagrees with rangefinder {H_rangefinder:.1f}m — using rangefinder")
```

**Edge cases**
- `H < 2.0 m`: clamp to 2.0 m minimum and log a warning. Prevents degenerate radius values downstream.
- `H > 60.0 m`: flag to operator (may require waiver or alternate flight mode). Do not clamp — surface the value and wait for operator acknowledgment before proceeding.

### Acceptance criteria (T2.1)
Estimated `H` within ±10% of ground-truth height on a measured test structure.

---

## Sub-step 2c — Orbit Radius Calculation

### What it does
Computes the orbit radius `r` such that the building fills 60–85% of the camera's vertical field of view when the drone orbits at mid-building height (`H/2` AGL). This is the standoff distance used as the default for all orbit-based passes in Stage 3 and Stage 5.

### Tech to install
No new packages. Uses `numpy` and camera intrinsics already available.

### Implementation steps

1. **Get VFOV from camera spec.** Either read from the drone SDK or derive from intrinsics:
   ```python
   VFOV = 2 * np.arctan(image_height_px / (2 * K[1, 1]))   # K[1,1] is fy
   ```
2. **Set orbit altitude.** The drone orbits at `z_orbit = H / 2` ENU meters above ground. This centers the building vertically in the frame.
3. **Apply the radius formula:**
   ```python
   margin = 3.0   # meters — lateral clearance beyond building footprint edge
   r = (H / 2 + margin) / np.tan(VFOV / 2)
   ```
   Interpretation: `H/2` is the half-height the vertical FOV must contain; `margin` adds clearance. Dividing by `tan(VFOV/2)` converts half-height to the required standoff distance.
4. **Clamp to safe operating range:**
   ```python
   r_raw = r
   r = float(np.clip(r, 3.0, 50.0))
   if r != r_raw:
       log.warn(f"Orbit radius clamped from {r_raw:.1f}m to {r:.1f}m")
   ```
5. **Verify framing.** Back-check that the building doesn't clip the frame:
   ```python
   theta_top = np.arctan((H / 2) / r)
   fill_ratio = theta_top / (VFOV / 2)   # should be 0.60–0.85
   if fill_ratio > 0.85:
       r *= 1.10   # increase by 10% and re-check once
   ```
6. Store `r` and `z_orbit` in stage output.

### Acceptance criteria (T2.2, T2.5)
- At computed `r`, building occupies 60–85% of vertical frame.
- For flat structures (H ≤ 2 m) and tall structures (H > 20 m): `r` stays in `[3, 50]` m; pipeline clamps and warns rather than generating an unsafe value.

---

## Sub-step 2d — Obstacle Map Construction

### What it does
Builds a 3D occupancy map (OctoMap) of the environment within the orbit annulus — the ring of airspace between `r_inner = r * 0.7` and `r_outer = r * 1.5` around the AOI centroid. Every occupied voxel is labeled with a semantic class: `traversable` (building wall — can approach) or `no-go` (tree, pole, wire — must avoid). This map is a side input to both Stage 3 (close-up viewpoint planning) and Stage 5 (collision-free path connectors).

### Tech to install
- `octomap-python` — 3D voxel occupancy map
  ```
  pip install octomap-python
  ```
- `sam2` — semantic mask generation, already installed from Stage 1
- `open3d` — already installed in 2b
- `openai-clip` — zero-shot region classification
  ```
  pip install openai-clip
  ```

### Implementation steps

**1. Build point cloud from depth estimates**
```python
all_pts = []
for frame, pose in zip(overflight_frames, overflight_poses):
    depth = model.infer_image(frame)                          # Depth Anything V2
    pts_cam = unproject(depth, K)                             # (N,3) in camera frame
    R_drone, t_drone = pose_to_Rt(pose)
    pts_enu = (R_drone @ pts_cam.T).T + t_drone              # ENU frame
    all_pts.append(pts_enu)
cloud = np.vstack(all_pts)
```

**2. Filter to orbit annulus**
```python
r_inner = r * 0.7
r_outer = r * 1.5
dist_2d = np.linalg.norm(cloud[:, :2] - aoi_centroid_enu[:2], axis=1)
mask = (dist_2d > r_inner) & (dist_2d < r_outer) & (cloud[:, 2] > -1.0)
cloud = cloud[mask]
```

**3. Insert into OctoMap**
```python
import octomap
tree = octomap.OcTree(0.25)     # 25 cm voxel resolution
for pt in cloud:
    tree.updateNode(pt, True)   # mark occupied
tree.updateInnerOccupancy()
```

**4. Semantic labeling with SAM 2 + CLIP**

For each overflight frame:
```python
# Generate masks automatically (no prompt required)
masks = automatic_mask_generator.generate(frame)

import clip, torch
clip_model, clip_preprocess = clip.load("ViT-B/32")
no_go_texts   = clip.tokenize(["tree", "vegetation", "bush", "utility pole", "wire", "fence"])
traversable_texts = clip.tokenize(["building wall", "concrete", "brick facade", "roof", "pavement"])

for mask in masks:
    crop = frame_crop(frame, mask['bbox'])
    img_tensor = clip_preprocess(Image.fromarray(crop)).unsqueeze(0)
    with torch.no_grad():
        logits_nogo, _ = clip_model(img_tensor, no_go_texts)
        logits_trav, _ = clip_model(img_tensor, traversable_texts)
    label = 'no-go' if logits_nogo.max() > logits_trav.max() else 'traversable'

    # Back-project mask pixels to ENU and label voxels
    for px, py in mask_pixel_coords(mask):
        ray_cam = np.linalg.inv(K) @ [px, py, 1]
        ray_enu = R_drone @ ray_cam
        t = -drone_pos_enu[2] / ray_enu[2]
        hit_enu = drone_pos_enu + t * ray_enu
        node = tree.search(hit_enu)
        if node:
            node.setValue(LABEL_MAP[label])
```

**5. Default labeling rule**
Any occupied voxel with no semantic label assigned defaults to `no-go`. Unlabeled = unknown = do not fly through.

**6. Inflate no-go voxels**
```python
# 1 m safety buffer around all no-go voxels (4 voxels at 25 cm resolution)
inflate_obstacle_voxels(tree, inflation_m=1.0)
```

**7. Extract no-fly volumes**
Cluster contiguous `no-go` voxels using connected-component analysis and compute an axis-aligned bounding box (AABB) for each cluster. Store as `no_fly_volumes` for fast collision pre-screening in Stage 5.

### Acceptance criteria (T2.3, T2.4)
- All obstacles >1 m tall within the orbit annulus appear in OctoMap; false-negative rate <5%.
- Trees labeled `no-go`, building wall labeled `traversable`; semantic confusion rate <10%.

---

## Stage 2 Output Contract

Before Stage 3 begins, the following must be in state:

| Field | Type | Description |
|---|---|---|
| `H` | `float` (meters) | Estimated building height AGL |
| `r` | `float` (meters) | Orbit radius for Stage 3 and Stage 5 |
| `z_orbit` | `float` (meters ENU) | Drone altitude for orbit passes (`H / 2`) |
| `obstacle_map` | `octomap.OcTree` | 3D occupancy + semantic labels in ENU frame |
| `no_fly_volumes` | list of AABB tuples | Axis-aligned bounding boxes around no-go clusters |

Gate check before Stage 3 starts:
```python
assert H > 0, "Height estimation failed"
assert 3.0 <= r <= 50.0, f"Orbit radius {r}m outside safe range"
assert obstacle_map is not None and obstacle_map.size() > 0, "OctoMap empty"
```
If any assertion fails: flag geometry failure, land safely, do not proceed to Stage 3.

---

## Dependencies Summary

| Package | Purpose | Install |
|---|---|---|
| `pymap3d` | ENU frame ops (from Stage 1) | `pip install pymap3d` |
| `numpy` | Trajectory math, radius formula | `pip install numpy` |
| `scipy` | Percentile-based height estimation | `pip install scipy` |
| `depth-anything-v2` | Monocular metric depth for DSM | `pip install depth-anything-v2` |
| `open3d` | Point cloud construction, RANSAC ground plane | `pip install open3d` |
| `octomap-python` | 3D voxel occupancy map | `pip install octomap-python` |
| `sam2` | Semantic mask generation (from Stage 1) | `pip install sam2` |
| `openai-clip` | Zero-shot region classification | `pip install openai-clip` |
| Drone SDK | Flight commands, rangefinder stream, camera trigger | DJI SDK or MAVSDK (platform-dependent) |
