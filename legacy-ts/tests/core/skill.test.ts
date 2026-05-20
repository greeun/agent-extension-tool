import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { listSkills, listAllSkills, linkSkill, unlinkSkill } from "../../src/core/skill.js";
import { mkdtemp, rm, mkdir, writeFile, symlink } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

describe("skill", () => {
  let tmpDir: string;
  let skillsDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-skill-"));
    skillsDir = join(tmpDir, "skills");
    await mkdir(skillsDir, { recursive: true });
    await mkdir(join(skillsDir, "seer"), { recursive: true });
    await writeFile(join(skillsDir, "seer", "SKILL.md"), "# Seer");
    const targetDir = join(tmpDir, "source-skill");
    await mkdir(targetDir, { recursive: true });
    await writeFile(join(targetDir, "SKILL.md"), "# External");
    await symlink(targetDir, join(skillsDir, "external-skill"));
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("listSkills returns directories and symlinks", async () => {
    const skills = await listSkills(skillsDir);
    expect(skills).toHaveLength(2);
    const names = skills.map((s) => s.name);
    expect(names).toContain("seer");
    expect(names).toContain("external-skill");
  });

  test("listSkills identifies symlinks", async () => {
    const skills = await listSkills(skillsDir);
    const ext = skills.find((s) => s.name === "external-skill")!;
    expect(ext.isSymlink).toBe(true);
    expect(ext.target).toBeDefined();
  });

  test("linkSkill creates symlink", async () => {
    const newTarget = join(tmpDir, "new-skill");
    await mkdir(newTarget);
    await writeFile(join(newTarget, "SKILL.md"), "# New");
    await linkSkill(skillsDir, newTarget, "new-skill");
    const skills = await listSkills(skillsDir);
    expect(skills.find((s) => s.name === "new-skill")).toBeDefined();
  });

  test("unlinkSkill removes symlink", async () => {
    await unlinkSkill(skillsDir, "external-skill");
    const skills = await listSkills(skillsDir);
    expect(skills.find((s) => s.name === "external-skill")).toBeUndefined();
  });

  test("unlinkSkill refuses to remove non-symlink directory", async () => {
    expect(unlinkSkill(skillsDir, "seer")).rejects.toThrow();
  });

  test("listAllSkills scans <projectDir>/.agents/ as project source", async () => {
    const projectDir = join(tmpDir, "proj");
    const dotAgents = join(projectDir, ".agents");
    await mkdir(join(dotAgents, "alpha"), { recursive: true });
    await writeFile(join(dotAgents, "alpha", "SKILL.md"), "# Alpha");
    const skills = await listAllSkills({ projectDir });
    const found = skills.find((s) => s.name === "alpha" && s.source === "project");
    expect(found).toBeDefined();
    expect(found!.path).toBe(join(dotAgents, "alpha"));
  });
});
