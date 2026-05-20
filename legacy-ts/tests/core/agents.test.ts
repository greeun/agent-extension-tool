import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, writeFile, mkdir } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { listAllAgents } from "../../src/core/agents.js";

const AGENT_WITH_FRONTMATTER = `---
description: "Searches and reads code files"
---

# Explorer

Fast read-only search agent.
`;

const AGENT_WITHOUT_FRONTMATTER = `# Reviewer

Reviews code for quality issues.
`;

describe("listAllAgents", () => {
  let tmpDir: string;
  let projectDir: string;
  let agentsDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-agents-"));
    projectDir = join(tmpDir, "project");
    agentsDir = join(projectDir, ".claude", "agents");
    await mkdir(agentsDir, { recursive: true });
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("returns project agents from .claude/agents/", async () => {
    await writeFile(join(agentsDir, "explorer.md"), AGENT_WITH_FRONTMATTER);
    const agents = await listAllAgents({ projectDir });
    const found = agents.find((a) => a.name === "explorer" && a.source === "project");
    expect(found).toBeDefined();
  });

  test("extracts description from YAML frontmatter", async () => {
    await writeFile(join(agentsDir, "explorer.md"), AGENT_WITH_FRONTMATTER);
    const agents = await listAllAgents({ projectDir });
    const found = agents.find((a) => a.name === "explorer" && a.source === "project");
    expect(found!.description).toBe("Searches and reads code files");
  });

  test("falls back to first non-header line for description", async () => {
    await writeFile(join(agentsDir, "reviewer.md"), AGENT_WITHOUT_FRONTMATTER);
    const agents = await listAllAgents({ projectDir });
    const found = agents.find((a) => a.name === "reviewer" && a.source === "project");
    expect(found!.description).toContain("Reviews");
  });

  test("sets sourcePath to full file path", async () => {
    await writeFile(join(agentsDir, "explorer.md"), AGENT_WITH_FRONTMATTER);
    const agents = await listAllAgents({ projectDir });
    const found = agents.find((a) => a.name === "explorer" && a.source === "project");
    expect(found!.sourcePath).toBe(join(agentsDir, "explorer.md"));
  });

  test("ignores non-.md files", async () => {
    await writeFile(join(agentsDir, "config.yaml"), "name: agent");
    const agents = await listAllAgents({ projectDir });
    expect(agents.find((a) => a.name === "config")).toBeUndefined();
  });

  test("returns empty project agents when dir does not exist", async () => {
    const agents = await listAllAgents({ projectDir: join(tmpDir, "nonexistent") });
    expect(agents.filter((a) => a.source === "project")).toHaveLength(0);
  });

  test("does not throw when no projectDir is given", async () => {
    const agents = await listAllAgents({});
    expect(Array.isArray(agents)).toBe(true);
  });

  test("returns multiple project agents", async () => {
    await writeFile(join(agentsDir, "a.md"), AGENT_WITH_FRONTMATTER);
    await writeFile(join(agentsDir, "b.md"), AGENT_WITHOUT_FRONTMATTER);
    const agents = await listAllAgents({ projectDir });
    const proj = agents.filter((a) => a.source === "project");
    expect(proj.length).toBeGreaterThanOrEqual(2);
    const names = proj.map((a) => a.name);
    expect(names).toContain("a");
    expect(names).toContain("b");
  });

  test("scans <projectDir>/.agents/ as project source", async () => {
    const dotAgents = join(projectDir, ".agents");
    await mkdir(dotAgents, { recursive: true });
    await writeFile(join(dotAgents, "dotted.md"), AGENT_WITH_FRONTMATTER);
    const agents = await listAllAgents({ projectDir });
    const found = agents.find((a) => a.name === "dotted" && a.source === "project");
    expect(found).toBeDefined();
    expect(found!.sourcePath).toBe(join(dotAgents, "dotted.md"));
  });
});
