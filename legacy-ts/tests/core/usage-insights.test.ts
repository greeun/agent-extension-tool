import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, mkdir, copyFile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { loadUsageInsights } from "../../src/core/usage-insights.js";

const FIXTURES = join(import.meta.dir, "../fixtures");

describe("loadUsageInsights", () => {
  let tmpDir: string;
  let projectsDir: string;
  let usageSnapshotPath: string;
  let cacheDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-insights-"));
    projectsDir = join(tmpDir, "projects");
    usageSnapshotPath = join(tmpDir, "usage-snapshot.json");
    cacheDir = join(tmpDir, "cache");
    await mkdir(cacheDir, { recursive: true });

    const projDir = join(projectsDir, "test-project");
    await mkdir(projDir, { recursive: true });

    // sess-skills-001: has Skill + Agent calls, 60k tokens
    await copyFile(
      join(FIXTURES, "session-with-skill-calls.jsonl"),
      join(projDir, "sess-skills-001.jsonl")
    );
    // sess-large: has 200k input tokens (large context)
    await copyFile(
      join(FIXTURES, "session-large-context.jsonl"),
      join(projDir, "sess-large.jsonl")
    );

    await copyFile(join(FIXTURES, "usage-snapshot.json"), usageSnapshotPath);
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true });
  });

  test("planLimits reads usage-snapshot.json", async () => {
    const result = await loadUsageInsights({ days: 7, projectsDir, usageSnapshotPath, cacheDir });
    expect(result.planLimits).not.toBeNull();
    expect(result.planLimits!.sessionUsedPct).toBe(14);
    expect(result.planLimits!.weekUsedPct).toBe(8);
    expect(result.planLimits!.sessionResetsAt).toBeInstanceOf(Date);
    expect(result.planLimits!.weekResetsAt).toBeInstanceOf(Date);
  });

  test("planLimits is null when snapshot missing", async () => {
    const result = await loadUsageInsights({
      days: 7,
      projectsDir,
      usageSnapshotPath: join(tmpDir, "nonexistent.json"),
      cacheDir,
    });
    expect(result.planLimits).toBeNull();
  });

  test("skillBreakdown identifies skills from JSONL", async () => {
    const result = await loadUsageInsights({ days: 7, projectsDir, usageSnapshotPath, cacheDir });
    const names = result.skillBreakdown.map((s) => s.name);
    expect(names).toContain("superpowers:brainstorming");
    expect(names).toContain("superpowers:writing-plans");
  });

  test("subagentBreakdown identifies agents from JSONL", async () => {
    const result = await loadUsageInsights({ days: 7, projectsDir, usageSnapshotPath, cacheDir });
    const names = result.subagentBreakdown.map((s) => s.name);
    expect(names).toContain("general-purpose");
  });

  test("pluginBreakdown derives from skill prefix", async () => {
    const result = await loadUsageInsights({ days: 7, projectsDir, usageSnapshotPath, cacheDir });
    const names = result.pluginBreakdown.map((s) => s.name);
    expect(names).toContain("superpowers");
  });

  test("subagentHeavyPct reflects sessions with Agent calls", async () => {
    const result = await loadUsageInsights({ days: 7, projectsDir, usageSnapshotPath, cacheDir });
    // sess-skills-001 has Agent calls → subagentHeavy
    expect(result.subagentHeavyPct).toBeGreaterThan(0);
    expect(result.subagentHeavyPct).toBeLessThan(100);
  });

  test("largeContextPct reflects sessions with input_tokens > 150000", async () => {
    const result = await loadUsageInsights({ days: 7, projectsDir, usageSnapshotPath, cacheDir });
    // sess-large: input_tokens=200000 → largeContext
    // sess-skills-001: input_tokens=50000 → not large
    // large session tokens = 230000, total ≈ 310000 → ~74%
    expect(result.largeContextPct).toBeGreaterThan(50);
  });

  test("tokenPct values sum to ≤ 100 for each breakdown", async () => {
    const result = await loadUsageInsights({ days: 7, projectsDir, usageSnapshotPath, cacheDir });
    const skillSum = result.skillBreakdown.reduce((s, x) => s + x.tokenPct, 0);
    const agentSum = result.subagentBreakdown.reduce((s, x) => s + x.tokenPct, 0);
    expect(skillSum).toBeLessThanOrEqual(100.1);
    expect(agentSum).toBeLessThanOrEqual(100.1);
  });

  test("returns empty breakdowns when no JSONL files exist", async () => {
    await rm(projectsDir, { recursive: true });
    await mkdir(projectsDir, { recursive: true });
    const result = await loadUsageInsights({ days: 7, projectsDir, usageSnapshotPath, cacheDir });
    expect(result.skillBreakdown).toHaveLength(0);
    expect(result.subagentBreakdown).toHaveLength(0);
  });
});
