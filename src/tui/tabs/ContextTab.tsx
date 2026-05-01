import React, { useState, useEffect } from "react";
import { Box, Text, useInput, useStdout } from "ink";
import { homedir } from "os";
import { Table } from "../components/Table.js";
import { DetailPanel } from "../components/DetailPanel.js";
import { Confirm } from "../components/Confirm.js";
import { PATHS } from "../../core/paths.js";
import { formatTokens } from "../../cli/formatters.js";
import { unlinkSkill } from "../../core/skill.js";
import {
  analyzeContext,
  type ContextAnalysis,
  type ContextSource,
  type Category,
} from "../../core/context-analysis.js";

// ── Types ──────────────────────────────────────────────────────────────────

interface CategoryRow {
  category: string;
  items: string;
  tokens: string;
  pct: string;
  bar: string;
  sources: ContextSource[];
}

// ── Constants ──────────────────────────────────────────────────────────────

const CATEGORY_LABELS: Record<Category, string> = {
  "system-prompt": "System prompt",
  "claude-md": "CLAUDE.md",
  "settings": "Settings",
  "memory": "Memory",
  "skills": "Skills metadata",
  "mcp-tools": "MCP tools",
  "plugins": "Plugins",
  "hooks": "Hooks output",
  "commands": "Commands",
  "agents": "Agents",
  "git-status": "Git status",
  "user-context": "User context",
};

const BAR_WIDTH = 16;

// ── Helpers ────────────────────────────────────────────────────────────────

function makeBar(pct: number, width: number = BAR_WIDTH): string {
  const filled = Math.round(Math.min(pct / 100, 1) * width);
  const empty = width - filled;
  return "█".repeat(filled) + "░".repeat(empty);
}

function makeUsageBar(pct: number, width: number = 30): string {
  const filled = Math.round(Math.min(pct / 100, 1) * width);
  const empty = width - filled;
  return "▓".repeat(filled) + "░".repeat(empty);
}

function groupByCategory(sources: ContextSource[]): CategoryRow[] {
  const map = new Map<Category, ContextSource[]>();
  for (const src of sources) {
    const existing = map.get(src.category) ?? [];
    existing.push(src);
    map.set(src.category, existing);
  }

  const totalTokens = sources.reduce((s, src) => s + src.estimatedTokens, 0);

  const rows: CategoryRow[] = [];
  for (const [cat, srcs] of map.entries()) {
    const catTokens = srcs.reduce((s, src) => s + src.estimatedTokens, 0);
    const catPct = totalTokens > 0 ? (catTokens / totalTokens) * 100 : 0;
    rows.push({
      category: CATEGORY_LABELS[cat] ?? cat,
      items: String(srcs.length),
      tokens: formatTokens(catTokens),
      pct: `${catPct.toFixed(1)}%`,
      bar: makeBar(catPct),
      sources: srcs,
    });
  }

  rows.sort((a, b) => {
    const aT = a.sources.reduce((s, src) => s + src.estimatedTokens, 0);
    const bT = b.sources.reduce((s, src) => s + src.estimatedTokens, 0);
    return bT - aT;
  });

  return rows;
}

// ── Component ──────────────────────────────────────────────────────────────

export function ContextTab() {
  const [analysis, setAnalysis] = useState<ContextAnalysis | null>(null);
  const [rows, setRows] = useState<CategoryRow[]>([]);
  const [index, setIndex] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<"list" | "confirm">("list");
  const [confirmMsg, setConfirmMsg] = useState("");
  const [confirmAction, setConfirmAction] = useState<(() => Promise<void>) | null>(null);
  const [status, setStatus] = useState("");

  const { stdout } = useStdout();
  const termWidth = stdout?.columns ?? 80;

  const load = async () => {
    const result = await analyzeContext({
      homeDir: homedir(),
      projectDir: process.cwd(),
      installedPluginsPath: PATHS.installedPlugins,
      model: "claude-opus-4-6",
      avgTurnsPerSession: 30,
      avgSessionsPerDay: 5,
    });
    setAnalysis(result);
    setRows(groupByCategory(result.sources));
    setIndex(0);
  };

  useEffect(() => {
    load();
  }, []);

  useInput((input, key) => {
    if (mode !== "list") return;

    if (input === "j" || key.downArrow) {
      if (rows.length > 0) setIndex((i) => Math.min(i + 1, rows.length - 1));
      return;
    }
    if (input === "k" || key.upArrow) {
      setIndex((i) => Math.max(i - 1, 0));
      return;
    }
    if (key.return) {
      setExpanded((e) => !e);
      return;
    }
    if (input === "r") {
      setStatus("Refreshed");
      load();
      return;
    }
    if (input === "e") {
      const selected = rows[index];
      if (!selected) return;
      const firstWithPath = selected.sources.find((s) => s.path);
      if (!firstWithPath?.path) return;
      const editor = process.env.EDITOR ?? "vi";
      try {
        Bun.spawn([editor, firstWithPath.path], { stdio: ["inherit", "inherit", "inherit"] });
      } catch {
        setStatus("Could not open editor");
      }
      return;
    }
    if (input === "d") {
      const selected = rows[index];
      if (!selected) return;
      const actionable = selected.sources.filter((s) => s.actionable);
      if (actionable.length === 0) return;

      const firstActionable = actionable[0];
      const catKey = firstActionable.category as Category;

      if (catKey === "skills") {
        setConfirmMsg(`Remove skill "${firstActionable.name}"?`);
        setConfirmAction(() => async () => {
          try {
            await unlinkSkill(PATHS.skills, firstActionable.name);
            setStatus(`Removed "${firstActionable.name}"`);
            await load();
          } catch (e: any) {
            setStatus(`Error: ${e.message}`);
          }
        });
        setMode("confirm");
      } else if (catKey === "memory") {
        setConfirmMsg(`Delete memory file "${firstActionable.name}"?`);
        setConfirmAction(() => async () => {
          try {
            const { unlink } = await import("fs/promises");
            await unlink(firstActionable.path);
            setStatus(`Deleted "${firstActionable.name}"`);
            await load();
          } catch (e: any) {
            setStatus(`Error: ${e.message}`);
          }
        });
        setMode("confirm");
      }
    }
  });

  if (analysis === null) {
    return (
      <Box flexDirection="column">
        <Text dimColor>Scanning context sources...</Text>
      </Box>
    );
  }

  const selected = rows[index];
  const { model, totalTokens, contextWindowSize, usedPercent, costImpact } = analysis;
  const usageBar = makeUsageBar(usedPercent);

  // Build detail panel content
  const detailFields = selected ? (() => {
    const catTokens = selected.sources.reduce((s, src) => s + src.estimatedTokens, 0);
    if (!expanded) {
      const firstHint = selected.sources.find((s) => s.hint)?.hint;
      return [
        { label: "Total tokens", value: formatTokens(catTokens) },
        { label: "Items", value: selected.items },
        ...(firstHint ? [{ label: "Hint", value: firstHint }] : []),
      ];
    }
    // Expanded: each source
    return selected.sources.map((src) => ({
      label: src.name,
      value: `${formatTokens(src.estimatedTokens)}${src.hint ? ` — ${src.hint}` : ""}`,
    }));
  })() : undefined;

  const tableRows = rows.map((r) => ({
    category: r.category,
    items: r.items,
    tokens: r.tokens,
    pct: r.pct,
    bar: r.bar,
  }));

  const shortcuts = selected
    ? `enter:${expanded ? "collapse" : "expand"}  e:edit  d:delete  r:refresh`
    : "r:refresh";

  return (
    <Box flexDirection="column">
      {/* Header */}
      <Box marginBottom={1}>
        <Text bold>Context</Text>
        <Box flexGrow={1} />
        <Text dimColor>{`Model: ${model} (${formatTokens(contextWindowSize)})`}</Text>
      </Box>

      {/* Usage summary */}
      <Box marginBottom={1} flexDirection="column">
        <Text>
          {"Session Start Context Usage  "}
          <Text bold>{`${usedPercent.toFixed(1)}%`}</Text>
          {` of ${formatTokens(contextWindowSize)} tokens (${formatTokens(totalTokens)} tok)`}
        </Text>
        <Box>
          <Text>{usageBar}</Text>
          <Text dimColor>{`  ${usedPercent.toFixed(1)}%`}</Text>
        </Box>
      </Box>

      {/* Table */}
      <Table
        columns={[
          { key: "category", label: "Category", width: 20 },
          { key: "items", label: "Items", width: 7 },
          { key: "tokens", label: "Tokens", width: 10 },
          { key: "pct", label: "%", width: 8 },
          { key: "bar", label: "Usage", width: 18 },
        ]}
        rows={tableRows}
        selectedIndex={index}
      />

      {/* Detail panel */}
      {selected ? (
        <DetailPanel
          title={selected.category}
          fields={detailFields}
          shortcuts={shortcuts}
        />
      ) : (
        <DetailPanel lines={["No context sources found."]} />
      )}

      {/* Cost Impact */}
      <Box borderStyle="single" paddingX={1} marginTop={1} flexDirection="column">
        <Text bold>{`Cost Impact (${model})`}</Text>
        <Box gap={2}>
          <Box flexDirection="column">
            <Text dimColor>Cache write</Text>
            <Text>{`$${costImpact.cacheWriteCost.toFixed(4)}`}</Text>
          </Box>
          <Box flexDirection="column">
            <Text dimColor>Cache read/turn</Text>
            <Text>{`$${costImpact.cacheReadCostPerTurn.toFixed(5)}`}</Text>
          </Box>
          <Box flexDirection="column">
            <Text dimColor>Per session</Text>
            <Text>{`$${costImpact.perSessionCost.toFixed(4)}`}</Text>
          </Box>
          <Box flexDirection="column">
            <Text dimColor>Monthly est.</Text>
            <Text>{`$${costImpact.monthlyCost.toFixed(2)}`}</Text>
          </Box>
        </Box>
      </Box>

      {/* Confirm dialog */}
      {mode === "confirm" && confirmAction && (
        <Confirm
          message={confirmMsg}
          onConfirm={async () => {
            await confirmAction();
            setMode("list");
            setConfirmAction(null);
          }}
          onCancel={() => {
            setMode("list");
            setConfirmAction(null);
          }}
        />
      )}

      {/* Status */}
      {status && (
        <Box marginTop={1}>
          <Text dimColor>{status}</Text>
        </Box>
      )}
    </Box>
  );
}
