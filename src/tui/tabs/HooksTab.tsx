import React, { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import { Table } from "../components/Table.js";
import { PATHS } from "../../core/paths.js";
import { listHooks, getHookDetail, type HookInfo } from "../../core/hooks.js";

const SOURCE_COLORS: Record<string, string> = {
  user: "cyan",
  project: "green",
  local: "yellow",
  plugin: "magenta",
};

export function HooksTab() {
  const [hooks, setHooks] = useState<HookInfo[]>([]);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    listHooks({
      userSettingsPath: PATHS.settings,
      projectDir: process.cwd(),
    }).then(setHooks);
  }, []);

  useInput((input, key) => {
    if (input === "j" || key.downArrow) setIndex((i) => Math.min(i + 1, hooks.length - 1));
    if (input === "k" || key.upArrow) setIndex((i) => Math.max(i - 1, 0));
  });

  const rows = hooks.map((h) => ({
    event: h.event,
    type: h.type,
    source: h.source,
    detail: getHookDetail(h).slice(0, 35),
    matcher: h.matcher === "*" ? "*" : h.matcher.slice(0, 10),
  }));

  const selected = hooks[index];

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

      {selected && (
        <Box flexDirection="column" borderStyle="single" paddingX={1} marginTop={1}>
          <Box>
            <Text bold>{selected.event}</Text>
            <Text> </Text>
            <Text color={SOURCE_COLORS[selected.source] ?? "white"}>
              [{selected.source}]
            </Text>
          </Box>

          <Text>Type:    {selected.type}</Text>
          <Text>Matcher: {selected.matcher}</Text>
          <Text>Source:  {selected.sourcePath}</Text>

          {selected.command && <Text>Command: {selected.command}</Text>}
          {selected.url && <Text>URL:     {selected.url}</Text>}
          {selected.server && <Text>Server:  {selected.server}  Tool: {selected.tool}</Text>}
          {selected.prompt && <Text>Prompt:  {selected.prompt.slice(0, 80)}</Text>}
          {selected.model && <Text>Model:   {selected.model}</Text>}
          {selected.timeout != null && <Text>Timeout: {selected.timeout}s</Text>}
          {selected.statusMessage && <Text>Status:  {selected.statusMessage}</Text>}
          {selected.condition && <Text>If:      {selected.condition}</Text>}
          {selected.async && <Text>Async:   yes</Text>}
          {selected.asyncRewake && <Text>Rewake:  yes</Text>}
          {selected.once && <Text>Once:    yes (removed after first run)</Text>}
        </Box>
      )}

      {hooks.length === 0 && (
        <Text dimColor>No hooks configured. Add hooks in settings.json → hooks</Text>
      )}

      <Box marginTop={1}>
        <Text dimColor>
          {hooks.length} hook(s) from {new Set(hooks.map((h) => h.source)).size} source(s)
          {" | "}
          <Text color="cyan">user</Text> <Text color="green">project</Text>{" "}
          <Text color="yellow">local</Text> <Text color="magenta">plugin</Text>
        </Text>
      </Box>
    </Box>
  );
}
