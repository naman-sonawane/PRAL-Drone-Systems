"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  Circle,
  useMap,
  useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { AOI, LatLng } from "@/lib/types";
import { DEFAULT_AOI } from "@fixtures/index";

type LeafletIconDefaultPrototype = typeof L.Icon.Default.prototype & {
  _getIconUrl?: () => string;
};

// Fix Leaflet's default icon paths in Next.js which cause 404s
if (typeof window !== "undefined") {
delete (L.Icon.Default.prototype as LeafletIconDefaultPrototype)._getIconUrl;
  L.Icon.Default.mergeOptions({
    iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
    iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
    shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  });
}

const AOI_COLOR = "#e50914";

interface MapAOISelectorProps {
  onAOIChange: (aoi: AOI | null) => void;
  initialAOI?: AOI;
  userLocation?: LatLng | null;
}

function metersToLatLngDelta(meters: number, lat: number): number {
  const latDelta = meters / 111320;
  const lngDelta = meters / (111320 * Math.cos((lat * Math.PI) / 180));
  return Math.max(latDelta, lngDelta);
}

function CircleDrawer({
  onComplete,
  drawing,
  setDrawing,
}: {
  onComplete: (center: LatLng, radiusM: number) => void;
  drawing: boolean;
  setDrawing: (v: boolean) => void;
}) {
  const [center, setCenter] = useState<LatLng | null>(null);
  const [radius, setRadius] = useState(0);
  const startRef = useRef<LatLng | null>(null);

  const map = useMapEvents({
    mousedown(e) {
      if (!drawing) return;
      const pt: LatLng = { lat: e.latlng.lat, lng: e.latlng.lng };
      startRef.current = pt;
      setCenter(pt);
      setRadius(0);
      map.dragging.disable();
    },
    mousemove(e) {
      if (!drawing || !startRef.current) return;
      const start = startRef.current;
      const current = e.latlng;
      const dist = map.distance(L.latLng(start.lat, start.lng), current);
      setRadius(Math.max(20, dist));
    },
    mouseup(e) {
      if (!drawing || !startRef.current) return;
      const start = startRef.current;
      const dist = map.distance(L.latLng(start.lat, start.lng), e.latlng);
      const finalRadius = Math.max(30, Math.min(dist, 500));
      onComplete(start, finalRadius);
      startRef.current = null;
      setCenter(null);
      setRadius(0);
      setDrawing(false);
      map.dragging.enable();
    },
  });

  if (!center || radius === 0) return null;

  return (
    <Circle
      center={[center.lat, center.lng]}
      radius={radius}
      pathOptions={{
        color: AOI_COLOR,
        fillColor: AOI_COLOR,
        fillOpacity: 0.15,
        weight: 2.5,
        dashArray: drawing ? "8 4" : undefined,
      }}
    />
  );
}

function MapController({ center, radius }: { center: LatLng; radius: number }) {
  const map = useMap();

  useEffect(() => {
    const delta = metersToLatLngDelta(radius * 2.5, center.lat);
    map.flyTo(
      [center.lat, center.lng],
      map.getBoundsZoom(
        L.latLngBounds(
          [center.lat - delta, center.lng - delta],
          [center.lat + delta, center.lng + delta]
        )
      ),
      { duration: 0.6 }
    );
  }, [center, radius, map]);

  return null;
}

function UserLocationMarker({ location }: { location: LatLng }) {
  return (
    <Circle
      center={[location.lat, location.lng]}
      radius={8}
      pathOptions={{
        color: "#fff",
        fillColor: "#4285F4",
        fillOpacity: 0.9,
        weight: 2,
      }}
    />
  );
}

function GeolocateController({
  location,
  hasFlown,
  onFlown,
}: {
  location: LatLng;
  hasFlown: boolean;
  onFlown: () => void;
}) {
  const map = useMap();

  useEffect(() => {
    if (!hasFlown) {
      map.flyTo([location.lat, location.lng], 17, { duration: 0.8 });
      onFlown();
    }
  }, [location, map, hasFlown, onFlown]);

  return null;
}

export default function MapAOISelector({
  onAOIChange,
  initialAOI = DEFAULT_AOI,
  userLocation = null,
}: MapAOISelectorProps) {
  const [aoi, setAoi] = useState<AOI | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [label, setLabel] = useState("");
  const [hasFlownToUser, setHasFlownToUser] = useState(false);

  const mapCenter = userLocation ?? initialAOI.center;

  const handleComplete = useCallback(
    (center: LatLng, radiusM: number) => {
      const newAOI: AOI = {
        id: `aoi-${Date.now()}`,
        center,
        radius_m: Math.round(radiusM),
        label: label || "Selected target",
      };
      setAoi(newAOI);
      onAOIChange(newAOI);
    },
    [label, onAOIChange]
  );

  function handleReset() {
    setAoi(null);
    setDrawing(false);
    onAOIChange(null);
  }

  function startDrawing() {
    setAoi(null);
    onAOIChange(null);
    setDrawing(true);
  }

  return (
    <div className="relative w-full h-full min-h-[480px] overflow-hidden border border-line">
      <MapContainer
        center={[mapCenter.lat, mapCenter.lng]}
        zoom={17}
        className="w-full h-full min-h-[480px]"
        zoomControl={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.esri.com/">Esri</a>'
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        />
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
          opacity={0.7}
        />

        {userLocation && !aoi && (
          <>
            <UserLocationMarker location={userLocation} />
            <GeolocateController
              location={userLocation}
              hasFlown={hasFlownToUser}
              onFlown={() => setHasFlownToUser(true)}
            />
          </>
        )}

        {aoi && (
          <>
            <Circle
              center={[aoi.center.lat, aoi.center.lng]}
              radius={aoi.radius_m}
              pathOptions={{
                color: AOI_COLOR,
                fillColor: AOI_COLOR,
                fillOpacity: 0.18,
                weight: 2.5,
              }}
            />
            <MapController center={aoi.center} radius={aoi.radius_m} />
          </>
        )}

        <CircleDrawer
          onComplete={handleComplete}
          drawing={drawing}
          setDrawing={setDrawing}
        />
      </MapContainer>

      <div className="absolute top-4 left-4 right-4 z-[1000] flex flex-col sm:flex-row gap-2 pointer-events-none">
        <div className="panel px-4 py-3 pointer-events-auto flex-1 max-w-sm">
          <p className="text-xs label-caps text-accent-ink mb-1">Area of interest</p>
          <p className="text-sm text-ink leading-snug">
            {drawing
              ? "Click and drag to set radius"
              : aoi
                ? `${aoi.radius_m}m radius · ${aoi.label}`
                : userLocation
                  ? "Draw a circle around the site to film"
                  : "Draw a circle around the site to film"}
          </p>
        </div>
      </div>

      <div className="absolute bottom-4 left-4 right-4 z-[1000] flex flex-col sm:flex-row gap-2 items-end pointer-events-none">

        <div className="flex gap-2 pointer-events-auto">
          {aoi && (
            <button
              onClick={handleReset}
              className="px-4 py-2.5 border border-line bg-panel-raised text-sm font-medium text-ink-muted hover:text-ink hover:border-line-strong transition-colors focus-ring"
            >
              Reset
            </button>
          )}
<button
  onClick={startDrawing}
  disabled={drawing}
  className={`px-5 py-2.5 text-sm font-medium transition-colors focus-ring ${
    drawing
      ? "bg-slate-200 text-slate-500 border border-slate-300 cursor-not-allowed"
      : "bg-white text-red-400 hover:bg-slate-100"
  }`}
>
  {drawing ? "Drawing…" : aoi ? "Redraw" : "Draw circle"}
</button>
        </div>
      </div>

      {drawing && (
        <div
          className="absolute inset-0 z-[999] cursor-crosshair"
          style={{ pointerEvents: "none" }}
        />
      )}
    </div>
  );
}
