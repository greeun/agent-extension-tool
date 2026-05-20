/**
 * 회귀: ContextTab가 카테고리 목록을 상하 이동해도 테이블 컬럼 헤더가
 * 항상 렌더되고, 전체 높이가 무한정 커지지 않아야 한다(윈도잉/높이 고정).
 */
import { describe, test, expect, mock } from "bun:test";
import React from "react";
import { render } from "ink-testing-library";

mock.module("../../src/config/index.js", () => ({
  loadConfig: async () => ({
    currency: ["usd"], exchangeRate: 1400, monthlyBudget: 100,
    timezone: "Asia/Seoul", locale: "ko-KR", startOfWeek: "monday",
    budgetWarningThreshold: 0.8, plans: {},
  }),
}));
mock.module("../../src/core/usage-unified.js", () => ({ loadUnifiedUsage: async () => [] }));
mock.module("../../src/core/rate-limits.js", () => ({
  readRateLimits: () => ({
    fiveHour: 42, fiveHourResetAt: new Date(Date.now() + 3_600_000),
    sevenDay: 71, sevenDayResetAt: new Date(Date.now() + 86_400_000),
  }),
}));

const CATS = ["claude-md","settings","memory","skills","mcp-tools","plugins","hooks","commands","agents","git-status","user-context","system-prompt"];
mock.module("../../src/core/context-analysis.js", () => ({
  analyzeContext: async () => ({
    totalTokens: 50_000, contextWindowSize: 200_000, usedPercent: 25,
    model: "claude-opus-4-6",
    sources: CATS.flatMap((c) =>
      Array.from({ length: 30 }, (_, i) => ({
        category: c, name: `${c}-src-${i}`, path: `/x/${c}/${i}`,
        estimatedTokens: 1000 + i, content: "line\n".repeat(20),
        actionable: false, hint: i === 0 ? "some hint text here" : undefined,
      }))),
    costImpact: { model: "claude-opus-4-6", cacheWriteCost: 0.1, cacheReadCostPerTurn: 0.01,
      perSessionCost: 0.2, monthlyCost: 5, avgTurnsPerSession: 30, avgSessionsPerDay: 5 },
  }),
}));

describe("ContextTab 높이 회귀", () => {
  test("무거운 데이터에서도 테이블 컬럼 헤더가 렌더된다", async () => {
    const { ContextTab } = await import("../../src/tui/tabs/ContextTab.js");
    const { lastFrame } = render(React.createElement(ContextTab));
    await new Promise((r) => setTimeout(r, 80));
    const frame = lastFrame() ?? "";
    expect(/Category\s+Items\s+Tokens\s+%\s+Usage/.test(frame)).toBe(true);
  });

  test("카테고리당 소스 30개여도 전체 높이가 윈도잉으로 제한된다", async () => {
    // 윈도잉이 없으면 한 카테고리만 펼쳐도 30+ 소스가 전부 렌더되어
    // 라인 수가 폭증한다. 카테고리 모드 기본 화면은 고정 높이여야 한다.
    const { ContextTab } = await import("../../src/tui/tabs/ContextTab.js");
    const { lastFrame } = render(React.createElement(ContextTab));
    await new Promise((r) => setTimeout(r, 80));
    const lines = (lastFrame() ?? "").split("\n").length;
    // Hint 행 고정 + 테이블 maxRows 적용 → 카테고리 모드는 항상 동일 높이.
    // 소스 30개가 전부 렌더되면 50줄을 훌쩍 넘는다.
    expect(lines).toBeLessThan(40);
  });
});
