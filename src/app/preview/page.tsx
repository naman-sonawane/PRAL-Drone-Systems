"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { PreviewCard } from "@/components/OptionCard";
import { GridSkeleton } from "@/components/LoadingSkeleton";
import { PrimaryButton } from "@/components/ProgressLoader";
import { api } from "@/lib/api";
import { getActiveMission, updateActiveMission } from "@/lib/storage";
import type { PreviewVariant } from "@/lib/types";
import { randomDelay } from "@/lib/utils";
import { ArrowRight, Play } from "lucide-react";

export default function PreviewPage() {
  const router = useRouter();
  const [previews, setPreviews] = useState<PreviewVariant[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [continuing, setContinuing] = useState(false);

  useEffect(() => {
    const mission = getActiveMission();
    if (!mission) {
      router.replace("/");
      return;
    }

    api
      .generatePreviews(
        mission.selected_clip_ids ?? [],
        mission.output_style ?? "listing_reel",
        mission.destination ?? "instagram"
      )
      .then((data) => {
        setPreviews(data);
        setSelectedId(data[0]?.id ?? null);
        setLoading(false);
      });
  }, [router]);

  const selectPreview = useCallback(async (id: string) => {
    setTogglingId(id);
    await randomDelay();
    setSelectedId(id);
    setTogglingId(null);
  }, []);

  async function handleExport() {
    if (!selectedId) return;
    setContinuing(true);
    await randomDelay(500, 900);
    updateActiveMission({ status: "exported", selected_preview_id: selectedId });
    router.push("/export");
  }

  return (
    <AuthGuard>
      <AppShell>
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-8"
          >
            <div className="flex items-center gap-2 text-pral-600 mb-2">
              <Play className="w-4 h-4" />
              <span className="text-sm font-medium">Rendered previews</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">
              Pick your cut
            </h1>
            <p className="text-muted mt-2 max-w-xl leading-relaxed">
              Multiple template variations rendered from your curated clips.
              Select the direction you want to ship.
            </p>
          </motion.div>

          {loading ? (
            <GridSkeleton count={3} />
          ) : (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
            >
              {previews.map((preview, i) => (
                <motion.div
                  key={preview.id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.08 }}
                >
                  <PreviewCard
                    title={preview.title}
                    duration={preview.duration_sec}
                    aspectRatio={preview.aspect_ratio}
                    gradient={`bg-gradient-to-br ${preview.thumbnail_gradient}`}
                    selected={selectedId === preview.id}
                    loading={togglingId === preview.id}
                    onClick={() => selectPreview(preview.id)}
                  />
                </motion.div>
              ))}
            </motion.div>
          )}

          <div className="mt-8 flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-sm text-muted">
              {selectedId
                ? `Selected: ${previews.find((p) => p.id === selectedId)?.title}`
                : "Select a preview to continue"}
            </p>
            <PrimaryButton
              loading={continuing}
              disabled={!selectedId || loading}
              onClick={handleExport}
            >
              Export media
              <ArrowRight className="w-4 h-4" />
            </PrimaryButton>
          </div>
        </div>
      </AppShell>
    </AuthGuard>
  );
}
