import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, writeFile, mkdir } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { listHooks, getHookDetail } from "../../src/core/hooks.js";

const USER_HOOKS_SETTINGS = {
  hooks: {
    PreToolUse: [
      {
        matcher: "Bash",
        hooks: [{ type: "command", command: "echo pre-tool" }],
      },
    ],
    Stop: [
      {
        matcher: "*",
        hooks: [{ type: "http", url: "http://localhost:9000/stop" }],
      },
    ],
  },
};

const PROJECT_HOOKS_SETTINGS = {
  hooks: {
    PostToolUse: [
      {
        matcher: "Edit",
        hooks: [
          {
            type: "mcp_tool",
            server: "my-server",
            tool: "notify",
            timeout: 5000,
          },
        ],
      },
    ],
  },
};

describe("listHooks", () => {
  let tmpDir: string;
  let userSettingsPath: string;
  let projectDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-hooks-"));
    userSettingsPath = join(tmpDir, "settings.json");
    projectDir = join(tmpDir, "project");
    await mkdir(join(projectDir, ".claude"), { recursive: true });
    await writeFile(userSettingsPath, JSON.stringify(USER_HOOKS_SETTINGS));
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("reads hooks from user settings", async () => {
    const hooks = await listHooks({ userSettingsPath });
    const events = hooks.map((h) => h.event);
    expect(events).toContain("PreToolUse");
    expect(events).toContain("Stop");
  });

  test("command hook has correct fields", async () => {
    const hooks = await listHooks({ userSettingsPath });
    const pre = hooks.find((h) => h.event === "PreToolUse");
    expect(pre).toBeDefined();
    expect(pre!.type).toBe("command");
    expect(pre!.command).toBe("echo pre-tool");
    expect(pre!.matcher).toBe("Bash");
    expect(pre!.source).toBe("user");
  });

  test("http hook has url field", async () => {
    const hooks = await listHooks({ userSettingsPath });
    const stop = hooks.find((h) => h.event === "Stop");
    expect(stop!.type).toBe("http");
    expect(stop!.url).toBe("http://localhost:9000/stop");
  });

  test("reads hooks from project settings", async () => {
    const projSettingsPath = join(projectDir, ".claude", "settings.json");
    await writeFile(projSettingsPath, JSON.stringify(PROJECT_HOOKS_SETTINGS));

    const hooks = await listHooks({ userSettingsPath, projectDir });
    const post = hooks.find((h) => h.event === "PostToolUse" && h.source === "project");
    expect(post).toBeDefined();
    expect(post!.type).toBe("mcp_tool");
    expect(post!.server).toBe("my-server");
    expect(post!.tool).toBe("notify");
    expect(post!.timeout).toBe(5000);
  });

  test("reads hooks from local settings", async () => {
    const localSettings = {
      hooks: {
        UserPromptSubmit: [{ matcher: "*", hooks: [{ type: "command", command: "echo local" }] }],
      },
    };
    await writeFile(join(projectDir, ".claude", "settings.local.json"), JSON.stringify(localSettings));

    const hooks = await listHooks({ userSettingsPath, projectDir });
    const local = hooks.find((h) => h.event === "UserPromptSubmit" && h.source === "local");
    expect(local).toBeDefined();
    expect(local!.command).toBe("echo local");
  });

  test("returns empty array when user settings has no hooks", async () => {
    await writeFile(userSettingsPath, JSON.stringify({ model: "claude" }));
    const hooks = await listHooks({ userSettingsPath });
    expect(hooks).toHaveLength(0);
  });

  test("returns empty array when user settings file is missing", async () => {
    const hooks = await listHooks({ userSettingsPath: join(tmpDir, "missing.json") });
    expect(hooks).toHaveLength(0);
  });

  test("if condition is mapped to condition field", async () => {
    const settings = {
      hooks: {
        PreToolUse: [{
          matcher: "Bash",
          hooks: [{ type: "command", command: "echo ok", if: "{{ input.command contains 'rm' }}" }],
        }],
      },
    };
    await writeFile(userSettingsPath, JSON.stringify(settings));
    const hooks = await listHooks({ userSettingsPath });
    expect(hooks[0].condition).toBe("{{ input.command contains 'rm' }}");
  });
});

describe("getHookDetail", () => {
  test("returns command for command type", () => {
    expect(getHookDetail({ type: "command", command: "echo hi", event: "Stop", matcher: "*", source: "user", sourcePath: "" })).toBe("echo hi");
  });

  test("returns url for http type", () => {
    expect(getHookDetail({ type: "http", url: "http://example.com", event: "Stop", matcher: "*", source: "user", sourcePath: "" })).toBe("http://example.com");
  });

  test("returns server:tool for mcp_tool type", () => {
    expect(getHookDetail({ type: "mcp_tool", server: "s", tool: "t", event: "Stop", matcher: "*", source: "user", sourcePath: "" })).toBe("s:t");
  });

  test("returns truncated prompt for prompt type", () => {
    const longPrompt = "a".repeat(100);
    const detail = getHookDetail({ type: "prompt", prompt: longPrompt, event: "Stop", matcher: "*", source: "user", sourcePath: "" });
    expect(detail.length).toBeLessThanOrEqual(60);
  });

  test("returns empty string for unknown type", () => {
    expect(getHookDetail({ type: "agent", event: "Stop", matcher: "*", source: "user", sourcePath: "" })).toBe("");
  });
});
