"""
Stage 2 visualization -- Streamlit debug app.

Run alongside the Stage 2 stream server (optional -- provides nadir frames):
    # Terminal 1
    python -m pipeline.stage2.stream_server --video DJI_0009.MP4 --autostart

    # Terminal 2
    streamlit run pipeline/visualize_stage2.py

In mock mode (default) no stream server or sensor is needed.

Requires: streamlit>=1.33, plotly, matplotlib, numpy, requests
"""
from __future__ import annotations

import json
import math
import os
import sys

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pipeline.stage2 import AOI, Stage2Runner
from pipeline.stage2.mock_data import build_mock_stage2_output, get_ply_footprint_polygon, get_ply_height_map
from pipeline.stage2.obstacle import LABEL_NO_GO, LABEL_TRAVERSABLE, VOXEL_SIZE
from pipeline.stage2.radius import compute_orbit_radius, compute_vfov

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Stage 2 -- Debug View", layout="wide")
st.title("Stage 2 -- Survey + Geometry")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Stream (optional)")
    stream_url = st.text_input("Stream URL", "http://localhost:5002")

    st.header("Mode")
    use_mock = st.checkbox("Use mock data (no sensor required)", value=True)
    if use_mock:
        st.caption("Mock mode: synthetic building walls, trees, and poles. No stream server needed.")

    st.header("AOI")
    polygon_json = st.text_area(
        "Polygon vertices (JSON: [[e,n], ...])",
        '[[-10,-8],[10,-8],[10,8],[-10,8]]',
    )

    st.header("Rangefinder")
    H_true = st.slider("H_true_mock (m)", 2.0, 60.0, 15.0, 0.5)
    alt_override = st.number_input("Survey altitude override (m, 0 = auto)", value=0.0)

    st.header("Camera")
    col_fx, col_fy = st.columns(2)
    fx = col_fx.number_input("fx (px)", value=1000.0)
    fy = col_fy.number_input("fy (px)", value=1000.0)
    col_cx, col_cy = st.columns(2)
    cx_input = col_cx.number_input("cx (px)", value=960.0)
    cy_input = col_cy.number_input("cy (px)", value=540.0)
    img_h = st.number_input("Image height (px)", value=1080, step=1)
    col_r, col_p, col_y = st.columns(3)
    roll_deg  = col_r.number_input("Roll °",  value=0.0)
    pitch_deg = col_p.number_input("Pitch °", value=-90.0)
    yaw_deg   = col_y.number_input("Yaw °",   value=0.0)

    st.header("DSM")
    depth_model_choice = st.selectbox(
        "Depth model",
        ["None (mock)", "DepthAnythingV2-S (vits)", "DepthAnythingV2-L (vitl)"],
    )
    if depth_model_choice != "None (mock)":
        checkpoint_path = st.text_input(
            "Checkpoint path",
            "pipeline/stage2/depth_anything_v2_vits.pth",
        )
    else:
        checkpoint_path = ""

    gp_method = st.selectbox(
        "Ground plane method",
        ["z-percentile fallback", "RANSAC (open3d)"],
    )

# ---------------------------------------------------------------------------
# Parse AOI polygon
# ---------------------------------------------------------------------------
try:
    raw_poly = json.loads(polygon_json)
    polygon_enu = [(float(v[0]), float(v[1])) for v in raw_poly]
    if len(polygon_enu) < 3:
        raise ValueError("Need at least 3 vertices")
    cx_aoi = sum(p[0] for p in polygon_enu) / len(polygon_enu)
    cn_aoi = sum(p[1] for p in polygon_enu) / len(polygon_enu)
    aoi = AOI(polygon_enu=polygon_enu, centroid_enu=(cx_aoi, cn_aoi), source="manual")
    with st.sidebar:
        st.caption(f"Centroid: E={cx_aoi:.1f} m, N={cn_aoi:.1f} m  |  {len(polygon_enu)} vertices")
except Exception as exc:
    st.error(f"Invalid AOI polygon JSON: {exc}")
    st.stop()

K = np.array(
    [[fx, 0.0, cx_input],
     [0.0, fy,  cy_input],
     [0.0, 0.0, 1.0]],
    dtype=np.float64,
)

# ---------------------------------------------------------------------------
# Run button
# ---------------------------------------------------------------------------
run_btn = st.button("Run Stage 2", type="primary", use_container_width=True)
if not run_btn:
    st.info("Configure the AOI and parameters in the sidebar, then click **Run Stage 2**.")
    st.stop()

# ---------------------------------------------------------------------------
# Execute Stage 2
# ---------------------------------------------------------------------------
out = None

if use_mock:
    with st.spinner("Building mock Stage 2 output..."):
        vfov = compute_vfov(K, int(img_h))
        r_mock, _, _ = compute_orbit_radius(H_true, vfov)

        # Override AOI polygon with the actual e7.ply building footprint
        _ply_poly = get_ply_footprint_polygon(H_true, r_mock, cx_aoi, cn_aoi)
        if _ply_poly:
            polygon_enu = _ply_poly
            cx_aoi = sum(p[0] for p in polygon_enu) / len(polygon_enu)
            cn_aoi = sum(p[1] for p in polygon_enu) / len(polygon_enu)
            aoi = AOI(
                polygon_enu=polygon_enu,
                centroid_enu=(cx_aoi, cn_aoi),
                source="ply_mock",
            )

        out = build_mock_stage2_output(aoi, r=r_mock, H=H_true, vfov_rad=vfov)
    st.success("Mock data generated.")
else:
    import io, logging
    log_buf = io.StringIO()
    _h = logging.StreamHandler(log_buf)
    _h.setLevel(logging.DEBUG)
    logging.getLogger("pipeline.stage2").addHandler(_h)
    logging.getLogger("pipeline.stage2").setLevel(logging.DEBUG)

    encoder = "vits" if "vits" in depth_model_choice else "vitl"
    with st.spinner("Running Stage 2 sub-steps..."):
        runner = Stage2Runner(
            K=K,
            image_height=int(img_h),
            stream_url=stream_url,
            H_true_mock=H_true,
        )
        if depth_model_choice != "None (mock)":
            from pipeline.stage2.height import _load_depth_model
            runner._depth_model = _load_depth_model(encoder=encoder, checkpoint=checkpoint_path)
        try:
            out = runner.run(aoi)
        except AssertionError as exc:
            st.error(f"Stage 2 gate check FAILED: {exc}")
        except Exception as exc:
            st.error(f"Stage 2 error: {exc}")

    logging.getLogger("pipeline.stage2").removeHandler(_h)
    with st.expander("Stage 2 log", expanded=False):
        st.text(log_buf.getvalue() or "(no log output)")

if out is None:
    st.stop()

# ===========================================================================
# Panel 1 — Height Estimation
# ===========================================================================
st.subheader("Panel 1 — Height Estimation")

if out.height_disagreed:
    st.warning(
        f"Rangefinder ({out.H_rangefinder:.1f} m) and DSM ({out.H_dsm:.1f} m) "
        f"disagree by >10% — DSM discarded, using rangefinder as ground truth."
    )
if out.height_warning:
    st.warning(out.height_warning)

c1, c2, c3 = st.columns(3)
c1.metric("H_rangefinder", f"{out.H_rangefinder:.2f} m")
c2.metric("H_dsm", f"{out.H_dsm:.2f} m")
c3.metric("H_fused", f"{out.H:.2f} m")

try:
    import plotly.graph_objects as _go_p1
except ImportError:
    _go_p1 = None

if _go_p1 is not None:
    _e_ctr, _n_ctr, _z_grid = get_ply_height_map(aoi, out.H, out.r, grid_res=0.5)
    if _e_ctr is not None:
        _fig_dm = _go_p1.Figure()
        _fig_dm.add_trace(_go_p1.Heatmap(
            x=_e_ctr, y=_n_ctr, z=_z_grid,
            colorscale="plasma", zmin=0, zmax=out.H,
            colorbar=dict(title="Elevation (m)"),
            name="Surface elevation",
        ))
        _ring_e = [p[0] for p in polygon_enu + [polygon_enu[0]]]
        _ring_n = [p[1] for p in polygon_enu + [polygon_enu[0]]]
        _fig_dm.add_trace(_go_p1.Scatter(
            x=_ring_e, y=_ring_n, mode="lines",
            line=dict(color="white", width=2), name="AOI",
        ))
        _theta_dm = np.linspace(0, 2 * math.pi, 360)
        _fig_dm.add_trace(_go_p1.Scatter(
            x=cx_aoi + out.r * np.cos(_theta_dm),
            y=cn_aoi + out.r * np.sin(_theta_dm),
            mode="lines",
            line=dict(color="cyan", width=1.5, dash="dash"),
            name=f"Orbit r={out.r:.1f} m",
        ))
        _fig_dm.update_layout(
            xaxis_title="East (m)", yaxis_title="North (m)",
            yaxis_scaleanchor="x",
            title="Top-down depth map — surface elevation from e7.ply",
            margin=dict(l=0, r=0, t=40, b=0),
            legend=dict(font=dict(size=10)),
        )
        st.plotly_chart(_fig_dm, use_container_width=True)
    else:
        st.info("e7.ply not found — depth map unavailable.")
else:
    st.warning("plotly not installed — `pip install plotly`")

st.divider()

# ===========================================================================
# Panel 2 — Orbit Ring
# ===========================================================================
st.subheader("Panel 2 — Orbit Ring")

if out.r_clamped:
    st.warning(f"Orbit radius clamped: raw {out.r_raw:.1f} m → {out.r:.1f} m")

c4, c5, c6 = st.columns(3)
c4.metric("H", f"{out.H:.2f} m")
c5.metric("r", f"{out.r:.2f} m")
c6.metric("z_orbit", f"{out.z_orbit:.2f} m AGL")

fig2, ax2 = plt.subplots(figsize=(7, 7))
ax2.set_aspect("equal")
ax2.set_xlabel("East (m)")
ax2.set_ylabel("North (m)")
ax2.set_title("Stage 1 ENU map + Stage 2 orbit ring")
ax2.grid(True, alpha=0.3)

ring = polygon_enu + [polygon_enu[0]]
ax2.fill([p[0] for p in ring], [p[1] for p in ring], alpha=0.25, color="tomato")
ax2.plot([p[0] for p in ring], [p[1] for p in ring], "tomato", linewidth=2)
ax2.plot(cx_aoi, cn_aoi, "r*", markersize=14, zorder=5)

theta = np.linspace(0, 2 * math.pi, 360)
ax2.plot(cx_aoi + out.r * np.cos(theta), cn_aoi + out.r * np.sin(theta),
         "b-", linewidth=2.5)
ax2.plot(cx_aoi + out.r * 0.7 * np.cos(theta), cn_aoi + out.r * 0.7 * np.sin(theta),
         "b--", linewidth=1, alpha=0.5)
ax2.plot(cx_aoi + out.r * 1.5 * np.cos(theta), cn_aoi + out.r * 1.5 * np.sin(theta),
         "b--", linewidth=1, alpha=0.5)

ax2.legend(handles=[
    mpatches.Patch(color="tomato", alpha=0.5, label="Confirmed AOI"),
    plt.Line2D([0], [0], color="b", linewidth=2, label=f"Orbit (r = {out.r:.1f} m)"),
    plt.Line2D([0], [0], color="b", linewidth=1, linestyle="--",
               label=f"Annulus [{out.r*0.7:.1f} – {out.r*1.5:.1f} m]"),
], fontsize=8, loc="upper right")
st.pyplot(fig2)
plt.close(fig2)

st.divider()

# ===========================================================================
# Panel 3 — Obstacle Map
# ===========================================================================
st.subheader("Panel 3 — Obstacle Map")

sam2_mode = st.radio(
    "Obstacle coloring",
    ["With SAM2 labeling", "Without SAM2 labeling"],
    horizontal=True,
    key="sam2_toggle",
)
use_sam2_colors = sam2_mode == "With SAM2 labeling"

# Gather voxel data
voxel_labels: dict = out.voxel_labels or {}
if voxel_labels:
    all_keys   = list(voxel_labels.keys())
    all_labels = np.array(list(voxel_labels.values()))
    vox_e = np.array([k[0] * VOXEL_SIZE for k in all_keys])
    vox_n = np.array([k[1] * VOXEL_SIZE for k in all_keys])
    vox_u = np.array([k[2] * VOXEL_SIZE for k in all_keys])
else:
    vox_e = vox_n = vox_u = all_labels = np.array([])

n_total = len(vox_e)
n_nogo  = int(np.sum(all_labels == LABEL_NO_GO))   if n_total else 0
n_trav  = int(np.sum(all_labels == LABEL_TRAVERSABLE)) if n_total else 0

if True:
    try:
        import plotly.graph_objects as go

        _color_map = {LABEL_NO_GO: "red", LABEL_TRAVERSABLE: "steelblue", 0: "grey"}
        traces = []

        if n_total > 0:
            for lbl_val, lbl_name, color in [
                (LABEL_NO_GO, "No-go", "red"),
                (LABEL_TRAVERSABLE, "Traversable", "steelblue"),
                (0, "Unlabeled", "grey"),
            ]:
                sel = all_labels == lbl_val
                if not sel.any():
                    continue
                plot_color = color if use_sam2_colors else "lightgrey"
                traces.append(go.Scatter3d(
                    x=vox_e[sel], y=vox_n[sel], z=vox_u[sel],
                    mode="markers",
                    marker=dict(size=2, color=plot_color, opacity=0.6),
                    name=lbl_name,
                ))

        # Orbit ring at z_orbit
        theta_b = np.linspace(0, 2 * math.pi, 180)
        traces.append(go.Scatter3d(
            x=cx_aoi + out.r * np.cos(theta_b),
            y=cn_aoi + out.r * np.sin(theta_b),
            z=np.full(180, out.z_orbit),
            mode="lines", line=dict(color="blue", width=4),
            name=f"Orbit ring (z={out.z_orbit:.1f} m)",
        ))
        traces.append(go.Scatter3d(
            x=[cx_aoi], y=[cn_aoi], z=[0.0],
            mode="markers",
            marker=dict(size=6, color="tomato", symbol="diamond"),
            name="AOI centroid",
        ))

        fig_3d = go.Figure(data=traces)
        fig_3d.update_layout(
            scene=dict(xaxis_title="East (m)", yaxis_title="North (m)", zaxis_title="Up (m)"),
            margin=dict(l=0, r=0, t=30, b=0),
            legend=dict(font=dict(size=11)),
        )
        st.plotly_chart(fig_3d, use_container_width=True)

    except ImportError:
        st.warning("plotly not installed — `pip install plotly`")

# Summary line
st.caption(
    f"Occupied voxels: {n_total}  |  No-go: {n_nogo}  |  "
    f"Traversable: {n_trav}  |  No-fly volumes: {len(out.no_fly_volumes)}"
)

st.divider()

# ===========================================================================
# Gate Check
# ===========================================================================
st.subheader("Stage 2 → 3 Gate Check")

checks = [
    ("H > 0",         out.H > 0,                                      f"H = {out.H:.2f} m"),
    ("3.0 ≤ r ≤ 50.0", 3.0 <= out.r <= 50.0,                         f"r = {out.r:.2f} m"),
    ("OctoMap populated", out.obstacle_map is not None and out.obstacle_map.size() > 0,
     f"{out.obstacle_map.size() if out.obstacle_map else 0} voxels"),
]
all_pass = all(ok for _, ok, _ in checks)

table_md = "| Check | Status | Value |\n|---|---|---|\n"
for label, ok, value in checks:
    status = ":white_check_mark: PASS" if ok else ":x: FAIL"
    table_md += f"| `{label}` | {status} | {value} |\n"
st.markdown(table_md)

if all_pass:
    st.success("All checks passed.")
    st.button("Proceed to Stage 3", type="primary", use_container_width=True)
else:
    failed = [label for label, ok, _ in checks if not ok]
    st.error(f"Gate check FAILED: {', '.join(failed)}")
    st.button("Proceed to Stage 3", type="primary", use_container_width=True, disabled=True)
