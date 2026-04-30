import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { listMcpServers } from "../../src/core/mcp.js";
import { mkdtemp, rm, mkdir, writeFile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

describe("mcp", () => {
  let tmpDir: string;
  let cacheDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-mcp-"));
    cacheDir = join(tmpDir, "cache");
    const pluginDir = join(cacheDir, "mkt1", "plugin-a", "1.0.0");
    await mkdir(join(pluginDir, ".claude-plugin"), { recursive: true });
    await writeFile(join(pluginDir, ".claude-plugin", "plugin.json"), JSON.stringify({
      name: "plugin-a", description: "A plugin with MCP",
      mcpServers: { "my-server": { command: "node", args: ["server.js"] } },
    }));
    const pluginDir2 = join(cacheDir, "mkt1", "plugin-b", "2.0.0");
    await mkdir(join(pluginDir2, ".claude-plugin"), { recursive: true });
    await writeFile(join(pluginDir2, ".claude-plugin", "plugin.json"), JSON.stringify({ name: "plugin-b", description: "No MCP" }));
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("listMcpServers finds MCP servers from plugin manifests", async () => {
    const installedPlugins = [
      { id: "plugin-a@mkt1", installPath: join(cacheDir, "mkt1", "plugin-a", "1.0.0") },
      { id: "plugin-b@mkt1", installPath: join(cacheDir, "mkt1", "plugin-b", "2.0.0") },
    ];
    const servers = await listMcpServers(installedPlugins);
    expect(servers).toHaveLength(1);
    expect(servers[0].name).toBe("my-server");
    expect(servers[0].pluginId).toBe("plugin-a@mkt1");
    expect(servers[0].command).toBe("node");
  });
});
