import React from "react";
import { Box, Text, useStdout } from "ink";

function charWidth(code: number): number {
  if (code <= 0x7e) return 1;
  if (
    (code >= 0x1100 && code <= 0x115f) ||
    (code >= 0x2e80 && code <= 0xa4cf && code !== 0x303f) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe10 && code <= 0xfe6f) ||
    (code >= 0xff01 && code <= 0xff60) ||
    (code >= 0xffe0 && code <= 0xffe6) ||
    (code >= 0x20000 && code <= 0x2fffd) ||
    (code >= 0x30000 && code <= 0x3fffd)
  ) return 2;
  return 1;
}

function displayWidth(str: string): number {
  let w = 0;
  for (const ch of str) w += charWidth(ch.codePointAt(0)!);
  return w;
}

function truncateToWidth(str: string, maxW: number): string {
  let w = 0;
  let i = 0;
  for (const ch of str) {
    const cw = charWidth(ch.codePointAt(0)!);
    if (w + cw > maxW) break;
    w += cw;
    i += ch.length;
  }
  return str.slice(0, i);
}

function sanitize(str: string): string {
  return str.replace(/[\x00-\x1f\x7f]/g, " ");
}

function fitToWidth(str: string, width: number): string {
  const truncated = truncateToWidth(sanitize(str), width);
  const dw = displayWidth(truncated);
  return truncated + " ".repeat(Math.max(0, width - dw));
}

interface Column {
  key: string;
  label: string;
  width: number;
}

interface Props {
  columns: Column[];
  rows: Record<string, string>[];
  selectedIndex: number;
  maxRows?: number;
  checked?: Set<number>;
}

export function Table({ columns, rows, selectedIndex, maxRows, checked }: Props) {
  const { stdout } = useStdout();
  const termWidth = (stdout?.columns ?? 80) - 2;
  const termRows = stdout?.rows ?? 24;
  const fixedWidth = 4 + columns.reduce((s, c) => s + c.width, 0);
  const extra = Math.max(0, termWidth - fixedWidth);

  const resolved = columns.map((col, i) =>
    i === columns.length - 1 ? { ...col, width: col.width + extra } : col,
  );

  const effectiveMaxRows = maxRows ?? Math.max(3, termRows - 22);
  let visibleStart = 0;
  let visibleEnd = rows.length;
  if (rows.length > effectiveMaxRows) {
    const half = Math.floor(effectiveMaxRows / 2);
    visibleStart = Math.min(Math.max(0, selectedIndex - half), rows.length - effectiveMaxRows);
    visibleEnd = visibleStart + effectiveMaxRows;
  }
  const visible = rows.slice(visibleStart, visibleEnd);
  const scrollInfo = rows.length > effectiveMaxRows
    ? ` (${selectedIndex + 1}/${rows.length})`
    : "";

  return (
    <Box flexDirection="column">
      <Box>
        <Box width={4}><Text bold>{checked ? "☑" : "#"}</Text></Box>
        {resolved.map((col) => (
          <Box key={col.key} width={col.width}>
            <Text bold>{col.label}</Text>
          </Box>
        ))}
        {scrollInfo && <Text dimColor>{scrollInfo}</Text>}
      </Box>
      <Text>{"─".repeat(4 + resolved.reduce((s, c) => s + c.width, 0))}</Text>
      {visible.map((row, vi) => {
        const i = visibleStart + vi;
        return (
          <Box key={i}>
            <Box width={4}>
              <Text inverse={i === selectedIndex} dimColor={i !== selectedIndex}>
                {checked
                  ? (checked.has(i) ? (i === selectedIndex ? "▸☑ " : " ☑ ") : (i === selectedIndex ? "▸☐ " : " ☐ "))
                  : (i === selectedIndex ? `▸${String(i + 1).padStart(2)}` : ` ${String(i + 1).padStart(2)}`)}
              </Text>
            </Box>
            {resolved.map((col) => (
              <Box key={col.key} width={col.width}>
                <Text inverse={i === selectedIndex}>
                  {fitToWidth(row[col.key] ?? "", col.width - 1)}
                </Text>
              </Box>
            ))}
          </Box>
        );
      })}
    </Box>
  );
}
