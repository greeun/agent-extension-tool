import { Box, Text } from "ink";
import { flattenDetailFields } from "./flattenDetailFields.js";

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
  const allLines: string[] = lines
    ? lines.slice()
    : flattenDetailFields(fields ?? [], contentWidth ?? DEFAULT_CONTENT_WIDTH);

  const titleRows = title ? 2 : 0;
  const shortcutsRows = shortcuts ? 2 : 0;
  const borderRows = 2;
  let visible = allLines;
  let indicator: string | undefined;

  if (maxHeight) {
    const reservedExcludingIndicator = borderRows + titleRows + shortcutsRows;
    const tentativeViewport = Math.max(1, maxHeight - reservedExcludingIndicator);
    const overflows = allLines.length > tentativeViewport;
    const viewport = overflows
      ? Math.max(1, maxHeight - reservedExcludingIndicator - 1)
      : tentativeViewport;
    const clampedScroll = Math.min(Math.max(0, scroll), Math.max(0, allLines.length - viewport));
    visible = allLines.slice(clampedScroll, clampedScroll + viewport);
    if (overflows) {
      const start = clampedScroll + 1;
      const end = Math.min(clampedScroll + viewport, allLines.length);
      indicator = `[${start}-${end}/${allLines.length}]`;
    }
  }

  const borderColor = focused ? "cyan" : undefined;

  if (lines) {
    return (
      <Box flexDirection="column" marginTop={1} borderStyle="single" borderColor={borderColor} paddingX={1}>
        {visible.map((line, i) => (
          <Text key={i}>{line}</Text>
        ))}
        {indicator && <Text dimColor>{indicator}</Text>}
      </Box>
    );
  }

  return (
    <Box flexDirection="column" marginTop={1} borderStyle="single" borderColor={borderColor} paddingX={1}>
      {title && (
        <Box marginBottom={1} justifyContent="space-between">
          <Text bold color="cyan">{title}</Text>
          {indicator && <Text dimColor>{indicator}</Text>}
        </Box>
      )}
      {!title && indicator && (
        <Box justifyContent="flex-end"><Text dimColor>{indicator}</Text></Box>
      )}
      {visible.map((line, i) => (
        <Text key={i}>{line}</Text>
      ))}
      {shortcuts && (
        <Box marginTop={1}>
          <Text dimColor>{shortcuts}</Text>
        </Box>
      )}
    </Box>
  );
}
