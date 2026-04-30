import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { parseCodexFile, extractCodexRateLimit } from "../../src/core/usage-codex.js";
import { mkdtemp, rm, mkdir, cp } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

describe("usage-codex", () => {
  let tmpDir: string;
  let filePath: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-codex-"));
    await mkdir(join(tmpDir, "sessions", "2026", "04", "29"), { recursive: true });
    filePath = join(tmpDir, "sessions", "2026", "04", "29", "rollout-001.jsonl");
    await cp(join(import.meta.dir, "../fixtures/codex-session.jsonl"), filePath);
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("parseCodexFile extracts token_count events", async () => {
    const entries = await parseCodexFile(filePath);
    expect(entries).toHaveLength(2);
    expect(entries[0].platform).toBe("codex");
    expect(entries[0].inputTokens).toBe(5000);
    expect(entries[0].cacheReadTokens).toBe(4000);
    expect(entries[0].outputTokens).toBe(800);
    expect(entries[0].reasoningTokens).toBe(200);
  });

  test("parseCodexFile uses last_token_usage for deltas", async () => {
    const entries = await parseCodexFile(filePath);
    expect(entries[1].inputTokens).toBe(7000);
    expect(entries[1].cacheReadTokens).toBe(6000);
    expect(entries[1].outputTokens).toBe(700);
  });

  test("parseCodexFile extracts model from session_meta", async () => {
    const entries = await parseCodexFile(filePath);
    expect(entries[0].model).toBe("gpt-5.3-codex");
  });

  test("extractCodexRateLimit returns rate limit info", async () => {
    const rl = await extractCodexRateLimit(filePath);
    expect(rl).not.toBeNull();
    expect(rl!.usedPercent).toBe(15.0);
    expect(rl!.windowMinutes).toBe(300);
  });
});
