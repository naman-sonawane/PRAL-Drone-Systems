# Stage 1b — AOI Annotation (Mapbox GL JS)

Interactive web app for OSM footprint lookup and manual AOI confirmation.
Replaces the old Streamlit + video-stream visualizer.

## Setup

1. Install dependencies (from this folder or repo root):
   ```
   pip install -r pipeline/stage1b/requirements.txt
   ```

2. Open `pipeline/stage1b/static/index.html` and replace `YOUR_MAPBOX_TOKEN`
   with your Mapbox public token.

3. Start the server from the **repo root**:
   ```
   python pipeline/stage1b/server.py
   ```
   Or with auto-reload during development:
   ```
   uvicorn pipeline.stage1b.server:app --reload
   ```

4. Open `http://localhost:8000` in your browser.

## Usage

- Enter lat/lon in the top bar and click **Go**, or click anywhere on the map to drop a pin.
- Click **Annotate** to query OSM for building footprints within 50 m of the pin.
- Click any highlighted polygon to confirm it as the AOI (shown as a red outline).
- If no footprints are found, a draw tool appears — trace a polygon manually and click **Confirm Manual**.
