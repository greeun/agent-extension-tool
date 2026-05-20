import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, writeFile, mkdir } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { loadProjectContext } from "../../src/core/project-context.js";

describe("loadProjectContext", () => {
  let tmpDir: string;
  let projectDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-projctx-"));
    projectDir = join(tmpDir, "myproject");
    await mkdir(join(projectDir, ".claude"), { recursive: true });
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("returns item for CLAUDE.md in project root", async () => {
    await writeFile(join(projectDir, "CLAUDE.md"), "# Instructions\nDo stuff.");
    const items = await loadProjectContext(projectDir);
    const found = items.find((i) => i.source === "project" && i.name.includes("CLAUDE.md (project)"));
    expect(found).toBeDefined();
    expect(found!.content).toContain("Do stuff.");
    expect(found!.lines).toBeGreaterThan(0);
  });

  test("returns item for CLAUDE.md in .claude subdir", async () => {
    await writeFile(join(projectDir, ".claude", "CLAUDE.md"), "# Nested\nNested content.");
    const items = await loadProjectContext(projectDir);
    const found = items.find((i) => i.name.includes("project/.claude"));
    expect(found).toBeDefined();
    expect(found!.content).toContain("Nested content.");
  });

  test("line count matches actual content", async () => {
    const content = "line1\nline2\nline3";
    await writeFile(join(projectDir, "CLAUDE.md"), content);
    const items = await loadProjectContext(projectDir);
    const found = items.find((i) => i.name.includes("CLAUDE.md (project)") && i.source === "project");
    expect(found!.lines).toBe(3);
  });

  test("does not return items for missing files", async () => {
    const items = await loadProjectContext(projectDir);
    const names = items.map((i) => i.name);
    // Without creating CLAUDE.md, it must not appear
    expect(names.some((n) => n.includes("CLAUDE.md (project)") && !n.includes("/.claude"))).toBe(false);
  });

  test("returns empty array for a brand-new empty project dir", async () => {
    const emptyDir = join(tmpDir, "empty");
    await mkdir(emptyDir);
    const items = await loadProjectContext(emptyDir);
    // Only items from user home (~/.claude, ~/CLAUDE.md etc.) which may or may not exist
    // project-scoped items must be empty
    const projectItems = items.filter((i) => i.source === "project");
    expect(projectItems).toHaveLength(0);
  });
});
