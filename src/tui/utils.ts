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
