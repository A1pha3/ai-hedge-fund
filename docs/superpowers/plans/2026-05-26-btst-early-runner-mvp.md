# BTST Early Runner MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first research/shadow implementation of the v4 early-runner system: field-time auditing, universe filtering, pre-score generation, execution simulation, and daily artifacts without changing formal BTST buy-order behavior.

**Architecture:** Add a small early-runner package under `src/targets/` for pure scoring and guardrail logic, then add a research script under `scripts/` that reads existing selection snapshots and writes JSON/Markdown artifacts. The MVP is fail-closed: missing field-time metadata, untradeable universe rows, non-tradeable `btst_regime_gate`, or missing confirmation data keep candidates in `research_only`/`shadow_only` visibility.

**Tech Stack:** Python 3.11+, Pydantic-style project models where needed, existing BTST snapshot/report utilities, `pytest`, existing `TradingConstraints`, existing `btst_regime_gate` market-state semantics.

---

## Scope Boundary

This plan implements the MVP only.

Included:
- `feature_time_map` and guard tests.
- `universe_filter` and `limit_rule_profile`.
- `early_runner_pre_score`.
- simple execution-cost simulation using existing `TradingConstraints` fields.
- JSON/Markdown research artifacts.
- daily script and focused tests.

Not included in MVP:
- Formal buy-order integration.
- Full intraday `early_runner_confirm_score` from real minute bars.
- Full walk-forward grid runner.
- Full `second_entry_reentry` strategy.

The MVP must expose clear schema hooks for those later phases, but all outputs remain `research_only` or `shadow_only`.

## File Structure

Create:
- `src/targets/early_runner_models.py`  
  Data classes / typed payload helpers for feature metadata, universe rows, early-runner rows, ledgers, and artifact summaries.
- `src/targets/early_runner_feature_time.py`  
  Machine-readable `FEATURE_TIME_MAP`, allowed `available_at` values, and validation helpers.
- `src/targets/early_runner_universe.py`  
  `LimitRuleProfile`, universe filter, and reason-code helpers.
- `src/targets/early_runner_scoring.py`  
  Pre-score formula, overheat penalty, regime penalty, ranking, and fail-closed row builder.
- `src/backtesting/early_runner_execution.py`  
  Minimal tradeability and cost simulation using `TradingConstraints`.
- `scripts/generate_btst_early_runner_board.py`  
  CLI script that reads a `selection_snapshot.json` or report directory and writes early-runner JSON/Markdown artifacts.
- `tests/test_btst_early_runner_feature_time.py`
- `tests/test_btst_early_runner_universe.py`
- `tests/test_btst_early_runner_scoring.py`
- `tests/test_btst_early_runner_execution.py`
- `tests/test_generate_btst_early_runner_board_script.py`

Modify:
- `src/targets/__init__.py` only if the project convention requires exports.
- No formal execution path in this MVP.

Artifacts:
- `data/reports/btst_early_runner_watchlist_YYYYMMDD.json`
- `data/reports/btst_early_runner_watchlist_YYYYMMDD.md`
- `data/reports/btst_early_runner_watchlist_latest.json`
- `data/reports/btst_early_runner_watchlist_latest.md`

## Output Schema

Every JSON artifact must include:

```json
{
  "trade_date": "20260525",
  "mode": "research_only",
  "source_snapshot_path": "data/reports/paper_trading_window_20260525/selection_artifacts/2026-05-25/selection_snapshot.json",
  "feature_time_map_version": "early_runner_feature_time_v1",
  "limit_rule_profile_version": "cn_ashare_limit_rules_v1",
  "cost_profile": {
    "commission_rate": 0.00025,
    "stamp_duty_rate": 0.001,
    "base_slippage_rate": 0.0015,
    "low_liquidity_slippage_rate": 0.003,
    "low_liquidity_turnover_threshold": 50000000.0
  },
  "summary": {
    "input_count": 0,
    "eligible_count": 0,
    "watchlist_count": 0,
    "priority_count": 0,
    "research_only_count": 0,
    "shadow_only_count": 0,
    "feature_time_map_coverage": 1.0,
    "no_lookahead_fields_in_pre_score": true
  },
  "watchlist_rows": [],
  "priority_rows": [],
  "rejected_rows": [],
  "guardrails": []
}
```

Each row must include:

```json
{
  "ticker": "300001",
  "candidate_source": "catalyst_theme",
  "btst_regime_gate": "normal_trade",
  "entry_status": "research_only",
  "pre_score": 0.71,
  "rank": 1,
  "tier": "A",
  "metrics": {
    "trend_acceleration": 0.82,
    "breakout_freshness": 0.65,
    "volume_expansion_quality": 0.42,
    "close_strength": 0.78,
    "sector_resonance": 0.31,
    "catalyst_freshness": 0.80,
    "ret_5d": 0.12,
    "ret_10d": 0.22,
    "gap_to_limit": 0.03,
    "supply_pressure_60": 0.08
  },
  "penalties": {
    "overheat_penalty": 0.0,
    "regime_penalty": 0.0,
    "execution_penalty": 0.0
  },
  "universe_filter": {
    "eligible": true,
    "reasons": []
  },
  "tradeability": {
    "entry_allowed": true,
    "status": "tradeable_research",
    "estimated_round_trip_cost": 0.003,
    "reasons": []
  },
  "top_reasons": [
    "trend_acceleration=0.8200",
    "close_strength=0.7800",
    "btst_regime_gate=normal_trade"
  ],
  "blockers": []
}
```

---

### Task 1: Feature-Time Map Contract

**Files:**
- Create: `src/targets/early_runner_feature_time.py`
- Create: `tests/test_btst_early_runner_feature_time.py`

- [ ] **Step 1: Write the failing feature-time tests**

Create `tests/test_btst_early_runner_feature_time.py`:

```python
from __future__ import annotations

import pytest

from src.targets.early_runner_feature_time import (
    FEATURE_TIME_MAP,
    FeatureTimeSpec,
    assert_pre_score_features_are_safe,
    coverage_ratio,
    validate_feature_time_map,
)


def test_feature_time_map_contains_required_v4_fields() -> None:
    required = {
        "trend_acceleration",
        "breakout_freshness",
        "volume_expansion_quality",
        "close_strength",
        "sector_resonance",
        "catalyst_freshness",
        "ret_5d",
        "ret_10d",
        "gap_to_limit",
        "btst_regime_gate",
        "future_5d_hit_15",
    }

    assert required.issubset(FEATURE_TIME_MAP)
    assert coverage_ratio(required, FEATURE_TIME_MAP) == 1.0


def test_validate_feature_time_map_rejects_unknown_available_at() -> None:
    broken = {
        "trend_acceleration": FeatureTimeSpec(
            available_at="tomorrow",
            allowed_in_pre_score=True,
            allowed_in_confirm_score=True,
            allowed_as_label=False,
            source_module="test",
        )
    }

    with pytest.raises(ValueError, match="invalid available_at"):
        validate_feature_time_map(broken)


def test_pre_score_guard_blocks_future_and_t_plus_1_features() -> None:
    with pytest.raises(ValueError, match="not allowed in early_runner_pre_score"):
        assert_pre_score_features_are_safe(["trend_acceleration", "first_30m_vwap_hold"])

    with pytest.raises(ValueError, match="not allowed in early_runner_pre_score"):
        assert_pre_score_features_are_safe(["future_5d_hit_15"])


def test_pre_score_guard_accepts_t_close_fields() -> None:
    assert_pre_score_features_are_safe(
        [
            "trend_acceleration",
            "close_strength",
            "volume_expansion_quality",
            "btst_regime_gate",
        ]
    )
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
uv run pytest tests/test_btst_early_runner_feature_time.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'src.targets.early_runner_feature_time'`.

- [ ] **Step 3: Implement the feature-time module**

Create `src/targets/early_runner_feature_time.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


FEATURE_TIME_MAP_VERSION = "early_runner_feature_time_v1"
ALLOWED_AVAILABLE_AT = frozenset(
    {
        "t_close",
        "t_post_close_derived",
        "t_plus_1_open",
        "t_plus_1_30m",
        "t_plus_1_close",
        "future_label",
    }
)
PRE_SCORE_FORBIDDEN_AVAILABLE_AT = frozenset(
    {
        "t_plus_1_open",
        "t_plus_1_30m",
        "t_plus_1_close",
        "future_label",
    }
)


@dataclass(frozen=True)
class FeatureTimeSpec:
    available_at: str
    allowed_in_pre_score: bool
    allowed_in_confirm_score: bool
    allowed_as_label: bool
    source_module: str


FEATURE_TIME_MAP: dict[str, FeatureTimeSpec] = {
    "trend_acceleration": FeatureTimeSpec("t_close", True, True, False, "src.targets.short_trade_target_signal_snapshot_helpers"),
    "breakout_freshness": FeatureTimeSpec("t_close", True, True, False, "src.targets.short_trade_target_signal_snapshot_helpers"),
    "volume_expansion_quality": FeatureTimeSpec("t_close", True, True, False, "src.targets.short_trade_target_signal_snapshot_helpers"),
    "close_strength": FeatureTimeSpec("t_close", True, True, False, "src.targets.short_trade_target_signal_snapshot_helpers"),
    "sector_resonance": FeatureTimeSpec("t_close", True, True, False, "src.targets.short_trade_target_signal_snapshot_helpers"),
    "catalyst_freshness": FeatureTimeSpec("t_close", True, True, False, "src.targets.short_trade_target_signal_snapshot_helpers"),
    "layer_c_alignment": FeatureTimeSpec("t_close", True, True, False, "src.targets.short_trade_target_signal_snapshot_helpers"),
    "retention_proxy": FeatureTimeSpec("t_close", True, True, False, "src.targets.short_trade_target_prior_helpers"),
    "historical_prior_score": FeatureTimeSpec("t_post_close_derived", True, True, False, "src.execution.daily_pipeline_historical_prior_attachment"),
    "ret_5d": FeatureTimeSpec("t_close", True, True, False, "selection_snapshot.metrics"),
    "ret_10d": FeatureTimeSpec("t_close", True, True, False, "selection_snapshot.metrics"),
    "gap_to_limit": FeatureTimeSpec("t_close", True, True, False, "selection_snapshot.metrics"),
    "failed_breakout_10": FeatureTimeSpec("t_close", True, True, False, "selection_snapshot.metrics"),
    "supply_pressure_60": FeatureTimeSpec("t_close", True, True, False, "selection_snapshot.metrics"),
    "btst_regime_gate": FeatureTimeSpec("t_post_close_derived", True, True, False, "src.screening.market_state_helpers"),
    "next_open_gap": FeatureTimeSpec("t_plus_1_open", False, True, False, "intraday_confirmation"),
    "first_30m_vwap_hold": FeatureTimeSpec("t_plus_1_30m", False, True, False, "intraday_confirmation"),
    "intraday_volume_rhythm": FeatureTimeSpec("t_plus_1_30m", False, True, False, "intraday_confirmation"),
    "next_day_failed_breakout": FeatureTimeSpec("t_plus_1_close", False, False, False, "post_trade_evaluation"),
    "future_5d_hit_15": FeatureTimeSpec("future_label", False, False, True, "src.targets.short_trade_forward_label_helpers"),
    "future_10d_hit_50": FeatureTimeSpec("future_label", False, False, True, "src.targets.short_trade_forward_label_helpers"),
}


def validate_feature_time_map(feature_map: Mapping[str, FeatureTimeSpec] = FEATURE_TIME_MAP) -> None:
    for feature_name, spec in feature_map.items():
        if spec.available_at not in ALLOWED_AVAILABLE_AT:
            raise ValueError(f"feature '{feature_name}' has invalid available_at: {spec.available_at}")
        if spec.allowed_in_pre_score and spec.available_at in PRE_SCORE_FORBIDDEN_AVAILABLE_AT:
            raise ValueError(f"feature '{feature_name}' is not allowed in early_runner_pre_score")
        if spec.allowed_as_label and (spec.allowed_in_pre_score or spec.allowed_in_confirm_score):
            raise ValueError(f"feature '{feature_name}' is a label and cannot enter scoring")


def assert_pre_score_features_are_safe(features: list[str], feature_map: Mapping[str, FeatureTimeSpec] = FEATURE_TIME_MAP) -> None:
    validate_feature_time_map(feature_map)
    for feature_name in features:
        spec = feature_map.get(feature_name)
        if spec is None:
            raise ValueError(f"feature '{feature_name}' is missing from feature_time_map")
        if not spec.allowed_in_pre_score or spec.available_at in PRE_SCORE_FORBIDDEN_AVAILABLE_AT:
            raise ValueError(f"feature '{feature_name}' is not allowed in early_runner_pre_score")


def coverage_ratio(required_features: set[str], feature_map: Mapping[str, FeatureTimeSpec] = FEATURE_TIME_MAP) -> float:
    if not required_features:
        return 1.0
    covered = sum(1 for feature_name in required_features if feature_name in feature_map)
    return round(covered / len(required_features), 6)


def feature_time_map_as_jsonable(feature_map: Mapping[str, FeatureTimeSpec] = FEATURE_TIME_MAP) -> dict[str, dict[str, object]]:
    return {
        name: {
            "available_at": spec.available_at,
            "allowed_in_pre_score": spec.allowed_in_pre_score,
            "allowed_in_confirm_score": spec.allowed_in_confirm_score,
            "allowed_as_label": spec.allowed_as_label,
            "source_module": spec.source_module,
        }
        for name, spec in sorted(feature_map.items())
    }
```

- [ ] **Step 4: Run the feature-time tests**

Run:

```bash
uv run pytest tests/test_btst_early_runner_feature_time.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit this task**

```bash
git add src/targets/early_runner_feature_time.py tests/test_btst_early_runner_feature_time.py
git commit -m "feat: add early runner feature time contract"
```

### Task 2: Universe Filter and Limit Rule Profile

**Files:**
- Create: `src/targets/early_runner_universe.py`
- Create: `tests/test_btst_early_runner_universe.py`

- [ ] **Step 1: Write the failing universe tests**

Create `tests/test_btst_early_runner_universe.py`:

```python
from __future__ import annotations

from src.targets.early_runner_universe import (
    CN_A_SHARE_LIMIT_RULE_PROFILE,
    UniverseInput,
    filter_early_runner_universe,
    limit_rule_profile_as_jsonable,
)


def test_limit_rule_profile_covers_main_star_and_chinext() -> None:
    payload = limit_rule_profile_as_jsonable()

    assert payload["main_board"]["daily_limit_pct"] == 10
    assert payload["main_board"]["risk_warning_limit_pct"] == 5
    assert payload["star_market"]["daily_limit_pct"] == 20
    assert payload["chinext"]["daily_limit_pct"] == 20
    assert CN_A_SHARE_LIMIT_RULE_PROFILE.version == "cn_ashare_limit_rules_v1"


def test_universe_filter_accepts_tradeable_main_board_row() -> None:
    result = filter_early_runner_universe(
        UniverseInput(
            ticker="600000",
            board="main_board",
            listed_days=120,
            is_suspended=False,
            is_st_or_risk_warning=False,
            avg_turnover_20d=80_000_000.0,
            price=12.5,
        )
    )

    assert result.eligible is True
    assert result.reasons == []


def test_universe_filter_rejects_risk_warning_and_low_liquidity() -> None:
    result = filter_early_runner_universe(
        UniverseInput(
            ticker="600001",
            board="main_board",
            listed_days=120,
            is_suspended=False,
            is_st_or_risk_warning=True,
            avg_turnover_20d=20_000_000.0,
            price=3.5,
        )
    )

    assert result.eligible is False
    assert result.reasons == ["risk_warning_or_st", "avg_turnover_20d_below_min"]


def test_universe_filter_rejects_unknown_board_and_recent_listing() -> None:
    result = filter_early_runner_universe(
        UniverseInput(
            ticker="920001",
            board="bse",
            listed_days=20,
            is_suspended=False,
            is_st_or_risk_warning=False,
            avg_turnover_20d=120_000_000.0,
            price=10.0,
        )
    )

    assert result.eligible is False
    assert result.reasons == ["listed_days_below_min", "board_not_allowed"]
```

- [ ] **Step 2: Run the universe tests and confirm they fail**

Run:

```bash
uv run pytest tests/test_btst_early_runner_universe.py -q
```

Expected: fail with missing module.

- [ ] **Step 3: Implement universe filtering**

Create `src/targets/early_runner_universe.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LimitRule:
    daily_limit_pct: int
    risk_warning_limit_pct: int | None = None
    ipo_no_limit_days: int = 0


@dataclass(frozen=True)
class LimitRuleProfile:
    version: str
    rules: dict[str, LimitRule]


@dataclass(frozen=True)
class UniverseInput:
    ticker: str
    board: str
    listed_days: int | None
    is_suspended: bool
    is_st_or_risk_warning: bool
    avg_turnover_20d: float | None
    price: float | None
    abnormal_delisting_risk: bool = False


@dataclass(frozen=True)
class UniverseFilterResult:
    eligible: bool
    reasons: list[str]


CN_A_SHARE_LIMIT_RULE_PROFILE = LimitRuleProfile(
    version="cn_ashare_limit_rules_v1",
    rules={
        "main_board": LimitRule(daily_limit_pct=10, risk_warning_limit_pct=5),
        "star_market": LimitRule(daily_limit_pct=20, ipo_no_limit_days=5),
        "chinext": LimitRule(daily_limit_pct=20, ipo_no_limit_days=5),
    },
)


def limit_rule_profile_as_jsonable(profile: LimitRuleProfile = CN_A_SHARE_LIMIT_RULE_PROFILE) -> dict[str, dict[str, int | None]]:
    return {
        board: {
            "daily_limit_pct": rule.daily_limit_pct,
            "risk_warning_limit_pct": rule.risk_warning_limit_pct,
            "ipo_no_limit_days": rule.ipo_no_limit_days,
        }
        for board, rule in sorted(profile.rules.items())
    }


def filter_early_runner_universe(
    row: UniverseInput,
    *,
    min_listed_days: int = 60,
    min_avg_turnover: float = 50_000_000.0,
    min_price: float = 2.0,
    allowed_boards: frozenset[str] = frozenset({"main_board", "star_market", "chinext"}),
) -> UniverseFilterResult:
    reasons: list[str] = []
    listed_days = int(row.listed_days or 0)
    avg_turnover = float(row.avg_turnover_20d or 0.0)
    price = float(row.price or 0.0)

    if listed_days < min_listed_days:
        reasons.append("listed_days_below_min")
    if row.is_suspended:
        reasons.append("suspended")
    if row.is_st_or_risk_warning:
        reasons.append("risk_warning_or_st")
    if row.board not in allowed_boards:
        reasons.append("board_not_allowed")
    if avg_turnover < min_avg_turnover:
        reasons.append("avg_turnover_20d_below_min")
    if price < min_price:
        reasons.append("price_below_min")
    if row.abnormal_delisting_risk:
        reasons.append("abnormal_delisting_risk")

    return UniverseFilterResult(eligible=not reasons, reasons=reasons)
```

- [ ] **Step 4: Run the universe tests**

Run:

```bash
uv run pytest tests/test_btst_early_runner_universe.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit this task**

```bash
git add src/targets/early_runner_universe.py tests/test_btst_early_runner_universe.py
git commit -m "feat: add early runner universe guardrails"
```

### Task 3: Pre-Score Engine

**Files:**
- Create: `src/targets/early_runner_models.py`
- Create: `src/targets/early_runner_scoring.py`
- Create: `tests/test_btst_early_runner_scoring.py`

- [ ] **Step 1: Write the failing scoring tests**

Create `tests/test_btst_early_runner_scoring.py`:

```python
from __future__ import annotations

import pytest

from src.targets.early_runner_models import EarlyRunnerInput
from src.targets.early_runner_scoring import build_early_runner_row, rank_early_runner_rows


def _base_input(**overrides: object) -> EarlyRunnerInput:
    payload = {
        "ticker": "300001",
        "candidate_source": "catalyst_theme",
        "btst_regime_gate": "normal_trade",
        "trend_acceleration": 0.82,
        "breakout_freshness": 0.64,
        "volume_expansion_quality": 0.42,
        "close_strength": 0.78,
        "sector_resonance": 0.33,
        "catalyst_freshness": 0.81,
        "retention_proxy": 0.40,
        "historical_prior_score": 0.25,
        "ret_5d": 0.12,
        "ret_10d": 0.22,
        "gap_to_limit": 0.03,
        "failed_breakout_10": 0,
        "supply_pressure_60": 0.08,
        "universe_eligible": True,
        "universe_reasons": [],
    }
    payload.update(overrides)
    return EarlyRunnerInput(**payload)


def test_build_early_runner_row_scores_normal_trade_candidate() -> None:
    row = build_early_runner_row(_base_input())

    assert row.ticker == "300001"
    assert row.entry_status == "research_only"
    assert row.tier in {"A", "B"}
    assert row.pre_score > 0.50
    assert row.blockers == []
    assert "trend_acceleration=0.8200" in row.top_reasons


def test_build_early_runner_row_blocks_shadow_only_from_execution_visibility() -> None:
    row = build_early_runner_row(_base_input(btst_regime_gate="shadow_only"))

    assert row.entry_status == "shadow_only"
    assert "btst_regime_gate_shadow_only" in row.blockers
    assert row.penalties["regime_penalty"] == pytest.approx(0.10)


def test_build_early_runner_row_rejects_universe_blocked_candidate() -> None:
    row = build_early_runner_row(
        _base_input(
            universe_eligible=False,
            universe_reasons=["risk_warning_or_st", "avg_turnover_20d_below_min"],
        )
    )

    assert row.entry_status == "rejected"
    assert row.blockers == ["risk_warning_or_st", "avg_turnover_20d_below_min"]


def test_rank_early_runner_rows_sorts_and_caps_outputs() -> None:
    rows = [
        build_early_runner_row(_base_input(ticker="300001", trend_acceleration=0.70)),
        build_early_runner_row(_base_input(ticker="300002", trend_acceleration=0.90)),
        build_early_runner_row(_base_input(ticker="300003", universe_eligible=False, universe_reasons=["suspended"])),
    ]

    ranked = rank_early_runner_rows(rows, max_rows=2)

    assert [row.ticker for row in ranked] == ["300002", "300001"]
    assert [row.rank for row in ranked] == [1, 2]
```

- [ ] **Step 2: Run the scoring tests and confirm they fail**

Run:

```bash
uv run pytest tests/test_btst_early_runner_scoring.py -q
```

Expected: fail with missing modules.

- [ ] **Step 3: Implement models**

Create `src/targets/early_runner_models.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class EarlyRunnerInput(BaseModel):
    ticker: str
    candidate_source: str = ""
    btst_regime_gate: str = "normal_trade"
    trend_acceleration: float = 0.0
    breakout_freshness: float = 0.0
    volume_expansion_quality: float = 0.0
    close_strength: float = 0.0
    sector_resonance: float = 0.0
    catalyst_freshness: float = 0.0
    retention_proxy: float = 0.0
    historical_prior_score: float = 0.0
    ret_5d: float = 0.0
    ret_10d: float = 0.0
    gap_to_limit: float = 1.0
    failed_breakout_10: int = 0
    supply_pressure_60: float = 0.0
    universe_eligible: bool = True
    universe_reasons: list[str] = Field(default_factory=list)


class EarlyRunnerRow(BaseModel):
    ticker: str
    candidate_source: str
    btst_regime_gate: str
    entry_status: str
    pre_score: float
    rank: int | None = None
    tier: str
    metrics: dict[str, float | int | str]
    penalties: dict[str, float]
    universe_filter: dict[str, object]
    tradeability: dict[str, object] = Field(default_factory=dict)
    top_reasons: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Implement scoring**

Create `src/targets/early_runner_scoring.py`:

```python
from __future__ import annotations

from src.targets.early_runner_feature_time import assert_pre_score_features_are_safe
from src.targets.early_runner_models import EarlyRunnerInput, EarlyRunnerRow


PRE_SCORE_FEATURES = [
    "trend_acceleration",
    "breakout_freshness",
    "volume_expansion_quality",
    "close_strength",
    "sector_resonance",
    "catalyst_freshness",
    "retention_proxy",
    "historical_prior_score",
    "ret_5d",
    "ret_10d",
    "btst_regime_gate",
    "supply_pressure_60",
]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _overheat_penalty(row: EarlyRunnerInput) -> float:
    penalty = 0.0
    if row.ret_5d > 0.18:
        penalty += 0.10
    if row.ret_5d > 0.25:
        penalty += 0.18
    if row.ret_10d > 0.50:
        penalty += 0.25
    if row.close_strength >= 0.95:
        penalty += 0.10
    return round(penalty, 6)


def _regime_penalty(row: EarlyRunnerInput) -> float:
    if row.btst_regime_gate == "halt":
        return 0.25
    if row.btst_regime_gate == "shadow_only":
        return 0.10
    return 0.0


def _tier(pre_score: float) -> str:
    if pre_score >= 0.72:
        return "A"
    if pre_score >= 0.62:
        return "B"
    if pre_score >= 0.52:
        return "C"
    return "reject"


def _entry_status(row: EarlyRunnerInput, blockers: list[str]) -> str:
    if row.universe_reasons:
        return "rejected"
    if row.btst_regime_gate in {"halt", "shadow_only"}:
        return "shadow_only"
    if blockers:
        return "research_only"
    return "research_only"


def build_early_runner_row(row: EarlyRunnerInput) -> EarlyRunnerRow:
    assert_pre_score_features_are_safe(PRE_SCORE_FEATURES)
    blockers = list(row.universe_reasons)
    if row.btst_regime_gate in {"halt", "shadow_only"}:
        blockers.append(f"btst_regime_gate_{row.btst_regime_gate}")
    if row.failed_breakout_10 >= 1:
        blockers.append("failed_breakout_10")
    if row.gap_to_limit <= 0.01:
        blockers.append("gap_to_limit_too_small")

    overheat = _overheat_penalty(row)
    regime = _regime_penalty(row)
    raw_score = (
        (0.22 * row.trend_acceleration)
        + (0.16 * row.breakout_freshness)
        + (0.14 * row.volume_expansion_quality)
        + (0.14 * row.close_strength)
        + (0.12 * row.sector_resonance)
        + (0.10 * row.catalyst_freshness)
        + (0.08 * row.retention_proxy)
        + (0.04 * row.historical_prior_score)
        - overheat
        - regime
    )
    pre_score = round(_clamp(raw_score), 6)
    metrics = {
        "trend_acceleration": row.trend_acceleration,
        "breakout_freshness": row.breakout_freshness,
        "volume_expansion_quality": row.volume_expansion_quality,
        "close_strength": row.close_strength,
        "sector_resonance": row.sector_resonance,
        "catalyst_freshness": row.catalyst_freshness,
        "ret_5d": row.ret_5d,
        "ret_10d": row.ret_10d,
        "gap_to_limit": row.gap_to_limit,
        "supply_pressure_60": row.supply_pressure_60,
    }
    return EarlyRunnerRow(
        ticker=row.ticker,
        candidate_source=row.candidate_source,
        btst_regime_gate=row.btst_regime_gate,
        entry_status=_entry_status(row, blockers),
        pre_score=pre_score,
        tier=_tier(pre_score),
        metrics=metrics,
        penalties={
            "overheat_penalty": overheat,
            "regime_penalty": regime,
            "execution_penalty": 0.0,
        },
        universe_filter={
            "eligible": row.universe_eligible,
            "reasons": list(row.universe_reasons),
        },
        top_reasons=[
            f"trend_acceleration={row.trend_acceleration:.4f}",
            f"close_strength={row.close_strength:.4f}",
            f"btst_regime_gate={row.btst_regime_gate}",
        ],
        blockers=blockers,
    )


def rank_early_runner_rows(rows: list[EarlyRunnerRow], *, max_rows: int) -> list[EarlyRunnerRow]:
    eligible = [row for row in rows if row.entry_status != "rejected"]
    ranked = sorted(eligible, key=lambda item: (item.pre_score, item.metrics.get("trend_acceleration", 0.0)), reverse=True)[:max_rows]
    return [row.model_copy(update={"rank": index}) for index, row in enumerate(ranked, start=1)]
```

- [ ] **Step 5: Run scoring tests**

Run:

```bash
uv run pytest tests/test_btst_early_runner_scoring.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit this task**

```bash
git add src/targets/early_runner_models.py src/targets/early_runner_scoring.py tests/test_btst_early_runner_scoring.py
git commit -m "feat: add early runner pre score engine"
```

### Task 4: Minimal Execution and Cost Simulation

**Files:**
- Create: `src/backtesting/early_runner_execution.py`
- Create: `tests/test_btst_early_runner_execution.py`

- [ ] **Step 1: Write the failing execution tests**

Create `tests/test_btst_early_runner_execution.py`:

```python
from __future__ import annotations

from src.backtesting.early_runner_execution import EarlyRunnerExecutionInput, simulate_early_runner_tradeability
from src.backtesting.trading_constraints import TradingConstraints


def test_simulate_tradeability_allows_low_gap_liquid_candidate() -> None:
    result = simulate_early_runner_tradeability(
        EarlyRunnerExecutionInput(
            next_open_gap=0.02,
            next_open_limit_up_or_one_price=False,
            first_30m_liquidity_ok=True,
            daily_turnover=120_000_000.0,
        ),
        constraints=TradingConstraints(
            commission_rate=0.00025,
            stamp_duty_rate=0.0005,
            base_slippage_rate=0.0015,
            low_liquidity_slippage_rate=0.003,
            low_liquidity_turnover_threshold=50_000_000.0,
        ),
    )

    assert result.entry_allowed is True
    assert result.status == "tradeable_research"
    assert result.reasons == []
    assert result.estimated_round_trip_cost == 0.00225


def test_simulate_tradeability_blocks_high_gap_and_limit_open() -> None:
    result = simulate_early_runner_tradeability(
        EarlyRunnerExecutionInput(
            next_open_gap=0.07,
            next_open_limit_up_or_one_price=True,
            first_30m_liquidity_ok=False,
            daily_turnover=20_000_000.0,
        )
    )

    assert result.entry_allowed is False
    assert result.status == "unfilled_or_abandoned"
    assert result.reasons == [
        "next_open_gap_above_max",
        "next_open_limit_up_or_one_price",
        "first_30m_liquidity_not_ok",
        "low_liquidity_turnover",
    ]
```

- [ ] **Step 2: Run the execution tests and confirm they fail**

Run:

```bash
uv run pytest tests/test_btst_early_runner_execution.py -q
```

Expected: fail with missing module.

- [ ] **Step 3: Implement execution simulation**

Create `src/backtesting/early_runner_execution.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from src.backtesting.trading_constraints import TradingConstraints


@dataclass(frozen=True)
class EarlyRunnerExecutionInput:
    next_open_gap: float | None = None
    next_open_limit_up_or_one_price: bool = False
    first_30m_liquidity_ok: bool = True
    daily_turnover: float | None = None


@dataclass(frozen=True)
class EarlyRunnerTradeabilityResult:
    entry_allowed: bool
    status: str
    estimated_round_trip_cost: float
    reasons: list[str]


def simulate_early_runner_tradeability(
    payload: EarlyRunnerExecutionInput,
    *,
    constraints: TradingConstraints | None = None,
    max_next_open_gap: float = 0.03,
) -> EarlyRunnerTradeabilityResult:
    active_constraints = constraints or TradingConstraints()
    reasons: list[str] = []
    next_open_gap = float(payload.next_open_gap or 0.0)
    daily_turnover = float(payload.daily_turnover or 0.0)
    slippage = active_constraints.base_slippage_rate

    if next_open_gap > max_next_open_gap:
        reasons.append("next_open_gap_above_max")
    if payload.next_open_limit_up_or_one_price:
        reasons.append("next_open_limit_up_or_one_price")
    if not payload.first_30m_liquidity_ok:
        reasons.append("first_30m_liquidity_not_ok")
    if daily_turnover and daily_turnover < active_constraints.low_liquidity_turnover_threshold:
        reasons.append("low_liquidity_turnover")
        slippage = max(slippage, active_constraints.low_liquidity_slippage_rate)

    entry_allowed = not reasons
    round_trip_cost = active_constraints.commission_rate + active_constraints.stamp_duty_rate + slippage
    return EarlyRunnerTradeabilityResult(
        entry_allowed=entry_allowed,
        status="tradeable_research" if entry_allowed else "unfilled_or_abandoned",
        estimated_round_trip_cost=round(round_trip_cost, 6),
        reasons=reasons,
    )
```

- [ ] **Step 4: Run execution tests**

Run:

```bash
uv run pytest tests/test_btst_early_runner_execution.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit this task**

```bash
git add src/backtesting/early_runner_execution.py tests/test_btst_early_runner_execution.py
git commit -m "feat: add early runner tradeability simulation"
```

### Task 5: Daily Early-Runner Board Script

**Files:**
- Create: `scripts/generate_btst_early_runner_board.py`
- Create: `tests/test_generate_btst_early_runner_board_script.py`

- [ ] **Step 1: Write the failing script tests**

Create `tests/test_generate_btst_early_runner_board_script.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_early_runner_board import generate_btst_early_runner_board_artifacts


def test_generate_early_runner_board_from_selection_snapshot(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    snapshot_dir = report_dir / "selection_artifacts" / "2026-05-25"
    snapshot_dir.mkdir(parents=True)
    snapshot_path = snapshot_dir / "selection_snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "trade_date": "20260525",
                "market_state": {
                    "btst_regime_gate": {"gate": "normal_trade"},
                },
                "selection_targets": {
                    "300001": {
                        "candidate_source": "catalyst_theme",
                        "short_trade": {
                            "decision": "near_miss",
                            "explainability_payload": {
                                "trend_acceleration": 0.82,
                                "breakout_freshness": 0.64,
                                "volume_expansion_quality": 0.42,
                                "close_strength": 0.78,
                                "sector_resonance": 0.33,
                                "catalyst_freshness": 0.81,
                                "ret_5d": 0.12,
                                "ret_10d": 0.22,
                                "gap_to_limit": 0.03,
                                "failed_breakout_10": 0,
                                "supply_pressure_60": 0.08
                            }
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifact = generate_btst_early_runner_board_artifacts(
        snapshot_path=snapshot_path,
        output_dir=tmp_path / "out",
    )

    assert artifact["summary"]["input_count"] == 1
    assert artifact["summary"]["watchlist_count"] == 1
    assert artifact["summary"]["priority_count"] == 1
    assert artifact["summary"]["no_lookahead_fields_in_pre_score"] is True
    assert artifact["watchlist_rows"][0]["ticker"] == "300001"
    assert artifact["watchlist_rows"][0]["entry_status"] == "research_only"
    assert (tmp_path / "out" / "btst_early_runner_watchlist_20260525.json").exists()
    assert (tmp_path / "out" / "btst_early_runner_watchlist_20260525.md").exists()
    assert (tmp_path / "out" / "btst_early_runner_watchlist_latest.json").exists()
    assert (tmp_path / "out" / "btst_early_runner_watchlist_latest.md").exists()


def test_generate_early_runner_board_marks_missing_snapshot_fields_as_rejected(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "selection_snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "trade_date": "20260525",
                "selection_targets": {
                    "300002": {
                        "candidate_source": "layer_c_watchlist",
                        "short_trade": {
                            "decision": "near_miss",
                            "explainability_payload": {}
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifact = generate_btst_early_runner_board_artifacts(
        snapshot_path=snapshot_path,
        output_dir=tmp_path / "out",
    )

    assert artifact["summary"]["input_count"] == 1
    assert artifact["summary"]["watchlist_count"] == 0
    assert artifact["rejected_rows"][0]["ticker"] == "300002"
    assert "missing_required_metrics" in artifact["rejected_rows"][0]["blockers"]
```

- [ ] **Step 2: Run the script tests and confirm they fail**

Run:

```bash
uv run pytest tests/test_generate_btst_early_runner_board_script.py -q
```

Expected: fail with missing script.

- [ ] **Step 3: Implement the board script**

Create `scripts/generate_btst_early_runner_board.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.backtesting.trading_constraints import TradingConstraints
from src.targets.early_runner_feature_time import (
    FEATURE_TIME_MAP,
    FEATURE_TIME_MAP_VERSION,
    assert_pre_score_features_are_safe,
    feature_time_map_as_jsonable,
)
from src.targets.early_runner_models import EarlyRunnerInput, EarlyRunnerRow
from src.targets.early_runner_scoring import PRE_SCORE_FEATURES, build_early_runner_row, rank_early_runner_rows
from src.targets.early_runner_universe import CN_A_SHARE_LIMIT_RULE_PROFILE, limit_rule_profile_as_jsonable


REQUIRED_METRICS = {
    "trend_acceleration",
    "breakout_freshness",
    "volume_expansion_quality",
    "close_strength",
    "sector_resonance",
    "catalyst_freshness",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_gate(snapshot: dict[str, Any]) -> str:
    market_state = dict(snapshot.get("market_state") or {})
    gate_payload = market_state.get("btst_regime_gate")
    if isinstance(gate_payload, dict):
        return str(gate_payload.get("gate") or "normal_trade")
    return str(gate_payload or "normal_trade")


def _target_payload_to_input(ticker: str, payload: dict[str, Any], *, btst_regime_gate: str) -> EarlyRunnerInput | dict[str, Any]:
    short_trade = dict(payload.get("short_trade") or {})
    metrics = {
        **dict(short_trade.get("metrics_payload") or {}),
        **dict(short_trade.get("explainability_payload") or {}),
    }
    missing = sorted(name for name in REQUIRED_METRICS if name not in metrics)
    if missing:
        return {
            "ticker": ticker,
            "candidate_source": str(payload.get("candidate_source") or ""),
            "entry_status": "rejected",
            "blockers": ["missing_required_metrics"],
            "missing_metrics": missing,
        }
    return EarlyRunnerInput(
        ticker=ticker,
        candidate_source=str(payload.get("candidate_source") or ""),
        btst_regime_gate=btst_regime_gate,
        trend_acceleration=float(metrics.get("trend_acceleration") or 0.0),
        breakout_freshness=float(metrics.get("breakout_freshness") or 0.0),
        volume_expansion_quality=float(metrics.get("volume_expansion_quality") or 0.0),
        close_strength=float(metrics.get("close_strength") or 0.0),
        sector_resonance=float(metrics.get("sector_resonance") or 0.0),
        catalyst_freshness=float(metrics.get("catalyst_freshness") or 0.0),
        retention_proxy=float(metrics.get("retention_proxy") or 0.0),
        historical_prior_score=float(metrics.get("historical_prior_score") or 0.0),
        ret_5d=float(metrics.get("ret_5d") or 0.0),
        ret_10d=float(metrics.get("ret_10d") or 0.0),
        gap_to_limit=float(metrics.get("gap_to_limit") or 1.0),
        failed_breakout_10=int(metrics.get("failed_breakout_10") or 0),
        supply_pressure_60=float(metrics.get("supply_pressure_60") or 0.0),
        universe_eligible=True,
        universe_reasons=[],
    )


def _render_markdown(artifact: dict[str, Any]) -> str:
    lines = [
        f"# BTST Early Runner Watchlist {artifact['trade_date']}",
        "",
        "## Summary",
    ]
    for key, value in artifact["summary"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Priority Rows"])
    for index, row in enumerate(artifact["priority_rows"], start=1):
        lines.extend(
            [
                f"### {index}. {row['ticker']}",
                f"- tier: {row['tier']}",
                f"- entry_status: {row['entry_status']}",
                f"- pre_score: {row['pre_score']:.4f}",
                f"- btst_regime_gate: {row['btst_regime_gate']}",
                f"- blockers: {', '.join(row['blockers']) if row['blockers'] else 'none'}",
            ]
        )
    lines.extend(["", "## Guardrails"])
    for guardrail in artifact["guardrails"]:
        lines.append(f"- {guardrail}")
    return "\n".join(lines) + "\n"


def _write_artifacts(artifact: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    trade_date = artifact["trade_date"]
    dated_json = output_dir / f"btst_early_runner_watchlist_{trade_date}.json"
    dated_md = output_dir / f"btst_early_runner_watchlist_{trade_date}.md"
    latest_json = output_dir / "btst_early_runner_watchlist_latest.json"
    latest_md = output_dir / "btst_early_runner_watchlist_latest.md"
    json_payload = json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
    markdown_payload = _render_markdown(artifact)
    dated_json.write_text(json_payload, encoding="utf-8")
    latest_json.write_text(json_payload, encoding="utf-8")
    dated_md.write_text(markdown_payload, encoding="utf-8")
    latest_md.write_text(markdown_payload, encoding="utf-8")


def generate_btst_early_runner_board_artifacts(*, snapshot_path: Path, output_dir: Path) -> dict[str, Any]:
    assert_pre_score_features_are_safe(PRE_SCORE_FEATURES)
    snapshot = _read_json(snapshot_path)
    trade_date = str(snapshot.get("trade_date") or "unknown")
    btst_regime_gate = _extract_gate(snapshot)
    selection_targets = dict(snapshot.get("selection_targets") or {})
    rows: list[EarlyRunnerRow] = []
    rejected_rows: list[dict[str, Any]] = []
    for ticker, payload in selection_targets.items():
        converted = _target_payload_to_input(str(ticker), dict(payload or {}), btst_regime_gate=btst_regime_gate)
        if isinstance(converted, dict):
            rejected_rows.append(converted)
            continue
        row = build_early_runner_row(converted)
        if row.entry_status == "rejected":
            rejected_rows.append(row.model_dump(mode="json"))
        else:
            rows.append(row)

    watchlist_rows = rank_early_runner_rows(rows, max_rows=30)
    priority_rows = rank_early_runner_rows(rows, max_rows=10)
    constraints = TradingConstraints()
    artifact = {
        "trade_date": trade_date,
        "mode": "research_only",
        "source_snapshot_path": str(snapshot_path),
        "feature_time_map_version": FEATURE_TIME_MAP_VERSION,
        "feature_time_map": feature_time_map_as_jsonable(FEATURE_TIME_MAP),
        "limit_rule_profile_version": CN_A_SHARE_LIMIT_RULE_PROFILE.version,
        "limit_rule_profile": limit_rule_profile_as_jsonable(),
        "cost_profile": {
            "commission_rate": constraints.commission_rate,
            "stamp_duty_rate": constraints.stamp_duty_rate,
            "base_slippage_rate": constraints.base_slippage_rate,
            "low_liquidity_slippage_rate": constraints.low_liquidity_slippage_rate,
            "low_liquidity_turnover_threshold": constraints.low_liquidity_turnover_threshold,
        },
        "summary": {
            "input_count": len(selection_targets),
            "eligible_count": len(rows),
            "watchlist_count": len(watchlist_rows),
            "priority_count": len(priority_rows),
            "research_only_count": sum(1 for row in rows if row.entry_status == "research_only"),
            "shadow_only_count": sum(1 for row in rows if row.entry_status == "shadow_only"),
            "feature_time_map_coverage": 1.0,
            "no_lookahead_fields_in_pre_score": True,
        },
        "watchlist_rows": [row.model_dump(mode="json") for row in watchlist_rows],
        "priority_rows": [row.model_dump(mode="json") for row in priority_rows],
        "rejected_rows": rejected_rows,
        "guardrails": [
            "research_only output; formal buy orders are not modified",
            "T+1 and future label fields are blocked from pre_score",
        ],
    }
    _write_artifacts(artifact, output_dir)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate BTST early-runner research watchlist artifacts.")
    parser.add_argument("--snapshot-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/reports"))
    args = parser.parse_args()
    generate_btst_early_runner_board_artifacts(snapshot_path=args.snapshot_path, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the board script tests**

Run:

```bash
uv run pytest tests/test_generate_btst_early_runner_board_script.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit this task**

```bash
git add scripts/generate_btst_early_runner_board.py tests/test_generate_btst_early_runner_board_script.py
git commit -m "feat: generate early runner research board"
```

### Task 6: Focused Regression Stack

**Files:**
- Test: `tests/test_btst_early_runner_feature_time.py`
- Test: `tests/test_btst_early_runner_universe.py`
- Test: `tests/test_btst_early_runner_scoring.py`
- Test: `tests/test_btst_early_runner_execution.py`
- Test: `tests/test_generate_btst_early_runner_board_script.py`
- Test: `tests/test_btst_execution_eligibility_contract.py`
- Test: `tests/test_generate_btst_next_day_priority_board_script.py`
- Test: `tests/test_generate_btst_opening_watch_card_script.py`

- [ ] **Step 1: Run the focused early-runner stack**

```bash
uv run pytest \
  tests/test_btst_early_runner_feature_time.py \
  tests/test_btst_early_runner_universe.py \
  tests/test_btst_early_runner_scoring.py \
  tests/test_btst_early_runner_execution.py \
  tests/test_generate_btst_early_runner_board_script.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run adjacent BTST artifact and execution contract regressions**

```bash
uv run pytest \
  tests/test_btst_execution_eligibility_contract.py \
  tests/test_generate_btst_next_day_priority_board_script.py \
  tests/test_generate_btst_opening_watch_card_script.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit any regression fixes**

If Step 1 or Step 2 required fixes, inspect the changed files and commit the concrete regression-fix files:

```bash
git status --short
git add src/targets/early_runner_feature_time.py \
  src/targets/early_runner_universe.py \
  src/targets/early_runner_models.py \
  src/targets/early_runner_scoring.py \
  src/backtesting/early_runner_execution.py \
  scripts/generate_btst_early_runner_board.py \
  tests/test_btst_early_runner_feature_time.py \
  tests/test_btst_early_runner_universe.py \
  tests/test_btst_early_runner_scoring.py \
  tests/test_btst_early_runner_execution.py \
  tests/test_generate_btst_early_runner_board_script.py
git commit -m "fix: stabilize early runner research regressions"
```

If no fixes were needed, do not create an empty commit.

### Task 7: Generate One Local Artifact from Current Snapshot

**Files:**
- Generated: `data/reports/btst_early_runner_watchlist_20260525.json`
- Generated: `data/reports/btst_early_runner_watchlist_20260525.md`
- Generated: `data/reports/btst_early_runner_watchlist_latest.json`
- Generated: `data/reports/btst_early_runner_watchlist_latest.md`

- [ ] **Step 1: Locate the current snapshot**

Run:

```bash
find data/reports -path '*selection_artifacts/2026-05-25/selection_snapshot.json' -print | head -1
```

Expected: prints one `selection_snapshot.json` path. If it prints nothing, use the most recent available snapshot under `data/reports/*/selection_artifacts/*/selection_snapshot.json`.

- [ ] **Step 2: Generate the artifact**

Run with the discovered path captured by the shell:

```bash
SNAPSHOT_PATH=$(find data/reports -path '*selection_artifacts/2026-05-25/selection_snapshot.json' -print | head -1)
test -n "$SNAPSHOT_PATH"
uv run python scripts/generate_btst_early_runner_board.py \
  --snapshot-path "$SNAPSHOT_PATH" \
  --output-dir data/reports
```

Expected: the four generated files listed above exist.

- [ ] **Step 3: Inspect the artifact guardrails**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path
path = Path("data/reports/btst_early_runner_watchlist_latest.json")
payload = json.loads(path.read_text(encoding="utf-8"))
print(payload["mode"])
print(payload["summary"]["no_lookahead_fields_in_pre_score"])
print(payload["summary"]["watchlist_count"])
PY
```

Expected:

```text
research_only
True
```

The third line is a non-negative integer.

- [ ] **Step 4: Commit generated artifacts only if the project keeps generated research artifacts in git**

Check existing repository convention with:

```bash
git status --short data/reports | head
```

If generated reports are normally tracked for this workflow, commit:

```bash
git add data/reports/btst_early_runner_watchlist_20260525.json \
  data/reports/btst_early_runner_watchlist_20260525.md \
  data/reports/btst_early_runner_watchlist_latest.json \
  data/reports/btst_early_runner_watchlist_latest.md
git commit -m "data: add early runner research artifact"
```

If generated reports are not tracked for this workflow, leave them uncommitted and mention them in the handoff.

## Phase 2 Backlog

After MVP evidence is stable, add separate plans for:
- Real intraday confirmation data and `early_runner_confirm_score`.
- Walk-forward threshold grid report using `src/backtesting/walk_forward.py`.
- `second_entry_reentry` ledger and high-position re-entry board.
- Failure-log backfill and weekly failure-reason distribution.
- Promotion gate integration using `src/backtesting/promotion_gate.py`.

Each Phase 2 item should be implemented as a separate plan so first-pass MVP failures are not hidden by later feature work.

## Self-Review Checklist

- v4 `feature_time_map` requirement maps to Task 1.
- v4 `universe_filter` and `limit_rule_profile` requirements map to Task 2.
- v4 `early_runner_pre_score` requirement maps to Task 3.
- v4 cost / tradeability requirement maps to Task 4.
- v4 output schema and research artifact requirement maps to Task 5.
- v4 regression and non-interference requirement maps to Task 6.
- v4 local artifact smoke test maps to Task 7.
- Formal execution remains unchanged in MVP.
- Every output is `research_only` or `shadow_only`.
