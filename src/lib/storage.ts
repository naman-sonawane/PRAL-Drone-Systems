import type { Mission } from "@/lib/types";

const MISSION_KEY = "pral_active_mission";

export function getActiveMission(): Mission | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(MISSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as Mission;
  } catch {
    return null;
  }
}

export function setActiveMission(mission: Mission): void {
  localStorage.setItem(MISSION_KEY, JSON.stringify(mission));
}

export function updateActiveMission(partial: Partial<Mission>): Mission | null {
  const current = getActiveMission();
  if (!current) return null;
  const updated: Mission = {
    ...current,
    ...partial,
    updated_at: new Date().toISOString(),
  };
  setActiveMission(updated);
  return updated;
}

export function clearActiveMission(): void {
  localStorage.removeItem(MISSION_KEY);
}
