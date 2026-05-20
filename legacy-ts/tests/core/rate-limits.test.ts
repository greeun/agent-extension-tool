import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, writeFile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { readRateLimits } from "../../src/core/rate-limits.js";

describe("readRateLimits", () => {
  let tmpDir: string;
  let snapshotPath: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-ratelimits-"));
    snapshotPath = join(tmpDir, "usage-snapshot.json");
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  function freshSnapshot(overrides: Record<string, unknown> = {}) {
    return {
      updated_at: new Date().toISOString(),
      five_hour: { used_percentage: 14, resets_at: new Date(Date.now() + 3600 * 1000).toISOString() },
      seven_day: { used_percentage: 8, resets_at: new Date(Date.now() + 7 * 86400 * 1000).toISOString() },
      ...overrides,
    };
  }

  test("returns null when file does not exist", () => {
    const result = readRateLimits(join(tmpDir, "nonexistent.json"));
    expect(result).toBeNull();
  });

  test("returns null when updated_at is missing", async () => {
    await writeFile(snapshotPath, JSON.stringify({
      five_hour: { used_percentage: 10 },
      seven_day: { used_percentage: 5 },
    }));
    expect(readRateLimits(snapshotPath)).toBeNull();
  });

  test("returns null when snapshot is stale", async () => {
    const staleAt = new Date(Date.now() - 10 * 60 * 1000).toISOString();
    await writeFile(snapshotPath, JSON.stringify(freshSnapshot({ updated_at: staleAt })));
    expect(readRateLimits(snapshotPath, 5 * 60 * 1000)).toBeNull();
  });

  test("returns null when both percentages are absent", async () => {
    await writeFile(snapshotPath, JSON.stringify({
      updated_at: new Date().toISOString(),
      five_hour: { used_percentage: null },
      seven_day: { used_percentage: null },
    }));
    expect(readRateLimits(snapshotPath)).toBeNull();
  });

  test("returns null when five_hour and seven_day keys are missing", async () => {
    await writeFile(snapshotPath, JSON.stringify({ updated_at: new Date().toISOString() }));
    expect(readRateLimits(snapshotPath)).toBeNull();
  });

  test("returns data for a fresh valid snapshot", async () => {
    await writeFile(snapshotPath, JSON.stringify(freshSnapshot()));
    const result = readRateLimits(snapshotPath);
    expect(result).not.toBeNull();
    expect(result!.fiveHour).toBe(14);
    expect(result!.sevenDay).toBe(8);
  });

  test("clamps percentage to 0-100", async () => {
    await writeFile(snapshotPath, JSON.stringify(freshSnapshot({
      five_hour: { used_percentage: 150, resets_at: new Date().toISOString() },
      seven_day: { used_percentage: -5, resets_at: new Date().toISOString() },
    })));
    const result = readRateLimits(snapshotPath);
    expect(result!.fiveHour).toBe(100);
    expect(result!.sevenDay).toBe(0);
  });

  test("parses numeric unix timestamp for resets_at", async () => {
    const resetTs = Math.floor(Date.now() / 1000) + 3600;
    await writeFile(snapshotPath, JSON.stringify({
      updated_at: new Date().toISOString(),
      five_hour: { used_percentage: 20, resets_at: resetTs },
      seven_day: { used_percentage: 5, resets_at: resetTs },
    }));
    const result = readRateLimits(snapshotPath);
    expect(result!.fiveHourResetAt).toBeInstanceOf(Date);
    expect(result!.sevenDayResetAt).toBeInstanceOf(Date);
  });

  test("returns null for malformed JSON", async () => {
    await writeFile(snapshotPath, "not json {");
    expect(readRateLimits(snapshotPath)).toBeNull();
  });
});
