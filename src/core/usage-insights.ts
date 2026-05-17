import { readdir, readFile, stat } from "fs/promises";
import { join } from "path";
import { readJson, writeJsonAtomic } from "./json-io.js";
import { AXT_CONFIG_DIR } from "./paths.js";

const CACHE_TTL_MS = 5 * 60 * 1000;
const insightsCachePath = (days: number) => join(AXT_CONFIG_DIR, "cache", `insights-${days}d.json`);

export interface PlanLimits {
  sessionUsedPct: number;
  weekUsedPct: number;
  sessionResetsAt: Date;
  weekResetsAt: Date;
}

export interface NamedPct {
  name: string;
  tokenPct: number;
}

export interface UsageInsights {
  planLimits: PlanLimits | null;
  subagentHeavyPct: number;
  largeContextPct: number;
  parallelSessionPct: number;
  skillBreakdown: NamedPct[];
  subagentBreakdown: NamedPct[];
  pluginBreakdown: NamedPct[];
}

export interface LoadInsightsOpts {
  days: 1 | 7;
  projectsDir: string;
  sessionMetaDir?: string; // kept for API compatibility, not used
  usageSnapshotPath: string;
  cacheDir?: string;
}

async function loadPlanLimits(snapshotPath: string): Promise<PlanLimits | null> {
  try {
    const raw = JSON.parse(await readFile(snapshotPath, "utf-8")) as {
      five_hour?: { used_percentage: number; resets_at: number };
      seven_day?: { used_percentage: number; resets_at: number };
    };
    if (!raw.five_hour || !raw.seven_day) return null;
    return {
      sessionUsedPct: raw.five_hour.used_percentage,
      weekUsedPct: raw.seven_day.used_percentage,
      sessionResetsAt: new Date(raw.five_hour.resets_at * 1000),
      weekResetsAt: new Date(raw.seven_day.resets_at * 1000),
    };
  } catch {
    return null;
  }
}

interface ParsedSession {
  filePath: string;
  inputTokens: number;
  outputTokens: number;
  hasAgentCalls: boolean;
  skills: string[];
  agents: string[];
  firstTimestamp: Date | null;
  lastTimestamp: Date | null;
}

async function parseJsonlSession(filePath: string): Promise<ParsedSession> {
  const empty: ParsedSession = {
    filePath, inputTokens: 0, outputTokens: 0,
    hasAgentCalls: false, skills: [], agents: [],
    firstTimestamp: null, lastTimestamp: null,
  };
  let content: string;
  try {
    content = await readFile(filePath, "utf-8");
  } catch {
    return empty;
  }

  let inputTokens = 0;
  let outputTokens = 0;
  let hasAgentCalls = false;
  const skills: string[] = [];
  const agents: string[] = [];
  let firstTimestamp: Date | null = null;
  let lastTimestamp: Date | null = null;

  for (const line of content.split("\n")) {
    if (!line.trim()) continue;
    try {
      const record = JSON.parse(line) as {
        type?: string;
        timestamp?: string;
        message?: {
          usage?: { input_tokens?: number; output_tokens?: number };
          content?: Array<{ type?: string; name?: string; input?: Record<string, unknown> }>;
        };
      };

      if (record.timestamp) {
        const ts = new Date(record.timestamp);
        if (!isNaN(ts.getTime())) {
          if (!firstTimestamp || ts < firstTimestamp) firstTimestamp = ts;
          if (!lastTimestamp || ts > lastTimestamp) lastTimestamp = ts;
        }
      }

      if (record.type !== "assistant") continue;

      const usage = record.message?.usage;
      if (usage) {
        inputTokens += usage.input_tokens ?? 0;
        outputTokens += usage.output_tokens ?? 0;
      }

      const contentArr = record.message?.content;
      if (!Array.isArray(contentArr)) continue;
      for (const block of contentArr) {
        if (block.type !== "tool_use") continue;
        if (block.name === "Skill") {
          skills.push((block.input?.skill as string) ?? "unknown");
        } else if (block.name === "Agent") {
          hasAgentCalls = true;
          agents.push(
            (block.input?.subagent_type as string) ??
            (block.input?.name as string) ??
            "general-purpose"
          );
        }
      }
    } catch {
      // skip malformed line
    }
  }

  return { filePath, inputTokens, outputTokens, hasAgentCalls, skills, agents, firstTimestamp, lastTimestamp };
}

async function findRecentJsonlFiles(projectsDir: string, cutoff: Date): Promise<string[]> {
  const result: string[] = [];
  let projects: string[];
  try {
    projects = await readdir(projectsDir);
  } catch {
    return [];
  }
  await Promise.all(projects.map(async (proj) => {
    const projDir = join(projectsDir, proj);
    let files: string[];
    try {
      files = await readdir(projDir);
    } catch {
      return;
    }
    await Promise.all(files.map(async (file) => {
      if (!file.endsWith(".jsonl")) return;
      const filePath = join(projDir, file);
      try {
        const s = await stat(filePath);
        if (s.mtime >= cutoff) result.push(filePath);
      } catch {
        // skip
      }
    }));
  }));
  return result;
}

function computeParallelPct(sessions: ParsedSession[], grandTotal: number): number {
  if (grandTotal === 0) return 0;
  const timed = sessions.filter((s) => s.firstTimestamp && s.lastTimestamp);
  let parallelTokens = 0;
  for (const m of timed) {
    const start = m.firstTimestamp!.getTime();
    const end = m.lastTimestamp!.getTime();
    const overlaps = timed.filter((other) => {
      if (other.filePath === m.filePath) return false;
      const oStart = other.firstTimestamp!.getTime();
      const oEnd = other.lastTimestamp!.getTime();
      return oStart < end && oEnd > start;
    });
    if (overlaps.length >= 3) parallelTokens += m.inputTokens + m.outputTokens;
  }
  return Math.round((parallelTokens / grandTotal) * 100);
}

interface InsightsCacheFile {
  savedAt: number;
  data: UsageInsights;
}

export async function loadUsageInsights(opts: LoadInsightsOpts): Promise<UsageInsights> {
  const { days, projectsDir, usageSnapshotPath } = opts;
  const cachePath = opts.cacheDir
    ? join(opts.cacheDir, `insights-${days}d.json`)
    : insightsCachePath(days);

  const cached = await readJson<InsightsCacheFile>(cachePath, { fallback: null as unknown as InsightsCacheFile });
  if (cached && Date.now() - cached.savedAt < CACHE_TTL_MS) {
    return cached.data;
  }

  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000);

  const [planLimits, jsonlFiles] = await Promise.all([
    loadPlanLimits(usageSnapshotPath),
    findRecentJsonlFiles(projectsDir, cutoff),
  ]);

  const sessions = await Promise.all(jsonlFiles.map(parseJsonlSession));

  const grandTotal = sessions.reduce((s, m) => s + m.inputTokens + m.outputTokens, 0);

  const subagentHeavyTokens = sessions
    .filter((m) => m.hasAgentCalls)
    .reduce((s, m) => s + m.inputTokens + m.outputTokens, 0);
  const largeContextTokens = sessions
    .filter((m) => m.inputTokens > 150_000)
    .reduce((s, m) => s + m.inputTokens + m.outputTokens, 0);

  const subagentHeavyPct = grandTotal > 0 ? Math.round((subagentHeavyTokens / grandTotal) * 100) : 0;
  const largeContextPct = grandTotal > 0 ? Math.round((largeContextTokens / grandTotal) * 100) : 0;
  const parallelSessionPct = computeParallelPct(sessions, grandTotal);

  const skillTokens: Record<string, number> = {};
  const agentTokens: Record<string, number> = {};

  for (const m of sessions) {
    const sessionTokens = m.inputTokens + m.outputTokens;
    const total = m.skills.length + m.agents.length;
    if (total === 0) continue;
    const share = sessionTokens / total;
    for (const s of m.skills) skillTokens[s] = (skillTokens[s] ?? 0) + share;
    for (const a of m.agents) agentTokens[a] = (agentTokens[a] ?? 0) + share;
  }

  const toBreakdown = (map: Record<string, number>): NamedPct[] =>
    Object.entries(map)
      .map(([name, tokens]) => ({
        name,
        tokenPct: grandTotal > 0 ? Math.round((tokens / grandTotal) * 100) : 0,
      }))
      .sort((a, b) => b.tokenPct - a.tokenPct);

  const skillBreakdown = toBreakdown(skillTokens);

  const pluginTokens: Record<string, number> = {};
  for (const [name, tokens] of Object.entries(skillTokens)) {
    if (name.includes(":")) {
      const plugin = name.split(":")[0];
      pluginTokens[plugin] = (pluginTokens[plugin] ?? 0) + tokens;
    }
  }

  const result: UsageInsights = {
    planLimits,
    subagentHeavyPct,
    largeContextPct,
    parallelSessionPct,
    skillBreakdown,
    subagentBreakdown: toBreakdown(agentTokens),
    pluginBreakdown: toBreakdown(pluginTokens),
  };

  writeJsonAtomic(cachePath, { savedAt: Date.now(), data: result } satisfies InsightsCacheFile).catch(() => {});

  return result;
}
