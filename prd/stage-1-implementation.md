# Stage 1 — GPS Target Selection & Confirmation: Implementation Spec

> Companion docs: footage-acquisition-execution.md · footage-acquisition-io.md · footage-acquisition-testing.md
> Input: user pin or polygon (lat/lon)
> Output: AOI — a confirmed building footprint/mask in local NED/ENU coordinates

---

## Overview

Stage 1 answers one question: *what exactly are we filming?* The user points roughly at a target; the system figures out the precise footprint and gets the user to confirm it before any real flying begins.

There are four sub-steps, each with a clear transform:

```
1a. Coordinate frame conversion   lat/lon → NED/ENU meters
1b. Prior footprint lookup        lat/lon → candidate polygons (no flying required)
1c. Onboard vision detection      nadir frame → bounding boxes → masks → GPS centroids
1d. User confirmation             candidate list → confirmed AOI polygon
```

---

## Sub-step 1a — Coordinate Frame Conversion

### What it does
Every downstream stage reasons in metric 3D space (meters). GPS lat/lon/alt must be converted to a local **ENU frame** (East-North-Up, meters relative to a home point) once at the start. All positions, paths, and obstacle maps live in this frame.

### Tech to install
- `pymap3d` (Python) — geodetic ↔ ENU/NED transforms, no dependencies beyond numpy
  ```
  pip install pymap3d
  ```

### Implementation steps
1. When the user drops a pin, record that lat/lon as the **home origin**.
2. Convert the pin to ENU: `e, n, u = pymap3d.geodetic2enu(lat, lon, alt, lat0, lon0, alt0)`
3. On every subsequent GPS reading (drone position, footprint vertex, obstacle), apply the same transform.
4. Store all coordinates internally as `(e, n, u)` tuples. Never mix frames.
5. For display back to the user, invert: `pymap3d.enu2geodetic(e, n, u, lat0, lon0, alt0)`.

### Acceptance criteria (T1.1)
Round-trip a known lat/lon → ENU → lat/lon. Reprojected coordinate must land within ±0.5 m of the input.

---

## Sub-step 1b — Prior Footprint Lookup

### What it does
Before the drone takes off, query a building database at the user's pin. Returns candidate footprint polygons instantly. These are the first set of candidates shown to the user — no flight budget spent.

### Tech to install
- `requests` (Python) — HTTP calls to Overpass API
- OSM Overpass API — free, no key required
- Google Open Buildings (optional) — better coverage outside Europe; requires GCS access or BigQuery
  ```
  pip install requests
  ```

### Implementation steps
1. Build an Overpass query for `building=*` within a radius of the pin (e.g., 100 m):
   ```python
   query = f"""
   [out:json];
   way["building"](around:100,{lat},{lon});
   out geom;
   """
   response = requests.post("https://overpass-api.de/api/interpreter", data=query)
   ```
2. Parse returned way geometries → list of lat/lon polygon rings.
3. Convert each polygon vertex to ENU (sub-step 1a).
4. Compute each polygon's centroid and bounding area.
5. Filter: discard footprints whose centroid is >50 m from the pin (likely noise).
6. Pass surviving polygons to the candidate list.

### Acceptance criteria (T1.2)
For a known building: at least one returned footprint overlaps the ground-truth footprint by ≥80% IoU. Query completes within 2 s.

---

## Sub-step 1c — Onboard Vision Detection

### What it does
The drone ascends to survey altitude, captures a single nadir (straight-down) frame, and runs open-vocabulary object detection to find building candidates from the air. This catches buildings that OSM hasn't mapped and gives a visual confirmation of what's actually there.

### Tech to install
- `ultralytics` — YOLO-World (open-vocabulary detector, text-promptable)
  ```
  pip install ultralytics
  ```
- `sam2` — Segment Anything Model 2 (polygon mask from a bounding box)
  ```
  pip install sam2
  # or: pip install git+https://github.com/facebookresearch/segment-anything-2
  ```
- `opencv-python` — image handling and reprojection math
  ```
  pip install opencv-python
  ```
- Camera intrinsics matrix `K` — from drone/gimbal spec sheet (focal length, principal point, image size). Must be calibrated or provided by the manufacturer SDK.

### Implementation steps

**1. Fly to survey altitude and capture nadir frame**
- Command drone to ascend to `h_survey` (e.g., 30–50 m AGL) directly above the pin.
- Point gimbal straight down (pitch = −90°).
- Capture one frame. Record the drone's GPS + altitude + heading at capture time → this is the camera pose for this frame.

**2. Detect building candidates with YOLO-World**
```python
from ultralytics import YOLO
model = YOLO("yolov8x-worldv2.pt")
model.set_classes(["building", "house", "structure", "roof"])
results = model.predict(nadir_frame)
boxes = results[0].boxes.xyxy  # pixel bounding boxes
```

**3. Refine each box into a polygon mask with SAM 2**
```python
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor
predictor = SAM2ImagePredictor(build_sam2(model_cfg, checkpoint))
predictor.set_image(nadir_frame)
masks, scores, _ = predictor.predict(box=box_xyxy)
# take highest-score mask
```

**4. Reproject mask centroid to GPS**

With the camera pose (drone GPS + altitude + heading) and intrinsics `K`:
```python
# pixel centroid of mask
cx, cy = mask_centroid(mask)
# unproject to a ray in camera frame
ray_cam = np.linalg.inv(K) @ [cx, cy, 1]
# rotate to world frame using drone heading/attitude
ray_world = R_drone @ ray_cam
# intersect ray with ground plane (z = 0 in ENU)
t = -drone_pos_enu[2] / ray_world[2]
ground_hit_enu = drone_pos_enu + t * ray_world
```
Convert `ground_hit_enu` back to lat/lon for display.

**5. Merge with prior candidates**
- Deduplicate: if a vision candidate centroid is within 5 m of a prior footprint centroid, they are the same building — keep the prior polygon, flag as "visually confirmed."
- New vision candidates (no prior match) get a rough bounding polygon from the SAM 2 mask reprojected to ground plane.

### Acceptance criteria (T1.3)
Bounding box centroid reprojects to within ±3 m of the building's known GPS centroid. SAM 2 mask IoU vs ground-truth footprint ≥ 0.75.

---

## Sub-step 1d — User Confirmation

### What it does
A Mapbox GL JS map UI serves as the single visualization surface for Stage 1. The user enters a target coordinate, triggers annotation, and confirms the AOI — all within the map. No camera feed, video stream, or annotated frame is shown to the user at any point.

### Tech to install
- **Mapbox GL JS** — satellite basemap + polygon overlay rendering
  ```
  npm install mapbox-gl
  ```

### UI flow

**1. Coordinate entry**
- User types a lat/lon (or address) into an input field.
- Map flies to that location and centers on it at ~zoom 18 (satellite basemap).
- A pin marker is placed at the entered coordinate.

**2. Annotate**
- User clicks **"Annotate"** button.
- This triggers the backend pipeline:
  - OSM Overpass query (sub-step 1b) → candidate footprint polygons
  - Vision detection on nadir frame (sub-step 1c) → additional candidates
- Candidate polygons are rendered on the map as semi-transparent overlays, each labeled with source (`OSM` / `vision`) and confidence score.
- The candidate whose centroid is closest to the pin is highlighted.

**3. Confirmation**
- User clicks a polygon → it locks as the AOI (solid outline, distinct color).
- All other candidates are cleared.
- Convert the AOI polygon vertices to ENU and store as the canonical AOI.
- **If no candidates exist** (OSM returned nothing, vision found nothing): a fallback draw tool appears — user draws a manual bounding polygon directly on the map. Never proceed to Stage 2 without a locked AOI.

### Acceptance criteria (T1.4 / T1.5)
- Tapped candidate's footprint becomes the locked AOI; all others cleared.
- On empty candidate list: graceful fallback UI, no crash, drone hovers safely.

---

## Stage 1 output contract

Before Stage 2 begins, the following must be in state:

| Field | Type | Description |
|---|---|---|
| `aoi_polygon_enu` | list of (e, n) tuples | Confirmed footprint in ENU meters |
| `aoi_centroid_enu` | (e, n) | Center of the AOI |
| `home_origin` | (lat, lon, alt) | ENU reference origin |
| `aoi_source` | `"osm"` / `"vision"` / `"manual"` | How the AOI was derived |

If `aoi_polygon_enu` is not populated, Stage 2 must not start.

**User-facing visualization:** The confirmed AOI polygon is rendered as an overlay on a satellite basemap (Mapbox GL JS or CesiumJS). This is the only visualization output of Stage 1 — no video stream or annotated frames are surfaced to the user.

---

## Dependencies summary

| Package | Purpose | Install |
|---|---|---|
| `pymap3d` | lat/lon ↔ ENU conversion | `pip install pymap3d` |
| `requests` | OSM Overpass API queries | `pip install requests` |
| `ultralytics` | YOLO-World open-vocab detection | `pip install ultralytics` |
| `sam2` | Polygon mask from bounding box | `pip install sam2` |
| `opencv-python` | Image handling, reprojection math | `pip install opencv-python` |
| `numpy` | Linear algebra for ray casting | `pip install numpy` |
| Drone SDK | Flight commands + camera pose | DJI SDK or MAVSDK (platform-dependent) |
| `mapbox-gl` | Satellite basemap, polygon overlays, AOI confirmation UI | `npm install mapbox-gl` |
