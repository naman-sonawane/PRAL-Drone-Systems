"""
Stage 1 visualization -- Streamlit debug app.

Run alongside stream_server.py:
    # Terminal 1
    python pipeline/stream_server.py --video DJI_0009.MP4

    # Terminal 2
    streamlit run pipeline/visualize.py

Requires: streamlit>=1.33, requests, matplotlib, pandas, opencv-python, numpy, pymap3d, flask
"""
import contextlib
import io
import os
import sys

import cv2
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import streamlit as st
from PIL import Image

# Make the project root importable
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pipeline.stage1 import CameraIntrinsics, MockDrone, Stage1Runner
from pipeline.stage1.coordinate import geodetic_to_enu
from pipeline.stage1.footprint import filter_by_distance, query_osm_footprints
from pipeline.stage1.types import HomeOrigin

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CHECKPOINT = os.path.join(_PIPELINE_DIR, "sam2.1_hiera_tiny.pt")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Stage 1 -- Debug View",
    layout="wide",
)
st.title("Stage 1 -- GPS Target Selection & Confirmation")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Stream")
    stream_url = st.text_input("Stream URL", "http://localhost:5001")

    st.header("Target Pin")
    lat = st.number_input("Latitude", value=37.774929, format="%.6f")
    lon = st.number_input("Longitude", value=-122.419416, format="%.6f")

    st.header("Camera Intrinsics")
    fx = st.number_input("fx (px)", value=1000.0)
    fy = st.number_input("fy (px)", value=1000.0)
    cx = st.number_input("cx (px)", value=960.0)
    cy = st.number_input("cy (px)", value=540.0)
    img_w = st.number_input("Width (px)", value=1920, step=1)
    img_h = st.number_input("Height (px)", value=1080, step=1)

    st.header("OSM Search")
    osm_radius = st.slider("Search radius (m)", 20, 300, 100)
    osm_max_dist = st.slider("Max candidate distance (m)", 10, 150, 50)

    st.header("SAM 2")
    sam2_cfg = st.text_input("Config", "configs/sam2.1/sam2.1_hiera_t.yaml")
    sam2_checkpoint = st.text_input("Checkpoint", _DEFAULT_CHECKPOINT)

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
col_live, col_results = st.columns([4, 6])

# ---------------------------------------------------------------------------
# Live feed (auto-refreshing fragment)
# ---------------------------------------------------------------------------
with col_live:
    st.subheader("Live Feed")

    @st.fragment(run_every=0.1)
    def _live_feed() -> None:
        try:
            resp = requests.get(f"{stream_url}/frame", timeout=1)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
            st.image(img, use_container_width=True)
        except Exception as exc:
            st.warning(f"Stream unavailable -- {exc}")
            return

        try:
            meta = requests.get(f"{stream_url}/status", timeout=1).json()
            st.caption(
                f"Frame {meta['frame_index']} / {meta['total_frames']}"
                f"  |  {meta['fps']} fps replay"
            )
        except Exception:
            pass

    _live_feed()

# ---------------------------------------------------------------------------
# Stage 1 controls & results
# ---------------------------------------------------------------------------
with col_results:
    st.subheader("Stage 1 Controls")
    run_btn = st.button("Run Stage 1", type="primary", use_container_width=True)

    if run_btn:
        intrinsics = CameraIntrinsics(
            fx=float(fx),
            fy=float(fy),
            cx=float(cx),
            cy=float(cy),
            width=int(img_w),
            height=int(img_h),
        )

        # Fetch current frame from stream for MockDrone
        frame_bgr: np.ndarray
        try:
            resp = requests.get(f"{stream_url}/frame", timeout=2)
            resp.raise_for_status()
            arr = np.frombuffer(resp.content, np.uint8)
            frame_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception:
            st.warning("Could not fetch frame from stream -- using blank frame.")
            frame_bgr = np.zeros((int(img_h), int(img_w), 3), dtype=np.uint8)

        drone = MockDrone(
            position_enu=(0.0, 0.0, 40.0),
            yaw=0.0,
            frame=frame_bgr,
        )

        runner = Stage1Runner(
            intrinsics=intrinsics,
            sam2_cfg=sam2_cfg,
            sam2_checkpoint=sam2_checkpoint,
        )

        log_buf = io.StringIO()
        aoi = None
        osm_candidates = []

        with st.spinner("Running Stage 1..."):
            try:
                with contextlib.redirect_stdout(log_buf):
                    aoi = runner.run(lat, lon, drone)
            except Exception as exc:
                st.error(f"Stage 1 failed: {exc}")

            # Re-fetch OSM candidates for display
            try:
                origin = HomeOrigin(lat=lat, lon=lon, alt=0.0)
                pin_enu = geodetic_to_enu(lat, lon, 0.0, origin)[:2]
                osm_candidates = query_osm_footprints(lat, lon, radius_m=osm_radius)
                osm_candidates = filter_by_distance(
                    osm_candidates, pin_enu, max_dist_m=osm_max_dist
                )
            except Exception as exc:
                st.warning(f"OSM re-fetch failed: {exc}")

        # --- Log ---
        st.subheader("Log")
        st.text_area("", log_buf.getvalue(), height=130, label_visibility="collapsed")

        if aoi is None:
            st.stop()

        # --- AOI summary metrics ---
        st.subheader("Confirmed AOI")
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Source", aoi.source)
        col_b.metric("Centroid E", f"{aoi.centroid_enu[0]:.1f} m")
        col_c.metric("Centroid N", f"{aoi.centroid_enu[1]:.1f} m")

        # --- Candidates table ---
        st.subheader(f"OSM Candidates ({len(osm_candidates)})")
        if osm_candidates:
            rows = [
                {
                    "id": c.id,
                    "source": c.source,
                    "confidence": c.confidence,
                    "centroid E (m)": round(c.centroid_enu[0], 2),
                    "centroid N (m)": round(c.centroid_enu[1], 2),
                    "vertices": len(c.polygon_enu),
                }
                for c in osm_candidates
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No OSM candidates found within the search radius.")

        # --- ENU map ---
        st.subheader("ENU Map")
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.set_aspect("equal")
        ax.set_xlabel("East (m)")
        ax.set_ylabel("North (m)")
        ax.set_title("Stage 1 Candidates & Confirmed AOI")
        ax.grid(True, alpha=0.3)

        for c in osm_candidates:
            if len(c.polygon_enu) >= 3:
                ring = c.polygon_enu + [c.polygon_enu[0]]
                xs = [p[0] for p in ring]
                ys = [p[1] for p in ring]
                ax.fill(xs, ys, alpha=0.15, color="steelblue")
                ax.plot(xs, ys, color="steelblue", linewidth=1)
                ax.plot(c.centroid_enu[0], c.centroid_enu[1], "o",
                        color="steelblue", markersize=4)

        if len(aoi.polygon_enu) >= 3:
            ring = aoi.polygon_enu + [aoi.polygon_enu[0]]
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            ax.fill(xs, ys, alpha=0.3, color="tomato")
            ax.plot(xs, ys, color="tomato", linewidth=2)
            ax.plot(aoi.centroid_enu[0], aoi.centroid_enu[1], "r*", markersize=14)

        # Pin at ENU origin
        ax.plot(0, 0, "k+", markersize=16, markeredgewidth=2)

        ax.legend(
            handles=[
                mpatches.Patch(color="steelblue", alpha=0.6,
                               label=f"OSM candidates ({len(osm_candidates)})"),
                mpatches.Patch(color="tomato", alpha=0.6,
                               label=f"Confirmed AOI ({aoi.source})"),
            ],
            loc="upper right",
            fontsize=8,
        )
        st.pyplot(fig)
        plt.close(fig)

        # --- Captured nadir frame ---
        st.subheader("Captured Nadir Frame")
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        st.image(frame_rgb, caption="Frame captured by MockDrone", use_container_width=True)
