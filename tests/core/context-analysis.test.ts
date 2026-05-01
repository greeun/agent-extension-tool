import { describe, test, expect, beforeAll, afterAll } from "bun:test";
import { estimateTokens, collectContextSources, type ContextSource } from "../../src/core/context-analysis.js";
import { mkdirSync, writeFileSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";

describe("estimateTokens", () => {
  test("estimates English text at ~1 token per 3.5 chars", () => {
    const text = "Hello world, this is a test string.";
    const tokens = estimateTokens(text);
    expect(tokens).toBe(Math.ceil(text.length / 3.5));
  });

  test("estimates Korean text at ~1 token per 1.5 chars", () => {
    const text = "안녕하세요 테스트입니다";
    const tokens = estimateTokens(text);
    expect(tokens).toBeGreaterThan(Math.ceil(text.length / 3.5));
  });

  test("handles mixed content", () => {
    const text = "Hello 안녕 world 세계";
    const tokens = estimateTokens(text);
    expect(tokens).toBeGreaterThan(0);
  });

  test("returns 0 for empty string", () => {
    expect(estimateTokens("")).toBe(0);
  });
});

describe("collectContextSources", () => {
  const testDir = join(tmpdir(), `axt-ctx-test-${Date.now()}`);
  const homeDir = join(testDir, "home");
  const projectDir = join(testDir, "project");

  beforeAll(() => {
    mkdirSync(join(homeDir, ".claude", "skills"), { recursive: true });
    mkdirSync(join(homeDir, ".claude", "commands"), { recursive: true });
    mkdirSync(join(homeDir, ".claude", "agents"), { recursive: true });
    mkdirSync(join(projectDir, ".claude"), { recursive: true });
    writeFileSync(join(homeDir, "CLAUDE.md"), "# Global instructions\nDo things.");
    writeFileSync(join(projectDir, "CLAUDE.md"), "# Project rules\nBuild stuff.\nMore lines here.");
    writeFileSync(join(homeDir, ".claude", "settings.json"), JSON.stringify({ permissions: { allow: ["Read"] } }));
  });

  afterAll(() => {
    rmSync(testDir, { recursive: true, force: true });
  });

  test("collects CLAUDE.md files", async () => {
    const sources = await collectContextSources({ homeDir, projectDir, installedPluginsPath: join(homeDir, ".claude", "plugins", "installed_plugins.json") });
    const claudeMdSources = sources.filter((s) => s.category === "claude-md");
    expect(claudeMdSources.length).toBeGreaterThanOrEqual(2);
    expect(claudeMdSources.some((s) => s.name.includes("global"))).toBe(true);
    expect(claudeMdSources.some((s) => s.name.includes("project"))).toBe(true);
  });

  test("all sources with content have estimatedTokens > 0", async () => {
    const sources = await collectContextSources({ homeDir, projectDir, installedPluginsPath: join(homeDir, ".claude", "plugins", "installed_plugins.json") });
    const withContent = sources.filter((s) => s.chars > 0);
    for (const s of withContent) {
      expect(s.estimatedTokens).toBeGreaterThan(0);
    }
  });

  test("includes system-prompt as fixed source", async () => {
    const sources = await collectContextSources({ homeDir, projectDir, installedPluginsPath: join(homeDir, ".claude", "plugins", "installed_plugins.json") });
    const sysPrompt = sources.find((s) => s.category === "system-prompt");
    expect(sysPrompt).toBeDefined();
    expect(sysPrompt!.estimatedTokens).toBe(4200);
  });

  test("includes user-context as fixed source", async () => {
    const sources = await collectContextSources({ homeDir, projectDir, installedPluginsPath: join(homeDir, ".claude", "plugins", "installed_plugins.json") });
    const userCtx = sources.find((s) => s.category === "user-context");
    expect(userCtx).toBeDefined();
    expect(userCtx!.estimatedTokens).toBe(280);
  });
});
