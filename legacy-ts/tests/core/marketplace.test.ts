import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { listMarketplaces, addMarketplace, removeMarketplace, parseMarketplaceSource } from "../../src/core/marketplace.js";
import { mkdtemp, rm, cp, mkdir } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

describe("marketplace", () => {
  let tmpDir: string;
  let kmPath: string;
  let mpDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-mkt-"));
    kmPath = join(tmpDir, "known_marketplaces.json");
    mpDir = join(tmpDir, "marketplaces");
    await mkdir(mpDir, { recursive: true });
    await cp(join(import.meta.dir, "../fixtures/known_marketplaces.json"), kmPath);
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("listMarketplaces returns all entries", async () => {
    const list = await listMarketplaces(kmPath);
    expect(list).toHaveLength(2);
    expect(list[0].name).toBe("claude-plugins-official");
    expect(list[1].name).toBe("superpowers-marketplace");
  });

  test("parseMarketplaceSource parses github: prefix", () => {
    const source = parseMarketplaceSource("github:user/repo");
    expect(source).toEqual({ source: "github", repo: "user/repo" });
  });

  test("parseMarketplaceSource parses git: prefix", () => {
    const source = parseMarketplaceSource("git:https://example.com/repo.git");
    expect(source).toEqual({ source: "git", url: "https://example.com/repo.git" });
  });

  test("parseMarketplaceSource parses dir: prefix", () => {
    const source = parseMarketplaceSource("dir:/path/to/local");
    expect(source).toEqual({ source: "directory", path: "/path/to/local" });
  });

  test("addMarketplace adds to known_marketplaces.json", async () => {
    await addMarketplace(kmPath, mpDir, "test-mkt", { source: "directory", path: tmpDir });
    const list = await listMarketplaces(kmPath);
    expect(list).toHaveLength(3);
    expect(list.find((m) => m.name === "test-mkt")).toBeDefined();
  });

  test("removeMarketplace removes from known_marketplaces.json", async () => {
    await removeMarketplace(kmPath, mpDir, "superpowers-marketplace");
    const list = await listMarketplaces(kmPath);
    expect(list).toHaveLength(1);
    expect(list[0].name).toBe("claude-plugins-official");
  });
});
