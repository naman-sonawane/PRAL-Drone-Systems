"use client";

import { motion, AnimatePresence } from "framer-motion";
import { Check } from "lucide-react";
import { clsx } from "clsx";

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

  return (
    <div className="max-w-md mx-auto w-full">
      <div className="text-center mb-8">
        <motion.div
          className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-pral-100 flex items-center justify-center"
          animate={{ scale: [1, 1.05, 1] }}
          transition={{ duration: 2, repeat: Infinity }}
        >
          <div className="w-8 h-8 border-3 border-pral-500 border-t-transparent rounded-full animate-spin" />
        </motion.div>
        <h2 className="text-xl font-semibold text-foreground">{title}</h2>
        {subtitle && <p className="text-sm text-muted mt-1">{subtitle}</p>}
      </div>

      <div className="mb-6">
        <div className="h-1.5 bg-border rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-pral-500 rounded-full"
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          />
        </div>
        <p className="text-xs text-muted mt-2 text-right">{Math.round(progress)}%</p>
      </div>

      <div className="space-y-2">
        <AnimatePresence mode="popLayout">
          {steps.map((step, i) => {
            const isComplete = i < currentStep;
            const isCurrent = i === currentStep;
            const isPending = i > currentStep;

            return (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className={clsx(
                  "flex items-start gap-3 p-3 rounded-xl transition-colors",
                  isCurrent && "bg-pral-50 border border-pral-200",
                  isComplete && "opacity-70",
                  isPending && "opacity-40"
                )}
              >
                <div
                  className={clsx(
                    "w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-0.5",
                    isComplete && "bg-pral-500 text-white",
                    isCurrent && "bg-pral-100 border-2 border-pral-500",
                    isPending && "bg-border"
                  )}
                >
                  {isComplete ? (
                    <Check className="w-3.5 h-3.5" />
                  ) : isCurrent ? (
                    <div className="w-2 h-2 rounded-full bg-pral-500 animate-pulse" />
                  ) : null}
                </div>
                <div>
                  <p className="text-sm font-medium text-foreground">{step.label}</p>
                  {step.description && (
                    <p className="text-xs text-muted mt-0.5">{step.description}</p>
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

interface SpinnerButtonProps {
  loading: boolean;
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
}

export function PrimaryButton({
  loading,
  children,
  className,
  onClick,
  disabled,
  type = "button",
}: SpinnerButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl",
        "bg-pral-600 text-white font-medium text-sm",
        "hover:bg-pral-700 active:bg-pral-800",
        "disabled:opacity-60 disabled:cursor-not-allowed",
        "transition-all duration-200 focus-ring shadow-sm",
        className
      )}
    >
      {loading && (
        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
      )}
      {children}
    </button>
  );
}
