/**
 * Mock API layer — swap implementations here when connecting to a real backend.
 */
import {
  createMissionFromAOI,
  getFootageSetForMission,
  MOCK_CLIPS,
  MOCK_PREVIEWS,
} from "@fixtures/index";
import type {
  AOI,
  CuratedFootageSet,
  Destination,
  FootageClip,
  Mission,
  OutputStyle,
  PreviewVariant,
} from "@/lib/types";
import { PROCESSING_STAGES } from "@/lib/types";
import { randomDelay, delay } from "@/lib/utils";

export interface ApiClient {
  createMission(aoi: AOI): Promise<Mission>;
  startProcessing(missionId: string): Promise<{ stages: typeof PROCESSING_STAGES }>;
  getFootageSet(missionId: string, aoi: AOI): Promise<CuratedFootageSet>;
  getClips(missionId: string): Promise<FootageClip[]>;
  generatePreviews(
    clipIds: string[],
    style: OutputStyle,
    destination: Destination
  ): Promise<PreviewVariant[]>;
  exportMedia(previewId: string): Promise<{ downloadUrl: string; filename: string }>;
}

class MockApiClient implements ApiClient {
  async createMission(aoi: AOI): Promise<Mission> {
    await randomDelay(400, 600);
    return createMissionFromAOI(aoi);
  }

  async startProcessing(_missionId: string) {
    await delay(500);
    return { stages: PROCESSING_STAGES };
  }

  async getFootageSet(missionId: string, aoi: AOI): Promise<CuratedFootageSet> {
    await randomDelay(500, 700);
    return getFootageSetForMission(missionId, aoi);
  }

  async getClips(_missionId: string): Promise<FootageClip[]> {
    await randomDelay(400, 700);
    return MOCK_CLIPS;
  }

  async generatePreviews(
    clipIds: string[],
    style: OutputStyle,
    destination: Destination
  ): Promise<PreviewVariant[]> {
    await randomDelay(600, 800);
    const primary = MOCK_PREVIEWS.find(
      (p) => p.style === style && p.destination === destination
    );
    const fallback = MOCK_PREVIEWS.find((p) => p.style === style);
    const base = primary ?? fallback ?? MOCK_PREVIEWS[0];
    return [
      { ...base, clip_ids: clipIds.length > 0 ? clipIds : base.clip_ids },
      ...MOCK_PREVIEWS.filter((p) => p.id !== base.id).slice(0, 2),
    ];
  }

  async exportMedia(previewId: string) {
    await randomDelay(800, 1200);
    const preview = MOCK_PREVIEWS.find((p) => p.id === previewId) ?? MOCK_PREVIEWS[0];
    return {
      downloadUrl: "#",
      filename: `${preview.title.toLowerCase().replace(/\s+/g, "-")}.mp4`,
    };
  }
}

export const api: ApiClient = new MockApiClient();
