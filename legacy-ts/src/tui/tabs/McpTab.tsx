import React, { useState, useEffect } from "react";
import { Box, useInput } from "ink";
import { Table } from "../components/Table.js";
import { PATHS } from "../../core/paths.js";
import { listInstalledPlugins } from "../../core/plugin.js";
import { readEnabledPlugins } from "../../core/settings.js";
import { listMcpServers, type McpServerInfo } from "../../core/mcp.js";

export function McpTab() {
  const [servers, setServers] = useState<McpServerInfo[]>([]);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    (async () => {
      const plugins = await listInstalledPlugins(PATHS.installedPlugins);
      const enabled = await readEnabledPlugins(PATHS.settings);
      const active = plugins.filter((p) => enabled[p.id] === true);
      setServers(await listMcpServers(active));
    })();
  }, []);

  useInput((input, key) => {
    if (input === "j" || key.downArrow) setIndex((i) => Math.min(i + 1, servers.length - 1));
    if (input === "k" || key.upArrow) setIndex((i) => Math.max(i - 1, 0));
  });

  const rows = servers.map((s) => ({
    name: s.name,
    command: [s.command, ...s.args].join(" "),
    plugin: s.pluginId,
  }));

  return (
    <Box flexDirection="column">
      <Table
        columns={[
          { key: "name", label: "Server", width: 25 },
          { key: "command", label: "Command", width: 25 },
          { key: "plugin", label: "Plugin", width: 30 },
        ]}
        rows={rows}
        selectedIndex={index}
      />
    </Box>
  );
}
