import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { loadConfig, saveConfig, DEFAULT_CONFIG } from "../../src/config/index.js";
import { mkdtemp, rm } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

describe("config", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-cfg-"));
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true });
  });

  test("loadConfig returns defaults when no file exists", async () => {
    const config = await loadConfig(join(tmpDir, "axt", "config.json"));
    expect(config.currency).toEqual(["usd", "krw"]);
    expect(config.exchangeRate).toBe(1400);
    expect(config.monthlyBudget).toBe(100);
    expect(config.timezone).toBe("Asia/Seoul");
    expect(config.locale).toBe("ko-KR");
    expect(config.startOfWeek).toBe("monday");
    expect(config.budgetWarningThreshold).toBe(0.8);
  });

  test("loadConfig merges saved values with defaults", async () => {
    const configPath = join(tmpDir, "axt", "config.json");
    await Bun.write(configPath, JSON.stringify({ exchangeRate: 1380 }));
    const config = await loadConfig(configPath);
    expect(config.exchangeRate).toBe(1380);
    expect(config.currency).toEqual(["usd", "krw"]);
  });

  test("saveConfig persists to disk", async () => {
    const configPath = join(tmpDir, "axt", "config.json");
    await saveConfig(configPath, { ...DEFAULT_CONFIG, exchangeRate: 1350 });
    const loaded = await loadConfig(configPath);
    expect(loaded.exchangeRate).toBe(1350);
  });
});
