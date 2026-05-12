import React, { useState, useEffect } from "react";
import { Box, Text, useInput, useStdout } from "ink";
import { Table } from "../components/Table.js";
import { PATHS } from "../../core/paths.js";
import type { CursorSummary } from "../../core/usage-cursor.js";

// tabbar(1) + separator(1) + paddingY(2) + header(1) + cards(6) + marginTop(1) + label(1) + table header(1) + table sep(1)
const CURSOR_OVERHEAD = 15;

interface Props {
  isFocused?: boolean;
  onFocusUp?: () => void;
  refreshKey?: number;
}

export function CursorTab({ isFocused = true, onFocusUp, refreshKey }: Props) {
  const { stdout } = useStdout();
  const termHeight = stdout?.rows ?? 24;
  const maxRows = Math.max(5, termHeight - CURSOR_OVERHEAD);

  const [summary, setSummary] = useState<CursorSummary | null>(null);
  const [commits, setCommits] = useState<Record<string, string>[]>([]);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState("");
  const [lastRefresh, setLastRefresh] = useState<string>("");

  const load = async () => {
    try {
      const { loadCursorMetrics, summarizeCursorMetrics } = await import("../../core/usage-cursor.js");
      const metrics = loadCursorMetrics(PATHS.cursorTrackingDb);
      const sum = summarizeCursorMetrics(metrics);
      setSummary(sum);
      setCommits(
        metrics.slice(0, 50).map((m) => ({
          hash: m.commitHash.slice(0, 8),
          message: m.commitMessage.slice(0, 40),
          aiPct: `${m.aiPercentage.toFixed(0)}%`,
          lines: `+${m.linesAdded}/-${m.linesDeleted}`,
          date: m.commitDate.slice(0, 16),
        }))
      );
      setLastRefresh(new Date().toLocaleTimeString());
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!refreshKey) return;
    load();
  }, [refreshKey]);

  useInput((input, key) => {
    if (!isFocused) return;
    if (error || !summary) return;
    if (input === "j" || key.downArrow) {
      if (commits.length > 0) setIndex((i) => Math.min(i + 1, commits.length - 1));
    }
    if (input === "k" || key.upArrow) {
      if (index <= 0 && onFocusUp) { onFocusUp(); return; }
      setIndex((i) => Math.max(i - 1, 0));
    }
  });

  if (error) {
    return (
      <Box flexDirection="column">
        <Text bold>Cursor IDE — AI Code Authorship</Text>
        <Box marginTop={1}><Text color="red">Cursor data not available: {error}</Text></Box>
      </Box>
    );
  }

  if (!summary) {
    return (
      <Box flexDirection="column">
        <Text bold>Cursor IDE — AI Code Authorship</Text>
        <Box marginTop={1}><Text dimColor>Loading Cursor metrics...</Text></Box>
      </Box>
    );
  }

  const pctBar = (pct: number) => {
    const filled = Math.round(pct / 100 * 20);
    return "█".repeat(filled) + "░".repeat(20 - filled);
  };

  return (
    <Box flexDirection="column">
      <Box>
        <Text bold>Cursor IDE — AI Code Authorship</Text>
        <Box flexGrow={1} />
        {lastRefresh && <Text dimColor>{lastRefresh}  r:refresh</Text>}
      </Box>

      <Box marginTop={1}>
        <Box flexDirection="column" borderStyle="single" paddingX={1} flexGrow={1} flexBasis={0}>
          <Text bold>Summary</Text>
          <Text>Commits:  {summary.totalCommits}</Text>
          <Text>Lines +:  {summary.totalLinesAdded.toLocaleString()}</Text>
          <Text>Lines -:  {summary.totalLinesDeleted.toLocaleString()}</Text>
        </Box>
        <Box flexDirection="column" borderStyle="single" paddingX={1} flexGrow={1} flexBasis={0}>
          <Text bold>AI vs Human</Text>
          <Text>AI lines:    {summary.aiLinesAdded.toLocaleString()}</Text>
          <Text>Human lines: {summary.humanLinesAdded.toLocaleString()}</Text>
          <Text>Avg AI %:    {summary.avgAiPercentage.toFixed(1)}%</Text>
        </Box>
        <Box flexDirection="column" borderStyle="single" paddingX={1} flexGrow={1} flexBasis={0}>
          <Text bold>AI Ratio</Text>
          <Text color="cyan">{pctBar(summary.avgAiPercentage)}</Text>
          <Text>{summary.avgAiPercentage.toFixed(1)}% AI-authored</Text>
        </Box>
      </Box>

      <Box marginTop={1} marginBottom={0} flexDirection="column">
        <Text bold>Recent Commits (top 50)</Text>
      </Box>
      <Table
        columns={[
          { key: "hash", label: "Hash", width: 10 },
          { key: "message", label: "Message", width: 42 },
          { key: "aiPct", label: "AI %", width: 7 },
          { key: "lines", label: "Lines", width: 14 },
        ]}
        rows={commits}
        selectedIndex={index}
        maxRows={maxRows}
      />
    </Box>
  );
}
