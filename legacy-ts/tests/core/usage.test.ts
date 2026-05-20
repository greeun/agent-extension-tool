import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { parseJsonlFile, aggregateDaily, aggregateBySession, computeBlocks, type UsageEntry } from "../../src/core/usage.js";
import { mkdtemp, rm, mkdir, cp } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

describe("usage", () => {
  let tmpDir: string;
  let projectsDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-usage-"));
    projectsDir = join(tmpDir, "projects");
    const projectDir = join(projectsDir, "test-project");
    await mkdir(projectDir, { recursive: true });
    await cp(join(import.meta.dir, "../fixtures/sample-session.jsonl"), join(projectDir, "sess-001.jsonl"));
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("parseJsonlFile extracts assistant entries only", async () => {
    const entries = await parseJsonlFile(join(projectsDir, "test-project", "sess-001.jsonl"));
    expect(entries).toHaveLength(2);
    expect(entries[0].model).toBe("claude-opus-4-6");
    expect(entries[0].inputTokens).toBe(100);
    expect(entries[0].outputTokens).toBe(500);
    expect(entries[0].cacheCreationTokens).toBe(2000);
    expect(entries[0].cacheReadTokens).toBe(5000);
  });

  test("parseJsonlFile extracts session and project info", async () => {
    const entries = await parseJsonlFile(join(projectsDir, "test-project", "sess-001.jsonl"));
    expect(entries[0].sessionId).toBe("sess-001");
    expect(entries[0].timestamp).toBe("2026-04-29T10:00:05.000Z");
  });

  test("aggregateDaily groups by date", () => {
    const entries: UsageEntry[] = [
      { model: "claude-opus-4-6", inputTokens: 100, outputTokens: 500, cacheCreationTokens: 2000, cacheReadTokens: 5000, sessionId: "s1", projectPath: "p1", timestamp: "2026-04-29T10:00:00.000Z" },
      { model: "claude-opus-4-6", inputTokens: 200, outputTokens: 800, cacheCreationTokens: 0, cacheReadTokens: 8000, sessionId: "s1", projectPath: "p1", timestamp: "2026-04-29T10:01:00.000Z" },
    ];
    const daily = aggregateDaily(entries, "UTC");
    expect(daily).toHaveLength(1);
    expect(daily[0].date).toBe("2026-04-29");
    expect(daily[0].inputTokens).toBe(300);
    expect(daily[0].outputTokens).toBe(1300);
    expect(daily[0].cacheCreationTokens).toBe(2000);
    expect(daily[0].cacheReadTokens).toBe(13000);
    expect(daily[0].sessions).toBe(1);
  });

  test("aggregateBySession groups by sessionId", () => {
    const entries: UsageEntry[] = [
      { model: "claude-opus-4-6", inputTokens: 100, outputTokens: 500, cacheCreationTokens: 2000, cacheReadTokens: 5000, sessionId: "s1", projectPath: "p1", timestamp: "2026-04-29T10:00:00.000Z" },
      { model: "claude-opus-4-6", inputTokens: 200, outputTokens: 800, cacheCreationTokens: 0, cacheReadTokens: 8000, sessionId: "s2", projectPath: "p1", timestamp: "2026-04-29T11:00:00.000Z" },
    ];
    const sessions = aggregateBySession(entries);
    expect(sessions).toHaveLength(2);
  });

  test("computeBlocks creates 5-hour windows", () => {
    const entries: UsageEntry[] = [
      { model: "claude-opus-4-6", inputTokens: 100, outputTokens: 500, cacheCreationTokens: 0, cacheReadTokens: 0, sessionId: "s1", projectPath: "p1", timestamp: "2026-04-29T08:30:00.000Z" },
      { model: "claude-opus-4-6", inputTokens: 200, outputTokens: 300, cacheCreationTokens: 0, cacheReadTokens: 0, sessionId: "s1", projectPath: "p1", timestamp: "2026-04-29T12:30:00.000Z" },
    ];
    const blocks = computeBlocks(entries, "UTC");
    expect(blocks.length).toBeGreaterThanOrEqual(1);
    expect(blocks[0].durationHours).toBe(5);
  });
});
