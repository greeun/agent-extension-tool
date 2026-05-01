import { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import { Table } from "../components/Table.js";
import { DetailView, useDetailView } from "../components/DetailView.js";
import { loadProjectContext, type ProjectContextItem } from "../../core/project-context.js";

function sourceIcon(source: string): string {
  switch (source) {
    case "global": return "●";
    case "user": return "◆";
    case "project": return "■";
    case "memory": return "◇";
    default: return "○";
  }
}

interface Props {
  isFocused?: boolean;
  onFocusUp?: () => void;
}

export function ProjectTab({ isFocused = true, onFocusUp }: Props) {
  const [items, setItems] = useState<ProjectContextItem[]>([]);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    loadProjectContext(process.cwd()).then(setItems);
  }, []);

  const selected = items[index];
  const detail = useDetailView({
    item: selected,
    previewLoader: (item: ProjectContextItem) => item.content.split("\n"),
  });

  useInput((input, key) => {
    if (!isFocused) return;
    if (detail.handleInput(input, key)) return;
    if (input === "p" && selected) { detail.openPreview(); return; }
    if (input === "j" || key.downArrow) {
      if (items.length > 0) {
        setIndex((i) => Math.min(i + 1, items.length - 1));
        detail.closePreview();
      }
    }
    if (input === "k" || key.upArrow) {
      if (index <= 0 && onFocusUp) { onFocusUp(); return; }
      setIndex((i) => Math.max(i - 1, 0));
      detail.closePreview();
    }
  });

  const rows = items.map((item) => ({
    name: `${sourceIcon(item.source)} ${item.name}`,
    source: item.source,
    lines: String(item.lines),
    path: item.path,
  }));

  return (
    <Box flexDirection="column">
      <Box marginBottom={1}>
        <Text bold>Project Context </Text>
        <Text dimColor>({items.length} files)</Text>
      </Box>

      <Table
        columns={[
          { key: "name", label: "File", width: 30 },
          { key: "source", label: "Source", width: 10 },
          { key: "lines", label: "Lines", width: 8 },
          { key: "path", label: "Path", width: 40 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
      <DetailView
        item={selected}
        title={selected?.name}
        fields={selected ? [
          { label: "Source", value: selected.source },
          { label: "Path", value: selected.path },
          { label: "Lines", value: String(selected.lines) },
        ] : []}
        emptyMessage="No project context files found."
        mode={detail.mode}
        previewLines={detail.previewLines}
        previewScroll={detail.previewScroll}
        previewTitle={selected?.name}
        previewSubtitle={selected?.path}
        shortcuts="p:preview"
      />
    </Box>
  );
}
