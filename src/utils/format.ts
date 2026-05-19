import chalk from "chalk";
import { convertCurrency } from "@pricing/models.js";

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function formatCost(usd: number, exchangeRate: number): string {
  const krw = convertCurrency(usd, "usd", "krw", exchangeRate);
  return `$${usd.toFixed(2)} / ₩${Math.round(krw).toLocaleString()}`;
}

export function budgetBar(used: number, budget: number, width: number = 25): string {
  const pct = Math.min(used / budget, 1.5);
  const filled = Math.round(Math.min(pct, 1) * width);
  const empty = width - filled;
  const bar = "█".repeat(filled) + "░".repeat(empty);
  const label = `$${used.toFixed(2)}/$${budget} (${(pct * 100).toFixed(0)}%)`;
  if (pct >= 1) return chalk.red(`${bar} ${label} ⛔`);
  if (pct >= 0.8) return chalk.yellow(`${bar} ${label} ⚠`);
  return chalk.green(`${bar} ${label}`);
}

export function formatResetTime(resetAt: Date | null, tz: string): string {
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
