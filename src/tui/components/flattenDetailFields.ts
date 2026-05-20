import stringWidth from "string-width";
import type { DetailField } from "./DetailPanel.js";

// Two measurements matter for terminal layout:
//   - widthNarrow(s): how Ink (and wrap-ansi) sizes a string. Drives Box
//     auto-padding and where Ink draws the right border.
//   - widthWide(s):   how a CJK-locale terminal (Korean macOS Terminal /
//     iTerm2 with "double-width ambiguous") actually renders the cells.
//     Drives whether the terminal wraps the line to column 0.
//
// We chunk by WIDE width so each value line visually fits in the user's
// terminal, and we pad to NARROW width so Ink does not auto-pad and pile
// extra trailing spaces on top of the wide content (which would push the
// rendered line past the terminal edge and wrap it).

export function widthNarrow(s: string): number {
  return stringWidth(s);
}

export function widthWide(s: string): number {
  return stringWidth(s, { ambiguousIsNarrow: false });
}

export function flattenDetailFields(fields: DetailField[], maxWidth: number): string[] {
  const out: string[] = [];
  const safeWidth = Math.max(1, maxWidth);
  for (const f of fields) {
    const labelPart = `${f.label}: `;
    const labelW = widthWide(labelPart);
    const valuePart = f.value && f.value.length > 0 ? f.value : "—";
    const valueWidth = Math.max(1, safeWidth - labelW);
    const valueLines = chunkByWidth(valuePart, valueWidth);
    out.push(`${labelPart}${valueLines[0] ?? ""}`);
    const indent = " ".repeat(labelW);
    for (let i = 1; i < valueLines.length; i++) {
      out.push(`${indent}${valueLines[i]}`);
    }
  }
  return out;
}

export function chunkByWidth(s: string, maxWidth: number): string[] {
  if (maxWidth <= 0) return [s];
  const result: string[] = [];
  let current = "";
  let currentW = 0;
  for (const ch of s) {
    const chW = widthWide(ch);
    if (currentW + chW > maxWidth && current.length > 0) {
      result.push(current);
      current = "";
      currentW = 0;
    }
    current += ch;
    currentW += chW;
  }
  if (current.length > 0) result.push(current);
  return result.length === 0 ? [""] : result;
}

/** Pad to a target NARROW width — chosen so Ink's box does not insert extra
 *  trailing spaces (which would expand the wide width of the rendered line). */
export function padToWidth(s: string, target: number): string {
  const w = widthNarrow(s);
  return w >= target ? s : s + " ".repeat(target - w);
}
