import { Box, Text, useStdout } from "ink";
import { fitToWidth, visibleWindow } from "../utils.js";

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

  const [visibleStart, visibleEnd] = visibleWindow(rows.length, selectedIndex, effectiveMaxRows);
  const visible = rows.slice(visibleStart, visibleEnd);

  return (
    <Box flexDirection="column">
      <Text bold wrap="truncate-end">{fitToWidth(checked ? "■" : "#", 4) + resolved.map((col) => fitToWidth(col.label, col.width)).join(gapStr)}</Text>
      <Text wrap="truncate-end">{"─".repeat(4 + resolved.reduce((s, c) => s + c.width, 0) + gapTotal)}</Text>
      {visible.map((row, vi) => {
        const i = visibleStart + vi;
        const sel = i === selectedIndex;
        const prefix = checked
          ? (checked.has(i) ? (sel ? "▸■ " : " ■ ") : (sel ? "▸□ " : " □ "))
          : (sel ? `▸${String(i + 1).padStart(2)} ` : ` ${String(i + 1).padStart(2)} `);
        const pf = fitToWidth(prefix, 4);
        const line = resolved.map((col) => fitToWidth(row[col.key] ?? "", col.width)).join(gapStr);
        // Use foreground color (cyan + bold) instead of `inverse` for the
        // selection highlight. `inverse` causes Ink to pad trailing spaces to
        // the full row width to keep the background flip visible, while
        // non-selected rows emit no trailing padding — under some terminal
        // multiplexers (WezTerm via cmux, …) that asymmetry produces a row
        // whose ▸/# column appear to vanish after a transition. Foreground
        // styling avoids the trailing-padding asymmetry entirely; the row
        // structure is now identical for selected and non-selected too.
        return (
          <Text key={i} wrap="truncate-end" {...(sel ? { bold: true } : {})}>
            <Text {...(sel ? { color: "cyan" } : { dimColor: true })}>{pf}</Text>
            <Text {...(sel ? { color: "cyan" } : {})}>{line}</Text>
          </Text>
        );
      })}
    </Box>
  );
}
