import { readFileSync } from "fs";

export interface RateLimitData {
  fiveHour: number | null;
  sevenDay: number | null;
  fiveHourResetAt: Date | null;
  sevenDayResetAt: Date | null;
}

interface ExternalSnapshot {
  five_hour?: {
    used_percentage?: number | null;
    resets_at?: string | number | null;
  } | null;
  seven_day?: {
    used_percentage?: number | null;
    resets_at?: string | number | null;
  } | null;
  updated_at?: string | number | null;
}

function parsePercent(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.round(Math.min(100, Math.max(0, value)));
}

function parseDate(value: unknown): Date | null {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    const ms = value > 1e12 ? value : value * 1000;
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (typeof value === "string" && value.trim()) {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

export function readRateLimits(
  snapshotPath: string,
  freshnessMs = 300_000,
): RateLimitData | null {
  try {
    const raw = readFileSync(snapshotPath, "utf8");
    const snap = JSON.parse(raw) as ExternalSnapshot;

    const updatedAt = parseDate(snap.updated_at);
    if (!updatedAt) return null;
    if (Date.now() - updatedAt.getTime() > freshnessMs) return null;

    const fiveHour = parsePercent(snap.five_hour?.used_percentage);
    const sevenDay = parsePercent(snap.seven_day?.used_percentage);
    if (fiveHour === null && sevenDay === null) return null;

    return {
      fiveHour,
      sevenDay,
      fiveHourResetAt: parseDate(snap.five_hour?.resets_at),
      sevenDayResetAt: parseDate(snap.seven_day?.resets_at),
    };
  } catch {
    return null;
  }
}
