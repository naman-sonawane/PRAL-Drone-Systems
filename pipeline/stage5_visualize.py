"""
stage5_visualize.py

Streamlit visualizer for Stage 5: Path Optimization & Variety Shots.

Displays:
  - PyDeck Mapbox map (top-left, 65%): value heatmap + trajectory path + waypoint markers
  - Plotly altitude profile (top-right, 35%): altitude vs waypoint index, colored by shot type
  - st.data_editor waypoint table (full-width, below): editable waypoint fields
  - "Export waypoints" button: saves edits back to stage5/waypoints.json

Run:
    streamlit run pipeline/stage5_visualize.py

Requires env var: MAPBOX_ACCESS_TOKEN (free Mapbox public token)

Inputs (relative to repo root, i.e. parent of pipeline/):
    stage4/interest_scores.npy   -- float32 (N_vertices,)
    stage4/building_mesh.ply     -- PLY triangle mesh
    stage5/waypoints.json        -- list of 10 waypoint dicts
    stage5/trajectory.npy        -- float32 (500, 5)

Optional CLI arg:
    --workspace /path/to/root    Override repo root (default: parent of this script)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import pyproj
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Page config — must be first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Stage 5 — Path Optimization", layout="wide")

# ---------------------------------------------------------------------------
# Workspace root resolution
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent   # pipeline/
_DEFAULT_ROOT = _SCRIPT_DIR.parent              # repo root

def _parse_workspace() -> Path:
    """Accept --workspace /some/path from sys.argv, else default to repo root."""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--workspace" and i + 1 < len(args):
            return Path(args[i + 1]).resolve()
    return _DEFAULT_ROOT

WORKSPACE = _parse_workspace()
STAGE4_DIR = WORKSPACE / "stage4"
STAGE5_DIR = WORKSPACE / "stage5"

WAYPOINTS_PATH   = STAGE5_DIR / "waypoints.json"
TRAJECTORY_PATH  = STAGE5_DIR / "trajectory.npy"
MESH_PATH        = STAGE4_DIR / "building_mesh.ply"
SCORES_PATH      = STAGE4_DIR / "interest_scores.npy"

VIZ_DIR = _DEFAULT_ROOT / "viz"

# ---------------------------------------------------------------------------
# Studio HTML builder — inlines geo_trace.js and stage-3.js so the iframe
# is fully self-contained (no relative-path loading issues in Streamlit).
# ---------------------------------------------------------------------------

@st.cache_data
def _build_studio_html() -> str:
    html = (VIZ_DIR / "studio.html").read_text()
    for fname in ("geo_trace.js", "stage-3.js"):
        src = (VIZ_DIR / fname).read_text()
        html = html.replace(
            f'<script src="./{fname}"></script>',
            f"<script>{src}</script>",
        )
    return html

# ---------------------------------------------------------------------------
# ENU -> lat/lon conversion
# ---------------------------------------------------------------------------
ORIGIN_LAT =  43.4730
ORIGIN_LON = -80.5395

_transformer = pyproj.Proj(
    proj="aeqd",
    lat_0=ORIGIN_LAT,
    lon_0=ORIGIN_LON,
    units="m",
)


def enu_to_latlon(pts_enu: np.ndarray) -> list[tuple[float, float]]:
    """
    Convert ENU coordinates to (lat, lon) tuples.

    Parameters
    ----------
    pts_enu : (N, 3) array of [x_east, y_north, z_up] in metres.

    Returns
    -------
    List of (lat, lon) tuples in WGS-84 decimal degrees.
    """
    lons, lats = _transformer(pts_enu[:, 0], pts_enu[:, 1], inverse=True)
    return list(zip(lats, lons))


# ---------------------------------------------------------------------------
# Shot type colors (RGBA)
# ---------------------------------------------------------------------------
SHOT_COLORS: dict[str, list[int]] = {
    "orbit":    [255, 200,   0, 255],   # amber
    "reveal":   [  0, 200, 255, 255],   # cyan
    "push_in":  [255,  80,  80, 255],   # coral
    "top_down": [180, 120, 255, 255],   # violet
}

# ---------------------------------------------------------------------------
# Cached data loaders
# ---------------------------------------------------------------------------

@st.cache_data
def load_mesh_and_scores(
    mesh_path: str,
    scores_path: str,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Load building mesh vertices and interest scores.

    Returns
    -------
    verts_enu   : (V, 3) float32 array of ENU vertex positions
    scores      : (V,)   float32 array of per-vertex interest scores
    """
    import open3d as o3d   # deferred: not always installed at import time

    mesh = o3d.io.read_triangle_mesh(mesh_path)
    verts_enu = np.asarray(mesh.vertices, dtype=np.float32)
    scores = np.load(scores_path).astype(np.float32)
    return verts_enu, scores


@st.cache_data
def load_trajectory(trajectory_path: str) -> np.ndarray:
    """Load trajectory array, shape (500, 5)."""
    return np.load(trajectory_path).astype(np.float32)


# ---------------------------------------------------------------------------
# Early-exit guard: require waypoints.json
# ---------------------------------------------------------------------------
if not WAYPOINTS_PATH.exists():
    st.error(
        f"Run stage5.py first to generate waypoints.\n\n"
        f"Expected: `{WAYPOINTS_PATH}`"
    )
    st.stop()

# ---------------------------------------------------------------------------
# Load waypoints
# ---------------------------------------------------------------------------
with open(WAYPOINTS_PATH) as fh:
    waypoints: list[dict] = json.load(fh)

# ---------------------------------------------------------------------------
# Load mesh + scores (cached)
# ---------------------------------------------------------------------------
_mesh_ok   = MESH_PATH.exists()
_scores_ok = SCORES_PATH.exists()

if not _mesh_ok:
    st.warning(f"Mesh not found at `{MESH_PATH}` — heatmap layer disabled.")
if not _scores_ok:
    st.warning(f"Interest scores not found at `{SCORES_PATH}` — heatmap layer disabled.")

verts_enu   = None
scores      = None
centroid_ll = (ORIGIN_LAT, ORIGIN_LON)   # fallback map center

if _mesh_ok and _scores_ok:
    verts_enu, scores = load_mesh_and_scores(str(MESH_PATH), str(SCORES_PATH))
    centroid_enu = verts_enu.mean(axis=0, keepdims=True)          # (1, 3)
    centroid_ll  = enu_to_latlon(centroid_enu)[0]                 # (lat, lon)

# ---------------------------------------------------------------------------
# Load trajectory (optional — path layer shown only if file exists)
# ---------------------------------------------------------------------------
trajectory = None
if TRAJECTORY_PATH.exists():
    trajectory = load_trajectory(str(TRAJECTORY_PATH))
else:
    st.warning(f"Trajectory not found at `{TRAJECTORY_PATH}` — path layer disabled.")

# ---------------------------------------------------------------------------
# Mapbox token
# ---------------------------------------------------------------------------
mapbox_token = os.environ.get("MAPBOX_ACCESS_TOKEN", "")
if not mapbox_token:
    st.warning(
        "Set the `MAPBOX_ACCESS_TOKEN` environment variable to enable the Mapbox basemap. "
        "The map will render in wireframe/fallback mode without it."
    )

# ===========================================================================
# Build PyDeck layers
# ===========================================================================

# ---- Layer 1: Heatmap ------------------------------------------------------
heatmap_layer = None
if verts_enu is not None and scores is not None:
    heatmap_data = [
        {"lat": float(lat), "lon": float(lon), "weight": float(s)}
        for (lat, lon), s in zip(enu_to_latlon(verts_enu), scores)
        if s > 0.2
    ]
    heatmap_layer = pdk.Layer(
        "HeatmapLayer",
        data=heatmap_data,
        get_position="[lon, lat]",
        get_weight="weight",
        radiusPixels=40,
        colorRange=[
            [  0,   0, 255, 100],   # blue  — low interest
            [  0, 255,   0, 160],   # green — mid
            [255,   0,   0, 200],   # red   — high interest
        ],
    )

# ---- Layer 2: Trajectory path ----------------------------------------------
path_layer = None
if trajectory is not None:
    traj_latlon = enu_to_latlon(trajectory[:, :3])
    path_layer = pdk.Layer(
        "PathLayer",
        data=[{"path": [[lon, lat] for lat, lon in traj_latlon]}],
        get_path="path",
        get_color=[255, 255, 255, 200],
        width_pixels=3,
    )

# ---- Layer 3: Waypoint markers ---------------------------------------------
waypoint_data = [
    {
        "lat":   w["lat"],
        "lon":   w["lon"],
        "color": SHOT_COLORS.get(w["shot_type"], [200, 200, 200, 255]),
        "label": f"{w['idx']}: {w['shot_type']}",
        "value": round(float(w["value"]), 2),
        "alt":   round(float(w["alt"]), 1),
    }
    for w in waypoints
]

waypoint_layer = pdk.Layer(
    "ScatterplotLayer",
    data=waypoint_data,
    get_position="[lon, lat]",
    get_fill_color="color",
    get_radius=6,
    radius_units="pixels",
    pickable=True,
)

# ---- Assemble deck ---------------------------------------------------------
active_layers = [
    layer for layer in [heatmap_layer, path_layer, waypoint_layer]
    if layer is not None
]

view = pdk.ViewState(
    latitude=centroid_ll[0],
    longitude=centroid_ll[1],
    zoom=17,
    pitch=0,
    bearing=0,
)

deck = pdk.Deck(
    layers=active_layers,
    initial_view_state=view,
    map_style="mapbox://styles/mapbox/dark-v11",
    map_provider="mapbox",
    api_keys={"mapbox": mapbox_token},
    tooltip={"text": "{label}\nvalue: {value}\nalt: {alt} m"},
)

# ===========================================================================
# Build Plotly altitude profile
# ===========================================================================
alt_colors = [
    f"rgb({SHOT_COLORS.get(w['shot_type'], [200, 200, 200, 255])[0]},"
    f"{SHOT_COLORS.get(w['shot_type'], [200, 200, 200, 255])[1]},"
    f"{SHOT_COLORS.get(w['shot_type'], [200, 200, 200, 255])[2]})"
    for w in waypoints
]

fig_alt = go.Figure()
fig_alt.add_trace(go.Scatter(
    x=list(range(len(waypoints))),
    y=[w["alt"] for w in waypoints],
    mode="lines+markers",
    line=dict(color="white", width=2),
    marker=dict(
        size=10,
        color=alt_colors,
    ),
    text=[w["shot_type"] for w in waypoints],
    hovertemplate="%{text}<br>alt: %{y:.0f} m<extra></extra>",
))
fig_alt.update_layout(
    plot_bgcolor="#111111",
    paper_bgcolor="#111111",
    font_color="white",
    xaxis=dict(
        title="Waypoint index",
        tickvals=list(range(len(waypoints))),
        gridcolor="#333333",
    ),
    yaxis=dict(
        title="Altitude (m AGL)",
        gridcolor="#333333",
    ),
    margin=dict(l=40, r=10, t=10, b=40),
    height=500,
)

# ===========================================================================
# Layout
# ===========================================================================
st.title("Stage 5 — Path Optimization & Variety Shots")

tab_map, tab_draw = st.tabs(["Waypoints & Map", "Shot Drawing"])

# ---------------------------------------------------------------------------
# Tab 1: existing heatmap + altitude profile + waypoint editor
# ---------------------------------------------------------------------------
with tab_map:
    col_map, col_chart = st.columns([0.65, 0.35])

    with col_map:
        st.pydeck_chart(deck, use_container_width=True, height=500)

    with col_chart:
        st.plotly_chart(fig_alt, use_container_width=True)

    st.subheader("Waypoint Editor")

    df = pd.DataFrame([
        {
            "idx":       int(w["idx"]),
            "lat":       float(w["lat"]),
            "lon":       float(w["lon"]),
            "alt":       float(w["alt"]),
            "yaw":       float(w["yaw"]),
            "pitch":     float(w["pitch"]),
            "shot_type": w["shot_type"],
            "value":     round(float(w["value"]), 3),
        }
        for w in waypoints
    ])

    edited_df = st.data_editor(
        df,
        column_config={
            "idx":       st.column_config.NumberColumn("idx",        disabled=True),
            "lat":       st.column_config.NumberColumn("lat",        format="%.6f"),
            "lon":       st.column_config.NumberColumn("lon",        format="%.6f"),
            "alt":       st.column_config.NumberColumn("alt (m AGL)", format="%.1f"),
            "yaw":       st.column_config.NumberColumn("yaw°",       format="%.1f"),
            "pitch":     st.column_config.NumberColumn("pitch°",     format="%.1f"),
            "shot_type": st.column_config.SelectboxColumn(
                "shot_type",
                options=["orbit", "reveal", "push_in", "top_down"],
            ),
            "value":     st.column_config.NumberColumn("value",      disabled=True),
        },
        use_container_width=True,
        hide_index=True,
    )

    waypoints = edited_df.to_dict(orient="records")

    if st.button("Export waypoints", type="primary"):
        STAGE5_DIR.mkdir(parents=True, exist_ok=True)
        with open(WAYPOINTS_PATH, "w") as fh:
            json.dump(waypoints, fh, indent=2)
        st.success(f"Saved to {WAYPOINTS_PATH}")

# ---------------------------------------------------------------------------
# Tab 2: viz/studio.html drawing tool — draw shot trajectories on the map
# ---------------------------------------------------------------------------
with tab_draw:
    if not (VIZ_DIR / "studio.html").exists():
        st.error(f"studio.html not found at `{VIZ_DIR}`")
    else:
        components.html(_build_studio_html(), height=820, scrolling=False)
