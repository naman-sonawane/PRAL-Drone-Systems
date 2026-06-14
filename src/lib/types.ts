
import {
  FaInstagram,
  FaTiktok,
  FaYoutube,
  FaFacebook,
  FaLinkedin,
} from "react-icons/fa";
import { Globe } from "lucide-react";

// Core types matching VISION.md hand-off contract

export type ShotType =
  | "orbit"
  | "reveal"
  | "flyover"
  | "hero"
  | "establishing";

export type OutputStyle =
  | "listing_reel"
  | "social_vertical"
  | "hero_shot"
  | "overview";

export type Destination =
  | "instagram"
  | "tiktok"
  | "youtube"
  | "facebook"
  | "linkedin"
  | "website";

export type MissionStatus =
  | "draft"
  | "processing"
  | "clips_ready"
  | "creating"
  | "preview_ready"
  | "exported";

export interface LatLng {
  lat: number;
  lng: number;
}

export interface CameraPose {
  position: LatLng;
  altitude_m: number;
  heading_deg: number;
  pitch_deg: number;
}

export interface PointOfInterest {
  id: string;
  name: string;
  location: LatLng;
  salience: number;
  category: "architecture" | "entrance" | "greenery" | "water" | "facade" | "landmark";
}

export interface ClipQuality {
  stability: number;
  exposure: number;
  focus: number;
  framing: number;
}

export interface FootageClip {
  id: string;
  title: string;
  duration_sec: number;
  shot_type: ShotType;
  thumbnail_url: string;
  preview_color: string;
  pose: CameraPose;
  pois: PointOfInterest[];
  quality: ClipQuality;
  timestamp: string;
}

export interface AOI {
  id: string;
  center: LatLng;
  radius_m: number;
  label: string;
  overview_map_url?: string;
  boundary?: LatLng[];
}

export interface CuratedFootageSet {
  id: string;
  mission_id: string;
  aoi: AOI;
  clips: FootageClip[];
  captured_at: string;
  total_duration_sec: number;
}

export interface Mission {
  id: string;
  name: string;
  status: MissionStatus;
  aoi: AOI;
  created_at: string;
  updated_at: string;
  footage_set_id?: string;
  selected_clip_ids?: string[];
  selected_preview_id?: string;
  output_style?: OutputStyle;
  destination?: Destination;
  progress_stage?: number;
}

export interface PreviewVariant {
  id: string;
  style: OutputStyle;
  destination: Destination;
  title: string;
  duration_sec: number;
  aspect_ratio: string;
  thumbnail_gradient: string;
  clip_ids: string[];
}

export interface UserSession {
  email: string;
  name: string;
  logged_in_at: string;
}

export const OUTPUT_STYLE_LABELS: Record<OutputStyle, { label: string; description: string }> = {
  listing_reel: {
    label: "Listing Reel",
    description: "30–60s paced tour, music-ready",
  },
  social_vertical: {
    label: "Social Vertical",
    description: "9:16 hook-first short cut",
  },
  hero_shot: {
    label: "Hero Shot",
    description: "Single best continuous reveal",
  },
  overview: {
    label: "Overview",
    description: "Wide establishing → details",
  },
};

export const DESTINATION_LABELS = {
  instagram: { label: "Instagram", icon: FaInstagram },
  tiktok: { label: "TikTok", icon: FaTiktok },
  youtube: { label: "YouTube", icon: FaYoutube },
  facebook: { label: "Facebook", icon: FaFacebook },
  linkedin: { label: "LinkedIn", icon: FaLinkedin },
  website: { label: "Website", icon: Globe },
} satisfies Record<
  Destination,
  {
    label: string;
    icon: React.ComponentType<{ className?: string }>;
  }
>;

export const PROCESSING_STAGES = [
  { id: 1, label: "Survey ascent", description: "Capturing wide overview of AOI" },
  { id: 2, label: "Sampling paths", description: "Planning broad coverage trajectories" },
  { id: 3, label: "Sample capture", description: "Collecting reconnaissance footage" },
  { id: 4, label: "Scene analysis", description: "Detecting points of interest" },
  { id: 5, label: "Value optimization", description: "Designing production shot list" },
  { id: 6, label: "Final trajectory", description: "Compiling flyable flight plan" },
  { id: 7, label: "Production capture", description: "Capturing curated footage set" },
];
