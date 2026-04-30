import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { readJson, writeJsonAtomic } from "../../src/core/json-io.js";
import { join } from "path";
import { mkdtemp, rm } from "fs/promises";
import { tmpdir } from "os";

describe("json-io", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-test-"));
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true });
  });

  test("readJson returns parsed object", async () => {
    const filePath = join(tmpDir, "test.json");
    await Bun.write(filePath, JSON.stringify({ name: "test", version: 1 }));
    const result = await readJson(filePath);
    expect(result).toEqual({ name: "test", version: 1 });
  });

  test("readJson returns fallback for missing file", async () => {
    const result = await readJson(join(tmpDir, "missing.json"), { fallback: {} });
    expect(result).toEqual({});
  });

  test("readJson throws for missing file without fallback", async () => {
    expect(readJson(join(tmpDir, "missing.json"))).rejects.toThrow();
  });

  test("writeJsonAtomic writes valid JSON", async () => {
    const filePath = join(tmpDir, "out.json");
    await writeJsonAtomic(filePath, { key: "value" });
    const content = await Bun.file(filePath).text();
    expect(JSON.parse(content)).toEqual({ key: "value" });
  });

  test("writeJsonAtomic creates .bak of existing file", async () => {
    const filePath = join(tmpDir, "out.json");
    await Bun.write(filePath, JSON.stringify({ old: true }));
    await writeJsonAtomic(filePath, { new: true });
    const backup = await Bun.file(filePath + ".bak").text();
    expect(JSON.parse(backup)).toEqual({ old: true });
  });

  test("writeJsonAtomic is atomic (tmp → rename)", async () => {
    const filePath = join(tmpDir, "atomic.json");
    await writeJsonAtomic(filePath, { data: "safe" });
    const content = await Bun.file(filePath).text();
    expect(JSON.parse(content)).toEqual({ data: "safe" });
  });
});
