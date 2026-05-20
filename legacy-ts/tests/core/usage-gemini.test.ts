import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { parseGeminiFile } from "../../src/core/usage-gemini.js";
import { mkdtemp, rm, mkdir, cp } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

describe("usage-gemini", () => {
  let tmpDir: string;
  let filePath: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-gemini-"));
    const chatDir = join(tmpDir, "tmp", "my-project", "chats");
    await mkdir(chatDir, { recursive: true });
    filePath = join(chatDir, "session-2026-04-29T09-00-abc.json");
    await cp(join(import.meta.dir, "../fixtures/gemini-session.json"), filePath);
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("parseGeminiFile extracts gemini role messages", async () => {
    const entries = await parseGeminiFile(filePath);
    expect(entries).toHaveLength(2);
    expect(entries[0].platform).toBe("gemini");
    expect(entries[0].model).toBe("gemini-2.5-pro");
  });

  test("parseGeminiFile maps all 5 token types", async () => {
    const entries = await parseGeminiFile(filePath);
    const e = entries[1];
    expect(e.inputTokens).toBe(2500);
    expect(e.outputTokens).toBe(800);
    expect(e.cacheReadTokens).toBe(1200);
    expect(e.reasoningTokens).toBe(150);
    expect(e.toolTokens).toBe(50);
  });

  test("parseGeminiFile extracts sessionId and projectPath", async () => {
    const entries = await parseGeminiFile(filePath);
    expect(entries[0].sessionId).toBe("gemini-sess-001");
    expect(entries[0].projectPath).toContain("my-project");
  });
});
