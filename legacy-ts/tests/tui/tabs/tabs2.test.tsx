/**
 * 남은 TUI 탭 컴포넌트 초기 렌더 상태 테스트
 * CommandsTab / AgentsTab / ProjectTab / UsageTab / CursorTab /
 * VaultTab / MarketTab / ManageTab / ContextTab / ExtensionsTab
 */

import { describe, test, expect, mock } from "bun:test";
import React from "react";
import { render } from "ink-testing-library";

// ─── 파일 전체 공통 mock (모든 탭에서 동적 import로 사용) ───────────────────

mock.module("../../../src/core/commands.js", () => ({
  listCommands: async () => [],
}));

mock.module("../../../src/core/agents.js", () => ({
  listAllAgents: async () => [],
}));

mock.module("../../../src/core/project-context.js", () => ({
  loadProjectContext: async () => [],
}));

mock.module("../../../src/core/project-usage.js", () => ({
  getProjectCount: () => 0,
  getProjects: () => [],
  scanProjectUsage: async () => new Map(),
}));

mock.module("../../../src/core/vault.js", () => ({
  listVaultItemsWithProjectState: async () => [],
  linkToProject: async () => {},
  unlinkFromProject: async () => {},
  linkToGlobal: async () => {},
  unlinkFromGlobal: async () => {},
  importToVault: async () => {},
  migrateToVault: async () => {},
  syncProject: async () => {},
}));

mock.module("../../../src/core/marketplace.js", () => ({
  listMarketplaces: async () => [],
  syncMarketplace: async () => ({ updated: false, before: "1.0.0", after: "1.0.0" }),
  removeMarketplace: async () => {},
  addMarketplace: async () => {},
  parseMarketplaceSource: () => null,
  getLocalVersion: async () => null,
  getMarketplaceVersion: async () => null,
  pooledMap: async (_items: any[], _fn: any, _opts?: any) => {},
}));

mock.module("../../../src/core/plugin.js", () => ({
  listInstalledPlugins: async () => [],
  getPluginInfo: async () => null,
  addInstalledPlugin: async () => {},
  removeInstalledPlugin: async () => {},
  updatePlugin: async () => ({ message: "ok" }),
}));

mock.module("../../../src/core/settings.js", () => ({
  readEnabledPlugins: async () => ({}),
  setPluginEnabled: async () => {},
  readFavoritePlugins: async () => ({}),
  setPluginFavorite: async () => {},
  readMarkedForUpdate: async () => ({}),
  setMarkedForUpdate: async () => {},
  removePluginFromSettings: async () => {},
  readExtraMarketplaces: async () => ({}),
}));

mock.module("../../../src/core/skill.js", () => ({
  listAllSkills: async () => [],
  linkSkill: async () => {},
  unlinkSkill: async () => {},
  isSymlinkSupported: () => true,
}));

mock.module("../../../src/core/mcp.js", () => ({
  listMcpServers: async () => [],
}));

mock.module("../../../src/core/hooks.js", () => ({
  listHooks: async () => [],
  getHookDetail: () => "",
  previewHook: async () => ({ type: "command", summary: "", output: "", exitCode: 0 }),
}));

mock.module("../../../src/core/usage-unified.js", () => ({
  loadUnifiedUsage: async () => [],
}));

mock.module("../../../src/core/usage.js", () => ({
  aggregateBySession: () => [],
  aggregateDaily: () => [],
  computeBlocks: () => [],
}));

mock.module("../../../src/core/usage-insights.js", () => ({
  loadUsageInsights: async () => ({
    planLimits: null,
    subagentHeavyPct: 0,
    largeContextPct: 0,
    parallelSessionPct: 0,
    skillBreakdown: [],
    subagentBreakdown: [],
    pluginBreakdown: [],
  }),
}));

mock.module("../../../src/config/index.js", () => ({
  loadConfig: async () => ({
    currency: ["usd"],
    exchangeRate: 1400,
    monthlyBudget: 100,
    timezone: "Asia/Seoul",
    locale: "ko-KR",
    startOfWeek: "monday",
    budgetWarningThreshold: 0.8,
    plans: {},
  }),
  saveConfig: async () => {},
}));

mock.module("../../../src/core/context-analysis.js", () => ({
  analyzeContext: async () => ({
    totalTokens: 0,
    contextWindowSize: 200_000,
    usedPercent: 0,
    model: "claude-opus-4-6",
    sources: [],
    costImpact: {
      model: "claude-opus-4-6",
      cacheWriteCost: 0,
      cacheReadCostPerTurn: 0,
      perSessionCost: 0,
      monthlyCost: 0,
      avgTurnsPerSession: 30,
      avgSessionsPerDay: 5,
    },
  }),
}));

mock.module("../../../src/core/rate-limits.js", () => ({
  readRateLimits: () => null,
}));

mock.module("../../../src/core/usage-cursor.js", () => ({
  loadCursorMetrics: () => [],
  summarizeCursorMetrics: () => ({
    totalCommits: 0,
    aiCommits: 0,
    avgAiPct: 0,
    totalLinesAdded: 0,
    totalLinesDeleted: 0,
    byRepo: {},
  }),
}));

// ─── CommandsTab ────────────────────────────────────────────────────────────

describe("CommandsTab", () => {
  test("크래시 없이 렌더된다", async () => {
    const { CommandsTab } = await import("../../../src/tui/tabs/CommandsTab.js");
    expect(() => render(React.createElement(CommandsTab))).not.toThrow();
  });

  test("컬럼 헤더 'Command'가 있다", async () => {
    const { CommandsTab } = await import("../../../src/tui/tabs/CommandsTab.js");
    const { lastFrame } = render(React.createElement(CommandsTab));
    expect(lastFrame() ?? "").toContain("Command");
  });

  test("'Description' 컬럼 헤더가 있다", async () => {
    const { CommandsTab } = await import("../../../src/tui/tabs/CommandsTab.js");
    const { lastFrame } = render(React.createElement(CommandsTab));
    expect(lastFrame() ?? "").toContain("Description");
  });

  test("커맨드 없으면 empty state 메시지가 있다", async () => {
    const { CommandsTab } = await import("../../../src/tui/tabs/CommandsTab.js");
    const { lastFrame } = render(React.createElement(CommandsTab));
    await new Promise((r) => setTimeout(r, 50));
    expect(lastFrame() ?? "").toContain("No commands found");
  });
});

// ─── AgentsTab ──────────────────────────────────────────────────────────────

describe("AgentsTab", () => {
  test("크래시 없이 렌더된다", async () => {
    const { AgentsTab } = await import("../../../src/tui/tabs/AgentsTab.js");
    expect(() => render(React.createElement(AgentsTab))).not.toThrow();
  });

  test("컬럼 헤더 'Agent'가 있다", async () => {
    const { AgentsTab } = await import("../../../src/tui/tabs/AgentsTab.js");
    const { lastFrame } = render(React.createElement(AgentsTab));
    expect(lastFrame() ?? "").toContain("Agent");
  });

  test("'Source' 컬럼 헤더가 있다", async () => {
    const { AgentsTab } = await import("../../../src/tui/tabs/AgentsTab.js");
    const { lastFrame } = render(React.createElement(AgentsTab));
    expect(lastFrame() ?? "").toContain("Source");
  });

  test("에이전트 없으면 empty state 메시지가 있다", async () => {
    const { AgentsTab } = await import("../../../src/tui/tabs/AgentsTab.js");
    const { lastFrame } = render(React.createElement(AgentsTab));
    await new Promise((r) => setTimeout(r, 50));
    expect(lastFrame() ?? "").toContain("No agents found");
  });
});

// ─── ProjectTab ─────────────────────────────────────────────────────────────

describe("ProjectTab", () => {
  test("크래시 없이 렌더된다", async () => {
    const { ProjectTab } = await import("../../../src/tui/tabs/ProjectTab.js");
    expect(() => render(React.createElement(ProjectTab))).not.toThrow();
  });

  test("'Project Context' 헤더가 있다", async () => {
    const { ProjectTab } = await import("../../../src/tui/tabs/ProjectTab.js");
    const { lastFrame } = render(React.createElement(ProjectTab));
    expect(lastFrame() ?? "").toContain("Project Context");
  });

  test("'File' 컬럼 헤더가 있다", async () => {
    const { ProjectTab } = await import("../../../src/tui/tabs/ProjectTab.js");
    const { lastFrame } = render(React.createElement(ProjectTab));
    expect(lastFrame() ?? "").toContain("File");
  });

  test("파일 없으면 empty state 메시지가 있다", async () => {
    const { ProjectTab } = await import("../../../src/tui/tabs/ProjectTab.js");
    const { lastFrame } = render(React.createElement(ProjectTab));
    await new Promise((r) => setTimeout(r, 50));
    expect(lastFrame() ?? "").toContain("No project context files found");
  });
});

// ─── UsageTab ───────────────────────────────────────────────────────────────

describe("UsageTab", () => {
  test("크래시 없이 렌더된다", async () => {
    const { UsageTab } = await import("../../../src/tui/tabs/UsageTab.js");
    expect(() => render(React.createElement(UsageTab))).not.toThrow();
  });

  test("렌더 후 내용이 비어있지 않다", async () => {
    const { UsageTab } = await import("../../../src/tui/tabs/UsageTab.js");
    const { lastFrame } = render(React.createElement(UsageTab));
    expect((lastFrame() ?? "").length).toBeGreaterThan(0);
  });

  test("platform prop으로 렌더해도 크래시 없다", async () => {
    const { UsageTab } = await import("../../../src/tui/tabs/UsageTab.js");
    expect(() =>
      render(React.createElement(UsageTab, { platform: "claude" }))
    ).not.toThrow();
  });
});

// ─── CursorTab ──────────────────────────────────────────────────────────────

describe("CursorTab", () => {
  test("크래시 없이 렌더된다", async () => {
    const { CursorTab } = await import("../../../src/tui/tabs/CursorTab.js");
    expect(() => render(React.createElement(CursorTab))).not.toThrow();
  });

  test("초기 상태에서 'Cursor IDE' 텍스트가 있다", async () => {
    const { CursorTab } = await import("../../../src/tui/tabs/CursorTab.js");
    const { lastFrame } = render(React.createElement(CursorTab));
    expect(lastFrame() ?? "").toContain("Cursor IDE");
  });

  test("로딩 중에는 'Loading Cursor metrics' 메시지가 있다", async () => {
    const { CursorTab } = await import("../../../src/tui/tabs/CursorTab.js");
    const { lastFrame } = render(React.createElement(CursorTab));
    // 동기 렌더 직후 — summary === null → 로딩 메시지
    expect(lastFrame() ?? "").toContain("Loading Cursor metrics");
  });
});

// ─── VaultTab ───────────────────────────────────────────────────────────────

describe("VaultTab", () => {
  test("크래시 없이 렌더된다", async () => {
    const { VaultTab } = await import("../../../src/tui/tabs/VaultTab.js");
    expect(() =>
      render(React.createElement(VaultTab, { onSubViewChange: () => {} }))
    ).not.toThrow();
  });

  test("빈 vault에서 'Vault is empty' 메시지가 있다", async () => {
    const { VaultTab } = await import("../../../src/tui/tabs/VaultTab.js");
    const { lastFrame } = render(
      React.createElement(VaultTab, { onSubViewChange: () => {} })
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(lastFrame() ?? "").toContain("Vault is empty");
  });

  test("'No item selected' detail panel이 있다", async () => {
    const { VaultTab } = await import("../../../src/tui/tabs/VaultTab.js");
    const { lastFrame } = render(
      React.createElement(VaultTab, { onSubViewChange: () => {} })
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(lastFrame() ?? "").toContain("No item selected");
  });

  test("빈 vault는 행 없이 렌더된다", async () => {
    const { VaultTab } = await import("../../../src/tui/tabs/VaultTab.js");
    const { lastFrame } = render(
      React.createElement(VaultTab, { onSubViewChange: () => {} })
    );
    await new Promise((r) => setTimeout(r, 50));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Vault is empty");
    expect(frame).not.toContain("▸ 1");
  });
});

// ─── MarketTab ──────────────────────────────────────────────────────────────

describe("MarketTab", () => {
  test("크래시 없이 렌더된다", async () => {
    const { MarketTab } = await import("../../../src/tui/tabs/MarketTab.js");
    expect(() => render(React.createElement(MarketTab))).not.toThrow();
  });

  test("'Marketplace' 컬럼 헤더가 있다", async () => {
    const { MarketTab } = await import("../../../src/tui/tabs/MarketTab.js");
    const { lastFrame } = render(React.createElement(MarketTab));
    expect(lastFrame() ?? "").toContain("Marketplace");
  });

  test("'Version' 컬럼 헤더가 있다", async () => {
    const { MarketTab } = await import("../../../src/tui/tabs/MarketTab.js");
    const { lastFrame } = render(React.createElement(MarketTab));
    expect(lastFrame() ?? "").toContain("Version");
  });

  test("마켓플레이스 없으면 empty state 메시지가 있다", async () => {
    const { MarketTab } = await import("../../../src/tui/tabs/MarketTab.js");
    const { lastFrame } = render(React.createElement(MarketTab));
    await new Promise((r) => setTimeout(r, 50));
    expect(lastFrame() ?? "").toContain("No marketplace registered");
  });
});

// ─── ManageTab ──────────────────────────────────────────────────────────────

describe("ManageTab", () => {
  test("크래시 없이 렌더된다", async () => {
    const { ManageTab } = await import("../../../src/tui/tabs/ManageTab.js");
    expect(() => render(React.createElement(ManageTab))).not.toThrow();
  });

  test("'Manage' 헤더가 있다", async () => {
    const { ManageTab } = await import("../../../src/tui/tabs/ManageTab.js");
    const { lastFrame } = render(React.createElement(ManageTab));
    expect(lastFrame() ?? "").toContain("Manage");
  });

  test("서브탭 레이블 'Plugins'가 있다", async () => {
    const { ManageTab } = await import("../../../src/tui/tabs/ManageTab.js");
    const { lastFrame } = render(React.createElement(ManageTab));
    expect(lastFrame() ?? "").toContain("Plugins");
  });

  test("서브탭 레이블 'Skills'가 있다", async () => {
    const { ManageTab } = await import("../../../src/tui/tabs/ManageTab.js");
    const { lastFrame } = render(React.createElement(ManageTab));
    expect(lastFrame() ?? "").toContain("Skills");
  });

  test("서브탭 레이블 'MCP'가 있다", async () => {
    const { ManageTab } = await import("../../../src/tui/tabs/ManageTab.js");
    const { lastFrame } = render(React.createElement(ManageTab));
    expect(lastFrame() ?? "").toContain("MCP");
  });
});

// ─── ContextTab ─────────────────────────────────────────────────────────────

describe("ContextTab", () => {
  test("크래시 없이 렌더된다", async () => {
    const { ContextTab } = await import("../../../src/tui/tabs/ContextTab.js");
    expect(() => render(React.createElement(ContextTab))).not.toThrow();
  });

  test("초기 로딩 상태에서 'Scanning context' 메시지가 있다", async () => {
    const { ContextTab } = await import("../../../src/tui/tabs/ContextTab.js");
    const { lastFrame } = render(React.createElement(ContextTab));
    // analysis === null 상태 → 로딩 메시지 표시
    expect(lastFrame() ?? "").toContain("Scanning context");
  });

  test("렌더 후 내용이 비어있지 않다", async () => {
    const { ContextTab } = await import("../../../src/tui/tabs/ContextTab.js");
    const { lastFrame } = render(React.createElement(ContextTab));
    expect((lastFrame() ?? "").length).toBeGreaterThan(0);
  });
});

// ─── ExtensionsTab ──────────────────────────────────────────────────────────

describe("ExtensionsTab", () => {
  const baseProps = {
    focusLayer: "mainTab" as const,
    setFocusLayer: () => {},
  };

  test("크래시 없이 렌더된다", async () => {
    const { ExtensionsTab } = await import("../../../src/tui/tabs/ExtensionsTab.js");
    expect(() =>
      render(React.createElement(ExtensionsTab, baseProps))
    ).not.toThrow();
  });

  test("서브탭 레이블 'Vault'가 있다", async () => {
    const { ExtensionsTab } = await import("../../../src/tui/tabs/ExtensionsTab.js");
    const { lastFrame } = render(React.createElement(ExtensionsTab, baseProps));
    expect(lastFrame() ?? "").toContain("Vault");
  });

  test("서브탭 레이블 'Skills'가 있다", async () => {
    const { ExtensionsTab } = await import("../../../src/tui/tabs/ExtensionsTab.js");
    const { lastFrame } = render(React.createElement(ExtensionsTab, baseProps));
    expect(lastFrame() ?? "").toContain("Skills");
  });

  test("서브탭 레이블 'Agents'가 있다", async () => {
    const { ExtensionsTab } = await import("../../../src/tui/tabs/ExtensionsTab.js");
    const { lastFrame } = render(React.createElement(ExtensionsTab, baseProps));
    expect(lastFrame() ?? "").toContain("Agents");
  });
});
