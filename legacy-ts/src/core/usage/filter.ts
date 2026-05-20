/** Claude semantics: millisecond comparison via Date.getTime(). */
export function filterByTimestampMs<T extends { timestamp: string }>(
  entries: T[],
  sinceMs: number | null,
  untilMs: number | null,
): T[] {
  return entries.filter((entry) => {
    if (sinceMs !== null) {
      const ts = new Date(entry.timestamp).getTime();
      if (ts < sinceMs) return false;
    }
    if (untilMs !== null) {
      const ts = new Date(entry.timestamp).getTime();
      if (ts > untilMs) return false;
    }
    return true;
  });
}

/** Codex/Gemini semantics: YYYY-MM-DD string prefix comparison. */
export function filterByDateString<T extends { timestamp: string }>(
  entries: T[],
  since: string | undefined,
  until: string | undefined,
): T[] {
  return entries.filter((e) => {
    const date = e.timestamp.slice(0, 10);
    if (since && date < since) return false;
    if (until && date > until) return false;
    return true;
  });
}
