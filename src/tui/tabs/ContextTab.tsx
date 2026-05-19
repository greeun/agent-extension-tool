import { useState, useEffect } from "react";
import { Box, Text, useInput, useStdout } from "ink";
import { homedir } from "os";
import { Table } from "../components/Table.js";
import { visibleWindow } from "../utils.js";
import { DetailPanel } from "../components/DetailPanel.js";
import { PreviewPanel, previewScrollHandler } from "../components/PreviewPanel.js";
import { Confirm } from "../components/Confirm.js";
import { PATHS, AXT_CONFIG_PATH } from "../../core/paths.js";
import { formatTokens } from "@utils/format.js";
import { unlinkSkill } from "../../core/skill.js";
import { aggregateBySession } from "../../core/usage.js";
import { loadUnifiedUsage } from "../../core/usage-unified.js";
import { loadConfig } from "../../config/index.js";
import { readRateLimits, type RateLimitData } from "../../core/rate-limits.js";
import {
  analyzeContext,
  type ContextAnalysis,
  type ContextSource,
  type Category,
} from "../../core/context-analysis.js";

interface SessionTokens {
  inputTokens: number;
  outputTokens: number;
  cacheWriteTokens: number;
  cacheReadTokens: number;
}

function emptySessionTokens(): SessionTokens {
  return { inputTokens: 0, outputTokens: 0, cacheWriteTokens: 0, cacheReadTokens: 0 };
}

function formatResetTime(resetAt: Date | null, tz: string): string {
  if (!resetAt) return "";
  const diffMs = resetAt.getTime() - Date.now();
  if (diffMs <= 0) return "now";
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  if (hours < 24) return remMins > 0 ? `${hours}h ${remMins}m` : `${hours}h`;
  const days = Math.floor(hours / 24);
  const remHours = hours % 24;
  return remHours > 0 ? `${days}d ${remHours}h` : `${days}d`;
}

function quotaBar(pct: number, width = 16): string {
  const filled = Math.round(Math.min(pct / 100, 1) * width);
  return "█".repeat(filled) + "░".repeat(width - filled);
}

function quotaColor(pct: number): string {
  if (pct >= 90) return "red";
  if (pct >= 70) return "yellow";
  return "green";
}

interface CategoryRow {
  category: string;
  catKey: Category;
  items: string;
  tokens: string;
  pct: string;
  bar: string;
  sources: ContextSource[];
}

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

function makeBar(pct: number, width: number = BAR_WIDTH): string {
  const filled = Math.round(Math.min(pct / 100, 1) * width);
  return "█".repeat(filled) + "░".repeat(width - filled);
}

function makeUsageBar(pct: number, width: number = 30): string {
  const filled = Math.round(Math.min(pct / 100, 1) * width);
  return "▓".repeat(filled) + "░".repeat(width - filled);
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
      catKey: cat,
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

function openInEditor(filePath: string, onDone: () => void, setStatus: (s: string) => void) {
  const editor = process.env.EDITOR ?? "vi";
  try {
    process.stdout.write("\x1b[?1049l");
    Bun.spawnSync([editor, filePath], { stdin: "inherit", stdout: "inherit", stderr: "inherit" });
    process.stdout.write("\x1b[?1049h\x1b[H\x1b[2J");
    onDone();
  } catch {
    process.stdout.write("\x1b[?1049h\x1b[H\x1b[2J");
    setStatus("Could not open editor");
  }
}

type ViewMode = "categories" | "sources" | "preview" | "confirm";

interface ContextTabProps {
  onSubViewChange?: (inSubView: boolean) => void;
}

export function ContextTab({ onSubViewChange }: ContextTabProps) {
  const [analysis, setAnalysis] = useState<ContextAnalysis | null>(null);
  const [rows, setRows] = useState<CategoryRow[]>([]);
  const [catIndex, setCatIndex] = useState(0);
  const [srcIndex, setSrcIndex] = useState(0);
  const [viewMode, setViewMode] = useState<ViewMode>("categories");
  const [previewScroll, setPreviewScroll] = useState(0);
  const [confirmMsg, setConfirmMsg] = useState("");
  const [confirmAction, setConfirmAction] = useState<(() => Promise<void>) | null>(null);
  const [status, setStatus] = useState("");

  const [rateLimits, setRateLimits] = useState<RateLimitData | null>(null);
  const [sessionTokens, setSessionTokens] = useState<SessionTokens>(emptySessionTokens());
  const [timezone, setTimezone] = useState("Asia/Seoul");

  const { stdout } = useStdout();
  const termRows = stdout?.rows ?? 24;
  // App chrome (tabbar+separator=2) + content padding (top+bottom=2) + PreviewPanel chrome (~9)
  const previewMaxLines = Math.max(5, termRows - 13);
  // ContextTab stacks rate-limit + budget + table + detail + cost-impact blocks.
  // Reserve ~31 rows of chrome (same as VaultTab's heavy layout) so the table
  // and the sources list window to the space that actually fits. Without this
  // the pane overflows the terminal and the top rows — including the table
  // column-header — scroll out of view while navigating.
  const listMaxRows = Math.max(3, termRows - 31);

  useEffect(() => {
    onSubViewChange?.(viewMode !== "categories");
  }, [viewMode]);

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
    setCatIndex(0);
    setSrcIndex(0);

    try {
      const config = await loadConfig(AXT_CONFIG_PATH);
      const tz = config.timezone;
      setTimezone(tz);

      setRateLimits(readRateLimits(PATHS.usageSnapshot));

      const todayStr = new Date().toLocaleDateString("en-CA", { timeZone: tz });
      const allEntries = await loadUnifiedUsage({
        claudeProjectsDir: PATHS.projects,
        codexSessionsDir: PATHS.codexSessions,
        geminiTmpDir: PATHS.geminiTmp,
        since: todayStr,
        platform: "claude",
      });

      const legacyEntries = allEntries.map((e) => ({
        ...e,
        cacheCreationTokens: e.cacheWriteTokens,
      }));
      const sessions = aggregateBySession(legacyEntries);
      if (sessions.length > 0) {
        const latest = sessions.sort((a, b) => b.lastTimestamp.localeCompare(a.lastTimestamp))[0];
        setSessionTokens({
          inputTokens: latest.inputTokens,
          outputTokens: latest.outputTokens,
          cacheWriteTokens: latest.cacheCreationTokens,
          cacheReadTokens: latest.cacheReadTokens,
        });
      } else {
        setSessionTokens(emptySessionTokens());
      }
    } catch {
      // usage loading is non-critical
    }
  };

  useEffect(() => { load(); }, []);

  const selectedRow = rows[catIndex];
  const selectedSource = selectedRow?.sources[srcIndex];

  useInput((input, key) => {
    if (viewMode === "confirm") return;

    if (input === "r") {
      setStatus("Refreshed");
      setViewMode("categories");
      load();
      return;
    }

    if (viewMode === "categories") {
      if (input === "j" || key.downArrow) setCatIndex((i) => Math.min(i + 1, rows.length - 1));
      if (input === "k" || key.upArrow) setCatIndex((i) => Math.max(i - 1, 0));
      if (key.return && selectedRow) {
        setSrcIndex(0);
        setViewMode("sources");
      }
      if (input === "e" && selectedRow) {
        const first = selectedRow.sources.find((s) => s.path);
        if (first?.path) {
          openInEditor(first.path, load, setStatus);
        }
      }
      return;
    }

    if (viewMode === "sources") {
      if (input === "j" || key.downArrow) setSrcIndex((i) => Math.min(i + 1, (selectedRow?.sources.length ?? 1) - 1));
      if (input === "k" || key.upArrow) setSrcIndex((i) => Math.max(i - 1, 0));
      if (key.escape || key.backspace || key.delete) {
        setViewMode("categories");
        return;
      }
      if (key.return && selectedSource?.content) {
        setPreviewScroll(0);
        setViewMode("preview");
        return;
      }
      if (input === "e" && selectedSource?.path) {
        openInEditor(selectedSource.path, load, setStatus);
        return;
      }
      if (input === "d" && selectedSource?.actionable) {
        if (selectedSource.category === "skills") {
          const skillName = selectedSource.name;
          setConfirmMsg(`Unlink skill "${skillName}"?`);
          setConfirmAction(() => async () => {
            try {
              await unlinkSkill(PATHS.skills, skillName);
              setStatus(`Unlinked "${skillName}"`);
              await load();
            } catch (e: any) { setStatus(`Error: ${e.message}`); }
          });
          setViewMode("confirm");
        } else if (selectedSource.category === "memory") {
          setConfirmMsg(`Delete memory "${selectedSource.name}"?`);
          setConfirmAction(() => async () => {
            try {
              const { unlink } = await import("fs/promises");
              await unlink(selectedSource.path);
              setStatus(`Deleted "${selectedSource.name}"`);
              await load();
            } catch (e: any) { setStatus(`Error: ${e.message}`); }
          });
          setViewMode("confirm");
        }
      }
      return;
    }

    if (viewMode === "preview") {
      if (key.escape || key.backspace || key.delete || key.return) {
        setViewMode("sources");
        return;
      }
      const lines = selectedSource?.content?.split("\n") ?? [];
      setPreviewScroll((s) => previewScrollHandler(input, key, s, lines.length, previewMaxLines));
      return;
    }
  });

  if (analysis === null) {
    return (
      <Box flexDirection="column">
        <Text dimColor>Scanning context sources...</Text>
      </Box>
    );
  }

  if (viewMode === "preview" && selectedSource?.content) {
    return (
      <Box flexDirection="column">
        <PreviewPanel
          title={selectedSource.name}
          subtitle={`${formatTokens(selectedSource.estimatedTokens)} tok  ${selectedSource.path}`}
          lines={selectedSource.content.split("\n")}
          scroll={previewScroll}
          maxLines={previewMaxLines}
          shortcuts="j/k:scroll  PgUp/PgDn:page  enter/esc:back"
        />
        {status && (
          <Box marginTop={1}>
            <Text dimColor>{status}</Text>
          </Box>
        )}
      </Box>
    );
  }

  const { model, totalTokens, contextWindowSize, usedPercent, costImpact } = analysis;
  const usageBar = makeUsageBar(usedPercent);

  const tableRows = rows.map((r) => ({
    category: r.category,
    items: r.items,
    tokens: r.tokens,
    pct: r.pct,
    bar: r.bar,
  }));

  const renderDetail = () => {
    if (!selectedRow) {
      return <DetailPanel lines={["No context sources found."]} />;
    }

    if (viewMode === "sources") {
      const all = selectedRow.sources;
      const [winStart, winEnd] = visibleWindow(all.length, srcIndex, listMaxRows);
      const sourceFields = all.slice(winStart, winEnd).map((src, vi) => {
        const i = winStart + vi;
        return {
          label: `${i === srcIndex ? "▸" : " "} ${src.name}`,
          value: `${formatTokens(src.estimatedTokens)} tok${src.content ? "" : " (fixed)"}${src.hint ? ` — ${src.hint}` : ""}`,
          color: i === srcIndex ? "cyan" : undefined,
        };
      });
      const more = all.length > sourceFields.length
        ? ` (${srcIndex + 1}/${all.length})`
        : "";
      return (
        <DetailPanel
          title={`${selectedRow.category} — ${selectedRow.tokens} (${selectedRow.pct})${more}`}
          fields={sourceFields}
          shortcuts="j/k:navigate  enter:preview  e:edit  d:delete  esc:back"
        />
      );
    }

    // viewMode === "categories"
    const firstHint = selectedRow.sources.find((s) => s.hint)?.hint;
    return (
      <DetailPanel
        title={selectedRow.category}
        fields={[
          { label: "Total tokens", value: selectedRow.tokens },
          { label: "Items", value: selectedRow.items },
          { label: "Percentage", value: selectedRow.pct },
          // Always render the Hint row (— when absent) so the panel height
          // stays constant as you navigate categories. A per-row height change
          // tips the pane over the terminal edge intermittently.
          { label: "Hint", value: firstHint ?? "—" },
        ]}
        shortcuts="j/k:navigate  enter:expand  e:edit  r:refresh"
      />
    );
  };

  return (
    <Box flexDirection="column">
      <Box marginBottom={1}>
        <Text bold>Context</Text>
        <Box flexGrow={1} />
        <Text dimColor>{`Model: ${model} (${formatTokens(contextWindowSize)})`}</Text>
      </Box>

      <Box marginBottom={1} flexDirection="column">
        <Box>
          <Text dimColor>{"5h:  "}</Text>
          {rateLimits?.fiveHour != null ? (
            <>
              <Text color={quotaColor(rateLimits.fiveHour)}>
                {quotaBar(rateLimits.fiveHour)} {rateLimits.fiveHour}%
              </Text>
              {rateLimits.fiveHourResetAt && (
                <Text dimColor>{` (resets in ${formatResetTime(rateLimits.fiveHourResetAt, timezone)})`}</Text>
              )}
            </>
          ) : (
            <Text dimColor>{"—  (no snapshot at ~/.claude/usage-snapshot.json)"}</Text>
          )}
        </Box>
        <Box>
          <Text dimColor>{"7d:  "}</Text>
          {rateLimits?.sevenDay != null ? (
            <>
              <Text color={quotaColor(rateLimits.sevenDay)}>
                {quotaBar(rateLimits.sevenDay)} {rateLimits.sevenDay}%
              </Text>
              {rateLimits.sevenDayResetAt && (
                <Text dimColor>{` (resets in ${formatResetTime(rateLimits.sevenDayResetAt, timezone)})`}</Text>
              )}
            </>
          ) : (
            <Text dimColor>—</Text>
          )}
        </Box>
        <Box>
          <Text dimColor>{"Tok: "}</Text>
          {(() => {
            const total = sessionTokens.inputTokens + sessionTokens.outputTokens + sessionTokens.cacheWriteTokens + sessionTokens.cacheReadTokens;
            if (total === 0) return <Text dimColor>— (no session)</Text>;
            const cache = sessionTokens.cacheWriteTokens + sessionTokens.cacheReadTokens;
            return (
              <Text>
                {`${formatTokens(total)} `}
                <Text dimColor>{`(In: ${formatTokens(sessionTokens.inputTokens)}, Out: ${formatTokens(sessionTokens.outputTokens)}${cache > 0 ? `, Cache: ${formatTokens(cache)}` : ""})`}</Text>
              </Text>
            );
          })()}
        </Box>
      </Box>

      <Box marginBottom={0} flexDirection="column">
        <Text>
          {"Context Budget  "}
          <Text bold color={usedPercent > 10 ? "yellow" : "green"}>
            {usedPercent.toFixed(1)}%
          </Text>
          {` of ${formatTokens(contextWindowSize)} (${formatTokens(totalTokens)} tok)`}
        </Text>
        <Box>
          <Text>{usageBar}</Text>
          <Text dimColor>{`  ${usedPercent.toFixed(1)}%`}</Text>
        </Box>
      </Box>
      <Table
        columns={[
          { key: "category", label: "Category", width: 20 },
          { key: "items", label: "Items", width: 7 },
          { key: "tokens", label: "Tokens", width: 10 },
          { key: "pct", label: "%", width: 8 },
          { key: "bar", label: "Usage", width: 18 },
        ]}
        rows={tableRows}
        selectedIndex={catIndex}
        maxRows={listMaxRows}
      />

      {renderDetail()}

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

      {viewMode === "confirm" && confirmAction && (
        <Confirm
          message={confirmMsg}
          onConfirm={async () => {
            await confirmAction();
            setViewMode("sources");
            setConfirmAction(null);
          }}
          onCancel={() => {
            setViewMode("sources");
            setConfirmAction(null);
          }}
        />
      )}

      {status && (
        <Box marginTop={1}>
          <Text dimColor>{status}</Text>
        </Box>
      )}
    </Box>
  );
}
