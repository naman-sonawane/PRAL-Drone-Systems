"""
Stage 4 -- Interest Field & Value Assignment (Streamlit)

Streamlit-native replacement for stage4_visualize.py (which uses Open3D GUI).
Displays the building mesh with optional heat-map overlay using Plotly Mesh3d.

Inputs (relative to pipeline/data/):
    building_mesh.ply     -- triangle mesh
    interest_scores.npy   -- per-vertex float32 scores in [0, 1]

Run standalone:  streamlit run pipeline/stage4_streamlit.py
Or via router:   streamlit run pipeline/app.py
"""
from __future__ import annotations

import os

import numpy as np
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Stage 4 -- Interest Field", layout="wide")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(_SCRIPT_DIR, "data")
MESH_PATH   = os.path.join(DATA_DIR, "building_mesh.ply")
SCORES_PATH = os.path.join(DATA_DIR, "interest_scores.npy")

st.title("Stage 4 -- Interest Field & Value Assignment")

if not os.path.exists(MESH_PATH) or not os.path.exists(SCORES_PATH):
    st.error(
        "Data files not found. Run `python pipeline/stage4_mock_data.py` first.\n\n"
        f"Expected:\n- `{MESH_PATH}`\n- `{SCORES_PATH}`"
    )
    st.stop()


@st.cache_data
def _load(mesh_path: str, scores_path: str):
    import open3d as o3d  # deferred: may not be installed everywhere
    mesh   = o3d.io.read_triangle_mesh(mesh_path)
    verts  = np.asarray(mesh.vertices,  dtype=np.float64)
    tris   = np.asarray(mesh.triangles, dtype=np.int32)
    scores = np.load(scores_path).astype(np.float32)
    return verts, tris, scores


verts, tris, scores = _load(MESH_PATH, SCORES_PATH)

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
show_heat = st.toggle("Heat Overlay", value=False,
                      help="Blue = low interest  |  Green = mid  |  Red = high")

# ---------------------------------------------------------------------------
# Build Plotly Mesh3d trace
# ---------------------------------------------------------------------------
COLORSCALE = [
    [0.0, "rgb(0,0,255)"],
    [0.5, "rgb(0,255,0)"],
    [1.0, "rgb(255,0,0)"],
]

if show_heat:
    mesh_trace = go.Mesh3d(
        x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
        i=tris[:, 0],  j=tris[:, 1],  k=tris[:, 2],
        intensity=scores,
        colorscale=COLORSCALE,
        showscale=True,
        colorbar=dict(title="Interest score", thickness=14, x=1.01),
        name="Building (heat)",
        flatshading=False,
        opacity=1.0,
    )
else:
    mesh_trace = go.Mesh3d(
        x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
        i=tris[:, 0],  j=tris[:, 1],  k=tris[:, 2],
        color="rgb(150,150,150)",
        name="Building",
        flatshading=False,
        opacity=1.0,
    )

fig = go.Figure(data=[mesh_trace])
fig.update_layout(
    scene=dict(
        xaxis_title="East (m)",
        yaxis_title="North (m)",
        zaxis_title="Up (m)",
        aspectmode="data",
        bgcolor="#1a1a1a",
    ),
    margin=dict(l=0, r=0, t=10, b=0),
    height=680,
    paper_bgcolor="#111111",
    font_color="white",
)

st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Vertices",            f"{len(verts):,}")
c2.metric("Triangles",           f"{len(tris):,}")
c3.metric("Mean interest score", f"{scores.mean():.3f}")
c4.metric("Max interest score",  f"{scores.max():.3f}")
