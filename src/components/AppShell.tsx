"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearSession, getSession } from "@/lib/auth";
import { useEffect, useState } from "react";
import type { UserSession } from "@/lib/types";

const STEPS = [
  { path: "/target", label: "Target" },
  { path: "/processing", label: "Acquire" },
  { path: "/clips", label: "Clips" },
  { path: "/create", label: "Style" },
  { path: "/preview", label: "Preview" },
  { path: "/export", label: "Export" },
];

export function AppShell({
  children,
  showSteps = true,
  actions,
}: {
  children: React.ReactNode;
  showSteps?: boolean;
  actions?: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [mounted, setMounted] = useState(false);
  const [user, setUser] = useState<UserSession | null>(null);

  useEffect(() => {
    setMounted(true);
    setUser(getSession());
  }, []);

  const currentStepIndex = STEPS.findIndex((s) => s.path === pathname);

  function handleLogout() {
    clearSession();
    router.push("/login");
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-4 z-50 mx-4 sm:mx-6">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-4 rounded-2xl border border-white/15 bg-white/10 backdrop-blur-xl shadow-lg shadow-black/5 ring-1 ring-black/5">
          <Link href="/" className="flex items-center gap-2.5 shrink-0">
            <Image
              src="/logomark.png"
              alt=""
              width={32}
              height={32}
              className="sm:hidden"
              priority
            />
            <Image
              src="/logotype.png"
              alt="PRAL"
              width={108}
              height={32}
              className="hidden sm:block h-7 w-auto"
              priority
            />
          </Link>

          {showSteps && currentStepIndex >= 0 && (
            <>
              <nav
                className="hidden lg:flex items-center flex-1 justify-center max-w-2xl"
                aria-label="Workflow"
              >
                {STEPS.map((step, i) => {
                  const isActive = i === currentStepIndex;
                  const isPast = i < currentStepIndex;
                  return (
                    <div key={step.path} className="flex items-center">
                      {i > 0 && (
                        <div
                          className={`w-6 h-px ${
                            isPast ? "bg-accent" : "bg-line"
                          }`}
                          aria-hidden
                        />
                      )}
                      <span
                        className={`px-3 py-1.5 text-xs font-medium tracking-wide transition-colors border-b-2 ${
                          isActive
                            ? "border-accent text-accent-ink"
                            : isPast
                              ? "border-transparent text-ink-muted"
                              : "border-transparent text-ink-faint"
                        }`}
                      >
                        <span className="tabular-nums mr-1.5 text-[10px]">
                          {String(i + 1).padStart(2, "0")}
                        </span>
                        {step.label}
                      </span>
                    </div>
                  );
                })}
              </nav>

              <div className="lg:hidden flex-1 text-center">
                <p className="text-[10px] label-caps text-ink-faint">
                  {String(currentStepIndex + 1).padStart(2, "0")} /{" "}
                  {String(STEPS.length).padStart(2, "0")}
                </p>
                <p className="text-sm font-medium text-ink">
                  {STEPS[currentStepIndex]?.label}
                </p>
              </div>
            </>
          )}

          {actions ? (
            <div className="shrink-0 flex justify-end items-center gap-3">
              {actions}
            </div>
          ) : (
            <div className="shrink-0 w-[72px] sm:w-[108px] flex justify-end">
              {mounted && user ? (
                <button
                  onClick={handleLogout}
                  className="text-xs text-ink-muted hover:text-ink transition-colors focus-ring px-2 py-1"
                >
                  <span className="hidden sm:inline truncate max-w-[100px]">
                    {user.name}
                  </span>
                  <span className="sm:hidden">Out</span>
                </button>
              ) : (
                <div className="w-8 h-8" aria-hidden />
              )}
            </div>
          )}
        </div>

      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
