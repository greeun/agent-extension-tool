import { readdir, readFile } from "fs/promises";
import { join } from "path";

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
  sessionMetaDir: string;
  usageSnapshotPath: string;
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

interface SessionMeta {
  session_id: string;
  start_time: string;
  duration_minutes: number;
  input_tokens: number;
  output_tokens: number;
  tool_counts: Record<string, number>;
}

async function loadSessionMetas(metaDir: string, cutoff: Date): Promise<SessionMeta[]> {
  let files: string[];
  try {
    files = await readdir(metaDir);
  } catch {
    return [];
  }
  const metas: SessionMeta[] = [];
  for (const file of files) {
    if (!file.endsWith(".json")) continue;
    try {
      const raw = JSON.parse(await readFile(join(metaDir, file), "utf-8")) as SessionMeta;
      if (new Date(raw.start_time) >= cutoff) metas.push(raw);
    } catch {
      // skip malformed
    }
  }
  return metas;
}

interface SessionTools {
  skills: string[];
  agents: string[];
}

async function extractToolsFromJsonl(filePath: string, sessionId: string): Promise<SessionTools> {
  const skills: string[] = [];
  const agents: string[] = [];
  let content: string;
  try {
    content = await readFile(filePath, "utf-8");
  } catch {
    return { skills, agents };
  }
  for (const line of content.split("\n")) {
    if (!line.trim()) continue;
    try {
      const record = JSON.parse(line) as {
        type?: string;
        sessionId?: string;
        message?: {
          content?: Array<{ type?: string; name?: string; input?: Record<string, unknown> }>;
        };
      };
      if (record.sessionId !== sessionId) continue;
      if (record.type !== "assistant") continue;
      const contentArr = record.message?.content;
      if (!Array.isArray(contentArr)) continue;
      for (const block of contentArr) {
        if (block.type !== "tool_use") continue;
        if (block.name === "Skill") {
          const skill = (block.input?.skill as string) ?? "unknown";
          skills.push(skill);
        } else if (block.name === "Agent") {
          const sub =
            (block.input?.subagent_type as string) ??
            (block.input?.name as string) ??
            "general-purpose";
          agents.push(sub);
        }
      }
    } catch {
      // skip malformed line
    }
  }
  return { skills, agents };
}

async function findJsonlForSession(projectsDir: string, sessionId: string): Promise<string | null> {
  let projects: string[];
  try {
    projects = await readdir(projectsDir);
  } catch {
    return null;
  }
  for (const proj of projects) {
    const candidate = join(projectsDir, proj, `${sessionId}.jsonl`);
    try {
      await readFile(candidate, "utf-8");
      return candidate;
    } catch {
      // not found here
    }
  }
  return null;
}

function computeParallelPct(metas: SessionMeta[], grandTotal: number): number {
  if (grandTotal === 0) return 0;
  let parallelTokens = 0;
  for (const m of metas) {
    const start = new Date(m.start_time).getTime();
    const end = start + m.duration_minutes * 60 * 1000;
    const overlaps = metas.filter((other) => {
      if (other.session_id === m.session_id) return false;
      const oStart = new Date(other.start_time).getTime();
      const oEnd = oStart + other.duration_minutes * 60 * 1000;
      return oStart < end && oEnd > start;
    });
    if (overlaps.length >= 3) {
      parallelTokens += m.input_tokens + m.output_tokens;
    }
  }
  return Math.round((parallelTokens / grandTotal) * 100);
}

export async function loadUsageInsights(opts: LoadInsightsOpts): Promise<UsageInsights> {
  const { days, projectsDir, sessionMetaDir, usageSnapshotPath } = opts;
  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000);

  const [planLimits, metas] = await Promise.all([
    loadPlanLimits(usageSnapshotPath),
    loadSessionMetas(sessionMetaDir, cutoff),
  ]);

  const grandTotal = metas.reduce((s, m) => s + m.input_tokens + m.output_tokens, 0);

  const subagentHeavyTokens = metas
    .filter((m) => (m.tool_counts["Agent"] ?? 0) > 0)
    .reduce((s, m) => s + m.input_tokens + m.output_tokens, 0);
  const largeContextTokens = metas
    .filter((m) => m.input_tokens > 150_000)
    .reduce((s, m) => s + m.input_tokens + m.output_tokens, 0);

  const subagentHeavyPct = grandTotal > 0 ? Math.round((subagentHeavyTokens / grandTotal) * 100) : 0;
  const largeContextPct = grandTotal > 0 ? Math.round((largeContextTokens / grandTotal) * 100) : 0;
  const parallelSessionPct = computeParallelPct(metas, grandTotal);

  const skillTokens: Record<string, number> = {};
  const agentTokens: Record<string, number> = {};

  const sessionsWithTools = metas.filter(
    (m) => (m.tool_counts["Skill"] ?? 0) > 0 || (m.tool_counts["Agent"] ?? 0) > 0
  );

  await Promise.all(
    sessionsWithTools.map(async (m) => {
      const jsonlPath = await findJsonlForSession(projectsDir, m.session_id);
      if (!jsonlPath) return;
      const { skills, agents } = await extractToolsFromJsonl(jsonlPath, m.session_id);
      const sessionTokens = m.input_tokens + m.output_tokens;
      const total = skills.length + agents.length;
      if (total === 0) return;
      const share = sessionTokens / total;
      for (const s of skills) skillTokens[s] = (skillTokens[s] ?? 0) + share;
      for (const a of agents) agentTokens[a] = (agentTokens[a] ?? 0) + share;
    })
  );

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
  const pluginBreakdown = toBreakdown(pluginTokens);

  return {
    planLimits,
    subagentHeavyPct,
    largeContextPct,
    parallelSessionPct,
    skillBreakdown,
    subagentBreakdown: toBreakdown(agentTokens),
    pluginBreakdown,
  };
}
