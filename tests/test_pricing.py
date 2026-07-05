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
    assert p.input == 5.0
    assert p.output == 25.0
    assert p.cache_write == 6.25
    assert p.cache_read == 0.5


def test_get_model_pricing_prefix_match():
    """`claude-opus-4-7-something` should resolve via `claude-opus-4-7`."""
    p = axt.get_model_pricing("claude-opus-4-7-r1")
    assert p is not None
    assert p.input == 5.0


def test_get_model_pricing_claude_5_family():
    """Current-generation models must be priced — a missing row silently
    zeroes their cost in every aggregate."""
    fable = axt.get_model_pricing("claude-fable-5")
    assert fable is not None
    assert fable.input == 10.0 and fable.output == 50.0
    assert fable.context_window == 1_000_000
    sonnet = axt.get_model_pricing("claude-sonnet-5")
    assert sonnet is not None
    assert sonnet.input == 3.0 and sonnet.output == 15.0
    # Dated ids resolve via prefix match.
    assert axt.get_model_pricing("claude-haiku-4-5-20251001") is not None


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
    # 5 + 25 + 6.25 + 0.5
    assert cost == pytest.approx(36.75)


def test_calculate_cost_unknown_model_is_zero():
    assert axt.calculate_cost(axt.TokenUsage(input_tokens=1_000_000, output_tokens=0), "x") == 0.0


def test_find_unpriced_models_counts_by_model():
    def entry(model):
        return axt.UnifiedUsageEntry(
            platform="claude", model=model,
            timestamp="2026-07-01T00:00:00Z", session_id="s", project_path="/p",
            input_tokens=1, output_tokens=1,
            cache_write_tokens=0, cache_read_tokens=0)

    entries = [entry("claude-opus-4-8"), entry("mystery-model"),
               entry("mystery-model"), entry("<synthetic>"), entry("unknown")]
    out = axt.find_unpriced_models(entries)
    # Priced and placeholder models are excluded; unpriced real ids counted.
    assert out == {"mystery-model": 2}


def test_find_unpriced_models_empty_when_all_priced():
    assert axt.find_unpriced_models([]) == {}


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


def test_load_config_theme_defaults_to_auto(tmp_path: Path):
    config = axt.load_config(tmp_path / "config.json")
    assert config.theme == "auto"


def test_save_load_config_roundtrips_theme(tmp_path: Path):
    p = tmp_path / "config.json"
    axt.save_config(p, axt.AxtConfig(theme="light"))
    assert axt.load_config(p).theme == "light"


def test_detect_terminal_is_light_via_colorfgbg():
    # COLORFGBG = "fg;bg" or "fg;default;bg"; last field is the bg color index.
    assert axt._detect_terminal_is_light({"COLORFGBG": "0;15"}) is True
    assert axt._detect_terminal_is_light({"COLORFGBG": "0;7"}) is True
    assert axt._detect_terminal_is_light({"COLORFGBG": "15;0"}) is False
    assert axt._detect_terminal_is_light({"COLORFGBG": "0;default;15"}) is True
    assert axt._detect_terminal_is_light({}) is None
    assert axt._detect_terminal_is_light({"COLORFGBG": "garbage"}) is None
    assert axt._detect_terminal_is_light({"COLORFGBG": "7"}) is None


def test_resolve_theme_priority():
    # CLI override beats everything.
    assert axt.resolve_theme("dark", "light") == "light"
    assert axt.resolve_theme("light", "dark") == "dark"
    # Saved explicit value beats auto-detect.
    assert axt.resolve_theme("light", None, {"COLORFGBG": "15;0"}) == "light"
    assert axt.resolve_theme("dark", None, {"COLORFGBG": "0;15"}) == "dark"
    # auto → COLORFGBG detection.
    assert axt.resolve_theme("auto", None, {"COLORFGBG": "0;15"}) == "light"
    assert axt.resolve_theme("auto", None, {"COLORFGBG": "15;0"}) == "dark"
    # auto with no signal → dark fallback.
    assert axt.resolve_theme("auto", None, {}) == "dark"
    # CLI "auto" forces detection even when a dark value is saved.
    assert axt.resolve_theme("dark", "auto", {"COLORFGBG": "0;15"}) == "light"


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


def test_parse_date_overflowing_numeric_returns_none():
    """A numeric value so large that datetime.fromtimestamp overflows is
    tolerated and returns None (lines 2514-2515)."""
    assert axt._parse_date(1e300) is None


def test_parse_date_unix_seconds_scaled_to_ms():
    """A value <= 1e12 is treated as seconds and scaled by 1000."""
    # 2026-04-29T10:00:00Z = 1777456800 seconds.
    d = axt._parse_date(1777456800)
    assert d is not None
    assert d.year == 2026 and d.month == 4 and d.day == 29


def test_parse_date_unix_millis_used_directly():
    """A value > 1e12 is already in milliseconds."""
    d = axt._parse_date(1777456800000)
    assert d is not None and d.year == 2026 and d.month == 4


def test_parse_percent_int_and_float_paths():
    """Ints and floats flow through the float() conversion (the surviving
    body of _parse_percent) and clamp/round as expected."""
    assert axt._parse_percent(33) == 33
    assert axt._parse_percent(33.6) == 34   # rounds
    assert axt._parse_percent(0) == 0
    assert axt._parse_percent(100) == 100


# ─── pricing table loading branches ──────────────────────────────────────────


def test_pricing_table_skips_non_dict_entries(tmp_path: Path, monkeypatch):
    """A models entry whose value is not a dict is skipped (line 2870), and
    reload_pricing_table clears the cache (line 2885)."""
    import axt.core as core

    pf = tmp_path / "pricing.json"
    pf.write_text(json.dumps({"models": {
        "good-model": {
            "input": 1.0, "output": 2.0,
            "cacheWrite": 3.0, "cacheRead": 4.0, "contextWindow": 12345,
        },
        "bad-model": "not-a-dict",  # skipped
        "no-window": {"input": 5.0, "output": 6.0},  # contextWindow absent → None
    }}))
    monkeypatch.setattr(core, "_PRICING_FILE", pf)
    core.reload_pricing_table()  # line 2885: cache reset to None
    try:
        table = core._pricing_table()
        assert "bad-model" not in table  # line 2870 hit
        assert table["good-model"].context_window == 12345
        assert table["good-model"].cache_write == 3.0
        assert table["no-window"].context_window is None
    finally:
        # Restore the real shipped pricing table for other tests.
        monkeypatch.undo()
        core.reload_pricing_table()


def test_calculate_cost_each_token_type_contributes():
    """Each token type contributes its own per-million rate independently."""
    p = axt.get_model_pricing("claude-opus-4-7")
    assert p is not None
    # input only
    only_in = axt.calculate_cost(axt.TokenUsage(input_tokens=1_000_000, output_tokens=0), "claude-opus-4-7")
    assert only_in == pytest.approx(p.input)
    # output only
    only_out = axt.calculate_cost(axt.TokenUsage(input_tokens=0, output_tokens=1_000_000), "claude-opus-4-7")
    assert only_out == pytest.approx(p.output)
    # cache write only
    only_cw = axt.calculate_cost(
        axt.TokenUsage(input_tokens=0, output_tokens=0, cache_creation_tokens=1_000_000),
        "claude-opus-4-7",
    )
    assert only_cw == pytest.approx(p.cache_write)
    # cache read only
    only_cr = axt.calculate_cost(
        axt.TokenUsage(input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000),
        "claude-opus-4-7",
    )
    assert only_cr == pytest.approx(p.cache_read)


# ─── billing-period month boundaries ─────────────────────────────────────────


def test_get_days_in_billing_period_january_rolls_back_to_december():
    """When `now` is in January before billing_start, the cycle rolls back into
    the previous December (line 2993)."""
    now = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
    # billing_start 15 → cycle is 2025-12-15 .. 2026-01-15.
    elapsed, total = axt.get_days_in_billing_period(15, now)
    assert elapsed == 21  # Dec 15 → Jan 5
    assert total == 31    # Dec 15 → Jan 15


def test_get_days_in_billing_period_december_cycle_end_crosses_year():
    """A cycle that starts in December ends in the following January
    (line 2998)."""
    now = datetime(2025, 12, 20, 0, 0, 0, tzinfo=timezone.utc)
    # billing_start 15 → cycle is 2025-12-15 .. 2026-01-15.
    elapsed, total = axt.get_days_in_billing_period(15, now)
    assert elapsed == 5   # Dec 15 → Dec 20
    assert total == 31    # Dec 15 → Jan 15


# ─── plan JSON conversion ────────────────────────────────────────────────────


def test_plan_from_json_non_dict_returns_none():
    """A non-dict plan payload yields None (line 3025)."""
    assert axt._plan_from_json("not-a-dict") is None
    assert axt._plan_from_json(None) is None
    assert axt._plan_from_json(42) is None


def test_plan_from_json_parses_full_payload():
    p = axt._plan_from_json({
        "plan": "max-20x", "monthlyCost": 200,
        "billingCycleStart": 7, "dailyRequestLimit": 500,
    })
    assert p is not None
    assert p.plan == "max-20x"
    assert p.monthly_cost == 200.0
    assert p.billing_cycle_start == 7
    assert p.daily_request_limit == 500


def test_plan_to_json_includes_daily_request_limit_when_set():
    """The optional dailyRequestLimit is emitted only when present (line 3041)."""
    pc = axt.PlanConfig(plan="max-5x", monthly_cost=100, billing_cycle_start=1, daily_request_limit=500)
    d = axt._plan_to_json(pc)
    assert d["dailyRequestLimit"] == 500
    assert d["plan"] == "max-5x"


def test_plan_to_json_omits_daily_request_limit_when_none():
    pc = axt.PlanConfig(plan="max-5x", monthly_cost=100, billing_cycle_start=1)
    d = axt._plan_to_json(pc)
    assert "dailyRequestLimit" not in d


def test_load_config_non_dict_payload_falls_back_to_defaults(tmp_path: Path):
    """A config.json that is a JSON array (not an object) is ignored and the
    defaults are returned (line 3049)."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps([1, 2, 3]))
    config = axt.load_config(p)
    assert config.currency == ("usd", "krw")
    assert config.exchange_rate == 1400
    assert config.plans["claude"].plan == "max-5x"


def test_load_config_ignores_non_dict_plans_section(tmp_path: Path):
    """A `plans` key that is not a dict leaves the default plan intact."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"exchangeRate": 1300, "plans": "oops"}))
    config = axt.load_config(p)
    assert config.exchange_rate == 1300
    assert config.plans["claude"].plan == "max-5x"  # default preserved


# ─── plan auto-detection ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tier,expected",
    [
        ("default_claude_max_20x", ("max-20x", 200.0)),
        ("default_claude_max_5x", ("max-5x", 100.0)),
        ("default_claude_pro", ("pro", 20.0)),
        ("MAX_20X", ("max-20x", 200.0)),
        ("something_team_seat", ("team", 30.0)),
        ("free_tier", ("free", 0.0)),
        ("garbage", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_parse_rate_limit_tier(tier, expected):
    assert axt.parse_rate_limit_tier(tier) == expected


def _write_claude_json(tmp_path: Path, oauth) -> Path:
    p = tmp_path / ".claude.json"
    payload = {} if oauth is None else {"oauthAccount": oauth}
    p.write_text(json.dumps(payload))
    return p


def test_detect_claude_plan_prefers_user_tier(tmp_path: Path):
    p = _write_claude_json(tmp_path, {
        "userRateLimitTier": "default_claude_max_5x",
        "organizationRateLimitTier": "default_claude_max_20x",
    })
    assert axt.detect_claude_plan(p) == ("max-5x", 100.0)


def test_detect_claude_plan_falls_back_to_org_tier(tmp_path: Path):
    p = _write_claude_json(tmp_path, {
        "userRateLimitTier": None,
        "organizationRateLimitTier": "default_claude_max_20x",
    })
    assert axt.detect_claude_plan(p) == ("max-20x", 200.0)


def test_detect_claude_plan_missing_oauth_returns_none(tmp_path: Path):
    assert axt.detect_claude_plan(_write_claude_json(tmp_path, None)) is None


def test_detect_claude_plan_missing_file_returns_none(tmp_path: Path):
    assert axt.detect_claude_plan(tmp_path / "nope.json") is None


def test_load_save_roundtrips_auto_detect_plan(tmp_path: Path):
    p = tmp_path / "config.json"
    assert axt.load_config(p).auto_detect_plan is True  # default on
    axt.save_config(p, axt.AxtConfig(auto_detect_plan=False))
    assert axt.load_config(p).auto_detect_plan is False


def test_resolve_claude_plan_overlays_detected(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.detect_claude_plan", lambda: ("max-20x", 200.0))
    cfg = axt.AxtConfig(
        auto_detect_plan=True,
        plans={"claude": axt.PlanConfig(plan="max-5x", monthly_cost=100, billing_cycle_start=7)},
    )
    resolved = axt.resolve_claude_plan(cfg)
    assert resolved.plan == "max-20x"
    assert resolved.monthly_cost == 200.0
    assert resolved.billing_cycle_start == 7  # user's billing cycle preserved


def test_resolve_claude_plan_respects_manual_pin(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.detect_claude_plan", lambda: ("max-20x", 200.0))
    cfg = axt.AxtConfig(
        auto_detect_plan=False,
        plans={"claude": axt.PlanConfig(plan="max-5x", monthly_cost=100)},
    )
    assert axt.resolve_claude_plan(cfg).plan == "max-5x"  # detection ignored


def test_resolve_claude_plan_falls_back_when_detection_fails(monkeypatch):
    monkeypatch.setattr("axt.detect_claude_plan", lambda: None)
    cfg = axt.AxtConfig(
        auto_detect_plan=True,
        plans={"claude": axt.PlanConfig(plan="max-5x", monthly_cost=100)},
    )
    assert axt.resolve_claude_plan(cfg).plan == "max-5x"
