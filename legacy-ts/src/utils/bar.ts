/**
 * Render a fixed-width ASCII bar. `filled` is the already-computed number of
 * filled cells (each call site keeps its own pct→filled rounding so output is
 * byte-identical to the prior inline implementations). The empty count is
 * guarded with Math.max(0, …) — identical to all callers for pct ∈ [0,100],
 * and merely safer (no RangeError) outside that unreachable domain.
 */
export function renderBar(
  filled: number,
  width: number,
  fillChar = "█",
  emptyChar = "░",
): string {
  return fillChar.repeat(Math.max(0, filled)) + emptyChar.repeat(Math.max(0, width - filled));
}
