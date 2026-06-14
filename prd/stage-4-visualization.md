# Stage 4 — Visualization PRD

> Companion docs: stage-4-implementation.md · footage-acquisition-io.md
> Scope: pitch-demo and operator-review view for Stage 4 outputs only. Stage 3 visualization lives in stage-3-visualization.md.

---

## Purpose

Stage 4 produces a per-vertex interest score for the building mesh. The visualization makes that "invisible" scoring step legible: a 3D building whose surface is lit up by a heat colormap, showing where the system found high-value shooting opportunities. This is the pitch-demo artifact for Stage 4 — the moment the audience sees the system has taste.

Default state: neutral gray mesh. One click: building lights up with the interest heatmap.

---

## Tool

**Open3D GUI** (`open3d.visualization.gui` / `open3d.visualization.rendering`)

| Property | Detail |
|---|---|
| Cross-platform | Yes — no browser, no server |
| Large mesh support | Yes — GPU-backed SceneWidget |
| Widget toolkit | Native panel with checkboxes, labels |
| Entry point | `pipeline/stage4_visualize.py` |
| Run | `python pipeline/stage4_visualize.py` |

---

## Inputs Consumed

| File | Format | Description |
|---|---|---|
| `pipeline/data/building_mesh.ply` | PLY | Triangle mesh; vertex colors set to neutral gray (0.6, 0.6, 0.6) |
| `pipeline/data/interest_scores.npy` | NumPy float32 | Per-vertex interest scores, one value per mesh vertex, range 0–1 |

Vertex count in `interest_scores.npy` must equal the vertex count of the mesh. The visualizer asserts this on load and exits with a clear error if they do not match.

---

## Layout

Window title: **"Stage 4 — Interest Field Visualization"**
Window size: **1200 × 800**

```
┌────────────────────────────────────┬──────────────┐
│                                    │ View Options │
│                                    │              │
│         SceneWidget                │ [x] Heat     │
│         (3D viewport)              │     Overlay  │
│                                    │              │
│         ~85% of window width       │ Interest     │
│                                    │ score:       │
│                                    │ 0.0 (blue)   │
│                                    │  →           │
│                                    │ 1.0 (red)    │
└────────────────────────────────────┴──────────────┘
```

### SceneWidget (left, ~85% width)

- Fills the left portion of the window; resizes with the window.
- Hosts the 3D scene via `open3d.visualization.rendering.Open3DScene`.
- Standard mouse behavior: orbit (left-drag), pan (middle-drag), zoom (scroll) — built-in SceneWidget, no custom event handling needed.

### Right Panel (fixed ~180 px wide)

| Element | Type | Detail |
|---|---|---|
| "View Options" | `Label` | Section header |
| "Heat Overlay" | `Checkbox` | Checked = heat-mapped vertex colors; unchecked = neutral gray |
| Interest score legend | `Label` (static) | `"Interest score: 0.0 (blue) → 1.0 (red)"` |

---

## Camera

Default camera placed slightly above and in front of the building centroid, looking at the mesh bounding-box center.

```python
bounds = mesh.get_axis_aligned_bounding_box()
center = bounds.get_center()
extent = bounds.get_max_bound() - bounds.get_min_bound()
eye    = center + [0, -max(extent) * 1.5, max(extent) * 0.6]
up     = [0, 0, 1]
widget.setup_camera(60.0, bounds, center)
```

The operator can freely orbit from this starting pose.

---

## Colormap

Jet-style, 3-stop linear interpolation implemented inline — no matplotlib dependency.

| Score | R | G | B | Color |
|---|---|---|---|---|
| 0.0 | 0.0 | 0.0 | 1.0 | Blue (low interest) |
| 0.5 | 0.0 | 1.0 | 0.0 | Green (medium interest) |
| 1.0 | 1.0 | 0.0 | 0.0 | Red (high interest) |

Between stops: linear interpolation per channel.

```python
def score_to_rgb(t: float) -> tuple[float, float, float]:
    """Map t in [0, 1] to RGB via blue -> green -> red."""
    t = float(np.clip(t, 0.0, 1.0))
    if t <= 0.5:
        s = t / 0.5          # 0 -> 1 in lower half
        return (0.0, s, 1.0 - s)
    else:
        s = (t - 0.5) / 0.5  # 0 -> 1 in upper half
        return (s, 1.0 - s, 0.0)
```

Applied as:

```python
colors = np.array([score_to_rgb(v) for v in interest_scores])
mesh.vertex_colors = o3d.utility.Vector3dVector(colors)
```

---

## Interaction

### Heat Overlay Checkbox

Toggling the checkbox swaps vertex colors live. Because Open3D's SceneWidget does not support in-place geometry color updates, the geometry is removed and re-added:

```python
def on_heat_toggle(checked):
    scene = widget.scene
    scene.remove_geometry("building")
    if checked:
        mesh.vertex_colors = o3d.utility.Vector3dVector(heat_colors)
    else:
        mesh.vertex_colors = o3d.utility.Vector3dVector(gray_colors)
    scene.add_geometry("building", mesh, material)
```

`heat_colors` and `gray_colors` are both pre-computed at load time so the toggle is instantaneous.

### Mouse Controls

| Gesture | Action |
|---|---|
| Left-drag | Orbit |
| Middle-drag / shift+left-drag | Pan |
| Scroll | Zoom |

Built-in SceneWidget behavior — no custom handler required.

---

## Pitch Use

1. Launch: `python pipeline/stage4_visualize.py`
2. Building appears in neutral gray — structure is visible, scoring is hidden.
3. Click "Heat Overlay" checkbox.
4. Building lights up: blue faces have low interest, green faces have medium interest, red faces have high interest.
5. Audience sees where the system decided to look — the "it has taste" moment.

The toggle is the entire demo interaction. Keep it on one click.

---

## Status

Draft v0.1
