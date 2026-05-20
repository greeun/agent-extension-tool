import { test, expect } from "bun:test";
import { groupByCategory } from "../../src/core/context/group.js";
import type { ContextSource } from "../../src/core/context/types.js";

function src(category: string, tokens: number): ContextSource {
  return { name: category + tokens, category: category as any, path: "", chars: 0, estimatedTokens: tokens, percentage: 0, actionable: false };
}

test("groups by category, sorts by total tokens desc", () => {
  const rows = groupByCategory([src("memory", 100), src("skills", 300), src("memory", 50)]);
  expect(rows[0].catKey).toBe("skills");
  expect(rows[1].catKey).toBe("memory");
  expect(rows[1].items).toBe("2");
});
