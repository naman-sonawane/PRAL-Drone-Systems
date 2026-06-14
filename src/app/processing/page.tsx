"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { ProgressLoader } from "@/components/ProgressLoader";
import { getActiveMission, updateActiveMission } from "@/lib/storage";
import { PROCESSING_STAGES } from "@/lib/types";

export default function ProcessingPage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(0);
  const [missionName, setMissionName] = useState("");

  useEffect(() => {
    const mission = getActiveMission();

    if (!mission) {
      router.replace("/");
      return;
    }

    setMissionName(mission.name);

    const timers: ReturnType<typeof setTimeout>[] = [];

    // Initial delay before processing starts
    let cumulativeDelay = 500;

    PROCESSING_STAGES.forEach((_, i) => {
      const isLastStage = i === PROCESSING_STAGES.length - 1;

      // Make stages take much longer with more randomness
      const stageDuration = isLastStage
        ? Math.floor(Math.random() * 5000) + 5000 // 5–10s
        : Math.floor(Math.random() * 3500) + 2000; // 2–5.5s

      const timer = setTimeout(() => {
        setCurrentStep(i);
        updateActiveMission({ progress_stage: i });
      }, cumulativeDelay);

      timers.push(timer);
      cumulativeDelay += stageDuration;
    });

    const doneTimer = setTimeout(() => {
      updateActiveMission({
        status: "clips_ready",
        progress_stage: PROCESSING_STAGES.length,
      });

      router.push("/clips");
    }, cumulativeDelay);

    timers.push(doneTimer);

    return () => {
      timers.forEach(clearTimeout);
    };
  }, [router]);

  return (
    <AuthGuard>
      <AppShell>
        <div className="max-w-lg mx-auto px-4 sm:px-6 py-16 sm:py-24">
          <ProgressLoader
            steps={PROCESSING_STAGES}
            currentStep={currentStep}
            title="Acquiring footage"
            subtitle={missionName || undefined}
          />
        </div>
      </AppShell>
    </AuthGuard>
  );
}