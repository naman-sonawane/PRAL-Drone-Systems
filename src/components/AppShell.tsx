"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LogOut, Radio } from "lucide-react";
import { clearSession, getSession } from "@/lib/auth";
import { useEffect, useState } from "react";
import type { UserSession } from "@/lib/types";

const STEPS = [
  { path: "/", label: "Target" },
  { path: "/processing", label: "Acquire" },
  { path: "/clips", label: "Clips" },
  { path: "/create", label: "Style" },
  { path: "/preview", label: "Preview" },
  { path: "/export", label: "Export" },
];

export function AppShell({
  children,
  showSteps = true,
}: {
  children: React.ReactNode;
  showSteps?: boolean;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<UserSession | null>(null);

  useEffect(() => {
    setUser(getSession());
  }, []);

  const currentStepIndex = STEPS.findIndex((s) => s.path === pathname);

  function handleLogout() {
    clearSession();
    router.push("/login");
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-50 glass border-b border-border/80">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="w-8 h-8 rounded-lg bg-pral-600 flex items-center justify-center shadow-sm">
              <Radio className="w-4 h-4 text-white" />
            </div>
            <span className="font-semibold text-foreground tracking-tight">PRAL</span>
          </Link>

          {showSteps && currentStepIndex >= 0 && (
            <nav className="hidden md:flex items-center gap-1">
              {STEPS.map((step, i) => {
                const isActive = i === currentStepIndex;
                const isPast = i < currentStepIndex;
                return (
                  <div key={step.path} className="flex items-center">
                    {i > 0 && (
                      <div
                        className={`w-6 h-px mx-1 ${isPast ? "bg-pral-400" : "bg-border"}`}
                      />
                    )}
                    <span
                      className={`text-xs font-medium px-2 py-1 rounded-full transition-colors ${
                        isActive
                          ? "bg-pral-100 text-pral-700"
                          : isPast
                            ? "text-pral-600"
                            : "text-muted"
                      }`}
                    >
                      {step.label}
                    </span>
                  </div>
                );
              })}
            </nav>
          )}

          {user && (
            <button
              onClick={handleLogout}
              className="flex items-center gap-2 text-sm text-muted hover:text-foreground transition-colors focus-ring rounded-lg px-2 py-1"
            >
              <span className="hidden sm:inline">{user.name}</span>
              <LogOut className="w-4 h-4" />
            </button>
          )}
        </div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
