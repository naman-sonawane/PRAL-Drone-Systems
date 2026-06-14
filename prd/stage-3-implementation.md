# Stage 3 — 360° Map (DFS/NBV): Implementation Spec

> Companion docs: footage-acquisition-io.md · footage-acquisition-testing.md · stage-2-implementation.md
> Input: AOI, `r`, `z_orbit`, obstacle map (OctoMap + no-fly volumes) from Stage 2
> Output: posed image set + 3D Gaussian Splatting scene

---

## Overview

Stage 3 answers: *what does this structure actually look like in 3D?* The drone orbits at the computed radius, continuously builds pose estimates and a coverage map, then closes in on any unseen surfaces. The loop terminates when coverage reaches the target or the battery floor is hit — whichever comes first.

There are 5 sub-steps, each with a clear transform:

```
3a. Base orbit capture         orbit at radius r, z_orbit altitude → orbit_frames (posed raw frames)
3b. Pose estimation            orbit_frames + K → PosedFrame list (COLMAP SfM / SLAM)
3c. Coverage mapping           PosedFrame list + obstacle_map → surface coverage map + frontier list
3d. Frontier detection & NBV   frontiers → ranked close-up viewpoints → LOS-checked positions
3e. 3D Gaussian Splatting      all PosedFrames → scene file (PSNR ≥ 25 dB / SSIM ≥ 0.85)
```

(3f stop condition is embedded in the 3d/3e loop inside the runner.)

---

## Sub-step 3a — Base Orbit Capture

### What it does
Computes N evenly-spaced waypoints on a horizontal circle of radius `r` at altitude `z_orbit` around `aoi_centroid_enu`. The drone flies to each waypoint, yaws to face the centroid, sets gimbal pitch so the centroid lands at frame center, and captures one frame. The output is a time-ordered list of `OrbitFrame` objects — raw images with GPS poses attached.

### Tech to install
- `numpy` — waypoint geometry (already installed)
- Drone SDK (DJI MSDK / MAVSDK) — flight commands, gimbal angle, camera trigger

### Implementation steps
1. Compute N: `N = max(24, math.ceil(2 * math.pi * r / 3.0))` — ensures ≤3 m between consecutive capture positions (≥60% frame overlap).
2. Generate waypoints:
   ```python
   thetas = np.linspace(0, 2 * np.pi, N, endpoint=False)
   ce, cn = aoi_centroid_enu[:2]
   waypoints = [(ce + r * np.cos(t), cn + r * np.sin(t), z_orbit) for t in thetas]
   ```
3. At each waypoint:
   - Fly drone to `(e, n, z_orbit)`.
   - Set yaw: `yaw = math.atan2(cn - n_wp, ce - e_wp)` (faces centroid).
   - Set gimbal pitch: `pitch = -math.atan2(z_orbit, r)` (tilts down to center the building).
   - Wait for position settled (velocity < 0.2 m/s).
   - Capture frame. Record `OrbitFrame(image, drone_pos_enu, drone_attitude_rpy, timestamp, pass_type="orbit")`.
4. Return `List[OrbitFrame]`.

### Acceptance criteria (T3.2)
After one full orbit, ≥95% of exposed building-surface voxels are marked "seen" in the coverage map (verified in sub-step 3c).

---

## Sub-step 3b — Pose Estimation

### What it does
Runs COLMAP Structure-from-Motion on the orbit frame set to recover metric camera poses. Each frame gets a COLMAP-refined `camera_pos_enu` and rotation matrix `R_cam_to_world`. When `pycolmap` is unavailable the mock assigns analytically-correct poses from known orbit geometry (used in unit tests).

### Tech to install
- `pycolmap` — Python bindings for COLMAP SfM
  ```
  pip install pycolmap
  ```
- `opencv-python` — JPEG frame write to COLMAP workspace (already installed)

### Implementation steps
1. Write frames to `{workspace_dir}/images/` as sequentially-named JPEGs:
   ```python
   import cv2
   for i, frame in enumerate(orbit_frames):
       cv2.imwrite(f"{workspace_dir}/images/{i:04d}.jpg", frame.image)
   ```
2. Write camera intrinsics as `cameras.txt` (COLMAP simple-pinhole format) using `K[0,0]` (fx), `K[1,1]` (fy), `K[0,2]` (cx), `K[1,2]` (cy).
3. Run incremental mapping:
   ```python
   import pycolmap
   reconstruction = pycolmap.incremental_mapping(
       database_path=f"{workspace_dir}/db.db",
       image_path=f"{workspace_dir}/images/",
       output_path=f"{workspace_dir}/sparse/",
   )[0]
   ```
4. For each registered image, extract pose:
   ```python
   for img_id, img in reconstruction.images.items():
       R = img.rotation_matrix()          # 3x3 world→camera
       t = img.projection_center()        # camera center in COLMAP world frame
       # align COLMAP world frame to ENU using known orbit center
       camera_pos_enu = colmap_to_enu(t, aoi_centroid_enu)
   ```
5. Compute mean reprojection error from `reconstruction.points3D` track residuals.
6. Return `List[PosedFrame]`, merging COLMAP outputs with original `OrbitFrame` timestamps.

**Fallback — MockPoseEstimator:**
Assigns poses analytically from orbit geometry: `camera_pos_enu = (cx + r*cos(theta_i), cn + r*sin(theta_i), z_orbit)`. `R_cam_to_world` derived from yaw and gimbal pitch used during capture. `reprojection_error_px = 0.0` (mock). Used when `pycolmap` is not installed.

### Acceptance criteria (T3.1)
Mean reprojection error < 1 px; camera positions within ±0.2 m of RTK GPS log.

---

## Sub-step 3c — Coverage Mapping

### What it does
Initialises a per-voxel coverage map over the building's traversable surface (all `LABEL_TRAVERSABLE` voxels in the OctoMap). Casts rays from each posed camera through a subsampled pixel grid into the OctoMap. Each ray hit on a traversable voxel increments its observation count. Voxels with count = 0 after the full frame set are "frontiers" — unseen surfaces the drone must revisit.

### Tech to install
- `numpy` — ray casting math (already installed)
- `octomap-python` — OctoMap queries (already installed from Stage 2)

### Implementation steps
1. **Build coverage map:**
   ```python
   coverage_map = CoverageMap(voxel_size=0.25)
   for key, label in obstacle_map.items():
       if label == LABEL_TRAVERSABLE:
           coverage_map.seen[key] = 0
   coverage_map.total_surface_voxels = len(coverage_map.seen)
   ```
2. **Mark seen voxels** (for each `PosedFrame`):
   ```python
   PIXEL_STEP = 10   # subsample: every 10th pixel
   for py in range(0, image_height, PIXEL_STEP):
       for px in range(0, image_width, PIXEL_STEP):
           # Unproject pixel to ray in world frame
           ray_cam = np.linalg.inv(K) @ [px, py, 1.0]
           ray_world = R_cam_to_world @ ray_cam
           ray_world /= np.linalg.norm(ray_world)
           # March along ray
           for step in np.arange(0.0, r * 2.0, voxel_size):
               pt = camera_pos_enu + step * ray_world
               key = world_to_voxel_key(pt, voxel_size)
               if key in coverage_map.seen:
                   coverage_map.seen[key] += 1
                   break   # ray stops at first surface hit
   ```
3. **Detect frontiers:**
   - Find all voxels with `seen[k] == 0`.
   - BFS-cluster contiguous unseen voxels (reuse BFS from `obstacle.py`'s `extract_no_fly_volumes`).
   - For each cluster, compute centroid, voxel count, and `is_occluded` (LOS from orbit is blocked).
   - Return `List[Frontier]`.
4. **Coverage fraction:** `sum(1 for v in seen.values() if v >= 1) / total_surface_voxels`.

### Acceptance criteria (T3.2, T3.3)
- ≥95% surface coverage after one orbit (T3.2).
- Occluded-face voxels flagged as frontiers; close-up viewpoint for that frontier ranks highest by information gain (T3.3).

---

## Sub-step 3d — Frontier Detection & NBV (Next-Best-View)

### What it does
Ranks frontier clusters by information gain. For each frontier that cannot be resolved from the orbit (is_occluded=True), generates a candidate close-up viewpoint at `r * 0.5` distance. Each viewpoint is line-of-sight checked against the OctoMap before the drone is commanded to fly there.

### Tech to install
- `numpy` — geometry, candidate sampling (already installed)
- `scipy.spatial.KDTree` — nearest-obstacle lookup (already installed from Stage 2)

### Implementation steps
1. **Rank frontiers:**
   ```python
   for f in frontiers:
       f.information_gain = f.voxel_count  # proportional to unseen area
   frontiers.sort(key=lambda f: f.information_gain, reverse=True)
   ```
2. **Generate close-up viewpoint** for each frontier:
   ```python
   def generate_closeup_viewpoint(frontier, obstacle_map, r, aoi_centroid_enu):
       # Sample 12 candidates on a sphere of radius r*0.5 around the frontier centroid
       candidates = sphere_sample(frontier.centroid_enu, radius=r * 0.5, n=12)
       for pos in candidates:
           if los_check(pos, frontier.centroid_enu, obstacle_map):
               yaw = atan2(frontier.centroid_enu[1] - pos[1],
                           frontier.centroid_enu[0] - pos[0])
               return (pos, yaw)
       return None   # no collision-free viewpoint found for this frontier
   ```
3. **LOS check:**
   ```python
   def los_check(start, end, obstacle_map, step=0.25):
       direction = np.array(end) - np.array(start)
       dist = np.linalg.norm(direction)
       direction /= dist
       for d in np.arange(0.0, dist, step):
           key = world_to_voxel_key(np.array(start) + d * direction, step)
           if obstacle_map.get(key) == LABEL_NO_GO:
               return False
       return True
   ```
4. **Fly close-up and capture:** for each valid viewpoint, command drone → capture `OrbitFrame(pass_type="closeup")` → append to frame list → re-run 3b and 3c on the augmented frame set → re-detect frontiers → repeat until coverage target or battery floor.

### Acceptance criteria (T3.3, T3.4)
- Occluded frontier identified as highest-ranked (T3.3).
- Generated close-up pose has LOS to frontier; no OctoMap collision along path (T3.4).

---

## Sub-step 3e — 3D Gaussian Splatting

### What it does
Trains a 3D Gaussian Splatting scene on the complete posed image set (orbit + all close-up frames). Evaluates render quality on held-out frames using PSNR and SSIM. Quality below the floor triggers a `reduced_confidence` flag rather than aborting.

### Tech to install
- `gsplat` — GPU-accelerated 3DGS training and rendering
  ```
  pip install gsplat
  ```
- `torch` — required by gsplat
  ```
  pip install torch
  ```
- `scikit-image` — PSNR and SSIM computation
  ```
  pip install scikit-image
  ```

### Implementation steps
1. **Build `transforms.json`** (Nerfstudio/gsplat format):
   ```python
   frames_data = []
   for pf in posed_frames:
       T = np.eye(4)
       T[:3, :3] = pf.R_cam_to_world
       T[:3, 3]  = pf.camera_pos_enu
       frames_data.append({"file_path": pf.image_path, "transform_matrix": T.tolist()})
   meta = {"fl_x": K[0,0], "fl_y": K[1,1], "cx": K[0,2], "cy": K[1,2],
           "w": image_width, "h": image_height, "frames": frames_data}
   json.dump(meta, open(f"{workspace_dir}/transforms.json", "w"))
   ```
2. **Hold out every 8th frame** for evaluation before training begins.
3. **Train:**
   ```python
   from gsplat import train_simple_trainer
   scene_path = train_simple_trainer(
       data_dir=workspace_dir,
       result_dir=f"{workspace_dir}/output/",
       max_steps=7000,
   )
   ```
4. **Evaluate** on held-out frames:
   ```python
   from skimage.metrics import peak_signal_noise_ratio, structural_similarity
   psnrs, ssims = [], []
   for hf in held_out_frames:
       rendered = render_frame(scene_path, hf.R_cam_to_world, hf.camera_pos_enu, K)
       psnrs.append(peak_signal_noise_ratio(hf.image, rendered))
       ssims.append(structural_similarity(hf.image, rendered, channel_axis=2))
   psnr_db = float(np.mean(psnrs))
   ssim    = float(np.mean(ssims))
   ```
5. If `gsplat` unavailable: `MockSplat` writes a placeholder `scene.ply` and returns `(psnr=28.0, ssim=0.90)`.

### Acceptance criteria (T3.6)
Novel-view renders of held-out frames achieve PSNR ≥ 25 dB / SSIM ≥ 0.85. Below threshold: `reduced_confidence = True`, quality warning logged, Stage 4 proceeds with flag.

---

## Stage 3 output contract

| Field | Type | Description |
|---|---|---|
| `posed_frames` | `List[PosedFrame]` | Full posed image set (orbit + close-up) |
| `scene_path` | `str` | Path to 3DGS scene output (or COLMAP sparse workspace) |
| `model_type` | `str` | `"3dgs"` or `"colmap"` |
| `coverage_fraction` | `float` | Fraction of surface voxels observed |
| `coverage_target_met` | `bool` | True if coverage ≥ target before battery floor |
| `battery_floor_hit` | `bool` | True if battery hit floor before coverage target |
| `psnr_db` | `float` | Mean PSNR on held-out frames (dB) |
| `ssim` | `float` | Mean SSIM on held-out frames |
| `mean_reprojection_error_px` | `float` | Mean COLMAP reprojection error |
| `reduced_confidence` | `bool` | True if quality metrics below floor |
| `quality_warning` | `str` | Human-readable description of any quality issues |

Gate check before Stage 4:
```python
assert len(posed_frames) >= min_posed_frames, "Insufficient posed frames"
assert mean_reprojection_error_px < 1.0, "Pose accuracy failed"
assert coverage_target_met or battery_floor_hit, "Stop condition not triggered"
# PSNR and SSIM failures set reduced_confidence flag — do NOT raise
```
If either hard assertion fails: flag reconstruction failure, land safely, do not proceed to Stage 4.

---

## Dependencies summary

| Package | Purpose | Install |
|---|---|---|
| `numpy` | Orbit geometry, ray casting, coverage math | `pip install numpy` |
| `pycolmap` | COLMAP SfM pose estimation (3b) | `pip install pycolmap` |
| `opencv-python` | Frame I/O, JPEG write to COLMAP workspace | `pip install opencv-python` |
| `gsplat` | 3D Gaussian Splatting training and rendering (3e) | `pip install gsplat` |
| `torch` | Required by gsplat | `pip install torch` |
| `scikit-image` | PSNR and SSIM computation for model quality gate | `pip install scikit-image` |
| `scipy` | KDTree for NBV candidate sampling | `pip install scipy` |
| `open3d` | Point cloud merging and visualization (optional) | `pip install open3d` |
| `octomap-python` | OctoMap queries for coverage + LOS checks (from Stage 2) | `pip install octomap-python` |
| Drone SDK | Flight commands, battery telemetry, gimbal control | DJI SDK or MAVSDK (platform-dependent) |
