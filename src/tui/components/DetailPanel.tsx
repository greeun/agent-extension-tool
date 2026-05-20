import { Box, Text } from "ink";
import {
  chunkByWidth,
  flattenDetailFields,
  padToWidth,
  widthNarrow,
  widthWide,
} from "./flattenDetailFields.js";

export interface DetailField {
  label: string;
  value: string;
  color?: string;
}

interface Props {
  title?: string;
  fields?: DetailField[];
  shortcuts?: string;
  lines?: string[];
  focused?: boolean;
  scroll?: number;
  maxHeight?: number;
  /** Inner content width used to wrap field values. Defaults to 80 when not provided. */
  contentWidth?: number;
}

const DEFAULT_CONTENT_WIDTH = 80;

export function DetailPanel({
  title,
  fields,
  shortcuts,
  lines,
  focused = false,
  scroll = 0,
  maxHeight,
  contentWidth,
}: Props) {
  const borderColor = focused ? "cyan" : undefined;
  // East Asian Ambiguous-width chars (→ — … etc.) render as 2 cells in
  // CJK-locale terminals but Ink/wrap-ansi measure them as 1. After Ink
  // auto-pads each row to fill the box's inner width in narrow units, the
  // resulting line is `innerWidth + ambiguous_count_in_row` cells wide on
  // the terminal — which can spill past the right edge and wrap to column 0.
  // Reserve a small safety margin so typical chunks (a few ambiguous chars
  // each) stay inside the terminal.
  const AMBIGUOUS_SAFETY = 6;
  const requestedWidth = Math.max(1, contentWidth ?? DEFAULT_CONTENT_WIDTH);
  const innerWidth = Math.max(1, requestedWidth - AMBIGUOUS_SAFETY);

  if (lines) {
    const { visible, indicator } = sliceLines(lines, maxHeight, false, false, scroll);
    return (
      <Box flexDirection="column" marginTop={1} borderStyle="single" borderColor={borderColor} paddingX={1} width={innerWidth + 4}>
        {visible.map((line, i) => (
          <Text key={i}>{padToWidth(line, innerWidth)}</Text>
        ))}
        {indicator && <Text dimColor>{padToWidth(indicator, innerWidth)}</Text>}
      </Box>
    );
  }

  const allFields = fields ?? [];
  const flat = flattenDetailFields(allFields, innerWidth);
  const hasTitle = !!title;
  const hasShortcuts = !!shortcuts;
  const { overflows, visible, indicator } = computeViewport(flat, maxHeight, hasTitle, hasShortcuts, scroll);

  // Rich render path: no overflow → preserve colors by rendering fields directly.
  if (!overflows) {
    return (
      <Box flexDirection="column" marginTop={1} borderStyle="single" borderColor={borderColor} paddingX={1} width={innerWidth + 4}>
        {title && (
          <>
            <Text bold color="cyan">{padToWidth(title, innerWidth)}</Text>
            <Text>{padToWidth("", innerWidth)}</Text>
          </>
        )}
        {allFields.flatMap((f, i) => renderColoredField(f, innerWidth, i))}
        {shortcuts && (
          <>
            <Text>{padToWidth("", innerWidth)}</Text>
            <Text dimColor>{padToWidth(shortcuts, innerWidth)}</Text>
          </>
        )}
      </Box>
    );
  }

  // Flat scroll path: content overflows, drop colors in favor of scroll.
  return (
    <Box flexDirection="column" marginTop={1} borderStyle="single" borderColor={borderColor} paddingX={1}>
      {title && (
        <>
          <Box justifyContent="space-between">
            <Text bold color="cyan">{title}</Text>
            {indicator && <Text dimColor>{indicator}</Text>}
          </Box>
          <Text>{padToWidth("", innerWidth)}</Text>
        </>
      )}
      {!title && indicator && (
        <Box justifyContent="flex-end"><Text dimColor>{indicator}</Text></Box>
      )}
      {visible.map((line, i) => (
        <Text key={i}>{padToWidth(line, innerWidth)}</Text>
      ))}
      {shortcuts && (
        <>
          <Text>{padToWidth("", innerWidth)}</Text>
          <Text dimColor>{padToWidth(shortcuts, innerWidth)}</Text>
        </>
      )}
    </Box>
  );
}

function renderColoredField(f: DetailField, innerWidth: number, fieldIndex: number) {
  const labelPart = `${f.label}: `;
  const labelW = widthWide(labelPart);
  const value = f.value && f.value.length > 0 ? f.value : "—";
  const valueWidth = Math.max(1, innerWidth - labelW);
  const valueLines = chunkByWidth(value, valueWidth);
  const indent = " ".repeat(labelW);
  return valueLines.map((line, i) => {
    // Pad to fill the box in NARROW width so Ink doesn't insert extra trailing
    // spaces (which would push the line past the terminal edge in CJK-locale
    // terminals that render ambiguous-width chars as 2 cells).
    const lineNarrow = widthNarrow(line);
    const padding = " ".repeat(Math.max(0, innerWidth - labelW - lineNarrow));
    if (i === 0) {
      return (
        <Text key={`${fieldIndex}-${i}`}>
          <Text dimColor>{labelPart}</Text>
          <Text color={f.color as any}>{line}</Text>
          {padding}
        </Text>
      );
    }
    return (
      <Text key={`${fieldIndex}-${i}`}>
        {indent}
        <Text color={f.color as any}>{line}</Text>
        {padding}
      </Text>
    );
  });
}

function computeViewport(
  allLines: string[],
  maxHeight: number | undefined,
  hasTitle: boolean,
  hasShortcuts: boolean,
  scroll: number,
): { viewport: number; overflows: boolean; visible: string[]; indicator?: string } {
  if (!maxHeight) {
    return { viewport: allLines.length, overflows: false, visible: allLines };
  }
  const reservedExcludingIndicator = 2 + (hasTitle ? 2 : 0) + (hasShortcuts ? 2 : 0);
  const tentativeViewport = Math.max(1, maxHeight - reservedExcludingIndicator);
  const overflows = allLines.length > tentativeViewport;
  const viewport = overflows
    ? Math.max(1, maxHeight - reservedExcludingIndicator - 1)
    : tentativeViewport;
  const clampedScroll = Math.min(Math.max(0, scroll), Math.max(0, allLines.length - viewport));
  const visible = allLines.slice(clampedScroll, clampedScroll + viewport);
  let indicator: string | undefined;
  if (overflows) {
    const start = clampedScroll + 1;
    const end = Math.min(clampedScroll + viewport, allLines.length);
    indicator = `[${start}-${end}/${allLines.length}]`;
  }
  return { viewport, overflows, visible, indicator };
}

function sliceLines(
  lines: string[],
  maxHeight: number | undefined,
  hasTitle: boolean,
  hasShortcuts: boolean,
  scroll: number,
): { visible: string[]; indicator?: string } {
  const { visible, indicator } = computeViewport(lines, maxHeight, hasTitle, hasShortcuts, scroll);
  return { visible, indicator };
}
