import React, { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import { Table } from "../components/Table.js";
import { DetailPanel } from "../components/DetailPanel.js";
import { listAllAgents, type AgentInfo } from "../../core/agents.js";

const SOURCE_COLORS: Record<string, string> = {
  user: "cyan",
  project: "green",
  plugin: "magenta",
};

export function AgentsTab() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [index, setIndex] = useState(0);

  useEffect(() => { listAllAgents({ projectDir: process.cwd() }).then(setAgents); }, []);

  useInput((input, key) => {
    if (input === "j" || key.downArrow) setIndex((i) => Math.min(i + 1, agents.length - 1));
    if (input === "k" || key.upArrow) setIndex((i) => Math.max(i - 1, 0));
  });

  const rows = agents.map((a) => ({
    name: a.name,
    source: a.source,
    description: a.description.slice(0, 40),
  }));

  const selected = agents[index];

  return (
    <Box flexDirection="column">
      <Table
        columns={[
          { key: "name", label: "Agent", width: 28 },
          { key: "source", label: "Source", width: 9 },
          { key: "description", label: "Description", width: 42 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
      {selected ? (
        <DetailPanel
          title={selected.name}
          fields={[
            { label: "Source", value: selected.source, color: SOURCE_COLORS[selected.source] },
            { label: "Path", value: selected.sourcePath },
            ...(selected.plugin ? [{ label: "Plugin", value: selected.plugin }] : []),
            { label: "Description", value: selected.description || "(none)" },
          ]}
        />
      ) : (
        <DetailPanel lines={["No agents found."]} />
      )}

      <Box marginTop={1}>
        <Text dimColor>
          {agents.length} agent(s) from {new Set(agents.map((a) => a.source)).size} source(s)
          {" | "}
          <Text color="cyan">user</Text> <Text color="green">project</Text>{" "}
          <Text color="magenta">plugin</Text>
        </Text>
      </Box>
    </Box>
  );
}
