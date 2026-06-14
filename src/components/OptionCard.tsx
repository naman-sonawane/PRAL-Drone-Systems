"use client";

import { clsx } from "clsx";
import { motion } from "framer-motion";
import type { ComponentType } from "react";

interface OptionCardProps {
  label: string;
  description?: string;
  icon?: ComponentType<{ className?: string }>;
  selected?: boolean;
  loading?: boolean;
  onClick?: () => void;
  aspect?: "square" | "wide" | "circle";
}

export function OptionCard({
  label,
  description,
  icon: Icon,
  selected,
  loading,
  onClick,
  aspect = "square",
}: OptionCardProps) {
  if (aspect === "circle") {
    return (
      <motion.button
        type="button"
        onClick={onClick}
        disabled={loading}
        title={label}
        whileTap={{ scale: 0.95 }}
        className={clsx(
          "relative flex items-center justify-center transition-colors duration-150 focus-ring rounded-full shrink-0",
          "w-14 h-14 sm:w-16 sm:h-16 border-2",
          selected
            ? "border-accent bg-accent-muted text-accent"
            : "border-line bg-panel-raised hover:border-line-strong hover:bg-panel text-ink",
          loading && "pointer-events-none"
        )}
      >
        {loading && (
          <div className="absolute inset-0 skeleton-shimmer z-10 rounded-full overflow-hidden" />
        )}
        {Icon && <Icon className="w-6 h-6 sm:w-7 sm:h-7" />}
        <span className="sr-only">{label}</span>
      </motion.button>
    );
  }

  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={loading}
      whileTap={{ scale: 0.995 }}
      className={clsx(
        "relative text-left border p-4 transition-colors duration-150 focus-ring",
        aspect === "wide" ? "flex items-center gap-4" : "flex flex-col",
        selected
          ? ""
          : "border-line bg-panel-raised hover:border-line-strong hover:bg-panel",
        loading && "pointer-events-none"
      )}
    >
      {loading && (
        <div className="absolute inset-0 skeleton-shimmer z-10" />
      )}

      {Icon && (
        <Icon className="shrink-0 w-6 h-6 text-ink" />
      )}

      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium text-sm text-ink">{label}</span>
          {selected && !loading && (
            <span className="text-[10px] label-caps text-accent shrink-0">
              Selected
            </span>
          )}
        </div>
        {description && (
          <p className="text-xs text-ink-muted mt-1.5 leading-relaxed">
            {description}
          </p>
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
      whileTap={{ scale: 0.995 }}
      className={clsx(
        "relative w-full text-left border overflow-hidden transition-colors focus-ring",
        selected
          ? "border-accent ring-1 ring-accent/20"
          : "border-line hover:border-line-strong"
      )}
    >
      <div className={clsx("h-36 bg-gradient-to-br relative", gradient)}>
        {loading ? (
          <div className="absolute inset-0 skeleton-shimmer" />
        ) : (
          <>
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-10 h-10 border border-white/40 flex items-center justify-center">
                <div className="w-0 h-0 border-t-[7px] border-t-transparent border-l-[12px] border-l-white border-b-[7px] border-b-transparent ml-0.5" />
              </div>
            </div>
            <div className="absolute top-0 right-0 px-2 py-1 bg-ink/70 text-white text-[11px] font-medium tabular-nums">
              {duration}s
            </div>
            {selected && (
              <div className="absolute top-0 left-0 px-2 py-1 bg-accent text-white text-[10px] label-caps">
                  ⠀
              </div>
            )}
          </>
        )}
      </div>
      <div className="p-3 bg-panel-raised border-t border-line">
        <p className="text-sm font-medium text-ink truncate">{title}</p>
        <div className="flex items-center justify-between mt-1">
          <span className="text-xs text-ink-muted capitalize">{shotType}</span>
          <span className="text-xs text-accent-ink font-medium tabular-nums">
            {Math.round(quality * 100)}%
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
      whileTap={{ scale: 0.995 }}
      className={clsx(
        "relative w-full text-left border overflow-hidden transition-colors focus-ring",
        selected
          ? "border-accent ring-1 ring-accent/20"
          : "border-line hover:border-line-strong"
      )}
    >
      <div className="p-4 bg-panel flex justify-center border-b border-line">
        <div
          className={clsx(
            "bg-gradient-to-br relative overflow-hidden",
            gradient,
            isVertical ? "w-24 h-44" : "w-full h-36"
          )}
        >
          {loading ? (
            <div className="absolute inset-0 skeleton-shimmer" />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-9 h-9 border border-white/40 flex items-center justify-center">
                <div className="w-0 h-0 border-t-[6px] border-t-transparent border-l-[10px] border-l-white border-b-[6px] border-b-transparent ml-0.5" />
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="px-4 py-3 bg-panel-raised">
        <p className="text-sm font-medium text-ink">{title}</p>
        <div className="flex items-center gap-2 mt-1 text-xs text-ink-muted tabular-nums">
          <span>{duration}</span>
          <span aria-hidden>·</span>
          <span>{aspectRatio}</span>
        </div>
      </div>
    </motion.button>
  );
}
