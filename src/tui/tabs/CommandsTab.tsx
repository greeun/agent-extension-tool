import React, { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import { Table } from "../components/Table.js";
import { DetailPanel } from "../components/DetailPanel.js";
import { listCommands, type CommandInfo } from "../../core/commands.js";

const SOURCE_COLORS: Record<string, string> = {
  user: "cyan",
  project: "green",
  plugin: "magenta",
};

export function CommandsTab() {
  const [commands, setCommands] = useState<CommandInfo[]>([]);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    listCommands({ projectDir: process.cwd() }).then(setCommands);
  }, []);

  useInput((input, key) => {
    if (input === "j" || key.downArrow) setIndex((i) => Math.min(i + 1, commands.length - 1));
    if (input === "k" || key.upArrow) setIndex((i) => Math.max(i - 1, 0));
  });

  const rows = commands.map((c) => ({
    name: `/${c.name}`,
    source: c.source,
    description: c.description.slice(0, 40),
  }));

  const selected = commands[index];

  return (
    <Box flexDirection="column">
      <Table
        columns={[
          { key: "name", label: "Command", width: 28 },
          { key: "source", label: "Source", width: 9 },
          { key: "description", label: "Description", width: 42 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
      {selected ? (
        <DetailPanel
          title={`/${selected.name}`}
          fields={[
            { label: "Source", value: selected.source, color: SOURCE_COLORS[selected.source] },
            { label: "Path", value: selected.sourcePath },
            ...(selected.plugin ? [{ label: "Plugin", value: selected.plugin }] : []),
            { label: "Description", value: selected.description || "(none)" },
          ]}
        />
      ) : (
        <DetailPanel lines={["No commands found."]} />
      )}
    </Box>
  );
}
