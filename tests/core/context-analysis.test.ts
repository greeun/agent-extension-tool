import { describe, test, expect, beforeAll, afterAll } from "bun:test";
import { estimateTokens, collectContextSources, analyzeContext, addHints, type ContextSource } from "../../src/core/context-analysis.js";
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

describe("analyzeContext", () => {
  const testDir = join(tmpdir(), `axt-ctx-analyze-${Date.now()}`);
  const homeDir = join(testDir, "home");
  const projectDir = join(testDir, "project");

  beforeAll(() => {
    mkdirSync(join(homeDir, ".claude"), { recursive: true });
    mkdirSync(join(projectDir, ".claude"), { recursive: true });
    writeFileSync(join(projectDir, "CLAUDE.md"), "A".repeat(3500));
  });

  afterAll(() => {
    rmSync(testDir, { recursive: true, force: true });
  });

  test("returns ContextAnalysis with totalTokens and usedPercent", async () => {
    const result = await analyzeContext({
      homeDir, projectDir,
      installedPluginsPath: join(homeDir, ".claude", "plugins", "installed_plugins.json"),
      model: "claude-opus-4-6",
      avgTurnsPerSession: 30, avgSessionsPerDay: 5,
    });
    expect(result.totalTokens).toBeGreaterThan(0);
    expect(result.contextWindowSize).toBe(1_000_000);
    expect(result.usedPercent).toBeGreaterThan(0);
    expect(result.usedPercent).toBeLessThan(100);
    expect(result.model).toBe("claude-opus-4-6");
    expect(result.sources.length).toBeGreaterThan(0);
  });

  test("costImpact is calculated correctly", async () => {
    const result = await analyzeContext({
      homeDir, projectDir,
      installedPluginsPath: join(homeDir, ".claude", "plugins", "installed_plugins.json"),
      model: "claude-opus-4-6",
      avgTurnsPerSession: 30, avgSessionsPerDay: 5,
    });
    expect(result.costImpact.cacheWriteCost).toBeGreaterThan(0);
    expect(result.costImpact.cacheReadCostPerTurn).toBeGreaterThan(0);
    expect(result.costImpact.perSessionCost).toBeGreaterThan(result.costImpact.cacheWriteCost);
    expect(result.costImpact.monthlyCost).toBeGreaterThan(0);
  });
});

describe("addHints", () => {
  test("adds hint to large CLAUDE.md sources", () => {
    const sources: ContextSource[] = [
      { name: "CLAUDE.md (project)", category: "claude-md", path: "/p/CLAUDE.md", chars: 7000, estimatedTokens: 2000, percentage: 30, actionable: true },
    ];
    addHints(sources);
    expect(sources[0].hint).toBeDefined();
    expect(sources[0].hint).toContain("tok");
  });

  test("adds hint for system-prompt fixed sources", () => {
    const sources: ContextSource[] = [
      { name: "Base system prompt", category: "system-prompt", path: "", chars: 0, estimatedTokens: 4200, percentage: 25, actionable: false },
    ];
    addHints(sources);
    expect(sources[0].hint).toContain("fixed");
  });

  test("marks mcp-tools as deferred", () => {
    const sources: ContextSource[] = [
      { name: "MCP: context7", category: "mcp-tools", path: "", chars: 30, estimatedTokens: 9, percentage: 1, actionable: false },
    ];
    addHints(sources);
    expect(sources[0].hint).toContain("deferred");
  });
});

describe("integration: full analysis flow", () => {
  const testDir = join(tmpdir(), `axt-ctx-integ-${Date.now()}`);
  const homeDir = join(testDir, "home");
  const projectDir = join(testDir, "project");

  beforeAll(() => {
    const claudeDir = join(homeDir, ".claude");
    const projectSettingsKey = projectDir.replace(/\//g, "-").replace(/^-/, "");
    const memDir = join(claudeDir, "projects", projectSettingsKey, "memory");
    mkdirSync(memDir, { recursive: true });
    mkdirSync(join(claudeDir, "skills"), { recursive: true });
    mkdirSync(join(claudeDir, "commands"), { recursive: true });
    mkdirSync(join(claudeDir, "agents"), { recursive: true });
    mkdirSync(join(projectDir, ".claude"), { recursive: true });

    writeFileSync(join(homeDir, "CLAUDE.md"), "Global rules: be helpful.");
    writeFileSync(join(projectDir, "CLAUDE.md"), "Project: axt\nLots of instructions here.\n".repeat(50));
    writeFileSync(join(claudeDir, "settings.json"), JSON.stringify({ hooks: {} }));
    writeFileSync(join(memDir, "MEMORY.md"), "- [user_role](user_role.md) — developer\n".repeat(10));
    writeFileSync(join(memDir, "user_role.md"), "---\nname: user_role\ntype: user\n---\nSenior developer");
  });

  afterAll(() => {
    rmSync(testDir, { recursive: true, force: true });
  });

  test("produces valid ContextAnalysis with all expected categories", async () => {
    const result = await analyzeContext({
      homeDir,
      projectDir,
      installedPluginsPath: join(homeDir, ".claude", "plugins", "installed_plugins.json"),
      model: "claude-opus-4-6",
      avgTurnsPerSession: 30,
      avgSessionsPerDay: 5,
    });

    expect(result.totalTokens).toBeGreaterThan(4200 + 280);
    expect(result.contextWindowSize).toBe(1_000_000);
    expect(result.usedPercent).toBeGreaterThan(0);

    const categories = new Set(result.sources.map((s) => s.category));
    expect(categories.has("system-prompt")).toBe(true);
    expect(categories.has("claude-md")).toBe(true);
    expect(categories.has("user-context")).toBe(true);
    expect(categories.has("git-status")).toBe(true);
    expect(categories.has("memory")).toBe(true);
    expect(categories.has("settings")).toBe(true);

    const percentSum = result.sources.reduce((sum, s) => sum + s.percentage, 0);
    expect(percentSum).toBeCloseTo(100, 0);

    expect(result.costImpact.monthlyCost).toBeGreaterThan(0);
    expect(result.costImpact.perSessionCost).toBeGreaterThan(0);
  });
});

