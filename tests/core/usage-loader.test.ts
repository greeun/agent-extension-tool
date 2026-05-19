import { test, expect } from "bun:test";
import { withCache } from "../../src/core/usage/loader.js";
import type { UsageLoader } from "../../src/core/usage/loader.js";

test("withCache delegates to the wrapped loader and returns its entries", async () => {
  let calls = 0;
  const base: UsageLoader = {
    platform: "claude",
    async load() { calls++; return [{ platform: "claude", model: "m", timestamp: "2026-05-01T00:00:00Z", sessionId: "s", projectPath: "p", inputTokens: 1, outputTokens: 0, cacheWriteTokens: 0, cacheReadTokens: 0, reasoningTokens: 0, toolTokens: 0 }]; }
  };
  const wrapped = withCache(base);
  const out = await wrapped.load({ dir: "/tmp/x" });
  expect(out.length).toBe(1);
  expect(calls).toBe(1);
  expect(wrapped.platform).toBe("claude");
});
