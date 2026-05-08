import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, mkdir } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

import { readProfile, writeProfile } from "../../src/core/vault.js";
import type { AxtProfile } from "../../src/core/vault.js";

describe("vault profile I/O", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-vault-"));
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true });
  });

  test("readProfile returns null when file does not exist", async () => {
    const profile = await readProfile(tmpDir);
    expect(profile).toBeNull();
  });

  test("writeProfile creates file and readProfile reads it back", async () => {
    const profile: AxtProfile = {
      extensions: {
        skills: ["brainstorming", "tdd"],
        commands: ["deploy"],
        agents: [],
        plugins: ["context7"],
      },
    };
    await writeProfile(tmpDir, profile);
    const result = await readProfile(tmpDir);
    expect(result).toEqual(profile);
  });

  test("writeProfile overwrites existing profile", async () => {
    const v1: AxtProfile = { extensions: { skills: ["a"], commands: [], agents: [], plugins: [] } };
    const v2: AxtProfile = { extensions: { skills: ["b", "c"], commands: ["d"], agents: [], plugins: [] } };
    await writeProfile(tmpDir, v1);
    await writeProfile(tmpDir, v2);
    const result = await readProfile(tmpDir);
    expect(result).toEqual(v2);
  });
});
