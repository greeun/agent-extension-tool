import React from "react";
import { Box, Text, useStdout } from "ink";

export type TabName = "extensions" | "context" | "project" | "dashboard" | "claude" | "codex" | "gemini" | "cursor";

const TABS: { key: TabName; label: string; short: string }[] = [
  { key: "extensions", label: "Extensions", short: "Ext" },
  { key: "context", label: "Context", short: "Ctx" },
  { key: "project", label: "Project", short: "Prj" },
  { key: "dashboard", label: "Dashboard", short: "Dash" },
  { key: "claude", label: "Claude", short: "Cla" },
  { key: "codex", label: "Codex", short: "Cdx" },
  { key: "gemini", label: "Gemini", short: "Gem" },
  { key: "cursor", label: "Cursor", short: "Cur" },
];

interface Props {
  active: TabName;
  focused?: boolean;
}

export function TabBar({ active, focused = true }: Props) {
  const { stdout } = useStdout();
  const termWidth = stdout?.columns ?? 80;
  const compact = termWidth < 100;

  return (
    <Box paddingX={1}>
      {TABS.map((tab, i) => {
        const label = compact ? tab.short : tab.label;
        const isActive = tab.key === active;
        return (
          <Box key={tab.key} marginRight={0}>
            <Text dimColor={!isActive} bold={isActive} color={isActive ? "yellow" : undefined} inverse={isActive && focused}>
              {` ${i + 1}:${label} `}
            </Text>
          </Box>
        );
      })}
      <Box flexGrow={1} />
      <Text dimColor>{"?:help"}</Text>
    </Box>
  );
}

export { TABS };
