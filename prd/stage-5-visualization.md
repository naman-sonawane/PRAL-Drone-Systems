# Stage 5 — Visualization PRD

> Companion docs: stage-5-implementation.md · footage-acquisition-io.md
> Scope: operator waypoint editor and pitch-demo view for Stage 5 outputs only.

---

## Purpose

Stage 5 produces 10 waypoints and a smooth trajectory through the interest field. The visualization makes this tangible: a top-down map shows the trajectory threading the value heatmap; a linked altitude profile shows the vertical shape of the path. The operator can edit any waypoint and see the trajectory update live. For the pitch, this is the "it plans like a pilot" moment before the beauty reel cut.

---

## Tool

**Streamlit** with PyDeck (Mapbox GL) + Plotly

| Property | Detail |
|---|---|
| Entry point | `pipeline/stage5_visualize.py` |
| Run | `streamlit run pipeline/stage5_visualize.py` |
| Mapbox renderer | `st.pydeck_chart` via `pydeck` |
| Altitude chart | `st.plotly_chart` via `plotly` |
| Waypoint editing | `st.data_editor` table (Streamlit-native; see note below) |

### Note on drag-and-drop
True drag-and-drop markers in Streamlit require a custom bidirectional JS component — out of scope for this stage. Instead, waypoints are edited via `st.data_editor`: the operator clicks a cell, types a new value, and the map rerenders on the next Streamlit rerun (< 1 s). This is the idiomatic Streamlit approach and sufficient for both pitch and operator use.

---

## Inputs Consumed

| File | Format | Description |
|---|---|---|
| `stage5/waypoints.json` | JSON, list of 10 | lat/lon/alt/yaw/pitch/shot_type/value/idx |
| `stage5/trajectory.npy` | float32 `(500, 5)` | Dense spline: x_enu, y_enu, z_enu, yaw, pitch |
| `stage4/interest_scores.npy` | float32 `(N_vertices,)` | Per-vertex interest scores (for heatmap layer) |
| `stage4/building_mesh.ply` | PLY | Building mesh (centroid → map anchor) |

---

## ENU → Lat/Lon Conversion

All ENU coordinates are anchored to the site origin: **43.4730° N, 80.5395° W**.

```python
import pyproj
import numpy as np

ORIGIN_LAT =  43.4730
ORIGIN_LON = -80.5395

transformer = pyproj.Proj(proj="aeqd", lat_0=ORIGIN_LAT, lon_0=ORIGIN_LON, units="m")

def enu_to_latlon(pts_enu: np.ndarray) -> list[tuple[float, float]]:
    """pts_enu: (N, 3) array of [x_east, y_north, z_up] in metres.
    Returns list of (lat, lon) tuples."""
    lons, lats = transformer(pts_enu[:, 0], pts_enu[:, 1], inverse=True)
    return list(zip(lats, lons))
```

This helper is used by both the trajectory path layer and the waypoint marker layer.

---

## Layout

```
┌────────────────────────────────────────┬──────────────────────┐
│                                        │  Altitude Profile    │
│    PyDeck Mapbox                       │  (Plotly line chart) │
│    - value heatmap layer               │                      │
│    - trajectory path layer             │  alt (m AGL)         │
│    - 10 waypoint markers               │  ┌───────────────┐   │
│      color-coded by shot type          │  │ ╱‾╲   ╱‾‾╲    │   │
│                                        │  │╱   ╲ ╱    ╲   │   │
│    ~65% of window width                │  └───────────────┘   │
│                                        │  waypoint idx 0→9    │
├────────────────────────────────────────┴──────────────────────┤
│  Waypoint Editor (st.data_editor)                             │
│  idx │ lat │ lon │ alt │ yaw │ pitch │ shot_type │ value      │
│   0  │ ... │ ... │ ... │ ... │  ...  │  orbit    │  0.82      │
│   1  │ ... │ ... │ ... │ ... │  ...  │  reveal   │  0.76      │
│   …  │  …  │  …  │  …  │  …  │   …   │    …      │   …        │
│   9  │ ... │ ... │ ... │ ... │  ...  │  top_down │  0.61      │
└───────────────────────────────────────────────────────────────┘
```

Top half: map (left, ~65%) + altitude profile (right, ~35%).
Bottom: full-width waypoint editor table.

---

## Map Layers (PyDeck)

Three layers, rendered in order:

### Layer 1 — Value Heatmap
Projects per-vertex interest scores to lat/lon via `enu_to_latlon` and renders a `HeatmapLayer`.

```python
import pydeck as pdk
import open3d as o3d
import numpy as np

mesh = o3d.io.read_triangle_mesh("stage4/building_mesh.ply")
verts_enu = np.asarray(mesh.vertices)
interest_scores = np.load("stage4/interest_scores.npy")
verts_latlon = enu_to_latlon(verts_enu)

heatmap_data = [
    {"lat": lat, "lon": lon, "weight": float(score)}
    for (lat, lon), score in zip(verts_latlon, interest_scores)
    if score > 0.2
]

heatmap_layer = pdk.Layer(
    "HeatmapLayer",
    data=heatmap_data,
    get_position="[lon, lat]",
    get_weight="weight",
    radiusPixels=40,
    colorRange=[
        [0,   0, 255, 100],   # blue  — low interest
        [0, 255,   0, 160],   # green — mid
        [255,  0,  0, 200],   # red   — high interest
    ],
)
```

### Layer 2 — Trajectory Path
Renders the 500-sample spline as a `PathLayer`.

```python
import json

trajectory = np.load("stage5/trajectory.npy")        # (500, 5)
traj_latlon = enu_to_latlon(trajectory[:, :3])

path_layer = pdk.Layer(
    "PathLayer",
    data=[{"path": [[lon, lat] for lat, lon in traj_latlon]}],
    get_path="path",
    get_color=[255, 255, 255, 200],
    width_pixels=3,
)
```

### Layer 3 — Waypoint Markers
10 `ScatterplotLayer` points, color-coded by shot type.

```python
SHOT_COLORS = {
    "orbit":    [255, 200,   0, 255],   # amber
    "reveal":   [  0, 200, 255, 255],   # cyan
    "push_in":  [255,  80,  80, 255],   # coral
    "top_down": [180, 120, 255, 255],   # violet
}

with open("stage5/waypoints.json") as f:
    waypoints = json.load(f)

waypoint_data = [
    {
        "lat":   w["lat"],
        "lon":   w["lon"],
        "color": SHOT_COLORS[w["shot_type"]],
        "label": f"{w['idx']}: {w['shot_type']}",
        "value": w["value"],
        "alt":   w["alt"],
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
```

Tooltip on hover: `"{label} · value {value:.2f} · alt {alt:.0f} m"`.

### Assembling the chart

```python
import streamlit as st

centroid_latlon = enu_to_latlon(verts_enu.mean(axis=0, keepdims=True))[0]

view = pdk.ViewState(
    latitude=centroid_latlon[0],
    longitude=centroid_latlon[1],
    zoom=17,
    pitch=0,        # top-down
    bearing=0,
)

deck = pdk.Deck(
    layers=[heatmap_layer, path_layer, waypoint_layer],
    initial_view_state=view,
    map_style="mapbox://styles/mapbox/dark-v11",
    tooltip={"text": "{label}\nvalue: {value}\nalt: {alt} m"},
)

col_map, col_chart = st.columns([0.65, 0.35])
with col_map:
    st.pydeck_chart(deck, use_container_width=True, height=500)
```

Requires `MAPBOX_ACCESS_TOKEN` set as an environment variable (free Mapbox public token).

---

## Altitude Profile (Plotly)

```python
import plotly.graph_objects as go

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=list(range(10)),
    y=[w["alt"] for w in waypoints],
    mode="lines+markers",
    line=dict(color="white", width=2),
    marker=dict(
        size=10,
        color=[f"rgb({c[0]},{c[1]},{c[2]})" for c in
               [SHOT_COLORS[w["shot_type"]] for w in waypoints]],
    ),
    text=[w["shot_type"] for w in waypoints],
    hovertemplate="%{text}<br>alt: %{y:.0f} m<extra></extra>",
))
fig.update_layout(
    plot_bgcolor="#111111",
    paper_bgcolor="#111111",
    font_color="white",
    xaxis=dict(title="Waypoint index", tickvals=list(range(10))),
    yaxis=dict(title="Altitude (m AGL)"),
    margin=dict(l=40, r=10, t=10, b=40),
    height=500,
)

with col_chart:
    st.plotly_chart(fig, use_container_width=True)
```

---

## Waypoint Editor

Full-width below the map row. Any cell edit triggers a Streamlit rerun; all three map layers and the altitude chart rebuild from `edited_df`.

```python
import pandas as pd

df = pd.DataFrame([{
    "idx":       w["idx"],
    "lat":       w["lat"],
    "lon":       w["lon"],
    "alt":       w["alt"],
    "yaw":       w["yaw"],
    "pitch":     w["pitch"],
    "shot_type": w["shot_type"],
    "value":     round(w["value"], 3),
} for w in waypoints])

edited_df = st.data_editor(
    df,
    column_config={
        "idx":       st.column_config.NumberColumn("idx",       disabled=True),
        "lat":       st.column_config.NumberColumn("lat",       format="%.6f"),
        "lon":       st.column_config.NumberColumn("lon",       format="%.6f"),
        "alt":       st.column_config.NumberColumn("alt (m AGL)", format="%.1f"),
        "yaw":       st.column_config.NumberColumn("yaw°",      format="%.1f"),
        "pitch":     st.column_config.NumberColumn("pitch°",    format="%.1f"),
        "shot_type": st.column_config.SelectboxColumn(
                         "shot_type",
                         options=["orbit", "reveal", "push_in", "top_down"]),
        "value":     st.column_config.NumberColumn("value",     disabled=True),
    },
    use_container_width=True,
    hide_index=True,
)
# After edit: rebuild waypoints list from edited_df for next render cycle
waypoints = edited_df.to_dict(orient="records")
```

---

## Export

```python
import json

if st.button("Export waypoints"):
    with open("stage5/waypoints.json", "w") as f:
        json.dump(waypoints, f, indent=2)
    st.success("Saved to stage5/waypoints.json")
```

---

## Pitch Use

1. `streamlit run pipeline/stage5_visualize.py`
2. Map appears: red value heatmap with a white trajectory line threading the bright zones.
3. 10 colored dots sit on the trajectory — amber orbit, cyan reveal, coral push-in, violet top-down.
4. Altitude profile shows the vertical shape of the path: climbs for reveals, dips for push-ins, peaks for top-downs.
5. Cut to the beauty reel.

The editor is operator-facing. The pitch never touches it.

---

## Dependencies Summary

| Package | Purpose | Install |
|---|---|---|
| `streamlit` | App shell | `pip install streamlit` |
| `pydeck` | Mapbox GL map layers | `pip install pydeck` |
| `plotly` | Altitude profile chart | `pip install plotly` |
| `pandas` | data_editor dataframe | `pip install pandas` |
| `pyproj` | ENU → lat/lon conversion | `pip install pyproj` |
| `numpy` | Trajectory array ops | from Stage 2 |
| `open3d` | Mesh vertex read for heatmap | from Stage 2/3 |

Requires env var: `MAPBOX_ACCESS_TOKEN` (free Mapbox public token).

---

## Status

Draft v0.1
