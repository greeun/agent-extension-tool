import { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import { SkillsTab } from "./SkillsTab.js";
import { HooksTab } from "./HooksTab.js";
import { CommandsTab } from "./CommandsTab.js";
import { AgentsTab } from "./AgentsTab.js";
import { PluginsTab } from "./PluginsTab.js";
import { MarketTab } from "./MarketTab.js";
import { VaultTab } from "./VaultTab.js";
import { PATHS } from "../../core/paths.js";
import { scanProjectUsage, type UsageIndex } from "../../core/project-usage.js";

type SubView = "skills" | "hooks" | "commands" | "agents" | "plugins" | "market" | "vault";

const SUB_VIEWS: { key: SubView; label: string }[] = [
  { key: "vault", label: "Vault" },
  { key: "skills", label: "Skills" },
  { key: "hooks", label: "Hooks" },
  { key: "commands", label: "Commands" },
  { key: "agents", label: "Agents" },
  { key: "plugins", label: "Plugins" },
  { key: "market", label: "Marketplace" },
];

interface Props {
  focusLayer: "mainTab" | "subTab" | "content";
  setFocusLayer: (layer: "mainTab" | "subTab" | "content") => void;
  onSubViewChange?: (inSubView: boolean) => void;
}

export function ExtensionsTab({ focusLayer, setFocusLayer, onSubViewChange }: Props) {
  const [view, setView] = useState<SubView>("vault");
  const [usageIndex, setUsageIndex] = useState<UsageIndex>(new Map());

  useEffect(() => {
    scanProjectUsage(PATHS.projects, PATHS.vault, "default").then(setUsageIndex);
  }, []);

  useInput((_input, key) => {
    if (focusLayer !== "subTab") return;

    if (key.tab && key.shift) {
      const idx = SUB_VIEWS.findIndex((sv) => sv.key === view);
      setView(SUB_VIEWS[(idx - 1 + SUB_VIEWS.length) % SUB_VIEWS.length].key);
      return;
    }
    if (key.tab) {
      const idx = SUB_VIEWS.findIndex((sv) => sv.key === view);
      setView(SUB_VIEWS[(idx + 1) % SUB_VIEWS.length].key);
      return;
    }
    if (key.leftArrow) {
      const idx = SUB_VIEWS.findIndex((sv) => sv.key === view);
      setView(SUB_VIEWS[(idx - 1 + SUB_VIEWS.length) % SUB_VIEWS.length].key);
    }
    if (key.rightArrow) {
      const idx = SUB_VIEWS.findIndex((sv) => sv.key === view);
      setView(SUB_VIEWS[(idx + 1) % SUB_VIEWS.length].key);
    }
    if (key.upArrow) setFocusLayer("mainTab");
    if (key.downArrow) setFocusLayer("content");
  });

  return (
    <Box flexDirection="column">
      <Box marginBottom={1}>
        {SUB_VIEWS.map((sv) => (
          <Box key={sv.key} marginRight={1}>
            <Text
              bold={sv.key === view}
              inverse={sv.key === view && focusLayer === "subTab"}
              dimColor={sv.key !== view && focusLayer !== "subTab"}
            >
              {sv.key === view && focusLayer === "subTab" ? ` ${sv.label} ` : sv.label}
            </Text>
          </Box>
        ))}
        <Box flexGrow={1} />
        <Text dimColor>{focusLayer === "subTab" ? "←→/Tab:switch" : ""}</Text>
      </Box>

      {view === "skills" && <SkillsTab isFocused={focusLayer === "content"} onFocusUp={() => setFocusLayer("subTab")} usageIndex={usageIndex} />}
      {view === "hooks" && <HooksTab isFocused={focusLayer === "content"} onFocusUp={() => setFocusLayer("subTab")} />}
      {view === "commands" && <CommandsTab isFocused={focusLayer === "content"} onFocusUp={() => setFocusLayer("subTab")} usageIndex={usageIndex} />}
      {view === "agents" && <AgentsTab isFocused={focusLayer === "content"} onFocusUp={() => setFocusLayer("subTab")} usageIndex={usageIndex} />}
      {view === "plugins" && <PluginsTab isFocused={focusLayer === "content"} onFocusUp={() => setFocusLayer("subTab")} onSubViewChange={onSubViewChange} />}
      {view === "market" && <MarketTab isFocused={focusLayer === "content"} onFocusUp={() => setFocusLayer("subTab")} />}
      {view === "vault" && <VaultTab isFocused={focusLayer === "content"} onFocusUp={() => setFocusLayer("subTab")} onSubViewChange={onSubViewChange} />}
    </Box>
  );
}
