"""
Stage 3 — 3D Coverage Heatmap Viewer

Displays the e7.ply building mesh colored by synthetic coverage intensity,
overlaid with a spline-deformed orbit ring driven by adjustable control points.

Run:
    streamlit run pipeline/visualize_stage3.py
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys

import numpy as np
import streamlit as st
import plotly.graph_objects as go
from scipy.interpolate import CubicSpline

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

st.set_page_config(page_title="Stage 3 — Coverage Heatmap", layout="wide")
st.title("Stage 3 — Coverage Heatmap")

# ---------------------------------------------------------------------------
# PLY loader
# ---------------------------------------------------------------------------
@st.cache_data
def load_ply(path: str):
    """Parse binary little-endian PLY: vertex (x,y,z) + face (RGBA + indices)."""
    if not os.path.isfile(path):
        return None, None
    with open(path, "rb") as f:
        header_lines = []
        while True:
            line = f.readline().decode("ascii", errors="replace").strip()
            header_lines.append(line)
            if line == "end_header":
                break
        n_verts = n_faces = 0
        for line in header_lines:
            if line.startswith("element vertex"):
                n_verts = int(line.split()[-1])
            elif line.startswith("element face"):
                n_faces = int(line.split()[-1])
        verts = np.frombuffer(f.read(n_verts * 12), dtype="<f4").reshape(n_verts, 3).copy()
        faces = np.zeros((n_faces, 3), dtype=np.int32)
        for i in range(n_faces):
            f.read(4)  # skip RGBA
            count = struct.unpack("B", f.read(1))[0]
            faces[i] = struct.unpack(f"<{count}i", f.read(count * 4))[:3]
    return verts, faces

# ---------------------------------------------------------------------------
# Load mesh (early, to derive orbit defaults)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Model")
    ply_path = st.text_input("PLY file", value="e7.ply")

_ply_abs = ply_path if os.path.isabs(ply_path) else os.path.join(_ROOT, ply_path)
verts, faces = load_ply(_ply_abs)

if verts is None:
    st.error(f"PLY file not found: {_ply_abs!r}")
    st.stop()

mesh_min = verts.min(axis=0)
mesh_max = verts.max(axis=0)
mesh_cen = (mesh_min + mesh_max) / 2.0
mesh_span_xy = max(mesh_max[0] - mesh_min[0], mesh_max[1] - mesh_min[1])
_default_r = float(round(mesh_span_xy * 0.75, 1))
_default_z = float(round(mesh_min[2] + (mesh_max[2] - mesh_min[2]) * 0.7, 1))

# ---------------------------------------------------------------------------
# Sidebar — JSON import
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Config File")
    export_path = st.text_input("JSON path", value="orbit_config.json")
    _json_abs = export_path if os.path.isabs(export_path) else os.path.join(_ROOT, export_path)

    _loaded_cfg: dict | None = None
    if os.path.isfile(_json_abs):
        load_json = st.checkbox("Load from JSON", value=False)
        if load_json:
            with open(_json_abs) as _f:
                _loaded_cfg = json.load(_f)
            st.success(f"Loaded {export_path}")

# ---------------------------------------------------------------------------
# Sidebar — orbit parameters
# ---------------------------------------------------------------------------
def _cfg(key, default):
    """Return value from loaded JSON config if available, else default."""
    if _loaded_cfg is not None and key in _loaded_cfg:
        return _loaded_cfg[key]
    return default

with st.sidebar:
    st.header("Orbit")
    r_input = st.number_input("Orbit radius r (m)", value=float(_cfg("r", _default_r)), min_value=1.0)
    z_orbit = st.number_input("Orbit altitude z_orbit (m)", value=float(_cfg("z_orbit", _default_z)))
    _aoi_default = _cfg("aoi_centroid", [float(round(mesh_cen[0], 2)), float(round(mesh_cen[1], 2))])
    aoi_ce = st.number_input("AOI centroid X", value=float(_aoi_default[0]))
    aoi_cn = st.number_input("AOI centroid Y", value=float(_aoi_default[1]))

# ---------------------------------------------------------------------------
# Sidebar — control points
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Control Points")
    _cp_default = _loaded_cfg["control_points"] if (_loaded_cfg and "control_points" in _loaded_cfg) else None
    _n_default = len(_cp_default) if _cp_default else 8
    n_cp = st.slider("Number of control points", 3, 12, _n_default)

    cp_deltas: list[float] = []
    for i in range(n_cp):
        angle_deg = i * 360.0 / n_cp
        _delta_default = 0.0
        if _cp_default and i < len(_cp_default):
            _delta_default = float(_cp_default[i].get("delta_r", 0.0))
        delta = st.slider(
            f"Point {i} ({angle_deg:.0f}\u00b0) \u0394r (m)",
            min_value=-8.0,
            max_value=8.0,
            value=_delta_default,
            step=0.1,
            key=f"cp_{i}",
        )
        cp_deltas.append(delta)

# ---------------------------------------------------------------------------
# Export button
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Export")
    if st.button("Save to JSON"):
        cfg_out = {
            "r": r_input,
            "z_orbit": z_orbit,
            "aoi_centroid": [aoi_ce, aoi_cn],
            "control_points": [
                {"angle_deg": round(i * 360.0 / n_cp, 4), "delta_r": cp_deltas[i]}
                for i in range(n_cp)
            ],
        }
        with open(_json_abs, "w") as _f:
            json.dump(cfg_out, _f, indent=2)
        st.success(f"Saved to {export_path}")

# ---------------------------------------------------------------------------
# Build spline-deformed orbit from control points
# ---------------------------------------------------------------------------
cp_angles = np.array([i * 2 * math.pi / n_cp for i in range(n_cp)])
cp_radii  = np.array([r_input + cp_deltas[i] for i in range(n_cp)])

# Periodic cubic spline: append first point at angle+2pi to close the loop
_angles_ext = np.append(cp_angles, cp_angles[0] + 2 * math.pi)
_radii_ext  = np.append(cp_radii,  cp_radii[0])
_spline = CubicSpline(_angles_ext, _radii_ext, bc_type="periodic" if False else "not-a-knot")

N_orbit = max(180, int(2 * math.pi * r_input / 0.5))
thetas = np.linspace(0, 2 * math.pi, N_orbit, endpoint=False)
r_vals = np.clip(_spline(thetas), 0.5, None)

orbit_x = aoi_ce + r_vals * np.cos(thetas)
orbit_y = aoi_cn + r_vals * np.sin(thetas)
orbit_z = np.full(N_orbit, z_orbit)

# closed loop for plotting
orbit_x_plot = np.append(orbit_x, orbit_x[0])
orbit_y_plot = np.append(orbit_y, orbit_y[0])
orbit_z_plot = np.append(orbit_z, orbit_z[0])

# Control point positions on the orbit ring
cp_x = aoi_ce + cp_radii * np.cos(cp_angles)
cp_y = aoi_cn + cp_radii * np.sin(cp_angles)
cp_z = np.full(n_cp, z_orbit)

# ---------------------------------------------------------------------------
# Per-vertex coverage weakness
# ---------------------------------------------------------------------------
v_x = verts[:, 0][:, None]
v_y = verts[:, 1][:, None]

dx = v_x - orbit_x[None, :]
dy = v_y - orbit_y[None, :]
dist2d = np.sqrt(dx ** 2 + dy ** 2)

raw_score = np.maximum(0.0, 1.0 - dist2d / r_input).sum(axis=1)

s_min, s_max = raw_score.min(), raw_score.max()
norm_score = (raw_score - s_min) / (s_max - s_min + 1e-9)
coverage_weakness = 1.0 - norm_score  # 0=well-covered (blue), 1=weak (red)

# ---------------------------------------------------------------------------
# Build Plotly figure
# ---------------------------------------------------------------------------
traces: list = []

traces.append(go.Mesh3d(
    x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
    i=faces[:, 0], j=faces[:, 1], k=faces[:, 2],
    intensity=coverage_weakness,
    intensitymode="vertex",
    colorscale=[[0.0, "rgb(0,0,255)"], [0.5, "rgb(0,255,0)"], [1.0, "rgb(255,0,0)"]],
    cmin=0.0,
    cmax=1.0,
    colorbar=dict(title="Weakness", thickness=14, x=1.01),
    opacity=1.0,
    name="Building mesh",
    showlegend=True,
    flatshading=False,
))

traces.append(go.Scatter3d(
    x=orbit_x_plot, y=orbit_y_plot, z=orbit_z_plot,
    mode="lines",
    line=dict(color="deepskyblue", width=4),
    name="Orbit ring",
))

# Control point markers
traces.append(go.Scatter3d(
    x=cp_x, y=cp_y, z=cp_z,
    mode="markers+text",
    marker=dict(
        size=8,
        color="orange",
        symbol="diamond",
        line=dict(color="white", width=1),
    ),
    text=[f"P{i}" for i in range(n_cp)],
    textposition="top center",
    textfont=dict(color="orange", size=10),
    name="Control points",
))

fig = go.Figure(data=traces)
fig.update_layout(
    scene=dict(
        xaxis_title="East (m)",
        yaxis_title="North (m)",
        zaxis_title="Up (m)",
        bgcolor="#1a1a1a",
        aspectmode="data",
    ),
    paper_bgcolor="#111111",
    font_color="white",
    margin=dict(l=0, r=0, t=10, b=0),
    height=680,
)

st.plotly_chart(fig, width="stretch")
