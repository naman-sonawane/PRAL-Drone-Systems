"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [mounted, setMounted] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    const authed = isAuthenticated();
    setAuthenticated(authed);
    setMounted(true);
    if (!authed) {
      router.replace("/login");
    }
  }, [router]);

  if (!mounted || !authenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-accent border-t-transparent animate-spin" />
      </div>
    );
  }

  return <>{children}</>;
}
