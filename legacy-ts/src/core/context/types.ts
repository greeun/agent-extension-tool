export type Category =
  | "system-prompt" | "claude-md" | "settings" | "memory" | "skills"
  | "mcp-tools" | "plugins" | "hooks" | "commands" | "agents"
  | "git-status" | "user-context";

export interface ContextSource {
  name: string;
  category: Category;
  path: string;
  chars: number;
  estimatedTokens: number;
  percentage: number;
  actionable: boolean;
  hint?: string;
  content?: string;
}

export interface CollectOptions {
  homeDir: string;
  projectDir: string;
  installedPluginsPath: string;
}

export interface CostImpact {
  model: string;
  cacheWriteCost: number;
  cacheReadCostPerTurn: number;
  avgTurnsPerSession: number;
  avgSessionsPerDay: number;
  perSessionCost: number;
  monthlyCost: number;
}

export interface ContextAnalysis {
  totalTokens: number;
  contextWindowSize: number;
  usedPercent: number;
  model: string;
  sources: ContextSource[];
  costImpact: CostImpact;
}

export interface AnalyzeOptions extends CollectOptions {
  model: string;
  avgTurnsPerSession: number;
  avgSessionsPerDay: number;
}
