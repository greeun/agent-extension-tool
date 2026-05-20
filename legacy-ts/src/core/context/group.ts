import { formatTokens } from "@utils/format.js";
import { renderBar } from "@utils/bar.js";
import type { Category, ContextSource } from "./types.js";

export interface CategoryRow {
  category: string;
  catKey: Category;
  items: string;
  tokens: string;
  pct: string;
  bar: string;
  sources: ContextSource[];
}

export const CATEGORY_LABELS: Record<Category, string> = {
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

export function groupByCategory(sources: ContextSource[]): CategoryRow[] {
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
      bar: renderBar(Math.round(Math.min(catPct / 100, 1) * BAR_WIDTH), BAR_WIDTH),
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
