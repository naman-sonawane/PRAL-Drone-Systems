"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { PrimaryButton, SecondaryButton } from "@/components/ProgressLoader";
import { api } from "@/lib/api";
import { clearActiveMission, getActiveMission } from "@/lib/storage";
import {
  DESTINATION_LABELS,
  OUTPUT_STYLE_LABELS,
  type Mission,
} from "@/lib/types";

export default function ExportPage() {
  const router = useRouter();
  const [mission, setMission] = useState<Mission | null>(null);
  const [exporting, setExporting] = useState(true);
  const [progress, setProgress] = useState(0);
  const [done, setDone] = useState(false);
  const [filename, setFilename] = useState("");

  useEffect(() => {
    const m = getActiveMission();
    if (!m) {
      router.replace("/");
      return;
    }
    setMission(m);

    const interval = setInterval(() => {
      setProgress((p) => Math.min(p + Math.random() * 5 + 2, 95));
    }, 600);

    api.exportMedia(m.selected_preview_id ?? "prev-1").then((result) => {
      clearInterval(interval);
      setProgress(100);
      setFilename(result.filename);
      setTimeout(() => {
        setExporting(false);
        setDone(true);
      }, 400);
    });

    return () => clearInterval(interval);
  }, [router]);

  function handleDownload() {
    const link = document.createElement("a");
    link.href = "#";
    link.download = filename;
    link.click();
  }

  function handleNewTarget() {
    clearActiveMission();
    router.push("/");
  }

  const styleLabel = mission?.output_style
    ? OUTPUT_STYLE_LABELS[mission.output_style].label
    : "-";
  const destLabel = mission?.destination
    ? DESTINATION_LABELS[mission.destination].label
    : "-";

  return (
    <AuthGuard>
      <AppShell showSteps={false}>
        <div className="max-w-lg mx-auto px-4 sm:px-6 py-16 sm:py-24">
          {exporting ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-center"
            >
              <div className="w-12 h-12 mx-auto mb-6 border border-line flex items-center justify-center">
                <div className="w-5 h-5 border-2 border-accent border-t-transparent animate-spin" />
              </div>
              <h1 className="text-xl font-medium mb-2">Exporting</h1>
              <p className="text-sm text-ink-muted mb-6">
                Rendering {styleLabel} for {destLabel}
              </p>
              <div className="h-1 bg-line overflow-hidden">
                <motion.div
                  className="h-full bg-accent"
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
              <p className="text-xs text-ink-faint mt-2 tabular-nums">
                {progress}%
              </p>
            </motion.div>
          ) : (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-center"
            >
              <p className="label-caps text-accent-ink mb-4">06 Export</p>
              <h1 className="text-2xl font-medium mb-2">Export complete</h1>
              <p className="text-ink-muted mb-8 leading-relaxed text-sm">
                {styleLabel} rendered for {destLabel}. Download the file or
                start over with a new location.
              </p>

              <div className="panel p-4 mb-8 text-left">
                <p className="text-xs label-caps text-ink-muted mb-3">
                  Details
                </p>
                <dl className="space-y-2 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt className="text-ink-muted">File</dt>
                    <dd className="font-medium text-ink text-right">{filename}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-ink-muted">Style</dt>
                    <dd className="font-medium">{styleLabel}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-ink-muted">Platform</dt>
                    <dd className="font-medium">{destLabel}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-ink-muted">Clips</dt>
                    <dd className="font-medium tabular-nums">
                      {mission?.selected_clip_ids?.length ?? 0}
                    </dd>
                  </div>
                </dl>
              </div>

              <div className="flex flex-col sm:flex-row gap-2 justify-center">
                <PrimaryButton onClick={handleDownload}>
                  Download MP4
                </PrimaryButton>
                <SecondaryButton onClick={() => {}}>
                  Copy link
                </SecondaryButton>
              </div>

              <button
                onClick={handleNewTarget}
                className="mt-8 text-sm text-ink-muted hover:text-accent transition-colors"
              >
                New location →
              </button>
            </motion.div>
          )}
        </div>
      </AppShell>
    </AuthGuard>
  );
}
