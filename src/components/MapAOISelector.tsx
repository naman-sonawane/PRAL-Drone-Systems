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
import { Circle as CircleIcon, MapPin, RotateCcw } from "lucide-react";
import type { AOI, LatLng } from "@/lib/types";
import { DEFAULT_AOI } from "@fixtures/index";

interface MapAOISelectorProps {
  onAOIChange: (aoi: AOI | null) => void;
  initialAOI?: AOI;
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
      const dist = map.distance(
        L.latLng(start.lat, start.lng),
        current
      );
      setRadius(Math.max(20, dist));
    },
    mouseup(e) {
      if (!drawing || !startRef.current) return;
      const start = startRef.current;
      const dist = map.distance(
        L.latLng(start.lat, start.lng),
        e.latlng
      );
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
        color: "#0c87e8",
        fillColor: "#0c87e8",
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
    map.flyTo([center.lat, center.lng], map.getBoundsZoom(
      L.latLngBounds(
        [center.lat - delta, center.lng - delta],
        [center.lat + delta, center.lng + delta]
      )
    ), { duration: 0.6 });
  }, [center, radius, map]);

  return null;
}

export default function MapAOISelector({
  onAOIChange,
  initialAOI = DEFAULT_AOI,
}: MapAOISelectorProps) {
  const [aoi, setAoi] = useState<AOI | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [label, setLabel] = useState("");

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
    <div className="relative w-full h-full min-h-[480px] rounded-2xl overflow-hidden border border-border card-shadow">
      <MapContainer
        center={[initialAOI.center.lat, initialAOI.center.lng]}
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

        {aoi && (
          <>
            <Circle
              center={[aoi.center.lat, aoi.center.lng]}
              radius={aoi.radius_m}
              pathOptions={{
                color: "#0c87e8",
                fillColor: "#0c87e8",
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

      {/* Floating controls */}
      <div className="absolute top-4 left-4 right-4 z-[1000] flex flex-col sm:flex-row gap-3 pointer-events-none">
        <div className="glass rounded-xl px-4 py-3 card-shadow pointer-events-auto flex-1 max-w-sm">
          <div className="flex items-center gap-2 text-pral-700 mb-1">
            <CircleIcon className="w-4 h-4" />
            <span className="text-sm font-medium">Circle to select target</span>
          </div>
          <p className="text-xs text-muted leading-relaxed">
            {drawing
              ? "Click and drag outward to draw your area of interest"
              : aoi
                ? `AOI: ${aoi.radius_m}m radius · ${aoi.label}`
                : "Draw a circle around the building or location to film"}
          </p>
        </div>
      </div>

      <div className="absolute bottom-4 left-4 right-4 z-[1000] flex flex-col sm:flex-row gap-3 items-end pointer-events-none">
        <div className="glass rounded-xl p-3 card-shadow pointer-events-auto flex-1 max-w-xs w-full">
          <label className="text-xs font-medium text-muted block mb-1.5">
            Target label
          </label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. Market Street Property"
            className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-white/90 focus:outline-none focus:ring-2 focus:ring-pral-500/30"
          />
        </div>

        <div className="flex gap-2 pointer-events-auto">
          {aoi && (
            <button
              onClick={handleReset}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl glass card-shadow text-sm font-medium text-muted hover:text-foreground transition-colors focus-ring"
            >
              <RotateCcw className="w-4 h-4" />
              Reset
            </button>
          )}
          <button
            onClick={startDrawing}
            disabled={drawing}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-all focus-ring ${
              drawing
                ? "bg-pral-100 text-pral-700 border-2 border-pral-400 border-dashed"
                : "bg-pral-600 text-white hover:bg-pral-700 shadow-sm"
            }`}
          >
            <MapPin className="w-4 h-4" />
            {drawing ? "Drawing…" : aoi ? "Redraw" : "Draw circle"}
          </button>
        </div>
      </div>

      {drawing && (
        <div className="absolute inset-0 z-[999] cursor-crosshair" style={{ pointerEvents: "none" }} />
      )}
    </div>
  );
}
