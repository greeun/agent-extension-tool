import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, writeFile, mkdir } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { listCommands } from "../../src/core/commands.js";

const CMD_WITH_FRONTMATTER = `---
description: "Runs the test suite"
---

# test

Run all tests.
`;

const CMD_WITHOUT_FRONTMATTER = `# deploy

Deploy the current build to staging.
`;

describe("listCommands", () => {
  let tmpDir: string;
  let projectDir: string;
  let cmdDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-commands-"));
    projectDir = join(tmpDir, "project");
    cmdDir = join(projectDir, ".claude", "commands");
    await mkdir(cmdDir, { recursive: true });
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("returns project commands from .claude/commands/", async () => {
    await writeFile(join(cmdDir, "test.md"), CMD_WITH_FRONTMATTER);
    const cmds = await listCommands({ projectDir });
    const found = cmds.find((c) => c.name === "test" && c.source === "project");
    expect(found).toBeDefined();
  });

  test("extracts description from YAML frontmatter", async () => {
    await writeFile(join(cmdDir, "test.md"), CMD_WITH_FRONTMATTER);
    const cmds = await listCommands({ projectDir });
    const found = cmds.find((c) => c.name === "test" && c.source === "project");
    expect(found!.description).toBe("Runs the test suite");
  });

  test("falls back to first non-header line for description", async () => {
    await writeFile(join(cmdDir, "deploy.md"), CMD_WITHOUT_FRONTMATTER);
    const cmds = await listCommands({ projectDir });
    const found = cmds.find((c) => c.name === "deploy" && c.source === "project");
    expect(found!.description).toContain("Deploy");
  });

  test("includes full content of the command file", async () => {
    await writeFile(join(cmdDir, "test.md"), CMD_WITH_FRONTMATTER);
    const cmds = await listCommands({ projectDir });
    const found = cmds.find((c) => c.name === "test" && c.source === "project");
    expect(found!.content).toBe(CMD_WITH_FRONTMATTER);
  });

  test("ignores non-.md files", async () => {
    await writeFile(join(cmdDir, "readme.txt"), "not a command");
    const cmds = await listCommands({ projectDir });
    expect(cmds.find((c) => c.name === "readme")).toBeUndefined();
  });

  test("sets sourcePath to full file path", async () => {
    await writeFile(join(cmdDir, "test.md"), CMD_WITH_FRONTMATTER);
    const cmds = await listCommands({ projectDir });
    const found = cmds.find((c) => c.name === "test" && c.source === "project");
    expect(found!.sourcePath).toBe(join(cmdDir, "test.md"));
  });

  test("returns empty project commands when dir does not exist", async () => {
    const cmds = await listCommands({ projectDir: join(tmpDir, "nonexistent") });
    expect(cmds.filter((c) => c.source === "project")).toHaveLength(0);
  });

  test("returns commands without projectDir", async () => {
    // Should not throw — user commands dir may or may not exist
    const cmds = await listCommands({});
    expect(Array.isArray(cmds)).toBe(true);
  });

  test("multiple project commands are all returned", async () => {
    await writeFile(join(cmdDir, "a.md"), CMD_WITH_FRONTMATTER);
    await writeFile(join(cmdDir, "b.md"), CMD_WITHOUT_FRONTMATTER);
    const cmds = await listCommands({ projectDir });
    const proj = cmds.filter((c) => c.source === "project");
    expect(proj.length).toBeGreaterThanOrEqual(2);
    const names = proj.map((c) => c.name);
    expect(names).toContain("a");
    expect(names).toContain("b");
  });
});
