import { useState, useEffect } from "react";
import { Box, useInput } from "ink";
import { Table } from "../components/Table.js";
import { DetailView, useDetailView, type DetailField } from "../components/DetailView.js";
import { SourceSummary } from "../components/SourceSummary.js";
import { SOURCE_COLORS } from "../constants.js";
import { PATHS } from "../../core/paths.js";
import { listHooks, getHookDetail, previewHook, type HookInfo } from "../../core/hooks.js";

function buildDetailFields(h: HookInfo): DetailField[] {
  const fields: DetailField[] = [
    { label: "Type", value: h.type },
    { label: "Matcher", value: h.matcher },
    { label: "Source", value: h.source, color: SOURCE_COLORS[h.source] },
    { label: "Path", value: h.sourcePath },
  ];
  if (h.command) fields.push({ label: "Command", value: h.command });
  if (h.url) fields.push({ label: "URL", value: h.url });
  if (h.server) fields.push({ label: "Server", value: h.server });
  if (h.tool) fields.push({ label: "Tool", value: h.tool });
  if (h.prompt) fields.push({ label: "Prompt", value: h.prompt });
  if (h.model) fields.push({ label: "Model", value: h.model });
  if (h.timeout != null) fields.push({ label: "Timeout", value: `${h.timeout}s` });
  if (h.statusMessage) fields.push({ label: "Status", value: h.statusMessage });
  if (h.condition) fields.push({ label: "If", value: h.condition });
  if (h.async) fields.push({ label: "Async", value: "yes" });
  if (h.asyncRewake) fields.push({ label: "Rewake", value: "yes" });
  if (h.once) fields.push({ label: "Once", value: "yes (removed after first run)" });
  return fields;
}

function parseHookPreviewOutput(r: { output?: string; error?: string; exitCode?: number | null; summary: string }): string[] {
  const lines: string[] = [];
  if (r.output) lines.push("── stdout ──", ...r.output.split("\n"));
  if (r.error) { if (lines.length) lines.push(""); lines.push("── stderr ──", ...r.error.split("\n")); }
  if (r.exitCode != null) lines.push("", `Exit: ${r.exitCode}`);
  return lines;
}

interface Props {
  isFocused?: boolean;
  onFocusUp?: () => void;
}

export function HooksTab({ isFocused = true, onFocusUp }: Props) {
  const [hooks, setHooks] = useState<HookInfo[]>([]);
  const [index, setIndex] = useState(0);
  const [previewTitle, setPreviewTitle] = useState("");

  useEffect(() => {
    listHooks({
      userSettingsPath: PATHS.settings,
      projectDir: process.cwd(),
      installedPluginsPath: PATHS.installedPlugins,
    }).then(setHooks);
  }, []);

  const selected = hooks[index];
  const detail = useDetailView({
    item: selected,
    previewLoader: async (h: HookInfo) => {
      const r = await previewHook(h);
      setPreviewTitle(r.summary);
      return parseHookPreviewOutput(r);
    },
  });

  useInput((input, key) => {
    if (!isFocused) return;
    if (detail.handleInput(input, key)) return;
    if (input === "p" && selected) { detail.openPreview(); return; }
    if (input === "j" || key.downArrow) {
      if (hooks.length > 0) setIndex((i) => Math.min(i + 1, hooks.length - 1));
    }
    if (input === "k" || key.upArrow) {
      if (index <= 0 && onFocusUp) { onFocusUp(); return; }
      setIndex((i) => Math.max(i - 1, 0));
    }
  });

  const rows = hooks.map((h) => ({
    event: h.event,
    type: h.type,
    source: h.source,
    detail: getHookDetail(h).slice(0, 35),
    matcher: h.matcher === "*" ? "*" : h.matcher.slice(0, 10),
  }));

  return (
    <Box flexDirection="column">
      <Table
        columns={[
          { key: "event", label: "Event", width: 22 },
          { key: "type", label: "Type", width: 10 },
          { key: "source", label: "Source", width: 9 },
          { key: "matcher", label: "Match", width: 12 },
          { key: "detail", label: "Detail", width: 36 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
      <DetailView
        item={selected}
        title={selected ? `${selected.event} [${selected.source}]` : undefined}
        fields={selected ? buildDetailFields(selected) : []}
        emptyMessage="No hooks configured. Add hooks in settings.json → hooks"
        mode={detail.mode}
        previewLines={detail.previewLines}
        previewScroll={detail.previewScroll}
        previewTitle={previewTitle}
        showLineNumbers={false}
        shortcuts="p:preview"
      />
      <SourceSummary items={hooks} label="hook" />
    </Box>
  );
}
