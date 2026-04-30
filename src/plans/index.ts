export interface PlanConfig {
  plan: string;
  monthlyCost: number;
  billingCycleStart: number;
  dailyRequestLimit?: number;
}

export interface PlanUsage {
  plan: string;
  monthlyCost: number;
  currentPeriodCost: number;
  projectedMonthlyCost: number;
  daysElapsed: number;
  daysRemaining: number;
  dailyAvgCost: number;
}

export function projectMonthlyCost(
  currentCost: number,
  daysElapsed: number,
  totalDays: number
): number {
  if (daysElapsed <= 0) return 0;
  const dailyAvg = currentCost / daysElapsed;
  return dailyAvg * totalDays;
}

export function computePlanUsage(
  config: PlanConfig,
  currentCost: number,
  daysElapsed: number,
  totalDays: number
): PlanUsage {
  const dailyAvgCost = daysElapsed > 0 ? currentCost / daysElapsed : 0;
  const daysRemaining = Math.max(0, totalDays - daysElapsed);
  const projected = projectMonthlyCost(currentCost, daysElapsed, totalDays);

  return {
    plan: config.plan,
    monthlyCost: config.monthlyCost,
    currentPeriodCost: currentCost,
    projectedMonthlyCost: projected,
    daysElapsed,
    daysRemaining,
    dailyAvgCost,
  };
}

export function getDaysInBillingPeriod(billingStart: number, now: Date): { elapsed: number; total: number } {
  const year = now.getUTCFullYear();
  const month = now.getUTCMonth();
  const periodStart = new Date(Date.UTC(year, month, billingStart));
  if (periodStart > now) {
    periodStart.setUTCMonth(periodStart.getUTCMonth() - 1);
  }
  const periodEnd = new Date(periodStart);
  periodEnd.setUTCMonth(periodEnd.getUTCMonth() + 1);

  const total = Math.round((periodEnd.getTime() - periodStart.getTime()) / (24 * 60 * 60 * 1000));
  const elapsed = Math.floor((now.getTime() - periodStart.getTime()) / (24 * 60 * 60 * 1000));

  return { elapsed: Math.max(0, elapsed), total };
}
