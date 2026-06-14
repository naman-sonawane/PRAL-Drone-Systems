# Stage 2 — Visualization PRD

> Companion docs: stage-2-implementation.md · footage-acquisition-io.md
> Scope: debug and operator-review views for Stage 2 outputs only. Stage 1 visualization lives in a separate section/file.

---

## Purpose

Stage 2 produces three things — `H`, `r`, and the obstacle map. The visualization must let an operator verify all three are correct before Stage 3 is allowed to start. Every panel below maps directly to one output.

---

## Layout

Single Streamlit page, three panels stacked vertically. Triggered by a "Run Stage 2" button that consumes a locked AOI from Stage 1 state.

---

## Configuration Inputs (Sidebar)

All inputs are set before clicking **Run Stage 2**. Grouped by which sub-step they feed.

### Mode
| Input | Widget | Default |
|---|---|---|
| Use mock data | checkbox | `True` — uses `build_mock_stage2_output`; no sensor or stream server required |

### AOI
| Input | Widget | Default |
|---|---|---|
| Polygon vertices | JSON textarea — array of `[e, n]` pairs | `[[-10,-8],[10,-8],[10,8],[-10,8]]` |
| Centroid E / N | read-only display | Auto-computed from polygon |

### Rangefinder
| Input | Widget | Default | Feeds |
|---|---|---|---|
| H_true_mock (m) | slider 2–60 | 15.0 | `MockOverflight` simulated building height |
| Survey altitude override (m) | number_input; 0 = auto | 0 | `drone_pos_enu[2]`; overrides `bbox_diagonal × 0.8` |

### Camera
| Input | Widget | Default | Feeds |
|---|---|---|---|
| fx / fy (px) | number_input | 1000.0 | K matrix for back-projection; fy drives VFOV |
| cx / cy (px) | number_input | 960 / 540 | K matrix principal point |
| Image height (px) | number_input | 1080 | VFOV computation for orbit radius |
| Roll / Pitch / Yaw (°) | number_input × 3 | 0 / −90 / 0 | `drone_attitude_rpy` for nadir frames; −90° pitch = straight down |

### DSM
| Input | Widget | Default | Feeds |
|---|---|---|---|
| Depth model | selectbox: `None (mock)` / `DepthAnythingV2-S` / `DepthAnythingV2-L` | None (mock) | Which depth estimator runs in 2b |
| Checkpoint path | text_input | `pipeline/stage2/depth_anything_v2_vits.pth` | Path to `.pth` weights; only shown when model ≠ None |
| Ground plane method | selectbox: `RANSAC (open3d)` / `z-percentile fallback` | z-percentile fallback | How DSM derives ground level from point cloud |

---

## Panel 1 — Height Estimation

**What's shown:**
- Rangefinder readings plotted as a 2D scatter in the ENU top-down plane, colored by measured surface elevation (low = dark, high = bright)
- AOI footprint polygon overlaid so readings inside vs. outside are visually separated
- Three metric boxes: `H_rangefinder`, `H_dsm`, `H_fused`
- If the two methods disagree by >10%: a yellow warning banner naming which value was discarded and why

**Why:** Lets the operator immediately see if a bad rangefinder reading (e.g. water reflection, glass roof) or a bad depth estimate is pulling the fused height off.

---

## Panel 2 — Orbit Ring

**What's shown:**
- The existing Stage 1 ENU map (AOI footprint + centroid) extended with:
  - A circle at radius `r` centered on `aoi_centroid_enu` (the planned orbit path)
  - A dashed inner circle at `r * 0.7` and outer circle at `r * 1.5` (the obstacle annulus bounds)
  - Three metric boxes: `H`, `r`, `z_orbit`
- If `r` was clamped: a yellow warning showing raw vs. clamped value

**Why:** One glance confirms the orbit ring clears the building footprint and sits at a sensible standoff. If the circle cuts through the footprint, something is wrong with H or the formula.

---

## Panel 3 — Obstacle Map

**SAM2 Labeling Toggle**

Above both tabs, a Streamlit radio widget lets the operator switch the color scheme for all voxel views in this panel:

```python
st.radio(
    "Obstacle coloring",
    options=["With SAM2 labeling", "Without SAM2 labeling"],
    horizontal=True,
    key="sam2_toggle",
)
```

- **"With SAM2 labeling"** — voxels colored by semantic label: `no-go` = red, `traversable` = blue, unlabeled occupied = grey, unoccupied = white. This is the default view.
- **"Without SAM2 labeling"** — all occupied voxels rendered in a single neutral color (grey), regardless of semantic label; unoccupied = white. No semantic distinction is drawn.

The toggle applies simultaneously to Tab A (top-down slice) and Tab B (3D scatter). Its purpose is to let the operator compare raw geometry against the SAM2-labeled result to spot regions where the labeler has mislabeled or missed obstacles.

---

Two tabs:

**Tab A — Top-down slice**
- 2D occupancy grid rendered as a Plotly heatmap at `z = z_orbit` (drone's orbit altitude)
- Voxel colors follow the active toggle state (see above)
- Orbit ring overlaid on top so the operator can see which no-go voxels sit inside the flight corridor

**Tab B — 3D scatter**
- Plotly 3D scatter of the obstacle point cloud
- Voxel colors follow the active toggle state (see above)
- AOI centroid marked, orbit ring drawn as a circle at `z_orbit`
- Camera controls: rotate/zoom in browser

**Summary line below tabs:**
- Total occupied voxels, no-go voxel count, traversable voxel count, no-fly volume count

**Why:** The top-down slice is the fast sanity check; the 3D view catches obstacles at unexpected altitudes (e.g. a tall crane that appears fine in top-down but would clip the orbit at `z_orbit`). The toggle makes it easy to isolate whether a problem is a geometry issue (visible in both modes) or a labeling issue (visible only in the "With SAM2 labeling" mode).

---

## Gate Check Display

After all three panels render, a final row shows the Stage 2 → 3 gate status:

| Check | Status |
|---|---|
| `H > 0` | PASS / FAIL |
| `3.0 ≤ r ≤ 50.0` | PASS / FAIL |
| OctoMap populated | PASS / FAIL |

If all pass: green "Proceed to Stage 3" button is enabled.
If any fail: button is disabled, failing check is highlighted in red with the raw value that failed.
