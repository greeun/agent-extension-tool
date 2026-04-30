import React from "react";
import { Box, Text, useStdout } from "ink";

export type TabName = "extensions" | "project" | "dashboard" | "claude" | "codex" | "gemini" | "cursor";

const TABS: { key: TabName; label: string; short: string }[] = [
  { key: "extensions", label: "Extensions", short: "Ext" },
  { key: "project", label: "Project", short: "Prj" },
  { key: "dashboard", label: "Dashboard", short: "Dash" },
  { key: "claude", label: "Claude", short: "Cla" },
  { key: "codex", label: "Codex", short: "Cdx" },
  { key: "gemini", label: "Gemini", short: "Gem" },
  { key: "cursor", label: "Cursor", short: "Cur" },
];

interface Props {
  active: TabName;
}

const HINT_FULL = "←→:tab  r:refresh  ?:help  q:quit";
const HINT_SHORT = "←→ ? q";

export function TabBar({ active }: Props) {
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
            <Text dimColor={!isActive} bold={isActive} inverse={isActive}>
              {` ${i + 1}:${label} `}
            </Text>
          </Box>
        );
      })}
      <Box flexGrow={1} />
      <Text dimColor>{compact ? HINT_SHORT : HINT_FULL}</Text>
    </Box>
  );
}

export { TABS };
