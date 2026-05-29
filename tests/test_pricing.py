"""Tests for Section 7 — pricing, plans, rate limits, and user config."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import axt


# ─── pricing.json lookup ─────────────────────────────────────────────────────


def test_get_model_pricing_exact_match():
    p = axt.get_model_pricing("claude-opus-4-7")
    assert p is not None
    assert p.input == 15.0
    assert p.output == 75.0
    assert p.cache_write == 18.75
    assert p.cache_read == 1.5


def test_get_model_pricing_prefix_match():
    """`claude-opus-4-7-something` should resolve via `claude-opus-4-7`."""
    p = axt.get_model_pricing("claude-opus-4-7-r1")
    assert p is not None
    assert p.input == 15.0


def test_get_model_pricing_unknown_returns_none():
    assert axt.get_model_pricing("totally-unknown-model") is None


def test_get_context_window_claude_models():
    assert axt.get_context_window_size("claude-opus-4-7") == 1_000_000
    assert axt.get_context_window_size("claude-haiku-4-5") == 200_000


def test_get_context_window_unknown_model():
    assert axt.get_context_window_size("totally-unknown-model") is None


def test_calculate_cost_claude_opus():
    cost = axt.calculate_cost(
        axt.TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000,
                       cache_creation_tokens=1_000_000, cache_read_tokens=1_000_000),
        "claude-opus-4-7",
    )
    # 15 + 75 + 18.75 + 1.5
    assert cost == pytest.approx(110.25)


def test_calculate_cost_unknown_model_is_zero():
    assert axt.calculate_cost(axt.TokenUsage(input_tokens=1_000_000, output_tokens=0), "x") == 0.0


def test_calculate_cost_zero_usage():
    assert axt.calculate_cost(axt.TokenUsage(0, 0, 0, 0), "claude-opus-4-7") == 0.0


# ─── convert_currency ────────────────────────────────────────────────────────


def test_convert_currency_usd_to_krw():
    assert axt.convert_currency(10, "usd", "krw", 1400) == 14000


def test_convert_currency_krw_to_usd():
    assert axt.convert_currency(14000, "krw", "usd", 1400) == 10


def test_convert_currency_same():
    assert axt.convert_currency(50, "usd", "usd", 1400) == 50


def test_convert_currency_unknown_passthrough():
    assert axt.convert_currency(50, "eur", "krw", 1400) == 50


# ─── Plans ───────────────────────────────────────────────────────────────────


def test_project_monthly_cost_basic():
    # 50 USD over 10 days, projected over 30 = 150
    assert axt.project_monthly_cost(50.0, 10, 30) == 150.0


def test_project_monthly_cost_zero_days():
    assert axt.project_monthly_cost(50.0, 0, 30) == 0.0


def test_compute_plan_usage():
    config = axt.PlanConfig(plan="max-5x", monthly_cost=100, billing_cycle_start=1)
    usage = axt.compute_plan_usage(config, current_cost=50.0, days_elapsed=10, total_days=30)
    assert usage.daily_avg_cost == 5.0
    assert usage.projected_monthly_cost == 150.0
    assert usage.days_remaining == 20


def test_get_days_in_billing_period_basic():
    # Cycle starts day 1; today = 2026-04-15 → 14 elapsed, 30 total.
    now = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    elapsed, total = axt.get_days_in_billing_period(1, now)
    assert elapsed == 14
    assert total == 30


def test_get_days_in_billing_period_rolls_back():
    """If `now` is before this month's billing_start day, start counts from prev month."""
    now = datetime(2026, 4, 5, 0, 0, 0, tzinfo=timezone.utc)
    # billing_start = 15 → cycle is 2026-03-15 to 2026-04-15.
    elapsed, total = axt.get_days_in_billing_period(15, now)
    assert elapsed == 21  # March 15 → April 5 = 21 days
    assert total == 31  # March 15 → April 15 = 31 days


# ─── User config ─────────────────────────────────────────────────────────────


def test_load_config_defaults_when_missing(tmp_path: Path):
    config = axt.load_config(tmp_path / "config.json")
    assert config.currency == ("usd", "krw")
    assert config.exchange_rate == 1400
    assert config.timezone == "Asia/Seoul"
    assert "claude" in config.plans
    assert config.plans["claude"].plan == "max-5x"


def test_load_config_merges_user_overrides(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "exchangeRate": 1350,
        "monthlyBudget": 200,
        "plans": {"claude": {"plan": "max-20x", "monthlyCost": 200}},
    }))
    config = axt.load_config(p)
    assert config.exchange_rate == 1350
    assert config.monthly_budget == 200
    assert config.plans["claude"].plan == "max-20x"
    assert config.plans["claude"].monthly_cost == 200


def test_save_then_load_config_roundtrip(tmp_path: Path):
    p = tmp_path / "config.json"
    custom = axt.AxtConfig(monthly_budget=250.0)
    axt.save_config(p, custom)
    loaded = axt.load_config(p)
    assert loaded.monthly_budget == 250.0


# ─── Rate limits ─────────────────────────────────────────────────────────────


def test_read_rate_limits_fresh(tmp_path: Path):
    now = datetime.now(timezone.utc)
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({
        "five_hour": {"used_percentage": 14, "resets_at": "2026-05-12T15:00:00Z"},
        "seven_day": {"used_percentage": 8, "resets_at": "2026-05-19T00:00:00Z"},
        "updated_at": now.isoformat().replace("+00:00", "Z"),
    }))
    rl = axt.read_rate_limits(p)
    assert rl is not None
    assert rl.five_hour == 14
    assert rl.seven_day == 8


def test_read_rate_limits_stale_returns_none(tmp_path: Path):
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({
        "five_hour": {"used_percentage": 50},
        "updated_at": "2020-01-01T00:00:00Z",
    }))
    assert axt.read_rate_limits(p, freshness_ms=1000) is None


def test_read_rate_limits_clamps_percent(tmp_path: Path):
    now = datetime.now(timezone.utc)
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({
        "five_hour": {"used_percentage": 150},  # out of range
        "updated_at": now.isoformat().replace("+00:00", "Z"),
    }))
    rl = axt.read_rate_limits(p)
    assert rl is not None and rl.five_hour == 100


def test_read_rate_limits_missing_file(tmp_path: Path):
    assert axt.read_rate_limits(tmp_path / "nope.json") is None


def test_read_rate_limits_unix_seconds_timestamp(tmp_path: Path):
    now = datetime.now(timezone.utc)
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({
        "five_hour": {"used_percentage": 25},
        "updated_at": int(now.timestamp()),  # unix seconds
    }))
    rl = axt.read_rate_limits(p)
    assert rl is not None and rl.five_hour == 25


# ─── rate-limit snapshot robustness ──────────────────────────────────────────


def test_read_rate_limits_malformed_json(tmp_path: Path):
    p = tmp_path / "snap.json"
    p.write_text("{ not valid json")
    assert axt.read_rate_limits(p) is None


def test_read_rate_limits_non_dict_json(tmp_path: Path):
    p = tmp_path / "snap.json"
    p.write_text("[1, 2, 3]")
    assert axt.read_rate_limits(p) is None


def test_read_rate_limits_missing_updated_at(tmp_path: Path):
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({"five_hour": {"used_percentage": 10}}))
    assert axt.read_rate_limits(p) is None


def test_read_rate_limits_no_percentages_returns_none(tmp_path: Path):
    now = datetime.now(timezone.utc).isoformat()
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({"updated_at": now}))  # fresh but no percentages
    assert axt.read_rate_limits(p) is None


def test_read_rate_limits_invalid_reset_date_tolerated(tmp_path: Path):
    """A bad `resets_at` must not discard the whole snapshot — the percentage
    is still reported, with reset time left as None."""
    now = datetime.now(timezone.utc).isoformat()
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({
        "updated_at": now,
        "five_hour": {"used_percentage": 30, "resets_at": "not-a-date"},
    }))
    rl = axt.read_rate_limits(p)
    assert rl is not None
    assert rl.five_hour == 30
    assert rl.five_hour_reset_at is None


def test_parse_percent_clamps_and_rejects():
    assert axt._parse_percent(150) == 100        # clamp high
    assert axt._parse_percent(-5) == 0            # clamp low
    assert axt._parse_percent("notnum") is None   # non-numeric
    assert axt._parse_percent(float("nan")) is None  # NaN guard


def test_parse_date_variants():
    assert axt._parse_date("not-a-date") is None
    assert axt._parse_date("") is None
    assert axt._parse_date(0) is None
    d = axt._parse_date("2026-04-29T10:00:00Z")
    assert d is not None and d.year == 2026 and d.month == 4
