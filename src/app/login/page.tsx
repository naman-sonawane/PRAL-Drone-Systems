"use client";

import { useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
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
    login(email || "naman@pral.io", password);
    router.push("/target");
  }

  return (
    <div className="min-h-screen flex">
      <div className="hidden lg:flex flex-1 bg-ink p-12 flex-col justify-between relative overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              "repeating-linear-gradient(0deg, transparent, transparent 39px, #fff 39px, #fff 40px)",
          }}
        />
        <div className="relative">
          <Image
            src="/logotype.png"
            alt="PRAL"
            width={140}
            height={42}
            className="h-9 w-auto brightness-0 invert"
            priority
          />
        </div>
        <div className="relative space-y-5 max-w-md">
          <h1 className="text-4xl lg:text-[2.75rem] font-medium text-white leading-tight">
            Aerial media, end to end.
          </h1>
          <p className="text-white/65 text-base leading-relaxed">
            Mark a location. PRAL acquires footage, curates clips, and renders
            platform-ready exports.
          </p>
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center p-6 sm:p-12 bg-canvas">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="w-full max-w-sm"
        >
          <div className="lg:hidden flex items-center gap-3 mb-10">
            <Image
              src="/logomark.png"
              alt=""
              width={36}
              height={36}
              priority
            />
            <Image
              src="/logotype.png"
              alt="PRAL"
              width={100}
              height={30}
              className="h-7 w-auto"
            />
          </div>

          <h2 className="text-2xl font-medium text-ink">Sign in</h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-xs label-caps text-ink-muted block mb-1.5">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="input-field"
              />
            </div>
            <div>
              <label className="text-xs label-caps text-ink-muted block mb-1.5">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="input-field"
              />
            </div>
            <PrimaryButton
              type="submit"
              loading={loading}
              className="w-full mt-2"
            >
              Continue
            </PrimaryButton>
          </form>
        </motion.div>
      </div>
    </div>
  );
}
