import { Box, Text, useStdout } from "ink";
import stringWidth from "string-width";
import { truncateToWidth, sanitize, fitToWidth } from "../utils.js";

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
  availableWidth?: number;
  gap?: number;
}

export function Table({ columns, rows, selectedIndex, maxRows, checked, availableWidth, gap = 0 }: Props) {
  const { stdout } = useStdout();
  const termWidth = availableWidth ?? ((stdout?.columns ?? 80) - 2);
  const termRows = stdout?.rows ?? 24;
  const gapStr = " ".repeat(gap);
  const effectiveMaxRows = maxRows ?? Math.max(3, termRows - 22);

  const gapTotal = (columns.length - 1) * gap;
  const fixedWidth = 4 + columns.reduce((s, c) => s + c.width, 0) + gapTotal;
  const extra = Math.max(0, termWidth - fixedWidth);
  const resolved = columns.map((col, i) =>
    i === columns.length - 1 ? { ...col, width: col.width + extra } : col,
  );

  let visibleStart = 0;
  let visibleEnd = rows.length;
  if (rows.length > effectiveMaxRows) {
    const half = Math.floor(effectiveMaxRows / 2);
    visibleStart = Math.min(Math.max(0, selectedIndex - half), rows.length - effectiveMaxRows);
    visibleEnd = visibleStart + effectiveMaxRows;
  }
  const visible = rows.slice(visibleStart, visibleEnd);

  return (
    <Box flexDirection="column">
      <Text bold>{fitToWidth(checked ? "■" : "#", 4) + resolved.map((col) => fitToWidth(col.label, col.width)).join(gapStr)}</Text>
      <Text>{"─".repeat(4 + resolved.reduce((s, c) => s + c.width, 0) + gapTotal)}</Text>
      {visible.map((row, vi) => {
        const i = visibleStart + vi;
        const sel = i === selectedIndex;
        const prefix = checked
          ? (checked.has(i) ? (sel ? "▸■ " : " ■ ") : (sel ? "▸□ " : " □ "))
          : (sel ? `▸${String(i + 1).padStart(2)} ` : ` ${String(i + 1).padStart(2)} `);
        const pf = fitToWidth(prefix, 4);
        const line = resolved.map((col) => fitToWidth(row[col.key] ?? "", col.width)).join(gapStr);
        return sel
          ? <Text key={i} inverse>{pf + line}</Text>
          : <Text key={i}><Text dimColor>{pf}</Text>{line}</Text>;
      })}
    </Box>
  );
}
