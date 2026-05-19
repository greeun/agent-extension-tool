import { spawnSync } from "child_process";

// ── Constants ──────────────────────────────────────────────────────────────

export const FIXED_SYSTEM_PROMPT_TOKENS = 4200;
export const FIXED_USER_CONTEXT_TOKENS = 280;
export const FIXED_HOOK_OUTPUT_TOKENS = 200;

// ── Helpers ────────────────────────────────────────────────────────────────

export function getClaudeVersion(): string {
  try {
    const result = spawnSync("claude", ["--version"], { encoding: "utf-8", timeout: 3000 });
    return result.stdout?.trim() ?? "unknown";
  } catch { return "unknown"; }
}

export function getGitStatus(projectDir: string): string {
  try {
    const result = spawnSync("git", ["status"], { cwd: projectDir, encoding: "utf-8", timeout: 5000 });
    return result.stdout?.trim() ?? "";
  } catch { return ""; }
}

export function buildSystemPromptPreview(version: string): string {
  return [
    `# Claude Code System Prompt (v${version})`,
    "",
    "The base system prompt is embedded in the Claude Code binary and sent",
    "at the start of every API call. It cannot be read directly from disk.",
    "",
    "## Known Sections",
    "",
    "1. Identity — \"You are Claude Code, Anthropic's official CLI for Claude.\"",
    "2. Tool definitions — Bash, Read, Edit, Write, Agent, WebSearch, etc.",
    "3. Safety & permissions — OWASP guidelines, destructive-action guards",
    "4. Git workflow — commit, PR, branch conventions",
    "5. Tone & style — concise, no emojis, file:line references",
    "6. Context management — compression, session guidance",
    "7. Environment — platform, shell, model, working directory",
    "",
    `Estimated tokens: ${FIXED_SYSTEM_PROMPT_TOKENS}`,
    "",
    "Note: Use \`claude --append-system-prompt <text>\` to add custom instructions.",
    "Use \`claude --system-prompt <text>\` to replace the entire system prompt.",
  ].join("\n");
}

export function buildUserContextPreview(homeDir: string, projectDir: string): string {
  const email = process.env.USER_EMAIL ?? process.env.EMAIL ?? "—";
  const today = new Date().toLocaleDateString("en-CA");
  return [
    "# User Context",
    "",
    "Dynamic per-session values injected by Claude Code:",
    "",
    `- userEmail: ${email}`,
    `- currentDate: ${today}`,
    `- homeDir: ${homeDir}`,
    `- projectDir: ${projectDir}`,
    `- platform: ${process.platform}`,
    `- shell: ${process.env.SHELL ?? "—"}`,
    "",
    `Estimated tokens: ${FIXED_USER_CONTEXT_TOKENS}`,
  ].join("\n");
}

export function buildHookPreview(hook: { event: string; type: string; command?: string; url?: string; server?: string; tool?: string; timeout?: number; matcher?: string }): string {
  const lines = [
    `# Hook: ${hook.event}`,
    "",
    `Type: ${hook.type}`,
  ];
  if (hook.matcher) lines.push(`Matcher: ${hook.matcher}`);
  if (hook.command) lines.push(`Command: ${hook.command}`);
  if (hook.url) lines.push(`URL: ${hook.url}`);
  if (hook.server) lines.push(`MCP Server: ${hook.server}`);
  if (hook.tool) lines.push(`Tool: ${hook.tool}`);
  if (hook.timeout) lines.push(`Timeout: ${hook.timeout}ms`);
  lines.push("", `Estimated output tokens: ${FIXED_HOOK_OUTPUT_TOKENS}`);
  return lines.join("\n");
}
