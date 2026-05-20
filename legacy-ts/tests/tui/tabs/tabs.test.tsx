/**
 * TUI 탭 컴포넌트 초기 렌더 상태 테스트
 *
 * 전략: useEffect로 비동기 데이터를 로드하는 탭들은 렌더 직후(동기) 초기 상태를 검사한다.
 * mock.module은 반드시 컴포넌트 import 전에 설정해야 한다.
 * 동적 import(await import())로 mock이 제대로 적용되도록 한다.
 */

import { describe, test, expect, mock, beforeAll } from "bun:test";
import React from "react";
import { render } from "ink-testing-library";

// ---------------------------------------------------------------------------
// OverviewTab
// ---------------------------------------------------------------------------

describe("OverviewTab", () => {
  // mock.module을 컴포넌트 import 전에 선언
  mock.module("../../../src/core/usage-unified.js", () => ({
    loadUnifiedUsage: async () => [],
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
  }));

  test("크래시 없이 렌더된다", async () => {
    // cachedState 모듈 캐시 격리: 동적 import
    const mod = await import("../../../src/tui/tabs/OverviewTab.js");
    const { OverviewTab } = mod;
    expect(() => {
      render(React.createElement(OverviewTab));
    }).not.toThrow();
  });

  test("'Total This Month' 텍스트가 있다", async () => {
    const { OverviewTab } = await import("../../../src/tui/tabs/OverviewTab.js");
    const { lastFrame } = render(React.createElement(OverviewTab));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Total This Month");
  });

  test("초기 loading 상태에서 렌더가 깨지지 않는다 (cachedState 없을 때 loading 표시)", async () => {
    const { OverviewTab } = await import("../../../src/tui/tabs/OverviewTab.js");
    const { lastFrame } = render(React.createElement(OverviewTab));
    const frame = lastFrame() ?? "";
    // "Total This Month"은 항상 있어야 한다 (loading 여부 무관)
    expect(frame).toContain("Total This Month");
  });
});

// ---------------------------------------------------------------------------
// PluginsTab
// ---------------------------------------------------------------------------

describe("PluginsTab", () => {
  // 반드시 import 전에 mock 설정
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

  test("크래시 없이 렌더된다", async () => {
    const { PluginsTab } = await import("../../../src/tui/tabs/PluginsTab.js");
    expect(() => {
      render(React.createElement(PluginsTab));
    }).not.toThrow();
  });

  test("컬럼 헤더 'Plugin'이 있다", async () => {
    const { PluginsTab } = await import("../../../src/tui/tabs/PluginsTab.js");
    const { lastFrame } = render(React.createElement(PluginsTab));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Plugin");
  });

  test("컬럼 헤더 'Version'이 있다", async () => {
    const { PluginsTab } = await import("../../../src/tui/tabs/PluginsTab.js");
    const { lastFrame } = render(React.createElement(PluginsTab));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Version");
  });

  test("컬럼 헤더 'Status'가 있다", async () => {
    const { PluginsTab } = await import("../../../src/tui/tabs/PluginsTab.js");
    const { lastFrame } = render(React.createElement(PluginsTab));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Status");
  });

  test("플러그인이 없으면 'No plugin selected' 메시지가 표시된다", async () => {
    const { PluginsTab } = await import("../../../src/tui/tabs/PluginsTab.js");
    const { lastFrame } = render(React.createElement(PluginsTab));
    // 초기 렌더 직후엔 plugins=[], 비동기 로드 전이므로 empty state
    await new Promise((r) => setTimeout(r, 50));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("No plugin selected");
  });
});

// ---------------------------------------------------------------------------
// SkillsTab
// ---------------------------------------------------------------------------

describe("SkillsTab", () => {
  mock.module("../../../src/core/skill.js", () => ({
    listAllSkills: async () => [],
    unlinkSkill: async () => {},
    linkSkill: async () => {},
    isSymlinkSupported: () => true,
  }));

  mock.module("../../../src/core/project-usage.js", () => ({
    getProjectCount: () => 0,
    buildUsageIndex: async () => new Map(),
  }));

  test("크래시 없이 렌더된다", async () => {
    const { SkillsTab } = await import("../../../src/tui/tabs/SkillsTab.js");
    expect(() => {
      render(React.createElement(SkillsTab));
    }).not.toThrow();
  });

  test("컬럼 헤더 'Skill'이 있다", async () => {
    const { SkillsTab } = await import("../../../src/tui/tabs/SkillsTab.js");
    const { lastFrame } = render(React.createElement(SkillsTab));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Skill");
  });

  test("컬럼 헤더 'Source'가 있다", async () => {
    const { SkillsTab } = await import("../../../src/tui/tabs/SkillsTab.js");
    const { lastFrame } = render(React.createElement(SkillsTab));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Source");
  });

  test("스킬이 없으면 empty detail 메시지가 있다", async () => {
    const { SkillsTab } = await import("../../../src/tui/tabs/SkillsTab.js");
    const { lastFrame } = render(React.createElement(SkillsTab));
    await new Promise((r) => setTimeout(r, 50));
    const frame = lastFrame() ?? "";
    // 스킬 없을 때 emptyMessage가 DetailView에 렌더됨
    expect(frame).toMatch(/No skills found/);
  });
});

// ---------------------------------------------------------------------------
// McpTab
// ---------------------------------------------------------------------------

describe("McpTab", () => {
  mock.module("../../../src/core/mcp.js", () => ({
    listMcpServers: async () => [],
  }));

  test("크래시 없이 렌더된다", async () => {
    const { McpTab } = await import("../../../src/tui/tabs/McpTab.js");
    expect(() => {
      render(React.createElement(McpTab));
    }).not.toThrow();
  });

  test("컬럼 헤더 'Server'가 있다", async () => {
    const { McpTab } = await import("../../../src/tui/tabs/McpTab.js");
    const { lastFrame } = render(React.createElement(McpTab));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Server");
  });

  test("컬럼 헤더 'Command'가 있다", async () => {
    const { McpTab } = await import("../../../src/tui/tabs/McpTab.js");
    const { lastFrame } = render(React.createElement(McpTab));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Command");
  });

  test("컬럼 헤더 'Plugin'이 있다", async () => {
    const { McpTab } = await import("../../../src/tui/tabs/McpTab.js");
    const { lastFrame } = render(React.createElement(McpTab));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Plugin");
  });
});

// ---------------------------------------------------------------------------
// HooksTab
// ---------------------------------------------------------------------------

describe("HooksTab", () => {
  mock.module("../../../src/core/hooks.js", () => ({
    listHooks: async () => [],
    getHookDetail: (h: unknown) => "",
    previewHook: async () => ({ output: "", error: "", exitCode: 0, summary: "preview" }),
  }));

  test("크래시 없이 렌더된다", async () => {
    const { HooksTab } = await import("../../../src/tui/tabs/HooksTab.js");
    expect(() => {
      render(React.createElement(HooksTab));
    }).not.toThrow();
  });

  test("컬럼 헤더 'Event'가 있다", async () => {
    const { HooksTab } = await import("../../../src/tui/tabs/HooksTab.js");
    const { lastFrame } = render(React.createElement(HooksTab));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Event");
  });

  test("컬럼 헤더 'Type'이 있다", async () => {
    const { HooksTab } = await import("../../../src/tui/tabs/HooksTab.js");
    const { lastFrame } = render(React.createElement(HooksTab));
    const frame = lastFrame() ?? "";
    expect(frame).toContain("Type");
  });

  test("훅이 없으면 empty detail 메시지가 있다", async () => {
    const { HooksTab } = await import("../../../src/tui/tabs/HooksTab.js");
    const { lastFrame } = render(React.createElement(HooksTab));
    await new Promise((r) => setTimeout(r, 50));
    const frame = lastFrame() ?? "";
    expect(frame).toMatch(/No hooks configured/);
  });
});
