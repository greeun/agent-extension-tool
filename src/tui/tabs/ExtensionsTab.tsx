import React, { useState } from "react";
import { Box, Text, useInput } from "ink";
import { SkillsTab } from "./SkillsTab.js";
import { HooksTab } from "./HooksTab.js";
import { CommandsTab } from "./CommandsTab.js";
import { AgentsTab } from "./AgentsTab.js";
import { PluginsTab } from "./PluginsTab.js";
import { MarketTab } from "./MarketTab.js";

type SubView = "skills" | "hooks" | "commands" | "agents" | "plugins" | "market";

const SUB_VIEWS: { key: SubView; label: string }[] = [
  { key: "skills", label: "Skills" },
  { key: "hooks", label: "Hooks" },
  { key: "commands", label: "Commands" },
  { key: "agents", label: "Agents" },
  { key: "plugins", label: "Plugins" },
  { key: "market", label: "Marketplace" },
];

export function ExtensionsTab() {
  const [view, setView] = useState<SubView>("skills");

  useInput((input, key) => {
    if (key.tab) {
      const idx = SUB_VIEWS.findIndex((sv) => sv.key === view);
      setView(SUB_VIEWS[(idx + 1) % SUB_VIEWS.length].key);
    }
  });

  return (
    <Box flexDirection="column">
      <Box marginBottom={1}>
        <Text bold>Extensions  </Text>
        {SUB_VIEWS.map((sv) => (
          <Box key={sv.key} marginRight={1}>
            <Text
              bold={sv.key === view}
              underline={sv.key === view}
              dimColor={sv.key !== view}
            >
              {sv.label}
            </Text>
          </Box>
        ))}
        <Box flexGrow={1} />
        <Text dimColor>Tab:switch</Text>
      </Box>

      {view === "skills" && <SkillsTab />}
      {view === "hooks" && <HooksTab />}
      {view === "commands" && <CommandsTab />}
      {view === "agents" && <AgentsTab />}
      {view === "plugins" && <PluginsTab />}
      {view === "market" && <MarketTab />}
    </Box>
  );
}
