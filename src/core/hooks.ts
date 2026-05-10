import { readJson } from "./json-io.js";
import { join } from "path";
import { existsSync } from "fs";
import { spawn } from "child_process";
import { listInstalledPlugins } from "./plugin.js";

export type HookType = "command" | "http" | "mcp_tool" | "prompt" | "agent";
export type HookSource = "user" | "project" | "local" | "plugin";

export interface HookEntry {
  type: HookType;
  command?: string;
  url?: string;
  headers?: Record<string, string>;
  server?: string;
  tool?: string;
  input?: Record<string, string>;
  prompt?: string;
  model?: string;
  timeout?: number;
  statusMessage?: string;
  async?: boolean;
  asyncRewake?: boolean;
  if?: string;
  once?: boolean;
  shell?: string;
  allowedEnvVars?: string[];
}

export interface HookRule {
  matcher: string;
  hooks: HookEntry[];
}

export interface HookInfo {
  event: string;
  matcher: string;
  source: HookSource;
  sourcePath: string;
  type: HookType;
  command?: string;
  url?: string;
  server?: string;
  tool?: string;
  prompt?: string;
  model?: string;
  timeout?: number;
  statusMessage?: string;
  async?: boolean;
  asyncRewake?: boolean;
  condition?: string;
  once?: boolean;
}

const HOOK_EVENTS = [
  "SessionStart", "Setup", "UserPromptSubmit", "UserPromptExpansion",
  "PreToolUse", "PermissionRequest", "PermissionDenied",
  "PostToolUse", "PostToolUseFailure", "PostToolBatch",
  "Stop", "StopFailure",
  "SubagentStart", "SubagentStop",
  "TaskCreated", "TaskCompleted", "TeammateIdle",
  "InstructionsLoaded", "ConfigChange", "CwdChanged", "FileChanged",
  "WorktreeCreate", "WorktreeRemove",
  "PreCompact", "PostCompact",
  "Elicitation", "ElicitationResult",
  "SessionEnd", "Notification",
] as const;

function extractHooks(
  settings: Record<string, unknown>,
  source: HookSource,
  sourcePath: string
): HookInfo[] {
  const hooksMap = (settings.hooks ?? {}) as Record<string, HookRule[]>;
  const result: HookInfo[] = [];

  for (const event of HOOK_EVENTS) {
    const rules = hooksMap[event];
    if (!Array.isArray(rules)) continue;
    for (const rule of rules) {
      for (const hook of rule.hooks) {
        const info: HookInfo = {
          event,
          matcher: rule.matcher || "*",
          source,
          sourcePath,
          type: (hook.type as HookType) ?? "command",
        };
        if (hook.command) info.command = hook.command;
        if (hook.url) info.url = hook.url;
        if (hook.server) info.server = hook.server;
        if (hook.tool) info.tool = hook.tool;
        if (hook.prompt) info.prompt = hook.prompt;
        if (hook.model) info.model = hook.model;
        if (hook.timeout != null) info.timeout = hook.timeout;
        if (hook.statusMessage) info.statusMessage = hook.statusMessage;
        if (hook.async) info.async = hook.async;
        if (hook.asyncRewake) info.asyncRewake = hook.asyncRewake;
        if (hook.if) info.condition = hook.if;
        if (hook.once) info.once = hook.once;
        result.push(info);
      }
    }
  }
  return result;
}

export async function listHooks(options: {
  userSettingsPath: string;
  projectDir?: string;
  installedPluginsPath?: string;
}): Promise<HookInfo[]> {
  const result: HookInfo[] = [];

  const userSettings = await readJson<Record<string, unknown>>(
    options.userSettingsPath, { fallback: {} }
  );
  result.push(...extractHooks(userSettings, "user", options.userSettingsPath));

  if (options.projectDir) {
    const projectSettingsPath = join(options.projectDir, ".claude", "settings.json");
    if (existsSync(projectSettingsPath)) {
      const projSettings = await readJson<Record<string, unknown>>(
        projectSettingsPath, { fallback: {} }
      );
      result.push(...extractHooks(projSettings, "project", projectSettingsPath));
    }

    const localSettingsPath = join(options.projectDir, ".claude", "settings.local.json");
    if (existsSync(localSettingsPath)) {
      const localSettings = await readJson<Record<string, unknown>>(
        localSettingsPath, { fallback: {} }
      );
      result.push(...extractHooks(localSettings, "local", localSettingsPath));
    }
  }

  if (options.installedPluginsPath && existsSync(options.installedPluginsPath)) {
    const plugins = await listInstalledPlugins(options.installedPluginsPath);
    for (const plugin of plugins) {
      const hooksPath = join(plugin.installPath, "hooks", "hooks.json");
      if (!existsSync(hooksPath)) continue;
      const hooksFile = await readJson<Record<string, unknown>>(
        hooksPath, { fallback: {} }
      );
      result.push(...extractHooks(hooksFile, "plugin", hooksPath));
    }
  }

  return result;
}

export interface HookPreviewResult {
  type: HookType;
  summary: string;
  output?: string;
  error?: string;
  exitCode?: number;
}

function buildSamplePayload(hook: HookInfo): Record<string, unknown> {
  const base: Record<string, unknown> = {
    session_id: "axt-preview",
    hook_event: hook.event,
  };
  if (hook.event === "PreToolUse" || hook.event === "PostToolUse") {
    base.tool_name = hook.matcher === "*" ? "Bash" : hook.matcher;
    base.tool_input = {};
  }
  if (hook.event === "UserPromptSubmit") {
    base.user_prompt = "(preview)";
  }
  return base;
}

export async function previewHook(hook: HookInfo, timeoutMs = 5000): Promise<HookPreviewResult> {
  if (hook.type === "command") {
    if (!hook.command) return { type: "command", summary: "(no command)" };
    const payload = JSON.stringify(buildSamplePayload(hook));
    return new Promise((resolve) => {
      const child = spawn("sh", ["-c", hook.command!], {
        stdio: ["pipe", "pipe", "pipe"],
        env: { ...process.env, HOOK_EVENT: hook.event },
        timeout: timeoutMs,
      });
      let stdout = "";
      let stderr = "";
      child.stdout.on("data", (d) => { stdout += d; });
      child.stderr.on("data", (d) => { stderr += d; });
      child.stdin.write(payload);
      child.stdin.end();
      child.on("close", (code) => {
        resolve({
          type: "command",
          summary: hook.command!,
          output: stdout.trim() || undefined,
          error: stderr.trim() || undefined,
          exitCode: code ?? 0,
        });
      });
      child.on("error", (err) => {
        resolve({
          type: "command",
          summary: hook.command!,
          error: err.message,
        });
      });
    });
  }

  if (hook.type === "http") {
    return {
      type: "http",
      summary: `${hook.url ?? "(no url)"}`,
      output: `POST ${hook.url}\nContent-Type: application/json\nBody: ${JSON.stringify(buildSamplePayload(hook), null, 2)}`,
    };
  }

  if (hook.type === "mcp_tool") {
    return {
      type: "mcp_tool",
      summary: `${hook.server}:${hook.tool}`,
      output: `Server: ${hook.server}\nTool: ${hook.tool}`,
    };
  }

  return {
    type: hook.type,
    summary: hook.type,
    output: hook.prompt ?? "(no prompt)",
  };
}

export function getHookDetail(hook: HookInfo): string {
  switch (hook.type) {
    case "command":
      return hook.command ?? "";
    case "http":
      return hook.url ?? "";
    case "mcp_tool":
      return `${hook.server}:${hook.tool}`;
    case "prompt":
    case "agent":
      return hook.prompt?.slice(0, 60) ?? "";
    default:
      return "";
  }
}
