"use client";

import Image from "next/image";
import Link from "next/link";
import { motion, easeOut, type Variants } from "framer-motion";
import { AppShell } from "@/components/AppShell";

const staggerContainer: Variants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1,
    },
  },
};

const fadeUp: Variants = {
  hidden: {
    opacity: 0,
    y: 20,
  },
  show: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.6,
      ease: easeOut,
    },
  },
};

export default function LandingPage() {
  return (
    <AppShell
      showSteps={false}
      actions={
        <>
          <Link
            href="/login"
            className="text-sm font-medium text-ink hover:text-accent transition-colors"
          >
            Log In
          </Link>
          <Link
            href="/target"
            className="px-4 py-2 bg-accent text-white text-sm font-medium rounded-sm hover:bg-accent-hover transition-colors focus-ring"
          >
            Get Started
          </Link>
        </>
      }
    >
      <div className="selection:bg-accent selection:text-white">
        {/* Hero Section */}
        <section className="relative pt-20 pb-32 overflow-hidden">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 relative z-10">
            <motion.div
              variants={staggerContainer}
              initial="hidden"
              animate="show"
              className="max-w-3xl"
            >
              <motion.div variants={fadeUp} className="mb-6 flex items-center gap-3">
                <div className="h-px w-8 bg-accent" />
                <span className="font-heading uppercase tracking-[0.15em] text-accent text-sm font-bold">
                  Next-Gen Cinematography
                </span>
              </motion.div>
              <motion.h1
                variants={fadeUp}
                className="text-5xl sm:text-7xl font-heading tracking-tight text-ink mb-6"
              >
                Automate your <br className="hidden sm:block" />
                <span className="text-accent">drone surveys</span> & filming.
              </motion.h1>
              <motion.p
                variants={fadeUp}
                className="text-lg sm:text-xl text-ink-muted mb-10 max-w-2xl leading-relaxed"
              >
                Define a capture zone and let PRAL handle the rest. From automated flight paths to AI-driven clip curation, focus on the story while we manage the skies.
              </motion.p>
              <motion.div variants={fadeUp} className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
                <Link
                  href="/target"
                  className="px-8 py-4 bg-ink text-white font-medium rounded-sm hover:bg-ink-muted transition-colors focus-ring inline-flex items-center justify-center"
                >
                  Start Mission
                </Link>
                <Link
                  href="#features"
                  className="px-8 py-4 bg-panel border border-line text-ink font-medium rounded-sm hover:bg-line transition-colors focus-ring inline-flex items-center justify-center"
                >
                  Explore Features
                </Link>
              </motion.div>
            </motion.div>
          </div>

          {/* Drone Image Placeholder */}
          <motion.div
            initial={{ opacity: 0, x: 100 }}
            animate={{ opacity: 1, x: 0 }}
transition={{
  duration: 1,
  delay: 0.2,
  ease: easeOut,
}}            className="absolute top-1/2 -translate-y-1/2 right-0 w-1/2 h-[800px] hidden lg:block opacity-90 pointer-events-none"
          >
            <div className="relative w-full h-full">
              {/* Replace src with your actual drone image (e.g. /hero-drone.png) */}
              <div className="absolute inset-0 bg-gradient-to-r from-canvas to-transparent z-10" />
              <div className="w-full h-full border-2 border-dashed border-line flex flex-col items-center justify-center text-ink-muted bg-panel/30">
                <span className="font-heading uppercase tracking-widest text-xl">hero-drone.png</span>
                <span className="text-sm mt-2">Recommended: Transparent background, high-res drone render</span>
              </div>
            </div>
          </motion.div>
        </section>

        {/* Features Section */}
        <section id="features" className="py-24 bg-panel-raised border-y border-line relative">
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <motion.div
              initial="hidden"
              whileInView="show"
              viewport={{ once: true, margin: "-100px" }}
              variants={staggerContainer}
              className="grid grid-cols-1 md:grid-cols-3 gap-12"
            >
              {/* Feature 1 */}
              <motion.div variants={fadeUp} className="group cursor-default">
                <div className="w-12 h-12 bg-panel flex items-center justify-center border border-line rounded-sm mb-6 group-hover:border-accent transition-colors">
                  <svg className="w-6 h-6 text-ink group-hover:text-accent transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
                <h3 className="text-xl font-medium mb-3">Target Selection</h3>
                <p className="text-ink-muted leading-relaxed">
                  Pinpoint your subject on the map. Define the Area of Interest with precision to ensure optimal flight patterns and safety boundaries.
                </p>
              </motion.div>

              {/* Feature 2 */}
              <motion.div variants={fadeUp} className="group cursor-default">
                <div className="w-12 h-12 bg-panel flex items-center justify-center border border-line rounded-sm mb-6 group-hover:border-accent transition-colors">
                  <svg className="w-6 h-6 text-ink group-hover:text-accent transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <h3 className="text-xl font-medium mb-3">Automated Flight</h3>
                <p className="text-ink-muted leading-relaxed">
                  Our system generates optimal flight trajectories, capturing all necessary angles automatically without manual piloting required.
                </p>
              </motion.div>

              {/* Feature 3 */}
              <motion.div variants={fadeUp} className="group cursor-default">
                <div className="w-12 h-12 bg-panel flex items-center justify-center border border-line rounded-sm mb-6 group-hover:border-accent transition-colors">
                  <svg className="w-6 h-6 text-ink group-hover:text-accent transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z" />
                  </svg>
                </div>
                <h3 className="text-xl font-medium mb-3">AI Curation</h3>
                <p className="text-ink-muted leading-relaxed">
                  Raw footage is instantly processed. High-quality clips are identified, curated, and prepared for styling and export in minutes.
                </p>
              </motion.div>
            </motion.div>
          </div>
        </section>

        {/* Interface Preview Section */}
        <section className="py-32">
          <div className="max-w-7xl mx-auto px-4 sm:px-6">
            <motion.div
              initial="hidden"
              whileInView="show"
              viewport={{ once: true, margin: "-100px" }}
              variants={fadeUp}
              className="text-center mb-16"
            >
              <h2 className="text-4xl font-heading tracking-tight mb-4">Command the skies from your screen</h2>
              <p className="text-ink-muted text-lg max-w-2xl mx-auto">
                A streamlined, intuitive dashboard that puts complex aerial surveying into a simple, step-by-step workflow.
              </p>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-100px" }}
transition={{
  duration: 0.8,
  ease: easeOut,
}}              className="relative w-full max-w-5xl mx-auto aspect-video rounded-sm overflow-hidden border border-line shadow-2xl bg-panel"
            >
              {/* Replace with your actual interface mockup (e.g. /interface-mockup.png) */}
              <div className="w-full h-full border-2 border-dashed border-line-strong flex flex-col items-center justify-center text-ink-muted">
                <span className="font-heading uppercase tracking-widest text-2xl mb-2">interface-mockup.png</span>
                <span className="text-base">Recommended: 1920x1080 screenshot of the PRAL map interface</span>
              </div>
            </motion.div>
          </div>
        </section>

      {/* Footer */}
      <footer className="border-t border-line py-12 bg-panel-raised">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-3">
            <Image
              src="/logomark.png"
              alt="PRAL"
              width={24}
              height={24}
              className="opacity-50 grayscale"
            />
            <span className="text-sm font-medium text-ink-faint uppercase tracking-widest">
              PRAL Drone Systems
            </span>
          </div>
          <div className="text-sm text-ink-faint">
            &copy; {new Date().getFullYear()} PRAL. All rights reserved.
          </div>
        </div>
      </footer>
      </div>
    </AppShell>
  );
}
