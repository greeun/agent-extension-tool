import React, { useState } from "react";
import { Box, Text, useInput } from "ink";
import { PluginsTab } from "./PluginsTab.js";
import { SkillsTab } from "./SkillsTab.js";
import { McpTab } from "./McpTab.js";
import { MarketTab } from "./MarketTab.js";

type SubView = "plugins" | "skills" | "mcp" | "market";

const SUB_VIEWS: { key: SubView; label: string }[] = [
  { key: "plugins", label: "Plugins" },
  { key: "skills", label: "Skills" },
  { key: "mcp", label: "MCP" },
  { key: "market", label: "Marketplace" },
];

export function ManageTab() {
  const [view, setView] = useState<SubView>("plugins");

  useInput((input, key) => {
    if (key.tab) {
      const idx = SUB_VIEWS.findIndex((sv) => sv.key === view);
      setView(SUB_VIEWS[(idx + 1) % SUB_VIEWS.length].key);
    }
  });

  return (
    <Box flexDirection="column">
      <Box marginBottom={1}>
        <Text bold>Claude Code Manage  </Text>
        {SUB_VIEWS.map((sv, i) => (
          <Box key={sv.key} marginRight={1}>
            <Text
              bold={sv.key === view}
              underline={sv.key === view}
              dimColor={sv.key !== view}
            >
              {`${i + 1}:${sv.label}`}
            </Text>
          </Box>
        ))}
      </Box>

      {view === "plugins" && <PluginsTab />}
      {view === "skills" && <SkillsTab />}
      {view === "mcp" && <McpTab />}
      {view === "market" && <MarketTab />}
    </Box>
  );
}
