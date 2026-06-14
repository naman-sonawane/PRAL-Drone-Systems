"""
stage4_visualize.py

Open3D GUI visualizer for Stage 4: Interest Field & Value Assignment.

Loads:
  - pipeline/data/building_mesh.ply       -- triangle mesh with neutral gray vertex colors
  - pipeline/data/interest_scores.npy     -- per-vertex float32 interest scores in [0, 1]

Displays the mesh in a 1200x800 window with a right-side panel containing a
"Heat Overlay" checkbox. Unchecked: neutral gray. Checked: jet-style colormap
(blue=low, green=medium, red=high) applied as vertex colors.

Run: python pipeline/stage4_visualize.py
"""

import os
import sys
import numpy as np
import open3d as o3d
import open3d.visualization.gui as gui
import open3d.visualization.rendering as rendering

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
MESH_PATH = os.path.join(DATA_DIR, "building_mesh.ply")
SCORES_PATH = os.path.join(DATA_DIR, "interest_scores.npy")

# ---------------------------------------------------------------------------
# Colormap: blue -> green -> red (jet-style, 3-stop linear, no matplotlib)
# ---------------------------------------------------------------------------

def score_to_rgb(t: float):
    """Map t in [0, 1] to (R, G, B) floats via blue -> green -> red."""
    t = float(np.clip(t, 0.0, 1.0))
    if t <= 0.5:
        s = t / 0.5           # 0 -> 1 in the lower half
        return (0.0, s, 1.0 - s)
    else:
        s = (t - 0.5) / 0.5  # 0 -> 1 in the upper half
        return (s, 1.0 - s, 0.0)


def scores_to_colors(scores: np.ndarray) -> np.ndarray:
    """Convert (N,) float32 scores to (N, 3) float64 RGB colors."""
    return np.array([score_to_rgb(v) for v in scores], dtype=np.float64)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

def main():
    # --- Load data ----------------------------------------------------------
    if not os.path.exists(MESH_PATH):
        print(f"ERROR: mesh not found at {MESH_PATH}")
        print("Run `python pipeline/stage4_mock_data.py` first.")
        sys.exit(1)
    if not os.path.exists(SCORES_PATH):
        print(f"ERROR: scores not found at {SCORES_PATH}")
        print("Run `python pipeline/stage4_mock_data.py` first.")
        sys.exit(1)

    mesh = o3d.io.read_triangle_mesh(MESH_PATH)
    interest_scores = np.load(SCORES_PATH)

    n_verts = len(mesh.vertices)
    assert interest_scores.shape[0] == n_verts, (
        f"Score count ({interest_scores.shape[0]}) does not match "
        f"mesh vertex count ({n_verts})"
    )

    # Pre-compute both color arrays so the toggle is instantaneous
    gray_colors = np.full((n_verts, 3), 0.6, dtype=np.float64)
    heat_colors = scores_to_colors(interest_scores)

    # --- GUI setup ----------------------------------------------------------
    app = gui.Application.instance
    app.initialize()

    window = app.create_window("Stage 4 — Interest Field Visualization", 1200, 800)

    # SceneWidget fills the left portion of the window
    scene_widget = gui.SceneWidget()
    scene_widget.scene = rendering.Open3DScene(window.renderer)

    # Material: unlit so vertex colors are shown without lighting distortion
    mat = rendering.MaterialRecord()
    mat.shader = "defaultUnlit"

    # Add mesh with default gray colors
    mesh.vertex_colors = o3d.utility.Vector3dVector(gray_colors)
    scene_widget.scene.add_geometry("building", mesh, mat)

    # Set default camera: slightly above and in front of the building
    bounds = mesh.get_axis_aligned_bounding_box()
    center = bounds.get_center()
    extent = bounds.get_max_bound() - bounds.get_min_bound()
    far = float(np.max(extent))
    scene_widget.setup_camera(60.0, bounds, center)

    # Right panel
    panel = gui.Vert(8, gui.Margins(8, 8, 8, 8))

    header = gui.Label("View Options")
    panel.add_child(header)

    heat_checkbox = gui.Checkbox("Heat Overlay")
    heat_checkbox.checked = False

    def on_heat_toggle(checked):
        scene_widget.scene.remove_geometry("building")
        if checked:
            mesh.vertex_colors = o3d.utility.Vector3dVector(heat_colors)
        else:
            mesh.vertex_colors = o3d.utility.Vector3dVector(gray_colors)
        scene_widget.scene.add_geometry("building", mesh, mat)

    heat_checkbox.set_on_checked(on_heat_toggle)
    panel.add_child(heat_checkbox)

    legend = gui.Label("Interest score:\n0.0 (blue)\n  ->\n1.0 (red)")
    panel.add_child(legend)

    # Layout: scene_widget on the left, panel on the right
    def on_layout(layout_context):
        r = window.content_rect
        panel_width = 180
        scene_widget.frame = gui.Rect(r.x, r.y, r.width - panel_width, r.height)
        panel.frame = gui.Rect(r.x + r.width - panel_width, r.y, panel_width, r.height)

    window.set_on_layout(on_layout)
    window.add_child(scene_widget)
    window.add_child(panel)

    app.run()


if __name__ == "__main__":
    main()
