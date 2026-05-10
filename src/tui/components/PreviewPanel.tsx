import { Box, Text } from "ink";

const DEFAULT_MAX_LINES = 30;
const DEFAULT_PAGE_SIZE = 10;

export interface PreviewPanelProps {
  title: string;
  subtitle?: string;
  lines: string[];
  scroll: number;
  maxLines?: number;
  showLineNumbers?: boolean;
  shortcuts?: string;
}

export function PreviewPanel({
  title,
  subtitle,
  lines,
  scroll,
  maxLines = DEFAULT_MAX_LINES,
  showLineNumbers = true,
  shortcuts = "j/k:scroll  PgUp/PgDn:page  q/Esc:close",
}: PreviewPanelProps) {
  const visible = lines.slice(scroll, scroll + maxLines);
  const hasMore = lines.length > maxLines;

  return (
    <Box flexDirection="column" marginTop={1} borderStyle="double" borderColor="yellow" paddingX={1}>
      <Box marginBottom={1}>
        <Text bold color="yellow">Preview: </Text>
        <Text bold>{title}</Text>
        {subtitle && <Text dimColor>  {subtitle}</Text>}
      </Box>
      <Box flexDirection="column">
        {visible.map((line, i) => (
          <Box key={scroll + i}>
            {showLineNumbers && (
              <Text dimColor>{String(scroll + i + 1).padStart(3)} </Text>
            )}
            <Text>{line || " "}</Text>
          </Box>
        ))}
      </Box>
      {hasMore && (
        <Box marginTop={1}>
          <Text dimColor>
            [{scroll + 1}-{Math.min(scroll + maxLines, lines.length)}/{lines.length}]
          </Text>
        </Box>
      )}
      <Box marginTop={1}>
        <Text dimColor>{shortcuts}</Text>
      </Box>
    </Box>
  );
}

export function previewScrollHandler(
  input: string,
  key: { downArrow: boolean; upArrow: boolean; pageDown: boolean; pageUp: boolean },
  scroll: number,
  totalLines: number,
  maxLines: number = DEFAULT_MAX_LINES,
  pageSize: number = DEFAULT_PAGE_SIZE,
): number {
  const maxScroll = Math.max(0, totalLines - maxLines);
  if (input === "j" || key.downArrow) return Math.min(scroll + 1, maxScroll);
  if (input === "k" || key.upArrow) return Math.max(scroll - 1, 0);
  if (key.pageDown) return Math.min(scroll + pageSize, maxScroll);
  if (key.pageUp) return Math.max(scroll - pageSize, 0);
  return scroll;
}
