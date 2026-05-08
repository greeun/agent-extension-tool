import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, mkdir, symlink } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

import { readProfile, writeProfile, listVaultItems, listVaultItemsWithProjectState } from "../../src/core/vault.js";
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

describe("listVaultItems", () => {
  let vaultDir: string;

  beforeEach(async () => {
    vaultDir = await mkdtemp(join(tmpdir(), "axt-vault-list-"));
    await mkdir(join(vaultDir, "skills"), { recursive: true });
    await mkdir(join(vaultDir, "commands"), { recursive: true });
    await mkdir(join(vaultDir, "agents"), { recursive: true });
  });

  afterEach(async () => {
    await rm(vaultDir, { recursive: true });
  });

  test("returns empty array when vault is empty", async () => {
    const items = await listVaultItems(vaultDir);
    expect(items).toEqual([]);
  });

  test("lists skills as directories", async () => {
    await mkdir(join(vaultDir, "skills", "brainstorming"));
    await Bun.write(join(vaultDir, "skills", "brainstorming", "skill.md"), "# Brainstorming");
    await mkdir(join(vaultDir, "skills", "tdd"));
    await Bun.write(join(vaultDir, "skills", "tdd", "skill.md"), "# TDD");

    const items = await listVaultItems(vaultDir);
    const skills = items.filter((i) => i.type === "skill");
    expect(skills).toHaveLength(2);
    expect(skills.map((s) => s.name).sort()).toEqual(["brainstorming", "tdd"]);
    expect(skills[0].isLinked).toBe(false);
  });

  test("lists commands as .md files", async () => {
    await Bun.write(join(vaultDir, "commands", "deploy.md"), "# Deploy");

    const items = await listVaultItems(vaultDir);
    const cmds = items.filter((i) => i.type === "command");
    expect(cmds).toHaveLength(1);
    expect(cmds[0].name).toBe("deploy.md");
  });

  test("lists agents as .md files", async () => {
    await Bun.write(join(vaultDir, "agents", "reviewer.md"), "# Reviewer");

    const items = await listVaultItems(vaultDir);
    const agents = items.filter((i) => i.type === "agent");
    expect(agents).toHaveLength(1);
    expect(agents[0].name).toBe("reviewer.md");
  });

  test("returns empty when vault dir does not exist", async () => {
    const items = await listVaultItems("/nonexistent/path");
    expect(items).toEqual([]);
  });
});

describe("listVaultItemsWithProjectState", () => {
  let vaultDir: string;
  let projectDir: string;

  beforeEach(async () => {
    vaultDir = await mkdtemp(join(tmpdir(), "axt-vault-state-"));
    projectDir = await mkdtemp(join(tmpdir(), "axt-project-"));
    await mkdir(join(vaultDir, "skills"), { recursive: true });
    await mkdir(join(vaultDir, "commands"), { recursive: true });
    await mkdir(join(vaultDir, "agents"), { recursive: true });
    await mkdir(join(projectDir, ".claude", "skills"), { recursive: true });
    await mkdir(join(projectDir, ".claude", "commands"), { recursive: true });
    await mkdir(join(projectDir, ".claude", "agents"), { recursive: true });
  });

  afterEach(async () => {
    await rm(vaultDir, { recursive: true });
    await rm(projectDir, { recursive: true });
  });

  test("detects linked skills via symlink", async () => {
    const skillPath = join(vaultDir, "skills", "tdd");
    await mkdir(skillPath);
    await Bun.write(join(skillPath, "skill.md"), "# TDD");
    await symlink(skillPath, join(projectDir, ".claude", "skills", "tdd"));

    const items = await listVaultItemsWithProjectState(vaultDir, projectDir);
    const tdd = items.find((i) => i.name === "tdd");
    expect(tdd).toBeDefined();
    expect(tdd!.isLinked).toBe(true);
  });

  test("unlinked items have isLinked false", async () => {
    await mkdir(join(vaultDir, "skills", "debug"));
    await Bun.write(join(vaultDir, "skills", "debug", "skill.md"), "# Debug");

    const items = await listVaultItemsWithProjectState(vaultDir, projectDir);
    const debug = items.find((i) => i.name === "debug");
    expect(debug).toBeDefined();
    expect(debug!.isLinked).toBe(false);
  });

  test("detects linked commands via symlink", async () => {
    const cmdPath = join(vaultDir, "commands", "deploy.md");
    await Bun.write(cmdPath, "# Deploy");
    await symlink(cmdPath, join(projectDir, ".claude", "commands", "deploy.md"));

    const items = await listVaultItemsWithProjectState(vaultDir, projectDir);
    const deploy = items.find((i) => i.name === "deploy.md");
    expect(deploy).toBeDefined();
    expect(deploy!.isLinked).toBe(true);
  });

  test("includes installed plugins with enabled state", async () => {
    const settingsPath = join(projectDir, ".claude", "settings.json");
    await Bun.write(settingsPath, JSON.stringify({ enabledPlugins: { "ctx7@mkt": true, "sp@mkt": false } }));

    const items = await listVaultItemsWithProjectState(vaultDir, projectDir, [
      { id: "ctx7@mkt", name: "context7" },
      { id: "sp@mkt", name: "superpowers" },
    ]);
    const ctx7 = items.find((i) => i.name === "context7");
    expect(ctx7).toBeDefined();
    expect(ctx7!.type).toBe("plugin");
    expect(ctx7!.isLinked).toBe(true);

    const sp = items.find((i) => i.name === "superpowers");
    expect(sp).toBeDefined();
    expect(sp!.isLinked).toBe(false);
  });
});
