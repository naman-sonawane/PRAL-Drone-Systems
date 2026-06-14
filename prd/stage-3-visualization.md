# Stage 3 — Visualization PRD

> Companion docs: stage-3-implementation.md · footage-acquisition-io.md
> Scope: debug and operator-review views for Stage 3 outputs only. Stage 2 visualization lives in a separate section/file.

---

## Purpose

Stage 3 produces a posed image set and a 3D Gaussian Splatting scene. The visualization must let an operator verify orbit geometry, pose accuracy, surface coverage, and model quality before Stage 4 is allowed to start. Every panel below maps directly to one output or sub-step.

---

## Layout

Single Streamlit page, five panels stacked vertically. Triggered by a "Run Stage 3" button that consumes locked AOI, `r`, `z_orbit`, and `obstacle_map` from Stage 2 state.

---

## Panel 1 — Orbit Path & Frame Positions

**What's shown:**
- ENU top-down map with the orbit ring (radius `r`, centered on `aoi_centroid_enu`) and AOI footprint overlaid
- Each `PosedFrame` plotted as a dot at `camera_pos_enu`, colored by `pass_type`: orbit = blue, closeup = orange
- Arrow on each dot indicating camera heading (derived from `R_cam_to_world`)
- Thumbnail strip below the map: one representative frame thumbnail per closeup viewpoint, ordered by flight sequence
- Three metric boxes: `n_orbit_frames`, `n_closeup_frames`, `closeup_viewpoints_flown`

**Why:** Confirms the orbit was fully closed and closeup waypoints are spatially distributed over the structure rather than clustered. A gap in the orbit ring or all-orange dots on one face indicates a flight path problem.

---

## Panel 2 — Pose Accuracy

**What's shown:**
- Scatter plot: GPS-reported XY position vs. COLMAP-estimated XY position for every frame, both series overlaid in the ENU plane (GPS = grey, COLMAP = colored by reprojection error, low = green, high = red)
- Reprojection error histogram: distribution of `reprojection_error_px` across all frames, with a vertical dashed line at the 1.0 px hard-fail threshold
- Three metric boxes: `mean_reprojection_error_px`, max reprojection error, frame count above 1.0 px threshold
- If `mean_reprojection_error_px >= 1.0`: red warning banner stating "Hard gate will fail — mean reprojection error exceeds 1.0 px"

**Why:** GPS drift and COLMAP drift show up as systematic offsets between the two scatter series. The histogram immediately reveals whether a few outlier frames are pulling the mean up or whether error is uniformly elevated (different root causes, different fixes).

---

## Panel 3 — Coverage Map

Two tabs:

**Tab A — Top-down slice**
- 2D heatmap of `coverage_map` at the mid-height slice of the structure (z = H / 2), colored by per-voxel observation count: 0 = white, 1–2 = yellow, 3–5 = orange, 6+ = dark red
- AOI footprint overlaid; voxels with zero observations highlighted with a black border (frontier voxels)
- Summary line: `coverage_fraction` as a percentage, `frontiers_detected` count, total surface voxels

**Tab B — 3D scatter**
- Plotly 3D scatter of all surface voxels, colored by observation count (same color scheme as Tab A)
- AOI centroid marked; orbit ring drawn as a circle at `z_orbit`
- Camera controls: rotate/zoom in browser

**Why:** The top-down slice is the fast sanity check for horizontal gaps; the 3D scatter reveals faces or overhangs that the orbit altitude missed. White voxels in Tab A or large uncolored regions in Tab B are directly actionable (add a closeup pass or lower `z_orbit`).

---

## Panel 4 — Model Quality

**What's shown:**
- Two metric boxes: `psnr_db` with threshold annotation (≥ 25 dB = pass, < 25 dB = soft fail), `ssim` with threshold annotation (≥ 0.85 = pass, < 0.85 = soft fail)
- If `reduced_confidence` is true: orange banner displaying `quality_warning` verbatim
- Side-by-side render comparisons for up to 4 held-out frames: left column = ground truth frame, right column = 3DGS render of the same viewpoint; PSNR and SSIM per-frame shown below each pair
- `scene_path` displayed as a copyable text field so the operator can open the scene in an external viewer

**Why:** PSNR/SSIM alone do not tell the operator where the model is failing. The side-by-side comparisons localise blur, floaters, or missing geometry to specific faces or altitudes, giving actionable feedback before committing to Stage 4.

---

## Panel 5 — Stop Condition

**What's shown:**
- Two status chips: "Coverage target met" (green if `coverage_target_met`, grey otherwise) and "Battery floor hit" (yellow if `battery_floor_hit`, grey otherwise)
- `coverage_fraction` as a progress bar against the 90% target line
- Explanatory note: if `battery_floor_hit` is true and `coverage_target_met` is false, display "Flight terminated at battery floor (30%). Coverage below target — review Panel 3 for gaps."
- If both are false: red warning banner ("Stage 3 stop condition not satisfied — pipeline state is inconsistent")

**Why:** The operator must know whether the mission ended cleanly (coverage hit) or was cut short (battery floor). These two states have different downstream implications for Stage 4 confidence and re-flight decisions.

---

## Gate Check Display

After all five panels render, a final row shows the Stage 3 → 4 gate status:

| Check | Hard/Soft | Status |
|---|---|---|
| `posed_frames >= 24` | Hard | PASS / FAIL |
| `mean_reprojection_error_px < 1.0` | Hard | PASS / FAIL |
| `coverage_target_met OR battery_floor_hit` | Hard | PASS / FAIL |
| `psnr_db >= 25` | Soft | PASS / WARN |
| `ssim >= 0.85` | Soft | PASS / WARN |

If all hard checks pass and no soft failures: green "Proceed to Stage 4" button is enabled.
If any hard check fails: button is disabled; failing row highlighted in red with the raw value that failed.
If hard checks pass but soft checks fail: button is enabled; failing soft row highlighted in orange; `reduced_confidence` flag noted beside the button.
