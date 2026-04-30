import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { Database } from "bun:sqlite";
import { loadCursorMetrics, summarizeCursorMetrics } from "../../src/core/usage-cursor.js";
import { mkdtemp, rm, mkdir } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

describe("usage-cursor", () => {
  let tmpDir: string;
  let dbPath: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "axt-cursor-"));
    await mkdir(join(tmpDir, "ai-tracking"), { recursive: true });
    dbPath = join(tmpDir, "ai-tracking", "ai-code-tracking.db");

    const db = new Database(dbPath);
    db.run(`CREATE TABLE scored_commits (
      commitHash TEXT NOT NULL, branchName TEXT NOT NULL, scoredAt INTEGER NOT NULL,
      linesAdded INTEGER, linesDeleted INTEGER, tabLinesAdded INTEGER, tabLinesDeleted INTEGER,
      composerLinesAdded INTEGER, composerLinesDeleted INTEGER,
      humanLinesAdded INTEGER, humanLinesDeleted INTEGER,
      blankLinesAdded INTEGER, blankLinesDeleted INTEGER,
      commitMessage TEXT, commitDate TEXT, v1AiPercentage TEXT, v2AiPercentage TEXT,
      PRIMARY KEY (commitHash, branchName)
    )`);
    db.run(`INSERT INTO scored_commits VALUES (
      'abc123', 'main', 1775000000000, 100, 20, 0, 0, 50, 10, 30, 5, 0, 0,
      'feat: add feature', 'Mon Apr 28 10:00:00 2026 +0900', '0.00', '70.00'
    )`);
    db.run(`INSERT INTO scored_commits VALUES (
      'def456', 'main', 1775100000000, 200, 50, 0, 0, 100, 25, 80, 20, 0, 0,
      'fix: bug fix', 'Tue Apr 29 10:00:00 2026 +0900', '0.00', '60.00'
    )`);
    db.close();
  });

  afterEach(async () => { await rm(tmpDir, { recursive: true }); });

  test("loadCursorMetrics reads scored commits", () => {
    const metrics = loadCursorMetrics(dbPath);
    expect(metrics).toHaveLength(2);
    expect(metrics[0].commitHash).toBe("def456");
    expect(metrics[0].aiPercentage).toBe(60.0);
  });

  test("loadCursorMetrics returns empty for missing db", () => {
    const metrics = loadCursorMetrics("/nonexistent/path.db");
    expect(metrics).toHaveLength(0);
  });

  test("summarizeCursorMetrics computes totals", () => {
    const metrics = loadCursorMetrics(dbPath);
    const summary = summarizeCursorMetrics(metrics);
    expect(summary.totalCommits).toBe(2);
    expect(summary.totalLinesAdded).toBe(300);
    expect(summary.humanLinesAdded).toBe(110);
    expect(summary.aiLinesAdded).toBe(190);
    expect(summary.avgAiPercentage).toBe(65.0);
  });
});
