"use client";

import { motion } from "framer-motion";

interface PageHeaderProps {
  step?: string;
  title: string;
  description: string;
  className?: string;
}

export function PageHeader({
  step,
  title,
  description,
  className = "mb-8",
}: PageHeaderProps) {
  return (
    <motion.header
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={className}
    >
      {step && (
        <p className="label-caps text-accent-ink mb-3 font-medium">{step}</p>
      )}
      <h1 className="text-2xl sm:text-3xl lg:text-[2rem] font-medium leading-tight">
        {title}
      </h1>
      <p className="text-ink-muted mt-3 max-w-xl text-[15px] leading-relaxed">
        {description}
      </p>
      <div className="mt-6 h-px w-full max-w-md bg-line" aria-hidden />
    </motion.header>
  );
}
