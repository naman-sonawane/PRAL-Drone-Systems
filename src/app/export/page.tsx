"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { PrimaryButton } from "@/components/ProgressLoader";
import { api } from "@/lib/api";
import { clearActiveMission, getActiveMission } from "@/lib/storage";
import {
  DESTINATION_LABELS,
  OUTPUT_STYLE_LABELS,
  type Mission,
} from "@/lib/types";
import { CheckCircle2, Download, Plus, Share2 } from "lucide-react";

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
      setProgress((p) => Math.min(p + 8, 95));
    }, 200);

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

  function handleNewMission() {
    clearActiveMission();
    router.push("/");
  }

  const styleLabel = mission?.output_style
    ? OUTPUT_STYLE_LABELS[mission.output_style].label
    : "—";
  const destLabel = mission?.destination
    ? DESTINATION_LABELS[mission.destination].label
    : "—";

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
              <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-pral-100 flex items-center justify-center">
                <div className="w-10 h-10 border-3 border-pral-500 border-t-transparent rounded-full animate-spin" />
              </div>
              <h1 className="text-xl font-semibold mb-2">Exporting media</h1>
              <p className="text-sm text-muted mb-6">
                Rendering final {styleLabel} for {destLabel}…
              </p>
              <div className="h-2 bg-border rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-pral-500 rounded-full"
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
              <p className="text-xs text-muted mt-2">{progress}%</p>
            </motion.div>
          ) : (
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="text-center"
            >
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: "spring", delay: 0.1 }}
                className="w-20 h-20 mx-auto mb-6 rounded-full bg-emerald-100 flex items-center justify-center"
              >
                <CheckCircle2 className="w-10 h-10 text-emerald-600" />
              </motion.div>

              <h1 className="text-2xl font-semibold mb-2">Ready to ship</h1>
              <p className="text-muted mb-8 leading-relaxed">
                Your {styleLabel} has been exported for {destLabel}.
                Download the file or start a new mission.
              </p>

              <div className="glass rounded-2xl p-4 mb-8 text-left card-shadow">
                <p className="text-xs font-medium text-muted uppercase tracking-wide mb-2">
                  Export details
                </p>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted">File</span>
                    <span className="font-medium text-foreground">{filename}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Style</span>
                    <span className="font-medium">{styleLabel}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Platform</span>
                    <span className="font-medium">{destLabel}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Clips used</span>
                    <span className="font-medium">
                      {mission?.selected_clip_ids?.length ?? 0}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex flex-col sm:flex-row gap-3 justify-center">
                <PrimaryButton onClick={handleDownload}>
                  <Download className="w-4 h-4" />
                  Download MP4
                </PrimaryButton>
                <button
                  onClick={() => {}}
                  className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl border border-border text-sm font-medium text-foreground hover:bg-surface transition-colors focus-ring"
                >
                  <Share2 className="w-4 h-4" />
                  Share link
                </button>
              </div>

              <button
                onClick={handleNewMission}
                className="mt-8 inline-flex items-center gap-2 text-sm text-pral-600 hover:text-pral-700 font-medium transition-colors"
              >
                <Plus className="w-4 h-4" />
                Start new mission
              </button>
            </motion.div>
          )}
        </div>
      </AppShell>
    </AuthGuard>
  );
}
