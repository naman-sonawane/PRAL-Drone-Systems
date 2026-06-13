import type { UserSession } from "@/lib/types";

const SESSION_KEY = "pral_session";

export function getSession(): UserSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as UserSession;
  } catch {
    return null;
  }
}

export function setSession(session: UserSession): void {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY);
}

export function login(email: string, _password: string): UserSession {
  const session: UserSession = {
    email,
    name: email.split("@")[0] || "User",
    logged_in_at: new Date().toISOString(),
  };
  setSession(session);
  return session;
}

export function isAuthenticated(): boolean {
  return getSession() !== null;
}
