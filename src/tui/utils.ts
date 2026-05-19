import stringWidth from "string-width";

export function truncateToWidth(str: string, maxW: number): string {
  let w = 0;
  let i = 0;
  for (const ch of str) {
    const cw = stringWidth(ch);
    if (w + cw > maxW) break;
    w += cw;
    i += ch.length;
  }
  return str.slice(0, i);
}

export function sanitize(str: string): string {
  return str.replace(/[\x00-\x1f\x7f]/g, " ");
}

export function fitToWidth(str: string, width: number): string {
  const truncated = truncateToWidth(sanitize(str), width);
  const dw = stringWidth(truncated);
  return truncated + " ".repeat(Math.max(0, width - dw));
}

/**
 * Compute the [start, end) slice of a list to render so it fits within
 * `maxRows`, keeping the selected item roughly centered. Shared by the Table
 * and any other scrollable list so a list never renders taller than the
 * space allotted to it (prevents the whole pane overflowing the terminal).
 */
export function visibleWindow(
  length: number,
  selectedIndex: number,
  maxRows: number,
): [number, number] {
  const cap = Math.max(1, Math.floor(maxRows));
  if (length <= cap) return [0, length];
  const half = Math.floor(cap / 2);
  const start = Math.min(Math.max(0, selectedIndex - half), length - cap);
  return [start, start + cap];
}
