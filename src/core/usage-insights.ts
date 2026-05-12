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

export async function loadUsageInsights(_opts: LoadInsightsOpts): Promise<UsageInsights> {
  throw new Error("not implemented");
}
