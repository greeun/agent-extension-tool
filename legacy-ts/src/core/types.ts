export type Platform = "claude" | "codex" | "gemini";

export interface UnifiedUsageEntry {
  platform: Platform;
  model: string;
  timestamp: string;
  sessionId: string;
  projectPath: string;
  inputTokens: number;
  outputTokens: number;
  cacheWriteTokens: number;
  cacheReadTokens: number;
  reasoningTokens: number;
  toolTokens: number;
}

export interface RateLimitInfo {
  platform: Platform;
  usedPercent: number;
  windowMinutes: number;
  resetsAt: string | null;
}
