import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { readEnabledPlugins, setPluginEnabled, removePluginFromSettings, readExtraMarketplaces } from "../../src/core/settings.js";
import { mkdtemp, rm, cp } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

describe("settings", () => {
  let tmpDir: string;
  let settingsPath: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-settings-"));
    settingsPath = join(tmpDir, "settings.json");
    await cp(join(import.meta.dir, "../fixtures/settings.json"), settingsPath);
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("readEnabledPlugins returns plugin map", async () => {
    const plugins = await readEnabledPlugins(settingsPath);
    expect(plugins["superpowers@claude-plugins-official"]).toBe(true);
    expect(plugins["feature-dev@claude-plugins-official"]).toBe(false);
  });

  test("setPluginEnabled enables a disabled plugin", async () => {
    await setPluginEnabled(settingsPath, "feature-dev@claude-plugins-official", true);
    const plugins = await readEnabledPlugins(settingsPath);
    expect(plugins["feature-dev@claude-plugins-official"]).toBe(true);
  });

  test("setPluginEnabled disables an enabled plugin", async () => {
    await setPluginEnabled(settingsPath, "superpowers@claude-plugins-official", false);
    const plugins = await readEnabledPlugins(settingsPath);
    expect(plugins["superpowers@claude-plugins-official"]).toBe(false);
  });

  test("setPluginEnabled preserves other settings", async () => {
    await setPluginEnabled(settingsPath, "feature-dev@claude-plugins-official", true);
    const raw = await Bun.file(settingsPath).json();
    expect(raw.model).toBe("claude-opus-4-6[1m]");
    expect(raw.permissions.defaultMode).toBe("acceptEdits");
  });

  test("removePluginFromSettings removes the key", async () => {
    await removePluginFromSettings(settingsPath, "feature-dev@claude-plugins-official");
    const plugins = await readEnabledPlugins(settingsPath);
    expect(plugins["feature-dev@claude-plugins-official"]).toBeUndefined();
  });

  test("readExtraMarketplaces returns marketplace sources", async () => {
    const extras = await readExtraMarketplaces(settingsPath);
    expect(extras["claude-hud"]).toBeDefined();
    expect(extras["claude-hud"].source.repo).toBe("jarrodwatts/claude-hud");
  });
});
