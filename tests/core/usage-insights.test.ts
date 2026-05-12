import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, mkdir, writeFile, copyFile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { loadUsageInsights } from "../../src/core/usage-insights.js";

const FIXTURES = join(import.meta.dir, "../fixtures");

describe("loadUsageInsights", () => {
  let tmpDir: string;
  let projectsDir: string;
  let sessionMetaDir: string;
  let usageSnapshotPath: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-insights-"));
    projectsDir = join(tmpDir, "projects");
    sessionMetaDir = join(tmpDir, "session-meta");
    usageSnapshotPath = join(tmpDir, "usage-snapshot.json");

    await mkdir(projectsDir, { recursive: true });
    await mkdir(sessionMetaDir, { recursive: true });

    // session-meta fixture: split array into individual files
    const metas = JSON.parse(
      await Bun.file(join(FIXTURES, "session-meta-with-skills.json")).text()
    ) as Array<{ session_id: string; [key: string]: unknown }>;
    for (const m of metas) {
      await writeFile(join(sessionMetaDir, `${m.session_id}.json`), JSON.stringify(m));
    }

    // JSONL fixture: place in projects/test-project/sess-skills-001.jsonl
    const skillSessionDir = join(projectsDir, "test-project");
    await mkdir(skillSessionDir, { recursive: true });
    await copyFile(
      join(FIXTURES, "session-with-skill-calls.jsonl"),
      join(skillSessionDir, "sess-skills-001.jsonl")
    );

    // usage-snapshot fixture
    await copyFile(join(FIXTURES, "usage-snapshot.json"), usageSnapshotPath);
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true });
  });

  test("planLimits reads usage-snapshot.json", async () => {
    const result = await loadUsageInsights({
      days: 7,
      projectsDir,
      sessionMetaDir,
      usageSnapshotPath,
    });
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
      sessionMetaDir,
      usageSnapshotPath: join(tmpDir, "nonexistent.json"),
    });
    expect(result.planLimits).toBeNull();
  });

  test("skillBreakdown identifies skills from JSONL", async () => {
    const result = await loadUsageInsights({
      days: 7,
      projectsDir,
      sessionMetaDir,
      usageSnapshotPath,
    });
    const names = result.skillBreakdown.map((s) => s.name);
    expect(names).toContain("superpowers:brainstorming");
    expect(names).toContain("superpowers:writing-plans");
  });

  test("subagentBreakdown identifies agents from JSONL", async () => {
    const result = await loadUsageInsights({
      days: 7,
      projectsDir,
      sessionMetaDir,
      usageSnapshotPath,
    });
    const names = result.subagentBreakdown.map((s) => s.name);
    expect(names).toContain("general-purpose");
  });

  test("pluginBreakdown derives from skill prefix", async () => {
    const result = await loadUsageInsights({
      days: 7,
      projectsDir,
      sessionMetaDir,
      usageSnapshotPath,
    });
    const names = result.pluginBreakdown.map((s) => s.name);
    expect(names).toContain("superpowers");
  });

  test("subagentHeavyPct reflects sessions with Agent calls", async () => {
    const result = await loadUsageInsights({
      days: 7,
      projectsDir,
      sessionMetaDir,
      usageSnapshotPath,
    });
    // sess-skills-001 has Agent: 1, total tokens = 60000
    // grandTotal = 315000, subagentHeavy = 60000 → ~19%
    expect(result.subagentHeavyPct).toBeGreaterThan(0);
    expect(result.subagentHeavyPct).toBeLessThan(100);
  });

  test("largeContextPct reflects sessions with input_tokens > 150000", async () => {
    const result = await loadUsageInsights({
      days: 7,
      projectsDir,
      sessionMetaDir,
      usageSnapshotPath,
    });
    // sess-skills-002: input_tokens=200000 → largeContext
    // 230000 / 315000 ≈ 73%
    expect(result.largeContextPct).toBeGreaterThan(50);
  });

  test("tokenPct values sum to ≤ 100 for each breakdown", async () => {
    const result = await loadUsageInsights({
      days: 7,
      projectsDir,
      sessionMetaDir,
      usageSnapshotPath,
    });
    const skillSum = result.skillBreakdown.reduce((s, x) => s + x.tokenPct, 0);
    const agentSum = result.subagentBreakdown.reduce((s, x) => s + x.tokenPct, 0);
    expect(skillSum).toBeLessThanOrEqual(100.1);
    expect(agentSum).toBeLessThanOrEqual(100.1);
  });

  test("returns empty breakdowns when no JSONL files exist", async () => {
    await rm(projectsDir, { recursive: true });
    await mkdir(projectsDir, { recursive: true });
    const result = await loadUsageInsights({
      days: 7,
      projectsDir,
      sessionMetaDir,
      usageSnapshotPath,
    });
    expect(result.skillBreakdown).toHaveLength(0);
    expect(result.subagentBreakdown).toHaveLength(0);
  });
});
