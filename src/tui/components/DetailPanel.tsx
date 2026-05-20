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
  const borderColor = focused ? "cyan" : undefined;

  if (lines) {
    const { visible, indicator } = sliceLines(lines, maxHeight, false, false, scroll);
    return (
      <Box flexDirection="column" marginTop={1} borderStyle="single" borderColor={borderColor} paddingX={1}>
        {visible.map((line, i) => (
          <Text key={i}>{line}</Text>
        ))}
        {indicator && <Text dimColor>{indicator}</Text>}
      </Box>
    );
  }

  const allFields = fields ?? [];
  const flat = flattenDetailFields(allFields, contentWidth ?? DEFAULT_CONTENT_WIDTH);
  const hasTitle = !!title;
  const hasShortcuts = !!shortcuts;
  const { overflows, visible, indicator } = computeViewport(flat, maxHeight, hasTitle, hasShortcuts, scroll);

  // Rich render path: no overflow → preserve colors by rendering fields directly.
  if (!overflows) {
    return (
      <Box flexDirection="column" marginTop={1} borderStyle="single" borderColor={borderColor} paddingX={1}>
        {title && (
          <Box marginBottom={1}>
            <Text bold color="cyan">{title}</Text>
          </Box>
        )}
        {allFields.map((f, i) => (
          <Box key={i}>
            <Text wrap="wrap">
              <Text dimColor>{f.label}: </Text>
              <Text color={f.color as any}>{f.value || "—"}</Text>
            </Text>
          </Box>
        ))}
        {shortcuts && (
          <Box marginTop={1}>
            <Text dimColor>{shortcuts}</Text>
          </Box>
        )}
      </Box>
    );
  }

  // Flat scroll path: content overflows, drop colors in favor of scroll.
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
