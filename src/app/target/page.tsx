"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { MapAOISelectorWrapper } from "@/components/MapAOISelectorWrapper";
import { PageHeader } from "@/components/PageHeader";
import { PrimaryButton } from "@/components/ProgressLoader";
import { api } from "@/lib/api";
import { setActiveMission } from "@/lib/storage";
import type { AOI } from "@/lib/types";

export default function MissionPage() {
  const router = useRouter();
  const [aoi, setAoi] = useState<AOI | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Scroll down smoothly after page loads
    const timer = setTimeout(() => {
      window.scrollTo({
        top: 200,
        behavior: "smooth",
      });
    }, 600);
    return () => clearTimeout(timer);
  }, []);

  async function handleStartMission() {
    if (!aoi) return;
    setLoading(true);
    const mission = await api.createMission({
      ...aoi,
      label: aoi.label || "Untitled site",
    });
    setActiveMission({ ...mission, status: "processing" });
    router.push("/processing");
  }

  return (
    <AuthGuard>
      <AppShell>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
          <PageHeader
            step="01 Target"
            title="Select location"
            description="Define the capture zone on the map. PRAL handles survey, filming, and clip curation from there."
          />

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.08 }}
          >
            <MapAOISelectorWrapper onAOIChange={setAoi} />
          </motion.div>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.16 }}
            className="action-bar"
          >
            <p className="text-sm text-ink-muted">
              {aoi
                ? `${aoi.radius_m}m radius`
                : " "}
            </p>
            <PrimaryButton
              loading={loading}
              disabled={!aoi}
              onClick={handleStartMission}
            >
              Acquire
            </PrimaryButton>
          </motion.div>
        </div>
      </AppShell>
    </AuthGuard>
  );
}
