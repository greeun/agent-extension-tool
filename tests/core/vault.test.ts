import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, mkdir, symlink, readlink, lstat, stat } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

import { readProfile, writeProfile, syncProject, listVaultItems, listVaultItemsWithProjectState, linkToProject, unlinkFromProject, linkToGlobal, unlinkFromGlobal, migrateToVault, parseYamlDescription } from "../../src/core/vault.js";
import type { AxtProfile, VaultItem } from "../../src/core/vault.js";

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

  test("detects global linked skills via symlink in globalDir", async () => {
    const skillPath = join(vaultDir, "skills", "tdd");
    await mkdir(skillPath);
    await Bun.write(join(skillPath, "skill.md"), "# TDD");

    const globalDir = await mkdtemp(join(tmpdir(), "axt-global-detect-"));
    await mkdir(join(globalDir, "skills"), { recursive: true });
    await symlink(skillPath, join(globalDir, "skills", "tdd"));

    const items = await listVaultItemsWithProjectState(vaultDir, projectDir, [], globalDir);
    const tdd = items.find((i) => i.name === "tdd");
    expect(tdd).toBeDefined();
    expect(tdd!.isGlobalLinked).toBe(true);
    expect(tdd!.isLinked).toBe(false);

    await rm(globalDir, { recursive: true });
  });

  test("unlinked global items have isGlobalLinked false", async () => {
    await mkdir(join(vaultDir, "skills", "debug"));
    await Bun.write(join(vaultDir, "skills", "debug", "skill.md"), "# Debug");

    const globalDir = await mkdtemp(join(tmpdir(), "axt-global-detect2-"));
    await mkdir(join(globalDir, "skills"), { recursive: true });

    const items = await listVaultItemsWithProjectState(vaultDir, projectDir, [], globalDir);
    const debug = items.find((i) => i.name === "debug");
    expect(debug).toBeDefined();
    expect(debug!.isGlobalLinked).toBe(false);

    await rm(globalDir, { recursive: true });
  });
});

describe("linkToProject", () => {
  let vaultDir: string;
  let projectDir: string;

  beforeEach(async () => {
    vaultDir = await mkdtemp(join(tmpdir(), "axt-vault-link-"));
    projectDir = await mkdtemp(join(tmpdir(), "axt-project-link-"));
    await mkdir(join(vaultDir, "skills"), { recursive: true });
    await mkdir(join(vaultDir, "commands"), { recursive: true });
  });

  afterEach(async () => {
    await rm(vaultDir, { recursive: true });
    await rm(projectDir, { recursive: true });
  });

  test("creates symlink for skill and updates profile", async () => {
    const skillPath = join(vaultDir, "skills", "tdd");
    await mkdir(skillPath);
    const item: VaultItem = { name: "tdd", type: "skill", path: skillPath, description: "", isLinked: false, isGlobalLinked: false };

    await linkToProject(projectDir, item);

    const linkPath = join(projectDir, ".claude", "skills", "tdd");
    const s = await lstat(linkPath);
    expect(s.isSymbolicLink()).toBe(true);
    const target = await readlink(linkPath);
    expect(target).toBe(skillPath);

    const profile = await readProfile(projectDir);
    expect(profile!.extensions.skills).toContain("tdd");
  });

  test("creates symlink for command and updates profile", async () => {
    const cmdPath = join(vaultDir, "commands", "deploy.md");
    await Bun.write(cmdPath, "# Deploy");
    const item: VaultItem = { name: "deploy.md", type: "command", path: cmdPath, description: "", isLinked: false, isGlobalLinked: false };

    await linkToProject(projectDir, item);

    const linkPath = join(projectDir, ".claude", "commands", "deploy.md");
    const s = await lstat(linkPath);
    expect(s.isSymbolicLink()).toBe(true);

    const profile = await readProfile(projectDir);
    expect(profile!.extensions.commands).toContain("deploy.md");
  });

  test("creates .claude subdirectories if missing", async () => {
    const skillPath = join(vaultDir, "skills", "tdd");
    await mkdir(skillPath);
    const item: VaultItem = { name: "tdd", type: "skill", path: skillPath, description: "", isLinked: false, isGlobalLinked: false };

    await linkToProject(projectDir, item);

    const linkPath = join(projectDir, ".claude", "skills", "tdd");
    const s = await lstat(linkPath);
    expect(s.isSymbolicLink()).toBe(true);
  });

  test("throws when non-symlink file already exists at link path", async () => {
    const skillPath = join(vaultDir, "skills", "tdd");
    await mkdir(skillPath);
    await mkdir(join(projectDir, ".claude", "skills"), { recursive: true });
    await Bun.write(join(projectDir, ".claude", "skills", "tdd"), "conflict");
    const item: VaultItem = { name: "tdd", type: "skill", path: skillPath, description: "", isLinked: false, isGlobalLinked: false };

    expect(linkToProject(projectDir, item)).rejects.toThrow("already exists");
  });
});

describe("unlinkFromProject", () => {
  let vaultDir: string;
  let projectDir: string;

  beforeEach(async () => {
    vaultDir = await mkdtemp(join(tmpdir(), "axt-vault-unlink-"));
    projectDir = await mkdtemp(join(tmpdir(), "axt-project-unlink-"));
    await mkdir(join(vaultDir, "skills"), { recursive: true });
  });

  afterEach(async () => {
    await rm(vaultDir, { recursive: true });
    await rm(projectDir, { recursive: true });
  });

  test("removes symlink and updates profile", async () => {
    const skillPath = join(vaultDir, "skills", "tdd");
    await mkdir(skillPath);
    const item: VaultItem = { name: "tdd", type: "skill", path: skillPath, description: "", isLinked: true, isGlobalLinked: false };

    await linkToProject(projectDir, item);
    await unlinkFromProject(projectDir, item);

    const linkPath = join(projectDir, ".claude", "skills", "tdd");
    let exists = true;
    try { await lstat(linkPath); } catch { exists = false; }
    expect(exists).toBe(false);

    const profile = await readProfile(projectDir);
    expect(profile!.extensions.skills).not.toContain("tdd");
  });
});

describe("syncProject", () => {
  let vaultDir: string;
  let projectDir: string;

  beforeEach(async () => {
    vaultDir = await mkdtemp(join(tmpdir(), "axt-vault-sync-"));
    projectDir = await mkdtemp(join(tmpdir(), "axt-project-sync-"));
    await mkdir(join(vaultDir, "skills"), { recursive: true });
    await mkdir(join(vaultDir, "commands"), { recursive: true });
    await mkdir(join(vaultDir, "agents"), { recursive: true });
  });

  afterEach(async () => {
    await rm(vaultDir, { recursive: true });
    await rm(projectDir, { recursive: true });
  });

  test("creates missing symlinks from profile", async () => {
    await mkdir(join(vaultDir, "skills", "tdd"));
    await Bun.write(join(vaultDir, "commands", "deploy.md"), "# Deploy");

    const profile: AxtProfile = {
      extensions: { skills: ["tdd"], commands: ["deploy.md"], agents: [], plugins: [] },
    };
    await writeProfile(projectDir, profile);

    const result = await syncProject(projectDir, vaultDir);
    expect(result.linked).toContain("skill:tdd");
    expect(result.linked).toContain("command:deploy.md");
    expect(result.errors).toHaveLength(0);

    const s = await lstat(join(projectDir, ".claude", "skills", "tdd"));
    expect(s.isSymbolicLink()).toBe(true);
  });

  test("removes extra symlinks not in profile", async () => {
    await mkdir(join(vaultDir, "skills", "tdd"));
    const skillPath = join(vaultDir, "skills", "tdd");
    await mkdir(join(projectDir, ".claude", "skills"), { recursive: true });
    await symlink(skillPath, join(projectDir, ".claude", "skills", "tdd"));

    const profile: AxtProfile = {
      extensions: { skills: [], commands: [], agents: [], plugins: [] },
    };
    await writeProfile(projectDir, profile);

    const result = await syncProject(projectDir, vaultDir);
    expect(result.unlinked).toContain("skill:tdd");

    let exists = true;
    try { await lstat(join(projectDir, ".claude", "skills", "tdd")); } catch { exists = false; }
    expect(exists).toBe(false);
  });

  test("reports error for profile entry not in vault", async () => {
    const profile: AxtProfile = {
      extensions: { skills: ["nonexistent"], commands: [], agents: [], plugins: [] },
    };
    await writeProfile(projectDir, profile);

    const result = await syncProject(projectDir, vaultDir);
    expect(result.errors.length).toBeGreaterThan(0);
    expect(result.errors[0]).toContain("nonexistent");
  });
});

describe("linkToGlobal", () => {
  let vaultDir: string;
  let globalDir: string;

  beforeEach(async () => {
    vaultDir = await mkdtemp(join(tmpdir(), "axt-vault-glink-"));
    globalDir = await mkdtemp(join(tmpdir(), "axt-global-glink-"));
    await mkdir(join(vaultDir, "skills"), { recursive: true });
    await mkdir(join(vaultDir, "commands"), { recursive: true });
    await mkdir(join(globalDir, "skills"), { recursive: true });
    await mkdir(join(globalDir, "commands"), { recursive: true });
  });

  afterEach(async () => {
    await rm(vaultDir, { recursive: true });
    await rm(globalDir, { recursive: true });
  });

  test("creates symlink in global dir for skill", async () => {
    const skillPath = join(vaultDir, "skills", "tdd");
    await mkdir(skillPath);
    const item: VaultItem = { name: "tdd", type: "skill", path: skillPath, description: "", isLinked: false, isGlobalLinked: false };

    await linkToGlobal(globalDir, item);

    const linkPath = join(globalDir, "skills", "tdd");
    const s = await lstat(linkPath);
    expect(s.isSymbolicLink()).toBe(true);
    const target = await readlink(linkPath);
    expect(target).toBe(skillPath);
  });

  test("creates symlink in global dir for command", async () => {
    const cmdPath = join(vaultDir, "commands", "deploy.md");
    await Bun.write(cmdPath, "# Deploy");
    const item: VaultItem = { name: "deploy.md", type: "command", path: cmdPath, description: "", isLinked: false, isGlobalLinked: false };

    await linkToGlobal(globalDir, item);

    const linkPath = join(globalDir, "commands", "deploy.md");
    const s = await lstat(linkPath);
    expect(s.isSymbolicLink()).toBe(true);
  });

  test("throws when non-symlink file exists at global path", async () => {
    const skillPath = join(vaultDir, "skills", "tdd");
    await mkdir(skillPath);
    await Bun.write(join(globalDir, "skills", "tdd"), "conflict");
    const item: VaultItem = { name: "tdd", type: "skill", path: skillPath, description: "", isLinked: false, isGlobalLinked: false };

    expect(linkToGlobal(globalDir, item)).rejects.toThrow("already exists");
  });
});

describe("unlinkFromGlobal", () => {
  let vaultDir: string;
  let globalDir: string;

  beforeEach(async () => {
    vaultDir = await mkdtemp(join(tmpdir(), "axt-vault-gunlink-"));
    globalDir = await mkdtemp(join(tmpdir(), "axt-global-gunlink-"));
    await mkdir(join(vaultDir, "skills"), { recursive: true });
    await mkdir(join(globalDir, "skills"), { recursive: true });
  });

  afterEach(async () => {
    await rm(vaultDir, { recursive: true });
    await rm(globalDir, { recursive: true });
  });

  test("removes symlink from global dir", async () => {
    const skillPath = join(vaultDir, "skills", "tdd");
    await mkdir(skillPath);
    const item: VaultItem = { name: "tdd", type: "skill", path: skillPath, description: "", isLinked: false, isGlobalLinked: true };

    await linkToGlobal(globalDir, item);
    await unlinkFromGlobal(globalDir, item);

    let exists = true;
    try { await lstat(join(globalDir, "skills", "tdd")); } catch { exists = false; }
    expect(exists).toBe(false);
  });
});

describe("migrateToVault", () => {
  let globalDir: string;
  let vaultDir: string;

  beforeEach(async () => {
    globalDir = await mkdtemp(join(tmpdir(), "axt-global-"));
    vaultDir = await mkdtemp(join(tmpdir(), "axt-vault-mig-"));
    await mkdir(join(globalDir, "skills"), { recursive: true });
    await mkdir(join(globalDir, "commands"), { recursive: true });
    await mkdir(join(globalDir, "agents"), { recursive: true });
    await mkdir(join(vaultDir, "skills"), { recursive: true });
    await mkdir(join(vaultDir, "commands"), { recursive: true });
    await mkdir(join(vaultDir, "agents"), { recursive: true });
  });

  afterEach(async () => {
    await rm(globalDir, { recursive: true });
    await rm(vaultDir, { recursive: true });
  });

  test("moves skill directories from global to vault", async () => {
    await mkdir(join(globalDir, "skills", "tdd"));
    await Bun.write(join(globalDir, "skills", "tdd", "skill.md"), "# TDD");

    const result = await migrateToVault(globalDir, vaultDir);
    expect(result.moved).toContain("skill:tdd");

    const vaultSkill = Bun.file(join(vaultDir, "skills", "tdd", "skill.md"));
    expect(await vaultSkill.exists()).toBe(true);

    let globalExists = true;
    try { await stat(join(globalDir, "skills", "tdd")); } catch { globalExists = false; }
    expect(globalExists).toBe(false);
  });

  test("moves command files from global to vault", async () => {
    await Bun.write(join(globalDir, "commands", "deploy.md"), "# Deploy");

    const result = await migrateToVault(globalDir, vaultDir);
    expect(result.moved).toContain("command:deploy.md");
  });

  test("skips items that already exist in vault", async () => {
    await mkdir(join(globalDir, "skills", "tdd"));
    await Bun.write(join(globalDir, "skills", "tdd", "skill.md"), "# Global TDD");
    await mkdir(join(vaultDir, "skills", "tdd"));
    await Bun.write(join(vaultDir, "skills", "tdd", "skill.md"), "# Vault TDD");

    const result = await migrateToVault(globalDir, vaultDir);
    expect(result.skipped).toContain("skill:tdd");

    const content = await Bun.file(join(vaultDir, "skills", "tdd", "skill.md")).text();
    expect(content).toBe("# Vault TDD");
  });
});

describe("parseYamlDescription", () => {
  test("plain single-line scalar", () => {
    expect(parseYamlDescription("name: x\ndescription: Hello world.")).toBe("Hello world.");
  });

  test("double-quoted single-line scalar is unquoted", () => {
    expect(parseYamlDescription('description: "Hello \\"world\\"."')).toBe('Hello "world".');
  });

  test("single-quoted scalar with escaped quote", () => {
    expect(parseYamlDescription("description: 'it''s fine'")).toBe("it's fine");
  });

  test("literal block scalar (|) is collapsed to one line", () => {
    const fm = "name: x\ndescription: |\n  Line one.\n  Line two.\nother: y";
    expect(parseYamlDescription(fm)).toBe("Line one. Line two.");
  });

  test("folded block scalar (>-) joins with spaces", () => {
    const fm = "description: >-\n  alpha\n  beta\n";
    expect(parseYamlDescription(fm)).toBe("alpha beta");
  });

  test("block scalar stops at next top-level key", () => {
    const fm = "description: |\n  kept\nname: not-part-of-desc";
    expect(parseYamlDescription(fm)).toBe("kept");
  });

  test("CRLF line endings are handled", () => {
    expect(parseYamlDescription("name: x\r\ndescription: CRLF works.\r\n")).toBe("CRLF works.");
  });

  test("multi-line double-quoted: trailing backslash joins with NO space", () => {
    // YAML double-quoted line continuation: `pale\` + `ttes` => `palettes`
    const fm = 'description: "21 pale\\\n  ttes, 50 fonts"';
    expect(parseYamlDescription(fm)).toBe("21 palettes, 50 fonts");
  });

  test("multi-line double-quoted: natural wrap folds to a space", () => {
    const fm = 'description: "first\n  second"';
    expect(parseYamlDescription(fm)).toBe("first second");
  });

  test("missing description returns empty string", () => {
    expect(parseYamlDescription("name: x\nother: y")).toBe("");
  });
});
