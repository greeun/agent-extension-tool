import { describe, test, expect } from "bun:test";
import { PATHS, AXT_CONFIG_DIR, AXT_CONFIG_PATH } from "../../src/core/paths.js";
import { homedir } from "os";
import { join } from "path";

describe("PATHS", () => {
  test("claudeDir is set", () => {
    expect(typeof PATHS.claudeDir).toBe("string");
    expect(PATHS.claudeDir.length).toBeGreaterThan(0);
  });

  test("settings path is inside claudeDir", () => {
    expect(PATHS.settings).toBe(join(PATHS.claudeDir, "settings.json"));
  });

  test("installedPlugins path is inside claudeDir", () => {
    expect(PATHS.installedPlugins).toBe(join(PATHS.claudeDir, "plugins", "installed_plugins.json"));
  });

  test("knownMarketplaces path is inside claudeDir", () => {
    expect(PATHS.knownMarketplaces).toBe(join(PATHS.claudeDir, "plugins", "known_marketplaces.json"));
  });

  test("skills path is inside claudeDir", () => {
    expect(PATHS.skills).toBe(join(PATHS.claudeDir, "skills"));
  });

  test("projects path is inside claudeDir", () => {
    expect(PATHS.projects).toBe(join(PATHS.claudeDir, "projects"));
  });

  test("usageSnapshot path is inside claudeDir", () => {
    expect(PATHS.usageSnapshot).toBe(join(PATHS.claudeDir, "usage-snapshot.json"));
  });

  test("codexSessions path is inside codexDir", () => {
    expect(PATHS.codexSessions).toBe(join(PATHS.codexDir, "sessions"));
  });

  test("cursorDir is inside home directory", () => {
    expect(PATHS.cursorDir).toBe(join(homedir(), ".cursor"));
  });

  test("vault path is inside axtDir", () => {
    expect(PATHS.vault).toBe(join(PATHS.axtDir, "vault"));
  });

  test("vaultSkills is inside vault", () => {
    expect(PATHS.vaultSkills).toBe(join(PATHS.vault, "skills"));
  });

  test("vaultCommands is inside vault", () => {
    expect(PATHS.vaultCommands).toBe(join(PATHS.vault, "commands"));
  });

  test("vaultAgents is inside vault", () => {
    expect(PATHS.vaultAgents).toBe(join(PATHS.vault, "agents"));
  });
});

describe("AXT_CONFIG_DIR", () => {
  test("is a non-empty string", () => {
    expect(typeof AXT_CONFIG_DIR).toBe("string");
    expect(AXT_CONFIG_DIR.length).toBeGreaterThan(0);
  });

  test("ends with /axt", () => {
    expect(AXT_CONFIG_DIR.endsWith("/axt") || AXT_CONFIG_DIR.endsWith("\\axt")).toBe(true);
  });
});

describe("AXT_CONFIG_PATH", () => {
  test("is config.json inside AXT_CONFIG_DIR", () => {
    expect(AXT_CONFIG_PATH).toBe(join(AXT_CONFIG_DIR, "config.json"));
  });
});
