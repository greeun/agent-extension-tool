import { useState, useEffect } from "react";
import { Box, useInput } from "ink";
import { readFile } from "fs/promises";
import { Table } from "../components/Table.js";
import { DetailView, useDetailView } from "../components/DetailView.js";
import { SourceSummary } from "../components/SourceSummary.js";
import { SOURCE_COLORS } from "../constants.js";
import { listAllAgents, type AgentInfo } from "../../core/agents.js";
import { getProjectCount, type UsageIndex } from "../../core/project-usage.js";

interface Props {
  isFocused?: boolean;
  onFocusUp?: () => void;
  usageIndex?: UsageIndex;
}

export function AgentsTab({ isFocused = true, onFocusUp, usageIndex }: Props) {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [index, setIndex] = useState(0);

  useEffect(() => { listAllAgents({ projectDir: process.cwd() }).then(setAgents); }, []);

  const selected = agents[index];
  const detail = useDetailView({
    item: selected,
    previewLoader: (a: AgentInfo) =>
      readFile(a.sourcePath, "utf-8").then((c) => c.split("\n")),
  });

  useInput((input, key) => {
    if (!isFocused) return;
    if (detail.handleInput(input, key)) return;
    if (input === "p") { detail.openPreview(); return; }
    if (input === "j" || key.downArrow) {
      if (agents.length > 0) setIndex((i) => Math.min(i + 1, agents.length - 1));
    }
    if (input === "k" || key.upArrow) {
      if (index <= 0 && onFocusUp) { onFocusUp(); return; }
      setIndex((i) => Math.max(i - 1, 0));
    }
  });

  const rows = agents.map((a) => {
    const count = usageIndex ? getProjectCount(usageIndex, "agent", `${a.name}.md`) : 0;
    return {
      name: a.name,
      source: a.source,
      projects: count > 0 ? `${count}` : "─",
      description: a.description.slice(0, 36),
    };
  });

  return (
    <Box flexDirection="column">
      <Table
        columns={[
          { key: "name", label: "Agent", width: 24 },
          { key: "source", label: "Source", width: 9 },
          { key: "projects", label: "Proj", width: 6 },
          { key: "description", label: "Description", width: 40 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
      <DetailView
        item={selected}
        title={selected?.name}
        fields={selected ? [
          { label: "Source", value: selected.source, color: SOURCE_COLORS[selected.source] },
          { label: "Path", value: selected.sourcePath },
          ...(selected.plugin ? [{ label: "Plugin", value: selected.plugin }] : []),
          { label: "Description", value: selected.description || "(none)" },
        ] : []}
        emptyMessage="No agents found."
        mode={detail.mode}
        previewLines={detail.previewLines}
        previewScroll={detail.previewScroll}
        previewTitle={selected?.name}
        previewSubtitle={selected?.sourcePath}
        shortcuts="p:preview"
      />
      <SourceSummary items={agents} label="agent" />
    </Box>
  );
}
