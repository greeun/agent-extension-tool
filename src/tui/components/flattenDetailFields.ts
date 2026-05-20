import type { DetailField } from "./DetailPanel.js";

export function flattenDetailFields(fields: DetailField[], width: number): string[] {
  const out: string[] = [];
  const safeWidth = Math.max(1, width);
  for (const f of fields) {
    const labelPart = `${f.label}: `;
    const valuePart = f.value && f.value.length > 0 ? f.value : "—";
    const valueWidth = Math.max(1, safeWidth - labelPart.length);
    const valueLines = chunk(valuePart, valueWidth);
    out.push(`${labelPart}${valueLines[0] ?? ""}`);
    const indent = " ".repeat(labelPart.length);
    for (let i = 1; i < valueLines.length; i++) {
      out.push(`${indent}${valueLines[i]}`);
    }
  }
  return out;
}

function chunk(s: string, width: number): string[] {
  if (width <= 0) return [s];
  const result: string[] = [];
  for (let i = 0; i < s.length; i += width) {
    result.push(s.slice(i, i + width));
  }
  return result.length === 0 ? [""] : result;
}
