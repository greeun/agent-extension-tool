import { statSync, existsSync } from "fs";
import { join, basename } from "path";
import { spawnSync } from "child_process";
import { listAllSkills } from "./skill.js";
import { listCommands } from "./commands.js";
import { listAllAgents } from "./agents.js";
import { listHooks } from "./hooks.js";
import { listMcpServers } from "./mcp.js";
import { listInstalledPlugins } from "./plugin.js";
import { readEnabledPlugins } from "./settings.js";
import { getModelPricing, getContextWindowSize } from "../pricing/models.js";
import { estimateTokens } from "@utils/tokens.js";
import { safeRead, safeReaddir } from "@utils/safe-io.js";
import type {
  Category,
  ContextSource,
  CollectOptions,
  CostImpact,
  ContextAnalysis,
  AnalyzeOptions,
} from "./context/types.js";

export { estimateTokens };

export type {
  Category,
  ContextSource,
  CollectOptions,
  CostImpact,
  ContextAnalysis,
  AnalyzeOptions,
} from "./context/types.js";

// ── Constants ──────────────────────────────────────────────────────────────

const FIXED_SYSTEM_PROMPT_TOKENS = 4200;
const FIXED_USER_CONTEXT_TOKENS = 280;
const FIXED_HOOK_OUTPUT_TOKENS = 200;
const MEMORY_LINE_LIMIT = 200;
const MEMORY_BYTE_LIMIT = 25 * 1024;

// ── Helpers ────────────────────────────────────────────────────────────────

function truncateMemory(content: string): string {
  const lines = content.split("\n");
  const limitedLines = lines.slice(0, MEMORY_LINE_LIMIT);
  const joined = limitedLines.join("\n");
  if (Buffer.byteLength(joined, "utf-8") <= MEMORY_BYTE_LIMIT) {
    return joined;
  }
  // Byte limit: trim chars until within limit
  let result = joined;
  while (Buffer.byteLength(result, "utf-8") > MEMORY_BYTE_LIMIT) {
    result = result.slice(0, result.length - 100);
  }
  return result;
}

function makeSource(
  name: string,
  category: Category,
  path: string,
  content: string,
  actionable: boolean,
  hint?: string,
): ContextSource {
  const tokens = estimateTokens(content);
  return {
    name,
    category,
    path,
    chars: content.length,
    estimatedTokens: tokens,
    percentage: 0,
    actionable,
    hint,
    content,
  };
}

function makeFixed(
  name: string,
  category: Category,
  tokens: number,
  content?: string,
): ContextSource {
  return {
    name,
    category,
    path: "",
    chars: content?.length ?? 0,
    estimatedTokens: tokens,
    percentage: 0,
    actionable: false,
    content,
  };
}

function getClaudeVersion(): string {
  try {
    const result = spawnSync("claude", ["--version"], { encoding: "utf-8", timeout: 3000 });
    return result.stdout?.trim() ?? "unknown";
  } catch { return "unknown"; }
}

function getGitStatus(projectDir: string): string {
  try {
    const result = spawnSync("git", ["status"], { cwd: projectDir, encoding: "utf-8", timeout: 5000 });
    return result.stdout?.trim() ?? "";
  } catch { return ""; }
}

function buildSystemPromptPreview(version: string): string {
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

function buildUserContextPreview(homeDir: string, projectDir: string): string {
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

function buildHookPreview(hook: { event: string; type: string; command?: string; url?: string; server?: string; tool?: string; timeout?: number; matcher?: string }): string {
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

// ── Main function ──────────────────────────────────────────────────────────

export async function collectContextSources(options: CollectOptions): Promise<ContextSource[]> {
  const { homeDir, projectDir, installedPluginsPath } = options;
  const sources: ContextSource[] = [];

  // 1. system-prompt (fixed)
  const claudeVersion = getClaudeVersion();
  sources.push(makeFixed("System Prompt", "system-prompt", FIXED_SYSTEM_PROMPT_TOKENS, buildSystemPromptPreview(claudeVersion)));

  // 2. claude-md
  const claudeMdCandidates = [
    { name: "CLAUDE.md (global)", path: join(homeDir, "CLAUDE.md") },
    { name: "CLAUDE.md (user)", path: join(homeDir, ".claude", "CLAUDE.md") },
    { name: "CLAUDE.md (project)", path: join(projectDir, "CLAUDE.md") },
    { name: "CLAUDE.md (project/.claude)", path: join(projectDir, ".claude", "CLAUDE.md") },
    { name: "CLAUDE.local.md (local)", path: join(projectDir, "CLAUDE.local.md") },
  ];
  for (const c of claudeMdCandidates) {
    const content = await safeRead(c.path);
    if (content !== null) {
      sources.push(makeSource(c.name, "claude-md", c.path, content, true));
    }
  }

  // 3. settings
  const projectSettingsKey = projectDir.replace(/\//g, "-").replace(/^-/, "");
  const projectSettingsDir = join(homeDir, ".claude", "projects", projectSettingsKey);
  const settingsCandidates = [
    { name: "settings.json (global)", path: join(homeDir, ".claude", "settings.json") },
    { name: "settings.local.json (global)", path: join(homeDir, ".claude", "settings.local.json") },
    { name: "settings.json (project)", path: join(projectSettingsDir, "settings.json") },
    { name: "settings.local.json (project)", path: join(projectSettingsDir, "settings.local.json") },
  ];
  for (const c of settingsCandidates) {
    const content = await safeRead(c.path);
    if (content !== null) {
      sources.push(makeSource(c.name, "settings", c.path, content, true));
    }
  }

  // 4. memory
  const memoryDir = join(homeDir, ".claude", "projects", projectSettingsKey, "memory");
  const memoryMainPath = join(memoryDir, "MEMORY.md");
  const memoryMain = await safeRead(memoryMainPath);
  if (memoryMain !== null) {
    const truncated = truncateMemory(memoryMain);
    sources.push(makeSource("MEMORY.md", "memory", memoryMainPath, truncated, true));
  }
  const memFiles = await safeReaddir(memoryDir);
  for (const f of memFiles) {
    if (!f.endsWith(".md") || f === "MEMORY.md") continue;
    const fullPath = join(memoryDir, f);
    const content = await safeRead(fullPath);
    if (content !== null) {
      sources.push(makeSource(`Memory: ${basename(f, ".md")}`, "memory", fullPath, content, true));
    }
  }

  // 5. skills
  try {
    const skills = await listAllSkills({ projectDir });
    for (const skill of skills) {
      const skillMdPath = join(skill.path, "SKILL.md");
      const skillMd = await safeRead(skillMdPath);
      let skillName = skill.name;
      let description = "";
      if (skillMd) {
        const fmMatch = skillMd.match(/^---\s*\n([\s\S]*?)\n---/);
        if (fmMatch) {
          const nameLine = fmMatch[1].match(/name:\s*"?([^"\n]+)"?/);
          if (nameLine) skillName = nameLine[1].trim();
          const descLine = fmMatch[1].match(/description:\s*"?([^"\n]+)"?/);
          if (descLine) description = descLine[1].trim();
        }
      }
      const text = `- ${skillName}: ${description}`;
      sources.push(makeSource(skill.name, "skills", skill.path, text, true));
    }
  } catch { /* gracefully handle missing data */ }

  // 6. mcp-tools
  try {
    const plugins = await listInstalledPlugins(installedPluginsPath);
    const mcpServers = await listMcpServers(plugins);
    for (const server of mcpServers) {
      const text = `- ${server.name} (${server.pluginId})`;
      sources.push(makeSource(server.name, "mcp-tools", "", text, false));
    }
  } catch { /* gracefully handle missing data */ }

  // 7. plugins
  try {
    const plugins = await listInstalledPlugins(installedPluginsPath);
    const userSettingsPath = join(homeDir, ".claude", "settings.json");
    const enabled = await readEnabledPlugins(userSettingsPath);
    for (const plugin of plugins) {
      if (enabled[plugin.id] !== true) continue;
      const text = `Plugin: ${plugin.name} v${plugin.version} — ${plugin.description ?? ""}`;
      sources.push(makeSource(plugin.name, "plugins", plugin.installPath, text, false));
    }
  } catch { /* gracefully handle missing data */ }

  // 8. hooks
  try {
    const userSettingsPath = join(homeDir, ".claude", "settings.json");
    const hooks = await listHooks({ userSettingsPath, projectDir, installedPluginsPath });
    const relevantHooks = hooks.filter(
      (h) => h.event === "SessionStart" || h.event === "UserPromptSubmit"
    );
    for (const hook of relevantHooks) {
      const name = `Hook: ${hook.event} (${hook.type})`;
      sources.push(makeFixed(name, "hooks", FIXED_HOOK_OUTPUT_TOKENS, buildHookPreview(hook)));
    }
  } catch { /* gracefully handle missing data */ }

  // 9. commands
  try {
    const commands = await listCommands({ projectDir });
    for (const cmd of commands) {
      const text = `- ${cmd.name}: ${cmd.description}`;
      sources.push(makeSource(cmd.name, "commands", cmd.sourcePath, text, true));
    }
  } catch { /* gracefully handle missing data */ }

  // 10. agents
  try {
    const agents = await listAllAgents({ projectDir });
    for (const agent of agents) {
      const text = `- ${agent.name}: ${agent.description}`;
      sources.push(makeSource(agent.name, "agents", agent.sourcePath, text, true));
    }
  } catch { /* gracefully handle missing data */ }

  // 11. git-status (fixed)
  const gitOutput = getGitStatus(projectDir);
  sources.push(makeFixed("Git Status", "git-status", 150, gitOutput || "No git repository or git not available."));

  // 12. user-context (fixed)
  sources.push(makeFixed("User Context", "user-context", FIXED_USER_CONTEXT_TOKENS, buildUserContextPreview(homeDir, projectDir)));

  // Calculate percentages
  const totalTokens = sources.reduce((sum, s) => sum + s.estimatedTokens, 0);
  for (const source of sources) {
    source.percentage = totalTokens > 0
      ? (source.estimatedTokens / totalTokens) * 100
      : 0;
  }

  return sources;
}

// ── Optimization Hints ─────────────────────────────────────────────────────

export function addHints(sources: ContextSource[]): void {
  const sortedByTokens = [...sources].sort((a, b) => b.estimatedTokens - a.estimatedTokens);
  const topNames = sortedByTokens.slice(0, 3).map((s) => s.name);

  for (const s of sources) {
    switch (s.category) {
      case "system-prompt":
        s.hint = `${s.estimatedTokens} tok (fixed, cannot reduce)`;
        break;
      case "user-context":
      case "git-status":
        s.hint = `${s.estimatedTokens} tok (fixed)`;
        break;
      case "claude-md":
        if (s.estimatedTokens > 500) {
          s.hint = `${s.estimatedTokens} tok — review for unnecessary sections`;
        }
        break;
      case "memory": {
        if (s.path) {
          try {
            const mtime = statSync(s.path).mtimeMs;
            const daysOld = Math.floor((Date.now() - mtime) / (24 * 60 * 60 * 1000));
            if (daysOld > 90) {
              s.hint = `${s.estimatedTokens} tok — not modified in ${daysOld} days (>90 days)`;
            }
          } catch {}
        }
        if (!s.hint && s.estimatedTokens > 100) {
          s.hint = `${s.estimatedTokens} tok`;
        }
        break;
      }
      case "skills":
        if (topNames.includes(s.name)) {
          s.hint = `${s.estimatedTokens} tok — top context consumer`;
        }
        break;
      case "hooks":
        s.hint = `~${s.estimatedTokens} tok estimated output`;
        break;
      case "mcp-tools":
        s.hint = `deferred — minimal context impact`;
        break;
      default:
        if (s.estimatedTokens > 100) {
          s.hint = `${s.estimatedTokens} tok`;
        }
    }
  }
}

// ── analyzeContext ─────────────────────────────────────────────────────────

export async function analyzeContext(options: AnalyzeOptions): Promise<ContextAnalysis> {
  const sources = await collectContextSources(options);
  const totalTokens = sources.reduce((sum, s) => sum + s.estimatedTokens, 0);
  const contextWindowSize = getContextWindowSize(options.model) ?? 1_000_000;
  const usedPercent = (totalTokens / contextWindowSize) * 100;

  const pricing = getModelPricing(options.model);
  const cacheWriteCost = pricing ? (totalTokens / 1_000_000) * pricing.cacheWrite : 0;
  const cacheReadCostPerTurn = pricing ? (totalTokens / 1_000_000) * pricing.cacheRead : 0;
  const perSessionCost = cacheWriteCost + (options.avgTurnsPerSession - 1) * cacheReadCostPerTurn;
  const monthlyCost = perSessionCost * options.avgSessionsPerDay * 30;

  addHints(sources);

  return {
    totalTokens,
    contextWindowSize,
    usedPercent,
    model: options.model,
    sources,
    costImpact: {
      model: options.model,
      cacheWriteCost,
      cacheReadCostPerTurn,
      avgTurnsPerSession: options.avgTurnsPerSession,
      avgSessionsPerDay: options.avgSessionsPerDay,
      perSessionCost,
      monthlyCost,
    },
  };
}
