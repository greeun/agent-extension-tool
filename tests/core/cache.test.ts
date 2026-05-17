import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, writeFile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { isCacheValid, getFileMtime } from "../../src/core/cache.js";

describe("isCacheValid", () => {
  test("returns false when lastUpdated is empty", () => {
    expect(isCacheValid({ version: 1, lastUpdated: "", files: {} })).toBe(false);
  });

  test("returns false when cache is older than maxAgeMs", () => {
    const stale = new Date(Date.now() - 10 * 60 * 1000).toISOString();
    expect(isCacheValid({ version: 1, lastUpdated: stale, files: {} }, 5 * 60 * 1000)).toBe(false);
  });

  test("returns true when cache is within maxAgeMs", () => {
    const fresh = new Date(Date.now() - 60 * 1000).toISOString();
    expect(isCacheValid({ version: 1, lastUpdated: fresh, files: {} }, 5 * 60 * 1000)).toBe(true);
  });

  test("uses 5-minute default when maxAgeMs is omitted", () => {
    const justUnder = new Date(Date.now() - 4 * 60 * 1000).toISOString();
    expect(isCacheValid({ version: 1, lastUpdated: justUnder, files: {} })).toBe(true);
    const justOver = new Date(Date.now() - 6 * 60 * 1000).toISOString();
    expect(isCacheValid({ version: 1, lastUpdated: justOver, files: {} })).toBe(false);
  });
});

describe("getFileMtime", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-cache-"));
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("returns 0 for a file that does not exist", async () => {
    const mtime = await getFileMtime(join(tmpDir, "nonexistent.json"));
    expect(mtime).toBe(0);
  });

  test("returns a positive mtime for an existing file", async () => {
    const filePath = join(tmpDir, "test.json");
    await writeFile(filePath, "{}");
    const mtime = await getFileMtime(filePath);
    expect(mtime).toBeGreaterThan(0);
  });

  test("mtime reflects the actual modification time", async () => {
    const filePath = join(tmpDir, "test.json");
    const before = Date.now();
    await writeFile(filePath, "{}");
    const mtime = await getFileMtime(filePath);
    expect(mtime).toBeGreaterThanOrEqual(before);
    expect(mtime).toBeLessThanOrEqual(Date.now() + 1000);
  });
});
