import { describe, test, expect } from "bun:test";
import { computePlanUsage, projectMonthlyCost, getDaysInBillingPeriod, type PlanConfig } from "../../src/plans/index.js";

describe("plans", () => {
  test("computePlanUsage calculates current period cost", () => {
    const plan: PlanConfig = { plan: "max-5x", monthlyCost: 100, billingCycleStart: 1 };
    const result = computePlanUsage(plan, 62.40, 18, 30);
    expect(result.currentPeriodCost).toBe(62.40);
    expect(result.daysElapsed).toBe(18);
    expect(result.daysRemaining).toBe(12);
  });

  test("projectMonthlyCost extrapolates from daily average", () => {
    const projected = projectMonthlyCost(62.40, 18, 30);
    expect(projected).toBeCloseTo(104.0, 0);
  });

  test("computePlanUsage handles zero elapsed days", () => {
    const plan: PlanConfig = { plan: "pro", monthlyCost: 200, billingCycleStart: 1 };
    const result = computePlanUsage(plan, 0, 0, 30);
    expect(result.dailyAvgCost).toBe(0);
    expect(result.projectedMonthlyCost).toBe(0);
  });

  test("computePlanUsage detects over-budget", () => {
    const plan: PlanConfig = { plan: "max-5x", monthlyCost: 100, billingCycleStart: 1 };
    const result = computePlanUsage(plan, 110, 30, 30);
    expect(result.projectedMonthlyCost).toBe(110);
    expect(result.currentPeriodCost).toBeGreaterThan(plan.monthlyCost);
  });

  test("getDaysInBillingPeriod returns correct values", () => {
    const now = new Date("2026-04-15T12:00:00Z");
    const { elapsed, total } = getDaysInBillingPeriod(1, now);
    expect(elapsed).toBe(14);
    expect(total).toBe(30);
  });
});
