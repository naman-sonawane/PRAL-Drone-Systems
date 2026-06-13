"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { ClipCard } from "@/components/OptionCard";
import { GridSkeleton } from "@/components/LoadingSkeleton";
import { PrimaryButton } from "@/components/ProgressLoader";
import { api } from "@/lib/api";
import { getActiveMission, updateActiveMission } from "@/lib/storage";
import type { FootageClip } from "@/lib/types";
import { randomDelay } from "@/lib/utils";
import { ArrowRight, Film } from "lucide-react";

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
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-8"
          >
            <div className="flex items-center gap-2 text-pral-600 mb-2">
              <Film className="w-4 h-4" />
              <span className="text-sm font-medium">Curated footage set</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">
              Review captured clips
            </h1>
            <p className="text-muted mt-2 max-w-xl leading-relaxed">
              Pipeline 1 complete. Select the clips to include in your finished
              media — or keep all for maximum coverage.
            </p>
          </motion.div>

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
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
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

          <div className="mt-8 flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-sm text-muted">
              {selectedIds.size} of {clips.length} clips selected
            </p>
            <PrimaryButton
              loading={continuing}
              disabled={selectedIds.size === 0 || loading}
              onClick={handleContinue}
            >
              Choose style & platform
              <ArrowRight className="w-4 h-4" />
            </PrimaryButton>
          </div>
        </div>
      </AppShell>
    </AuthGuard>
  );
}
