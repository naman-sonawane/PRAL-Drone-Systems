import type {
  AOI,
  CuratedFootageSet,
  FootageClip,
  Mission,
  PointOfInterest,
  PreviewVariant,
} from "@/lib/types";

const DEFAULT_CENTER = { lat: 37.7749, lng: -122.4194 };

const POIS: PointOfInterest[] = [
  {
    id: "poi-1",
    name: "Main facade",
    location: { lat: 37.7752, lng: -122.4198 },
    salience: 0.94,
    category: "facade",
  },
  {
    id: "poi-2",
    name: "Grand entrance",
    location: { lat: 37.7747, lng: -122.4192 },
    salience: 0.88,
    category: "entrance",
  },
  {
    id: "poi-3",
    name: "Rooftop garden",
    location: { lat: 37.7755, lng: -122.4188 },
    salience: 0.76,
    category: "greenery",
  },
  {
    id: "poi-4",
    name: "Courtyard fountain",
    location: { lat: 37.7744, lng: -122.4201 },
    salience: 0.71,
    category: "water",
  },
];

export const DEFAULT_AOI: AOI = {
  id: "aoi-default",
  center: DEFAULT_CENTER,
  radius_m: 120,
  label: "Market Street Property",
};

export const MOCK_CLIPS: FootageClip[] = [
  {
    id: "clip-1",
    title: "Facade orbit — golden hour",
    duration_sec: 18,
    shot_type: "orbit",
    thumbnail_url: "/thumbnails/orbit.jpg",
    preview_color: "from-amber-500/80 to-orange-600/80",
    pose: {
      position: { lat: 37.7752, lng: -122.4198 },
      altitude_m: 45,
      heading_deg: 210,
      pitch_deg: -25,
    },
    pois: [POIS[0], POIS[1]],
    quality: { stability: 0.96, exposure: 0.92, focus: 0.94, framing: 0.91 },
    timestamp: "2026-06-13T16:42:00Z",
  },
  {
    id: "clip-2",
    title: "Entrance reveal",
    duration_sec: 12,
    shot_type: "reveal",
    thumbnail_url: "/thumbnails/reveal.jpg",
    preview_color: "from-sky-500/80 to-blue-600/80",
    pose: {
      position: { lat: 37.7747, lng: -122.4192 },
      altitude_m: 28,
      heading_deg: 180,
      pitch_deg: -18,
    },
    pois: [POIS[1]],
    quality: { stability: 0.93, exposure: 0.89, focus: 0.91, framing: 0.95 },
    timestamp: "2026-06-13T16:44:00Z",
  },
  {
    id: "clip-3",
    title: "Rooftop flyover",
    duration_sec: 22,
    shot_type: "flyover",
    thumbnail_url: "/thumbnails/flyover.jpg",
    preview_color: "from-emerald-500/80 to-teal-600/80",
    pose: {
      position: { lat: 37.7755, lng: -122.4188 },
      altitude_m: 55,
      heading_deg: 45,
      pitch_deg: -35,
    },
    pois: [POIS[2]],
    quality: { stability: 0.91, exposure: 0.94, focus: 0.88, framing: 0.87 },
    timestamp: "2026-06-13T16:46:00Z",
  },
  {
    id: "clip-4",
    title: "Establishing wide",
    duration_sec: 15,
    shot_type: "establishing",
    thumbnail_url: "/thumbnails/establishing.jpg",
    preview_color: "from-violet-500/80 to-purple-600/80",
    pose: {
      position: { lat: 37.7749, lng: -122.4194 },
      altitude_m: 80,
      heading_deg: 0,
      pitch_deg: -45,
    },
    pois: POIS,
    quality: { stability: 0.97, exposure: 0.95, focus: 0.93, framing: 0.9 },
    timestamp: "2026-06-13T16:48:00Z",
  },
  {
    id: "clip-5",
    title: "Hero descent",
    duration_sec: 20,
    shot_type: "hero",
    thumbnail_url: "/thumbnails/hero.jpg",
    preview_color: "from-rose-500/80 to-pink-600/80",
    pose: {
      position: { lat: 37.7750, lng: -122.4196 },
      altitude_m: 60,
      heading_deg: 135,
      pitch_deg: -30,
    },
    pois: [POIS[0], POIS[3]],
    quality: { stability: 0.94, exposure: 0.91, focus: 0.96, framing: 0.93 },
    timestamp: "2026-06-13T16:50:00Z",
  },
  {
    id: "clip-6",
    title: "Courtyard orbit",
    duration_sec: 16,
    shot_type: "orbit",
    thumbnail_url: "/thumbnails/courtyard.jpg",
    preview_color: "from-cyan-500/80 to-blue-500/80",
    pose: {
      position: { lat: 37.7744, lng: -122.4201 },
      altitude_m: 35,
      heading_deg: 270,
      pitch_deg: -22,
    },
    pois: [POIS[3]],
    quality: { stability: 0.9, exposure: 0.87, focus: 0.89, framing: 0.88 },
    timestamp: "2026-06-13T16:52:00Z",
  },
];

export const MOCK_FOOTAGE_SET: CuratedFootageSet = {
  id: "cfs-001",
  mission_id: "mission-001",
  aoi: DEFAULT_AOI,
  clips: MOCK_CLIPS,
  captured_at: "2026-06-13T16:52:00Z",
  total_duration_sec: MOCK_CLIPS.reduce((sum, c) => sum + c.duration_sec, 0),
};

export const MOCK_MISSION: Mission = {
  id: "mission-001",
  name: "Market Street Property",
  status: "draft",
  aoi: DEFAULT_AOI,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

export const MOCK_PREVIEWS: PreviewVariant[] = [
  {
    id: "prev-1",
    style: "listing_reel",
    destination: "instagram",
    title: "Listing Reel — Market Street",
    duration_sec: 45,
    aspect_ratio: "16:9",
    thumbnail_gradient: "from-amber-500 to-orange-600",
    clip_ids: ["clip-1", "clip-2", "clip-4", "clip-5"],
  },
  {
    id: "prev-2",
    style: "social_vertical",
    destination: "tiktok",
    title: "Vertical Hook — Facade Reveal",
    duration_sec: 22,
    aspect_ratio: "9:16",
    thumbnail_gradient: "from-sky-500 to-blue-600",
    clip_ids: ["clip-2", "clip-5"],
  },
  {
    id: "prev-3",
    style: "hero_shot",
    destination: "youtube",
    title: "Hero Descent — Full Reveal",
    duration_sec: 20,
    aspect_ratio: "16:9",
    thumbnail_gradient: "from-rose-500 to-pink-600",
    clip_ids: ["clip-5"],
  },
  {
    id: "prev-4",
    style: "overview",
    destination: "website",
    title: "Overview Cut — Full Property",
    duration_sec: 38,
    aspect_ratio: "16:9",
    thumbnail_gradient: "from-violet-500 to-purple-600",
    clip_ids: ["clip-4", "clip-3", "clip-1", "clip-6"],
  },
];

export function createMissionFromAOI(aoi: AOI): Mission {
  return {
    id: `mission-${Date.now()}`,
    name: aoi.label || "New Mission",
    status: "draft",
    aoi,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

export function getFootageSetForMission(missionId: string, aoi: AOI): CuratedFootageSet {
  return {
    ...MOCK_FOOTAGE_SET,
    id: `cfs-${missionId}`,
    mission_id: missionId,
    aoi,
  };
}
