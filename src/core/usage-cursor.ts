import { Database } from "bun:sqlite";
import { existsSync } from "fs";

export interface CursorCommitMetrics {
  commitHash: string;
  branchName: string;
  scoredAt: number;
  linesAdded: number;
  linesDeleted: number;
  humanLinesAdded: number;
  humanLinesDeleted: number;
  composerLinesAdded: number;
  composerLinesDeleted: number;
  aiPercentage: number;
  commitMessage: string;
  commitDate: string;
}

export interface CursorSummary {
  totalCommits: number;
  totalLinesAdded: number;
  totalLinesDeleted: number;
  humanLinesAdded: number;
  humanLinesDeleted: number;
  aiLinesAdded: number;
  aiLinesDeleted: number;
  avgAiPercentage: number;
}

export function loadCursorMetrics(
  dbPath: string,
  options?: { since?: string; until?: string }
): CursorCommitMetrics[] {
  if (!existsSync(dbPath)) return [];

  const db = new Database(dbPath, { readonly: true });
  try {
    let query = "SELECT * FROM scored_commits";
    const conditions: string[] = [];
    const params: any[] = [];

    if (options?.since) {
      conditions.push("commitDate >= ?");
      params.push(options.since);
    }
    if (options?.until) {
      conditions.push("commitDate <= ?");
      params.push(options.until);
    }

    if (conditions.length > 0) {
      query += " WHERE " + conditions.join(" AND ");
    }
    query += " ORDER BY scoredAt DESC";

    const rows = db.query(query).all(...params) as any[];

    return rows.map((row) => ({
      commitHash: row.commitHash,
      branchName: row.branchName,
      scoredAt: row.scoredAt,
      linesAdded: row.linesAdded ?? 0,
      linesDeleted: row.linesDeleted ?? 0,
      humanLinesAdded: row.humanLinesAdded ?? 0,
      humanLinesDeleted: row.humanLinesDeleted ?? 0,
      composerLinesAdded: row.composerLinesAdded ?? 0,
      composerLinesDeleted: row.composerLinesDeleted ?? 0,
      aiPercentage: parseFloat(row.v2AiPercentage ?? row.v1AiPercentage ?? "0"),
      commitMessage: row.commitMessage ?? "",
      commitDate: row.commitDate ?? "",
    }));
  } finally {
    db.close();
  }
}

export function summarizeCursorMetrics(metrics: CursorCommitMetrics[]): CursorSummary {
  if (metrics.length === 0) {
    return { totalCommits: 0, totalLinesAdded: 0, totalLinesDeleted: 0, humanLinesAdded: 0, humanLinesDeleted: 0, aiLinesAdded: 0, aiLinesDeleted: 0, avgAiPercentage: 0 };
  }

  const totalLinesAdded = metrics.reduce((s, m) => s + m.linesAdded, 0);
  const totalLinesDeleted = metrics.reduce((s, m) => s + m.linesDeleted, 0);
  const humanLinesAdded = metrics.reduce((s, m) => s + m.humanLinesAdded, 0);
  const humanLinesDeleted = metrics.reduce((s, m) => s + m.humanLinesDeleted, 0);
  const aiLinesAdded = totalLinesAdded - humanLinesAdded;
  const aiLinesDeleted = totalLinesDeleted - humanLinesDeleted;
  const avgAi = metrics.reduce((s, m) => s + m.aiPercentage, 0) / metrics.length;

  return {
    totalCommits: metrics.length,
    totalLinesAdded,
    totalLinesDeleted,
    humanLinesAdded,
    humanLinesDeleted,
    aiLinesAdded,
    aiLinesDeleted,
    avgAiPercentage: avgAi,
  };
}
