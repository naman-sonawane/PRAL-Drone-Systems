"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { OptionCard } from "@/components/OptionCard";
import { PageHeader } from "@/components/PageHeader";
import { PrimaryButton } from "@/components/ProgressLoader";
import { api } from "@/lib/api";
import { getActiveMission, updateActiveMission } from "@/lib/storage";
import {
  DESTINATION_LABELS,
  OUTPUT_STYLE_LABELS,
  type Destination,
  type OutputStyle,
} from "@/lib/types";
import { randomDelay } from "@/lib/utils";

export default function CreatePage() {
  const router = useRouter();
  const [style, setStyle] = useState<OutputStyle>("listing_reel");
  const [destination, setDestination] = useState<Destination>("instagram");
  const [loadingStyle, setLoadingStyle] = useState<OutputStyle | null>(null);
  const [loadingDest, setLoadingDest] = useState<Destination | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    const mission = getActiveMission();
    if (!mission) {
      router.replace("/");
      return;
    }
    if (mission.output_style) setStyle(mission.output_style);
    if (mission.destination) setDestination(mission.destination);
  }, [router]);

  const selectStyle = useCallback(async (s: OutputStyle) => {
    setLoadingStyle(s);
    await randomDelay();
    setStyle(s);
    updateActiveMission({ output_style: s });
    setLoadingStyle(null);
  }, []);

  const selectDestination = useCallback(async (d: Destination) => {
    setLoadingDest(d);
    await randomDelay();
    setDestination(d);
    updateActiveMission({ destination: d });
    setLoadingDest(null);
  }, []);

  async function handleGenerate() {
    setGenerating(true);
    const mission = getActiveMission();
    if (!mission) return;

    await api.generatePreviews(
      mission.selected_clip_ids ?? [],
      style,
      destination
    );

    updateActiveMission({
      status: "preview_ready",
      output_style: style,
      destination,
    });
    router.push("/preview");
  }

  return (
    <AuthGuard>
      <AppShell>
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
          <PageHeader
            step="04 Style"
            title="Output settings"
            description="Choose an edit style and destination. PRAL will render matching preview cuts."
            className="mb-10"
          />

          <section className="mb-10">
            <h2 className="section-label">Edit style</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {(Object.keys(OUTPUT_STYLE_LABELS) as OutputStyle[]).map((key) => (
                <OptionCard
                  key={key}
                  label={OUTPUT_STYLE_LABELS[key].label}
                  description={OUTPUT_STYLE_LABELS[key].description}
                  selected={style === key}
                  loading={loadingStyle === key}
                  onClick={() => selectStyle(key)}
                />
              ))}
            </div>
          </section>

          <section className="mb-10">
            <h2 className="section-label">Destination</h2>
            <div className="flex flex-wrap gap-4">
              {(Object.keys(DESTINATION_LABELS) as Destination[]).map((key) => (
                <OptionCard
                  key={key}
                  label={DESTINATION_LABELS[key].label}
                  icon={DESTINATION_LABELS[key].icon}
                  selected={destination === key}
                  loading={loadingDest === key}
                  onClick={() => selectDestination(key)}
                  aspect="circle"
                />
              ))}
            </div>
          </section>

          <div className="flex justify-end">
            <PrimaryButton loading={generating} onClick={handleGenerate}>
              Render previews
            </PrimaryButton>
          </div>
        </div>
      </AppShell>
    </AuthGuard>
  );
}
