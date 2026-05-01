import { useState, useEffect } from "react";
import { Box, useInput } from "ink";
import { Table } from "../components/Table.js";
import { DetailView } from "../components/DetailView.js";
import { SOURCE_COLORS } from "../constants.js";
import { listCommands, type CommandInfo } from "../../core/commands.js";

interface Props {
  isFocused?: boolean;
  onFocusUp?: () => void;
}

export function CommandsTab({ isFocused = true, onFocusUp }: Props) {
  const [commands, setCommands] = useState<CommandInfo[]>([]);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    listCommands({ projectDir: process.cwd() }).then(setCommands);
  }, []);

  useInput((input, key) => {
    if (!isFocused) return;
    if (input === "j" || key.downArrow) {
      if (commands.length > 0) setIndex((i) => Math.min(i + 1, commands.length - 1));
    }
    if (input === "k" || key.upArrow) {
      if (index <= 0 && onFocusUp) { onFocusUp(); return; }
      setIndex((i) => Math.max(i - 1, 0));
    }
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
      <DetailView
        item={selected}
        title={selected ? `/${selected.name}` : undefined}
        fields={selected ? [
          { label: "Source", value: selected.source, color: SOURCE_COLORS[selected.source] },
          { label: "Path", value: selected.sourcePath },
          ...(selected.plugin ? [{ label: "Plugin", value: selected.plugin }] : []),
          { label: "Description", value: selected.description || "(none)" },
        ] : []}
        emptyMessage="No commands found."
      />
    </Box>
  );
}
