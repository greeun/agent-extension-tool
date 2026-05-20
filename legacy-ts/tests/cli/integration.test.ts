import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, mkdir } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

const PROJECT_ROOT = "/Users/uni4love/project/workspace/211-withwiz/claude-utils/axt";

describe("cli integration", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-cli-"));
    // Ensure minimal directory structure so env overrides are valid paths
    await mkdir(join(tmpDir, "claude"), { recursive: true });
    await mkdir(join(tmpDir, "xdg", "axt"), { recursive: true });
    await mkdir(join(tmpDir, "codex"), { recursive: true });
    await mkdir(join(tmpDir, "gemini"), { recursive: true });
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true });
  });

  function runCli(args: string[], extraEnv?: Record<string, string>) {
    return Bun.spawnSync(["bun", "bin/axt.ts", ...args], {
      cwd: PROJECT_ROOT,
      env: {
        ...process.env,
        CLAUDE_CONFIG_DIR: join(tmpDir, "claude"),
        XDG_CONFIG_HOME: join(tmpDir, "xdg"),
        CODEX_HOME: join(tmpDir, "codex"),
        GEMINI_CLI_HOME: join(tmpDir, "gemini"),
        ...extraEnv,
      },
      timeout: 15000,
    });
  }

  function decode(buf: Uint8Array): string {
    return new TextDecoder().decode(buf);
  }

  test("axt --help exits 0 and mentions axt", () => {
    const result = runCli(["--help"]);
    const out = decode(result.stdout);
    expect(result.exitCode).toBe(0);
    expect(out.toLowerCase()).toContain("axt");
  });

  test("axt --version exits 0", () => {
    const result = runCli(["--version"]);
    expect(result.exitCode).toBe(0);
  });

  test("axt plugin list exits 0 without installed_plugins.json", () => {
    const result = runCli(["plugin", "list"]);
    const out = decode(result.stdout);
    expect(result.exitCode).toBe(0);
    // Should gracefully say no plugins
    expect(out).toContain("No plugins installed.");
  });

  test("axt skill list exits 0 without skills directory", () => {
    const result = runCli(["skill", "list"]);
    const out = decode(result.stdout);
    expect(result.exitCode).toBe(0);
    expect(out).toContain("No standalone skills found.");
  });

  test("axt mcp list exits 0 when no active plugins", () => {
    const result = runCli(["mcp", "list"]);
    const out = decode(result.stdout);
    expect(result.exitCode).toBe(0);
    expect(out).toContain("No MCP servers found in active plugins.");
  });

  test("axt vault list exits 0 (vault may be empty or populated)", () => {
    const result = runCli(["vault", "list"]);
    const out = decode(result.stdout);
    expect(result.exitCode).toBe(0);
    // Vault lives in ~/.axt/vault (not overridable via env).
    // Either "Vault is empty." or a table of extensions is acceptable.
    const isEmpty = out.includes("Vault is empty.");
    const hasExtensions = out.includes("extension(s) in vault");
    expect(isEmpty || hasExtensions).toBe(true);
  });

  test("axt usage today exits 0 and shows 'No usage data' or date string", () => {
    const result = runCli(["usage", "today"]);
    const out = decode(result.stdout);
    expect(result.exitCode).toBe(0);
    const hasNoData = out.includes("No usage data");
    const hasToday = /\d{4}-\d{2}-\d{2}/.test(out);
    expect(hasNoData || hasToday).toBe(true);
  });

  test("axt context --help exits 0 and mentions context", () => {
    const result = runCli(["context", "--help"]);
    const out = decode(result.stdout);
    expect(result.exitCode).toBe(0);
    expect(out.toLowerCase()).toContain("context");
  });

  test("axt market list exits 0 without marketplaces", () => {
    const result = runCli(["market", "list"]);
    const out = decode(result.stdout);
    expect(result.exitCode).toBe(0);
    expect(out).toContain("No marketplaces registered.");
  });

  test("axt plan overview exits 0", () => {
    const result = runCli(["plan", "overview"]);
    expect(result.exitCode).toBe(0);
    // When DEFAULT_CONFIG plans are used, Total line should appear
    const out = decode(result.stdout);
    // Either "Total" from plan summary or empty output are both acceptable
    const stderr = decode(result.stderr);
    // Ensure no crash (no unhandled rejection message)
    expect(stderr).not.toContain("Unhandled");
    // If there is output, it may include "Total"
    if (out.length > 0) {
      expect(out).toContain("Total");
    }
  });
});
