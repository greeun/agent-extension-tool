import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { listInstalledPlugins, getPluginInfo, addInstalledPlugin, removeInstalledPlugin } from "../../src/core/plugin.js";
import { mkdtemp, rm, cp } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

describe("plugin", () => {
  let tmpDir: string;
  let ipPath: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-plugin-"));
    ipPath = join(tmpDir, "installed_plugins.json");
    await cp(join(import.meta.dir, "../fixtures/installed_plugins.json"), ipPath);
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("listInstalledPlugins returns all plugins", async () => {
    const plugins = await listInstalledPlugins(ipPath);
    expect(plugins).toHaveLength(2);
    expect(plugins[0].id).toBe("superpowers@claude-plugins-official");
    expect(plugins[0].version).toBe("5.0.7");
  });

  test("getPluginInfo returns specific plugin", async () => {
    const info = await getPluginInfo(ipPath, "superpowers@claude-plugins-official");
    expect(info).not.toBeNull();
    expect(info!.version).toBe("5.0.7");
    expect(info!.installPath).toContain("superpowers");
  });

  test("getPluginInfo returns null for unknown plugin", async () => {
    const info = await getPluginInfo(ipPath, "nonexistent@nowhere");
    expect(info).toBeNull();
  });

  test("addInstalledPlugin adds new entry", async () => {
    await addInstalledPlugin(ipPath, { id: "test-plugin@test-market", version: "1.0.0", installPath: "/tmp/test", scope: "user" });
    const info = await getPluginInfo(ipPath, "test-plugin@test-market");
    expect(info).not.toBeNull();
    expect(info!.version).toBe("1.0.0");
  });

  test("removeInstalledPlugin removes entry", async () => {
    await removeInstalledPlugin(ipPath, "context7@claude-plugins-official");
    const plugins = await listInstalledPlugins(ipPath);
    expect(plugins).toHaveLength(1);
    expect(plugins[0].id).toBe("superpowers@claude-plugins-official");
  });
});
