"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { ClipCard } from "@/components/OptionCard";
import { GridSkeleton } from "@/components/LoadingSkeleton";
import { PageHeader } from "@/components/PageHeader";
import { PrimaryButton } from "@/components/ProgressLoader";
import { api } from "@/lib/api";
import { getActiveMission, updateActiveMission } from "@/lib/storage";
import type { FootageClip } from "@/lib/types";
import { randomDelay } from "@/lib/utils";

export default function ClipsPage() {
  const router = useRouter();
  const [clips, setClips] = useState<FootageClip[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [continuing, setContinuing] = useState(false);

  useEffect(() => {
    const mission = getActiveMission();
    if (!mission) {
      router.replace("/");
      return;
    }

    api.getClips(mission.id).then((data) => {
      setClips(data);
      setSelectedIds(new Set(data.map((c) => c.id)));
      setLoading(false);
    });
  }, [router]);

  const toggleClip = useCallback(async (id: string) => {
    setTogglingId(id);
    await randomDelay();
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setTogglingId(null);
  }, []);

  async function handleContinue() {
    setContinuing(true);
    await randomDelay(500, 900);
    updateActiveMission({
      selected_clip_ids: Array.from(selectedIds),
      status: "creating",
    });
    router.push("/create");
  }

  const avgQuality = (clip: FootageClip) => {
    const q = clip.quality;
    return (q.stability + q.exposure + q.focus + q.framing) / 4;
  };

  return (
    <AuthGuard>
      <AppShell>
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
          <PageHeader
            step="03 Clips"
            title="Review footage"
            description="Acquisition complete. Choose which clips to include in the final edit."
          />

          {loading ? (
            <GridSkeleton count={6} />
          ) : (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
            >
              {clips.map((clip, i) => (
                <motion.div
                  key={clip.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.04 }}
                >
                  <ClipCard
                    title={clip.title}
                    duration={clip.duration_sec}
                    shotType={clip.shot_type}
                    gradient={clip.preview_color}
                    quality={avgQuality(clip)}
                    selected={selectedIds.has(clip.id)}
                    loading={togglingId === clip.id}
                    onClick={() => toggleClip(clip.id)}
                  />
                </motion.div>
              ))}
            </motion.div>
          )}

          <div className="action-bar">
            <p className="text-sm text-ink-muted tabular-nums">
              {selectedIds.size} of {clips.length} selected
            </p>
            <PrimaryButton
              loading={continuing}
              disabled={selectedIds.size === 0 || loading}
              onClick={handleContinue}
            >
              Configure output
            </PrimaryButton>
          </div>
        </div>
      </AppShell>
    </AuthGuard>
  );
}
