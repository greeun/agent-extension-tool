import { useState, useEffect } from "react";
import { Box, useInput, useStdout } from "ink";
import { Table } from "../components/Table.js";
import { DetailView } from "../components/DetailView.js";
import { SOURCE_COLORS } from "../constants.js";
import { listCommands, type CommandInfo } from "../../core/commands.js";
import { getProjectCount, type UsageIndex } from "../../core/project-usage.js";
import { useDetailScroll } from "../components/useDetailScroll.js";
import { useDetailMaxHeight } from "../components/useDetailMaxHeight.js";
import { flattenDetailFields } from "../components/flattenDetailFields.js";

interface Props {
  isFocused?: boolean;
  onFocusUp?: () => void;
  usageIndex?: UsageIndex;
}

export function CommandsTab({ isFocused = true, onFocusUp, usageIndex }: Props) {
  const [commands, setCommands] = useState<CommandInfo[]>([]);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    listCommands({ projectDir: process.cwd() }).then(setCommands);
  }, []);

  const rows = commands.map((c) => {
    const count = usageIndex ? getProjectCount(usageIndex, "command", `${c.name}.md`) : 0;
    return {
      name: `/${c.name}`,
      source: c.source,
      projects: count > 0 ? `${count}` : "─",
      description: c.description.slice(0, 36),
    };
  });

  const selected = commands[index];

  const { stdout } = useStdout();
  const cols = stdout?.columns ?? 80;
  const detailFields = selected ? [
    { label: "Source", value: selected.source, color: SOURCE_COLORS[selected.source] },
    { label: "Path", value: selected.sourcePath },
    ...(selected.plugin ? [{ label: "Plugin", value: selected.plugin }] : []),
    { label: "Description", value: selected.description || "(none)" },
  ] : [];
  const detailMaxHeight = useDetailMaxHeight(10);
  const flat = flattenDetailFields(detailFields, cols - 4);
  const viewport = Math.max(1, detailMaxHeight - 4);
  const detailScroll = useDetailScroll({
    totalLines: flat.length,
    viewportLines: viewport,
    resetKey: selected?.sourcePath,
  });

  useInput((input, key) => {
    if (!isFocused) return;
    if (detailScroll.handleInput(input, key)) return;
    if (input === "j" || key.downArrow) {
      if (commands.length > 0) setIndex((i) => Math.min(i + 1, commands.length - 1));
    }
    if (input === "k" || key.upArrow) {
      if (index <= 0 && onFocusUp) { onFocusUp(); return; }
      setIndex((i) => Math.max(i - 1, 0));
    }
  });

  return (
    <Box flexDirection="column">
      <Table
        columns={[
          { key: "name", label: "Command", width: 24 },
          { key: "source", label: "Source", width: 9 },
          { key: "projects", label: "Proj", width: 6 },
          { key: "description", label: "Description", width: 40 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
      <DetailView
        item={selected}
        title={selected ? `/${selected.name}` : undefined}
        fields={detailFields}
        emptyMessage="No commands found."
        shortcuts="Enter:detail  Esc:back  j/k:scroll"
        detailFocused={detailScroll.focused}
        detailScroll={detailScroll.scroll}
        detailMaxHeight={detailMaxHeight}
        detailContentWidth={cols - 4}
      />
    </Box>
  );
}
