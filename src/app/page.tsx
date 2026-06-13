"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { MapAOISelectorWrapper } from "@/components/MapAOISelectorWrapper";
import { PrimaryButton } from "@/components/ProgressLoader";
import { api } from "@/lib/api";
import { setActiveMission } from "@/lib/storage";
import type { AOI } from "@/lib/types";
import { ArrowRight, Target } from "lucide-react";

export default function MissionPage() {
  const router = useRouter();
  const [aoi, setAoi] = useState<AOI | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleStartMission() {
    if (!aoi) return;
    setLoading(true);
    const mission = await api.createMission({
      ...aoi,
      label: aoi.label || "New target",
    });
    setActiveMission({ ...mission, status: "processing" });
    router.push("/processing");
  }

  return (
    <AuthGuard>
      <AppShell>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-8"
          >
            <div className="flex items-center gap-2 text-pral-600 mb-2">
              <Target className="w-4 h-4" />
              <span className="text-sm font-medium">New mission</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-semibold text-foreground tracking-tight">
              Select your target
            </h1>
            <p className="text-muted mt-2 max-w-xl leading-relaxed">
              Circle the building or location you want filmed. PRAL will survey,
              capture, and curate footage autonomously.
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
          >
            <MapAOISelectorWrapper onAOIChange={setAoi} />
          </motion.div>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.2 }}
            className="mt-8 flex flex-col sm:flex-row items-center justify-between gap-4"
          >
            <p className="text-sm text-muted">
              {aoi
                ? `Ready to film · ${aoi.radius_m}m capture radius`
                : "Draw a circle on the map to continue"}
            </p>
            <PrimaryButton
              loading={loading}
              disabled={!aoi}
              onClick={handleStartMission}
            >
              Start acquisition
              <ArrowRight className="w-4 h-4" />
            </PrimaryButton>
          </motion.div>
        </div>
      </AppShell>
    </AuthGuard>
  );
}
