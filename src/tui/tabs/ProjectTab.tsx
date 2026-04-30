import React, { useState, useEffect } from "react";
import { Box, Text, useInput, useStdout } from "ink";
import { loadProjectContext, type ProjectContextItem } from "../../core/project-context.js";

export function ProjectTab() {
  const [items, setItems] = useState<ProjectContextItem[]>([]);
  const [index, setIndex] = useState(0);
  const [scroll, setScroll] = useState(0);
  const { stdout } = useStdout();
  const viewHeight = Math.max((stdout?.rows ?? 24) - 10, 6);

  useEffect(() => {
    loadProjectContext(process.cwd()).then(setItems);
  }, []);

  const selected = items[index];
  const contentLines = selected?.content.split("\n") ?? [];
  const maxScroll = Math.max(0, contentLines.length - viewHeight);

  useInput((input, key) => {
    if (input === "j" || key.downArrow) {
      setIndex((i) => Math.min(i + 1, items.length - 1));
      setScroll(0);
    }
    if (input === "k" || key.upArrow) {
      setIndex((i) => Math.max(i - 1, 0));
      setScroll(0);
    }
    if (input === "]" || key.pageDown) setScroll((s) => Math.min(s + viewHeight, maxScroll));
    if (input === "[" || key.pageUp) setScroll((s) => Math.max(s - viewHeight, 0));
  });
  const visibleLines = contentLines.slice(scroll, scroll + viewHeight);

  return (
    <Box flexDirection="column">
      <Box marginBottom={1}>
        <Text bold>Project Context </Text>
        <Text dimColor>({items.length} files)</Text>
      </Box>

      <Box>
        <Box flexDirection="column" width={36} marginRight={1}>
          {items.map((item, i) => (
            <Text
              key={item.path}
              inverse={i === index}
              bold={i === index}
              dimColor={i !== index}
            >
              {i === index ? " ▸ " : "   "}
              {sourceIcon(item.source)} {item.name}
            </Text>
          ))}
        </Box>

        <Box flexDirection="column" flexGrow={1} borderStyle="single" paddingX={1}>
          {selected ? (
            <>
              <Box marginBottom={1}>
                <Text bold color="cyan">{selected.name}</Text>
                <Text dimColor>  {selected.path}</Text>
              </Box>
              <Text dimColor>
                {selected.lines} lines  |  [/]:page scroll
                {scroll > 0 ? `  (line ${scroll + 1})` : ""}
              </Text>
              <Box flexDirection="column" marginTop={1}>
                {visibleLines.map((line, i) => (
                  <Text key={scroll + i} wrap="truncate">{line}</Text>
                ))}
                {scroll + viewHeight < contentLines.length && (
                  <Text dimColor>  ↓ {contentLines.length - scroll - viewHeight} more lines</Text>
                )}
              </Box>
            </>
          ) : (
            <Text dimColor>No project context files found.</Text>
          )}
        </Box>
      </Box>
    </Box>
  );
}

function sourceIcon(source: string): string {
  switch (source) {
    case "global": return "●";
    case "user": return "◆";
    case "project": return "■";
    case "memory": return "◇";
    default: return "○";
  }
}
