"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { AOI, LatLng } from "@/lib/types";
import { DEFAULT_AOI } from "@fixtures/index";
import { Skeleton } from "./LoadingSkeleton";

const MapAOISelector = dynamic(() => import("./MapAOISelector"), {
  ssr: false,
  loading: () => (
    <div className="w-full min-h-[480px] border border-line overflow-hidden">
      <Skeleton className="w-full h-[480px]" />
    </div>
  ),
});

export function MapAOISelectorWrapper({
  onAOIChange,
  initialAOI = DEFAULT_AOI,
}: {
  onAOIChange: (aoi: AOI | null) => void;
  initialAOI?: AOI;
}) {
  const [userLocation, setUserLocation] = useState<LatLng | null>(null);
  const [geoReady, setGeoReady] = useState(false);

  useEffect(() => {
    if (!navigator.geolocation) {
      setGeoReady(true);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        setUserLocation({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        });
        setGeoReady(true);
      },
      () => setGeoReady(true),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
  }, []);

  if (!geoReady) {
    return (
      <div className="w-full min-h-[480px] border border-line overflow-hidden">
        <Skeleton className="w-full h-[480px]" />
      </div>
    );
  }

  return (
    <MapAOISelector
      onAOIChange={onAOIChange}
      initialAOI={initialAOI}
      userLocation={userLocation}
    />
  );
}
