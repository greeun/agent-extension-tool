import { readJson } from "./json-io.js";
import { join } from "path";

interface McpServerDef {
  command: string;
  args?: string[];
  env?: Record<string, string>;
}

interface PluginManifest {
  name: string;
  description?: string;
  mcpServers?: Record<string, McpServerDef>;
}

export interface McpServerInfo {
  name: string;
  pluginId: string;
  command: string;
  args: string[];
  env: Record<string, string>;
}

export async function listMcpServers(
  installedPlugins: Array<{ id: string; installPath: string }>
): Promise<McpServerInfo[]> {
  const servers: McpServerInfo[] = [];
  for (const plugin of installedPlugins) {
    const manifestPath = join(plugin.installPath, ".claude-plugin", "plugin.json");
    const manifest = await readJson<PluginManifest>(manifestPath, { fallback: { name: "" } });
    if (!manifest.mcpServers) continue;
    for (const [name, def] of Object.entries(manifest.mcpServers)) {
      servers.push({ name, pluginId: plugin.id, command: def.command, args: def.args ?? [], env: def.env ?? {} });
    }
  }
  return servers;
}
