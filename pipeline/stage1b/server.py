"""
Stage 1b visualization server.

FastAPI server that exposes OSM footprint lookup via JSON endpoints
and serves the Mapbox GL JS frontend from static/index.html.

Run from repo root:
    python pipeline/stage1b/server.py
    # or
    uvicorn pipeline.stage1b.server:app --reload
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Allow running directly from any working directory
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from pipeline.stage1.footprint import query_osm_footprints, filter_by_distance
from pipeline.stage1.coordinate import enu_to_geodetic
from pipeline.stage1.types import HomeOrigin

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="PRAL Stage 1b — AOI Annotation")


# ── Request / response models ─────────────────────────────────────────────────

class AnnotateRequest(BaseModel):
    lat: float
    lon: float


class CandidateOut(BaseModel):
    id: str
    source: str
    confidence: float
    centroid_lat: float
    centroid_lon: float
    polygon_latlon: list[list[float]]  # [[lat, lon], ...]


class AnnotateResponse(BaseModel):
    candidates: list[CandidateOut]
    pin_lat: float
    pin_lon: float


class ConfirmRequest(BaseModel):
    candidate_id: str
    candidates: list[CandidateOut]


class AOIOut(BaseModel):
    source: str
    centroid_lat: float
    centroid_lon: float
    polygon_latlon: list[list[float]]


class ConfirmResponse(BaseModel):
    aoi: AOIOut


# ── Helper ────────────────────────────────────────────────────────────────────

def _enu_polygon_to_latlon(
    polygon_enu: list[tuple[float, float]],
    origin: HomeOrigin,
) -> list[list[float]]:
    result = []
    for e, n in polygon_enu:
        lat, lon, _ = enu_to_geodetic(e, n, 0.0, origin)
        result.append([lat, lon])
    return result


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    html = (STATIC_DIR / "index.html").read_text()
    token = os.environ.get("MAPBOX_ACCESS_TOKEN", "")
    html = html.replace("YOUR_MAPBOX_TOKEN", token)
    return HTMLResponse(html)


@app.post("/annotate", response_model=AnnotateResponse)
def annotate(req: AnnotateRequest):
    origin = HomeOrigin(lat=req.lat, lon=req.lon, alt=0.0)

    try:
        raw = query_osm_footprints(req.lat, req.lon, radius_m=100.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OSM query failed: {exc}")

    # pin is at origin → ENU (0, 0)
    pin_enu = (0.0, 0.0)
    filtered = filter_by_distance(raw, pin_enu, max_dist_m=50.0)

    candidates_out: list[CandidateOut] = []
    for c in filtered:
        centroid_lat, centroid_lon, _ = enu_to_geodetic(
            c.centroid_enu[0], c.centroid_enu[1], 0.0, origin
        )
        polygon_latlon = _enu_polygon_to_latlon(c.polygon_enu, origin)
        candidates_out.append(
            CandidateOut(
                id=c.id,
                source=c.source,
                confidence=c.confidence,
                centroid_lat=centroid_lat,
                centroid_lon=centroid_lon,
                polygon_latlon=polygon_latlon,
            )
        )

    return AnnotateResponse(
        candidates=candidates_out,
        pin_lat=req.lat,
        pin_lon=req.lon,
    )


@app.post("/confirm", response_model=ConfirmResponse)
def confirm(req: ConfirmRequest):
    match = next((c for c in req.candidates if c.id == req.candidate_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    return ConfirmResponse(
        aoi=AOIOut(
            source=match.source,
            centroid_lat=match.centroid_lat,
            centroid_lon=match.centroid_lon,
            polygon_latlon=match.polygon_latlon,
        )
    )


# ── Static files (served after API routes) ────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
