import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { loadUnifiedUsage, claudeToUnified } from "../../src/core/usage-unified.js";
import type { UsageEntry } from "../../src/core/usage.js";
import { mkdtemp, rm, mkdir, cp } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

describe("usage-unified", () => {
  test("claudeToUnified converts Claude entries to unified format", () => {
    const claude: UsageEntry = {
      model: "claude-opus-4-6",
      inputTokens: 100,
      outputTokens: 500,
      cacheCreationTokens: 2000,
      cacheReadTokens: 5000,
      sessionId: "s1",
      projectPath: "p1",
      timestamp: "2026-04-29T10:00:00.000Z",
    };
    const unified = claudeToUnified(claude);
    expect(unified.platform).toBe("claude");
    expect(unified.cacheWriteTokens).toBe(2000);
    expect(unified.cacheReadTokens).toBe(5000);
    expect(unified.reasoningTokens).toBe(0);
    expect(unified.toolTokens).toBe(0);
  });

  test("loadUnifiedUsage loads from available platforms", async () => {
    const tmpDir = await mkdtemp(join(tmpdir(), "axt-unified-"));
    const claudeDir = join(tmpDir, "claude-projects", "proj");
    await mkdir(claudeDir, { recursive: true });
    await cp(
      join(import.meta.dir, "../fixtures/sample-session.jsonl"),
      join(claudeDir, "sess.jsonl")
    );

    const entries = await loadUnifiedUsage({
      claudeProjectsDir: join(tmpDir, "claude-projects"),
      codexSessionsDir: join(tmpDir, "codex-sessions"),
      geminiTmpDir: join(tmpDir, "gemini-tmp"),
    });

    expect(entries.length).toBeGreaterThan(0);
    expect(entries[0].platform).toBe("claude");

    await rm(tmpDir, { recursive: true });
  });

  test("loadUnifiedUsage filters by platform", async () => {
    const tmpDir = await mkdtemp(join(tmpdir(), "axt-unified-"));
    const claudeDir = join(tmpDir, "claude-projects", "proj");
    await mkdir(claudeDir, { recursive: true });
    await cp(
      join(import.meta.dir, "../fixtures/sample-session.jsonl"),
      join(claudeDir, "sess.jsonl")
    );

    const entries = await loadUnifiedUsage({
      claudeProjectsDir: join(tmpDir, "claude-projects"),
      codexSessionsDir: join(tmpDir, "codex-sessions"),
      geminiTmpDir: join(tmpDir, "gemini-tmp"),
      platform: "codex",
    });

    expect(entries).toHaveLength(0);

    await rm(tmpDir, { recursive: true });
  });

  test("loadUnifiedUsage handles missing directories gracefully", async () => {
    const entries = await loadUnifiedUsage({
      claudeProjectsDir: "/nonexistent/path1",
      codexSessionsDir: "/nonexistent/path2",
      geminiTmpDir: "/nonexistent/path3",
      forceRefresh: true,
    });
    expect(entries).toHaveLength(0);
  });
});
