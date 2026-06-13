"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Radio, ArrowRight } from "lucide-react";
import { login } from "@/lib/auth";
import { PrimaryButton } from "@/components/ProgressLoader";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    await new Promise((r) => setTimeout(r, 600));
    login(email || "demo@pral.io", password);
    router.push("/");
  }

  return (
    <div className="min-h-screen flex">
      <div className="hidden lg:flex flex-1 bg-gradient-to-br from-pral-950 via-pral-900 to-pral-800 p-12 flex-col justify-between relative overflow-hidden">
        <div className="absolute inset-0 opacity-20">
          <div className="absolute top-1/4 left-1/4 w-96 h-96 rounded-full bg-pral-400 blur-3xl" />
          <div className="absolute bottom-1/4 right-1/4 w-64 h-64 rounded-full bg-pral-300 blur-3xl" />
        </div>
        <div className="relative flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center">
            <Radio className="w-5 h-5 text-white" />
          </div>
          <span className="text-white font-semibold text-lg">PRAL</span>
        </div>
        <div className="relative space-y-4 max-w-md">
          <h1 className="text-4xl font-bold text-white leading-tight">
            Film any location. Ship polished media.
          </h1>
          <p className="text-pral-200 text-lg leading-relaxed">
            Draw a circle on the map. The drone handles the rest — curated clips,
            ready-to-share previews, one click to export.
          </p>
        </div>
        <p className="relative text-pral-400 text-sm">Demo mode · any credentials work</p>
      </div>

      <div className="flex-1 flex items-center justify-center p-6 sm:p-12">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="w-full max-w-sm"
        >
          <div className="lg:hidden flex items-center gap-2 mb-8">
            <div className="w-8 h-8 rounded-lg bg-pral-600 flex items-center justify-center">
              <Radio className="w-4 h-4 text-white" />
            </div>
            <span className="font-semibold">PRAL</span>
          </div>

          <h2 className="text-2xl font-semibold text-foreground">Sign in</h2>
          <p className="text-muted text-sm mt-1 mb-8">
            Enter any email and password to continue
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-sm font-medium text-foreground block mb-1.5">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="w-full px-4 py-3 rounded-xl border border-border bg-surface-elevated text-sm focus:outline-none focus:ring-2 focus:ring-pral-500/30 transition-shadow"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-foreground block mb-1.5">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full px-4 py-3 rounded-xl border border-border bg-surface-elevated text-sm focus:outline-none focus:ring-2 focus:ring-pral-500/30 transition-shadow"
              />
            </div>
            <PrimaryButton
              type="submit"
              loading={loading}
              className="w-full mt-2"
            >
              Continue
              <ArrowRight className="w-4 h-4" />
            </PrimaryButton>
          </form>
        </motion.div>
      </div>
    </div>
  );
}
