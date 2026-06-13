"use client";

import dynamic from "next/dynamic";
import type { AOI } from "@/lib/types";
import { DEFAULT_AOI } from "@fixtures/index";
import { Skeleton } from "./LoadingSkeleton";

const MapAOISelector = dynamic(() => import("./MapAOISelector"), {
  ssr: false,
  loading: () => (
    <div className="w-full min-h-[480px] rounded-2xl border border-border overflow-hidden">
      <Skeleton className="w-full h-[480px] rounded-2xl" />
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
  return <MapAOISelector onAOIChange={onAOIChange} initialAOI={initialAOI} />;
}
