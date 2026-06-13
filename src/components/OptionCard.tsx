"use client";

import { clsx } from "clsx";
import { motion } from "framer-motion";
import { Check } from "lucide-react";

interface OptionCardProps {
  label: string;
  description?: string;
  icon?: React.ReactNode;
  selected?: boolean;
  loading?: boolean;
  onClick?: () => void;
  aspect?: "square" | "wide";
}

export function OptionCard({
  label,
  description,
  icon,
  selected,
  loading,
  onClick,
  aspect = "square",
}: OptionCardProps) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={loading}
      whileTap={{ scale: 0.98 }}
      className={clsx(
        "relative text-left rounded-2xl border-2 p-4 transition-all duration-200 focus-ring",
        aspect === "wide" ? "flex items-center gap-4" : "flex flex-col",
        selected
          ? "border-pral-500 bg-pral-50/80 card-shadow"
          : "border-border bg-surface-elevated hover:border-pral-300 hover:bg-pral-50/30",
        loading && "pointer-events-none"
      )}
    >
      {loading && (
        <div className="absolute inset-0 rounded-2xl skeleton-shimmer z-10" />
      )}

      {icon && (
        <div
          className={clsx(
            "flex items-center justify-center rounded-xl bg-pral-100 text-pral-600 shrink-0",
            aspect === "wide" ? "w-12 h-12" : "w-10 h-10 mb-3"
          )}
        >
          {icon}
        </div>
      )}

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm text-foreground">{label}</span>
          {selected && !loading && (
            <Check className="w-4 h-4 text-pral-600 shrink-0" />
          )}
        </div>
        {description && (
          <p className="text-xs text-muted mt-1 leading-relaxed">{description}</p>
        )}
      </div>
    </motion.button>
  );
}

interface ClipCardProps {
  title: string;
  duration: number;
  shotType: string;
  gradient: string;
  quality: number;
  selected?: boolean;
  loading?: boolean;
  onClick?: () => void;
}

export function ClipCard({
  title,
  duration,
  shotType,
  gradient,
  quality,
  selected,
  loading,
  onClick,
}: ClipCardProps) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={loading}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.98 }}
      className={clsx(
        "relative w-full text-left rounded-2xl border-2 overflow-hidden transition-all focus-ring",
        selected ? "border-pral-500 card-shadow" : "border-border hover:border-pral-300"
      )}
    >
      <div className={clsx("h-36 bg-gradient-to-br relative", gradient)}>
        {loading ? (
          <div className="absolute inset-0 skeleton-shimmer" />
        ) : (
          <>
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-12 h-12 rounded-full bg-white/20 backdrop-blur flex items-center justify-center">
                <div className="w-0 h-0 border-t-[8px] border-t-transparent border-l-[14px] border-l-white border-b-[8px] border-b-transparent ml-1" />
              </div>
            </div>
            <div className="absolute top-3 right-3 px-2 py-0.5 rounded-full bg-black/40 text-white text-xs font-medium">
              {duration}s
            </div>
            {selected && (
              <div className="absolute top-3 left-3 w-6 h-6 rounded-full bg-pral-500 flex items-center justify-center">
                <Check className="w-3.5 h-3.5 text-white" />
              </div>
            )}
          </>
        )}
      </div>
      <div className="p-3 bg-surface-elevated">
        <p className="text-sm font-medium text-foreground truncate">{title}</p>
        <div className="flex items-center justify-between mt-1">
          <span className="text-xs text-muted capitalize">{shotType}</span>
          <span className="text-xs text-pral-600 font-medium">
            {Math.round(quality * 100)}% quality
          </span>
        </div>
      </div>
    </motion.button>
  );
}

interface PreviewCardProps {
  title: string;
  duration: number;
  aspectRatio: string;
  gradient: string;
  selected?: boolean;
  loading?: boolean;
  onClick?: () => void;
}

export function PreviewCard({
  title,
  duration,
  aspectRatio,
  gradient,
  selected,
  loading,
  onClick,
}: PreviewCardProps) {
  const isVertical = aspectRatio === "9:16";

  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={loading}
      whileHover={{ y: -2 }}
      className={clsx(
        "relative w-full text-left rounded-2xl border-2 overflow-hidden transition-all focus-ring",
        selected ? "border-pral-500 card-shadow" : "border-border hover:border-pral-300"
      )}
    >
      <div className="p-4 bg-surface-elevated flex justify-center">
        <div
          className={clsx(
            "bg-gradient-to-br rounded-xl relative overflow-hidden",
            gradient,
            isVertical ? "w-24 h-44" : "w-full h-36"
          )}
        >
          {loading ? (
            <div className="absolute inset-0 skeleton-shimmer" />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-10 h-10 rounded-full bg-white/25 backdrop-blur flex items-center justify-center">
                <div className="w-0 h-0 border-t-[6px] border-t-transparent border-l-[10px] border-l-white border-b-[6px] border-b-transparent ml-0.5" />
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="px-4 pb-4 bg-surface-elevated">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-xs text-muted">{duration}s</span>
          <span className="text-xs text-muted">·</span>
          <span className="text-xs text-muted">{aspectRatio}</span>
        </div>
      </div>
    </motion.button>
  );
}
