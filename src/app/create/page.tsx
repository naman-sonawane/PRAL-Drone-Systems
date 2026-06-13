"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Clapperboard,
  Film,
  Globe,
  Instagram,
  Layout,
  Linkedin,
  Monitor,
  Smartphone,
  Sparkles,
  Youtube,
} from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { OptionCard } from "@/components/OptionCard";
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
import { ArrowRight } from "lucide-react";

const STYLE_ICONS: Record<OutputStyle, React.ReactNode> = {
  listing_reel: <Film className="w-5 h-5" />,
  social_vertical: <Smartphone className="w-5 h-5" />,
  hero_shot: <Sparkles className="w-5 h-5" />,
  overview: <Layout className="w-5 h-5" />,
};

const DEST_ICONS: Record<Destination, React.ReactNode> = {
  instagram: <Instagram className="w-5 h-5" />,
  tiktok: <Monitor className="w-5 h-5" />,
  youtube: <Youtube className="w-5 h-5" />,
  facebook: <Globe className="w-5 h-5" />,
  linkedin: <Linkedin className="w-5 h-5" />,
  website: <Globe className="w-5 h-5" />,
};

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
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-10"
          >
            <div className="flex items-center gap-2 text-pral-600 mb-2">
              <Clapperboard className="w-4 h-4" />
              <span className="text-sm font-medium">Media processing</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">
              Style & destination
            </h1>
            <p className="text-muted mt-2 max-w-xl leading-relaxed">
              Pick how your footage should be assembled and where you plan to
              share it. PRAL will render matching previews.
            </p>
          </motion.div>

          <section className="mb-10">
            <h2 className="text-sm font-semibold text-foreground mb-4">
              Output style
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {(Object.keys(OUTPUT_STYLE_LABELS) as OutputStyle[]).map((key) => (
                <OptionCard
                  key={key}
                  label={OUTPUT_STYLE_LABELS[key].label}
                  description={OUTPUT_STYLE_LABELS[key].description}
                  icon={STYLE_ICONS[key]}
                  selected={style === key}
                  loading={loadingStyle === key}
                  onClick={() => selectStyle(key)}
                />
              ))}
            </div>
          </section>

          <section className="mb-10">
            <h2 className="text-sm font-semibold text-foreground mb-4">
              Destination
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {(Object.keys(DESTINATION_LABELS) as Destination[]).map((key) => (
                <OptionCard
                  key={key}
                  label={DESTINATION_LABELS[key].label}
                  icon={DEST_ICONS[key]}
                  selected={destination === key}
                  loading={loadingDest === key}
                  onClick={() => selectDestination(key)}
                  aspect="wide"
                />
              ))}
            </div>
          </section>

          <div className="flex justify-end">
            <PrimaryButton loading={generating} onClick={handleGenerate}>
              Generate previews
              <ArrowRight className="w-4 h-4" />
            </PrimaryButton>
          </div>
        </div>
      </AppShell>
    </AuthGuard>
  );
}
