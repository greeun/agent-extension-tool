import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, mkdir } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import {
  scanProjectUsage,
  getProjectCount,
  getProjects,
  type UsageIndex,
} from "../../src/core/project-usage.js";

describe("getProjectCount", () => {
  test("returns 0 for an empty index", () => {
    const index: UsageIndex = new Map();
    expect(getProjectCount(index, "skill", "my-skill")).toBe(0);
  });

  test("returns the number of projects using a skill", () => {
    const index: UsageIndex = new Map([
      ["skill:my-skill", { type: "skill", name: "my-skill", projects: [{ path: "/a", name: "a" }, { path: "/b", name: "b" }] }],
    ]);
    expect(getProjectCount(index, "skill", "my-skill")).toBe(2);
  });

  test("returns 0 for a missing key", () => {
    const index: UsageIndex = new Map([
      ["skill:other", { type: "skill", name: "other", projects: [{ path: "/a", name: "a" }] }],
    ]);
    expect(getProjectCount(index, "skill", "my-skill")).toBe(0);
  });
});

describe("getProjects", () => {
  test("returns empty array for empty index", () => {
    const index: UsageIndex = new Map();
    expect(getProjects(index, "plugin", "foo")).toEqual([]);
  });

  test("returns project refs for a known entry", () => {
    const projects = [{ path: "/proj/a", name: "a" }];
    const index: UsageIndex = new Map([
      ["plugin:foo", { type: "plugin", name: "foo", projects }],
    ]);
    expect(getProjects(index, "plugin", "foo")).toEqual(projects);
  });
});

describe("scanProjectUsage", () => {
  let tmpDir: string;
  let projectsDir: string;
  let vaultDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-projuse-"));
    projectsDir = join(tmpDir, "projects");
    vaultDir = join(tmpDir, "vault");
    await mkdir(projectsDir, { recursive: true });
    await mkdir(vaultDir, { recursive: true });
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("returns empty index when projectsDir does not exist", async () => {
    const index = await scanProjectUsage(join(tmpDir, "nonexistent"), vaultDir);
    expect(index.size).toBe(0);
  });

  test("returns empty index when projectsDir is empty", async () => {
    const index = await scanProjectUsage(projectsDir, vaultDir);
    expect(index.size).toBe(0);
  });

  test("skips directories not starting with '-'", async () => {
    await mkdir(join(projectsDir, "misc-dir"), { recursive: true });
    const index = await scanProjectUsage(projectsDir, vaultDir);
    expect(index.size).toBe(0);
  });
});
