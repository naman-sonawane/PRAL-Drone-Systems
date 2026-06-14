"use client";

import { motion, AnimatePresence } from "framer-motion";
import { clsx } from "clsx";
import { useEffect, useRef } from "react";

interface Step {
  id: number | string;
  label: string;
  description?: string;
}

interface ProgressLoaderProps {
  steps: Step[];
  currentStep: number;
  title?: string;
  subtitle?: string;
}

export function ProgressLoader({
  steps,
  currentStep,
  title = "Processing",
  subtitle,
}: ProgressLoaderProps) {
  const progress = Math.min(100, ((currentStep + 1) / steps.length) * 100);
  const stepsContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (stepsContainerRef.current) {
      const container = stepsContainerRef.current;
      const currentStepElement = container.children[currentStep] as HTMLElement;
      
      if (currentStepElement) {
        setTimeout(() => {
          currentStepElement.scrollIntoView({
            behavior: "smooth",
            block: "nearest",
          });
        }, 100);
      }
    }
  }, [currentStep]);

  return (
    <div className="max-w-md mx-auto w-full">
      <div className="text-center mb-8">
        <div className="w-12 h-12 mx-auto mb-5 border border-line flex items-center justify-center">
          <div className="w-5 h-5 border-2 border-accent border-t-transparent animate-spin" />
        </div>
        <h2 className="text-xl font-medium text-ink">{title}</h2>
        {subtitle && (
          <p className="text-sm text-ink-muted mt-1.5">{subtitle}</p>
        )}
      </div>

      <div className="mb-6">
        <div className="h-1 bg-line overflow-hidden">
          <motion.div
            className="h-full bg-accent"
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          />
        </div>
        <p className="text-xs text-ink-faint mt-2 text-right tabular-nums">
          {Math.round(progress)}%
        </p>
      </div>

      <div 
        ref={stepsContainerRef}
        className="space-y-0 border border-line divide-y divide-line max-h-96 overflow-y-auto"
      >
        <AnimatePresence mode="popLayout">
          {steps.map((step, i) => {
            const isComplete = i < currentStep;
            const isCurrent = i === currentStep;
            const isPending = i > currentStep;

            return (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04 }}
                className={clsx(
                  "flex items-start gap-3 px-4 py-3 transition-colors",
                  isCurrent && "bg-accent-muted",
                  isComplete && "opacity-80",
                  isPending && "opacity-45"
                )}
              >
                <span
                  className={clsx(
                    "w-5 h-5 shrink-0 mt-0.5 flex items-center justify-center text-[10px] font-medium tabular-nums border",
                    isComplete && "bg-accent text-white border-accent",
                    isCurrent && "border-accent text-accent bg-panel-raised",
                    isPending && "border-line text-ink-faint bg-panel"
                  )}
                >
                  {isComplete ? "✓" : i + 1}
                </span>
                <div>
                  <p className="text-sm font-medium text-ink">{step.label}</p>
                  {step.description && (
                    <p className="text-xs text-ink-muted mt-0.5">
                      {step.description}
                    </p>
                  )}
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}

interface ButtonProps {
  loading?: boolean;
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
}

export function PrimaryButton({
  loading = false,
  children,
  className,
  onClick,
  disabled,
  type = "button",
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-2 px-5 py-2.5",
        "bg-accent text-white text-sm font-medium",
        "hover:bg-accent-hover active:bg-accent-ink",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "transition-colors duration-150 focus-ring",
        className
      )}
    >
      {loading && (
        <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white animate-spin" />
      )}
      {children}
    </button>
  );
}

export function SecondaryButton({
  loading = false,
  children,
  className,
  onClick,
  disabled,
  type = "button",
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-2 px-5 py-2.5",
        "border border-line-strong bg-panel-raised text-ink text-sm font-medium",
        "hover:border-ink-faint hover:bg-panel",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "transition-colors duration-150 focus-ring",
        className
      )}
    >
      {loading && (
        <div className="w-3.5 h-3.5 border-2 border-ink-faint border-t-ink animate-spin" />
      )}
      {children}
    </button>
  );
}
