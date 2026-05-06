# BTST Candidate-Pool Frontier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a validation-first, source-aware candidate-pool frontier expansion path that widens BTST replay inputs for corridor/post-gate shadow families and reports source-level quality deltas.

**Architecture:** Add a focused frontier helper that decides which shadow/boundary entries can be promoted into the replay universe, then wire that helper into `refresh_selection_artifacts_from_daily_events.py` so refreshed reports produce wider `selection_targets` without changing unrelated runtime behavior. Extend replay diagnostics to summarize selected/tradeable quality by frontier source family so later multi-window and optimization work can tell whether sample growth is useful or just noisy.

**Tech Stack:** Python 3.11+, Pydantic models, existing BTST refresh/replay scripts, pytest

---

## File Map

- Create: `src/screening/candidate_pool_frontier_helpers.py`
  - Owns source-family normalization, source-aware gating, promoted-entry shaping, and frontier diagnostics payload building.
- Modify: `scripts/refresh_selection_artifacts_from_daily_events.py`
  - Calls the new helper during artifact refresh, injects promoted frontier entries into replay rebuilding, and stores per-source expansion diagnostics.
- Modify: `scripts/btst_profile_replay_utils.py`
  - Aggregates row outcomes by frontier source family for tradeable/selected surfaces.
- Modify: `scripts/analyze_btst_multi_window_profile_validation.py`
  - Surfaces frontier-source summaries in JSON and markdown output.
- Create: `tests/test_btst_candidate_pool_frontier_helpers.py`
  - Unit coverage for source-family classification and gating.
- Modify: `tests/test_refresh_selection_artifacts_from_daily_events_script.py`
  - Regression coverage for refreshed artifact promotion and diagnostics.
- Create: `tests/test_btst_profile_replay_utils.py`
  - Coverage for source-family replay summaries.
- Modify: `tests/test_analyze_btst_multi_window_profile_validation_script.py`
  - Coverage for multi-window reporting of frontier-source metrics.

## Task 1: Build the source-aware frontier helper

**Files:**
- Create: `src/screening/candidate_pool_frontier_helpers.py`
- Test: `tests/test_btst_candidate_pool_frontier_helpers.py`

- [ ] **Step 1: Write the failing helper tests**

```python
from __future__ import annotations

from src.screening.candidate_pool_frontier_helpers import (
    build_candidate_pool_frontier_entries,
    classify_candidate_pool_frontier_source_family,
)


def test_classify_candidate_pool_frontier_source_family_maps_corridor_and_post_gate() -> None:
    assert classify_candidate_pool_frontier_source_family(
        {
            "candidate_source": "upstream_liquidity_corridor_shadow",
            "candidate_pool_lane": "layer_a_liquidity_corridor",
        }
    ) == "upstream_liquidity_corridor_shadow"
    assert classify_candidate_pool_frontier_source_family(
        {
            "candidate_source": "post_gate_liquidity_competition_shadow",
            "candidate_pool_lane": "post_gate_liquidity_competition",
        }
    ) == "post_gate_liquidity_competition_shadow"


def test_build_candidate_pool_frontier_entries_keeps_only_entries_that_meet_source_gates() -> None:
    promoted_entries, diagnostics = build_candidate_pool_frontier_entries(
        released_shadow_entries=[
            {
                "ticker": "300720",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "candidate_pool_lane": "layer_a_liquidity_corridor",
                "candidate_pool_rank": 1131,
                "candidate_pool_avg_amount_share_of_cutoff": 0.3221,
                "candidate_pool_avg_amount_share_of_min_gate": 9.6762,
                "short_trade_boundary_metrics": {
                    "trend_acceleration": 0.8507,
                    "close_strength": 0.9092,
                    "catalyst_freshness": 0.0,
                },
            },
            {
                "ticker": "301188",
                "candidate_source": "upstream_liquidity_corridor_shadow",
                "candidate_pool_lane": "layer_a_liquidity_corridor",
                "candidate_pool_rank": 3179,
                "candidate_pool_avg_amount_share_of_cutoff": 0.0738,
                "candidate_pool_avg_amount_share_of_min_gate": 2.4069,
                "short_trade_boundary_metrics": {
                    "trend_acceleration": 0.0,
                    "close_strength": 0.068,
                    "catalyst_freshness": 0.0,
                },
            },
        ],
        shadow_observation_entries=[],
    )

    assert [entry["ticker"] for entry in promoted_entries] == ["300720"]
    assert promoted_entries[0]["frontier_expansion_source_family"] == "upstream_liquidity_corridor_shadow"
    assert diagnostics["source_family_counts"]["upstream_liquidity_corridor_shadow"]["promoted_count"] == 1
    assert diagnostics["source_family_counts"]["upstream_liquidity_corridor_shadow"]["rejected_count"] == 1
```

- [ ] **Step 2: Run the helper tests to verify they fail**

Run: `uv run pytest tests/test_btst_candidate_pool_frontier_helpers.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.screening.candidate_pool_frontier_helpers'`

- [ ] **Step 3: Write the minimal helper implementation**

```python
from __future__ import annotations

from typing import Any


SUPPORTED_FRONTIER_FAMILIES = frozenset(
    {
        "upstream_liquidity_corridor_shadow",
        "post_gate_liquidity_competition_shadow",
    }
)


def classify_candidate_pool_frontier_source_family(entry: dict[str, Any]) -> str | None:
    candidate_source = str(entry.get("candidate_source") or "").strip()
    if candidate_source in SUPPORTED_FRONTIER_FAMILIES:
        return candidate_source

    lane = str(entry.get("candidate_pool_lane") or "").strip()
    if lane == "layer_a_liquidity_corridor":
        return "upstream_liquidity_corridor_shadow"
    if lane == "post_gate_liquidity_competition":
        return "post_gate_liquidity_competition_shadow"
    return None


def _meets_frontier_gate(entry: dict[str, Any], *, source_family: str) -> bool:
    metrics = dict(entry.get("short_trade_boundary_metrics") or {})
    rank = int(entry.get("candidate_pool_rank") or 0)
    cutoff_share = float(entry.get("candidate_pool_avg_amount_share_of_cutoff") or 0.0)
    min_gate_share = float(entry.get("candidate_pool_avg_amount_share_of_min_gate") or 0.0)
    trend_acceleration = float(metrics.get("trend_acceleration") or 0.0)
    close_strength = float(metrics.get("close_strength") or 0.0)

    if source_family == "upstream_liquidity_corridor_shadow":
        return rank > 0 and rank <= 1500 and min_gate_share >= 4.0 and cutoff_share >= 0.20 and trend_acceleration >= 0.70 and close_strength >= 0.85
    if source_family == "post_gate_liquidity_competition_shadow":
        return rank > 0 and rank <= 1500 and min_gate_share >= 3.0 and cutoff_share >= 0.18 and trend_acceleration >= 0.75 and close_strength >= 0.88
    return False


def build_candidate_pool_frontier_entries(
    *,
    released_shadow_entries: list[dict[str, Any]],
    shadow_observation_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    promoted_entries: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {"source_family_counts": {}}

    for entry in [*list(released_shadow_entries or []), *list(shadow_observation_entries or [])]:
        current = dict(entry or {})
        source_family = classify_candidate_pool_frontier_source_family(current)
        if source_family is None:
            continue

        bucket = diagnostics["source_family_counts"].setdefault(source_family, {"promoted_count": 0, "rejected_count": 0})
        if not _meets_frontier_gate(current, source_family=source_family):
            bucket["rejected_count"] += 1
            continue

        promoted_entries.append(
            {
                **current,
                "frontier_expansion_enabled": True,
                "frontier_expansion_source_family": source_family,
                "frontier_expansion_reason": "candidate_pool_frontier_expanded",
            }
        )
        bucket["promoted_count"] += 1

    return promoted_entries, diagnostics
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `uv run pytest tests/test_btst_candidate_pool_frontier_helpers.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/screening/candidate_pool_frontier_helpers.py tests/test_btst_candidate_pool_frontier_helpers.py
git commit -m "feat: add btst candidate pool frontier helper"
```

## Task 2: Wire frontier expansion into refreshed replay artifacts

**Files:**
- Modify: `scripts/refresh_selection_artifacts_from_daily_events.py`
- Modify: `tests/test_refresh_selection_artifacts_from_daily_events_script.py`

- [ ] **Step 1: Add failing refresh-script coverage for promoted frontier entries**

```python
def test_refresh_selection_artifacts_from_daily_events_promotes_frontier_entries_into_supplemental_replay(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    report_dir = tmp_path / "paper_trading_20260406_20260406_frontier_refresh"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260406"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [],
                        "released_shadow_entries": [_make_corridor_released_shadow_entry(shadow_visibility_gap_selected=True)],
                        "shadow_observation_entries": [],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps({"event": "paper_trading_day", "trade_date": trade_date, "current_plan": plan.model_dump(mode="json")}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(refresh_module, "_load_latest_historical_prior_by_ticker", lambda _report_dir: {})

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-06")

    replay_input = json.loads((report_dir / "selection_artifacts" / "2026-04-06" / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    promoted = [entry for entry in replay_input["supplemental_short_trade_entries"] if entry.get("frontier_expansion_enabled")]

    assert [entry["ticker"] for entry in promoted] == ["300720"]
    assert promoted[0]["frontier_expansion_source_family"] == "upstream_liquidity_corridor_shadow"
    assert replay_input["source_summary"]["frontier_source_family_counts"]["upstream_liquidity_corridor_shadow"]["promoted_count"] == 1
```

- [ ] **Step 2: Run the refresh-script test to verify it fails**

Run: `uv run pytest tests/test_refresh_selection_artifacts_from_daily_events_script.py::test_refresh_selection_artifacts_from_daily_events_promotes_frontier_entries_into_supplemental_replay -q`

Expected: FAIL because `frontier_expansion_enabled` and `frontier_source_family_counts` are missing from the refreshed replay input.

- [ ] **Step 3: Implement refresh/rebuild wiring**

```python
from src.screening.candidate_pool_frontier_helpers import build_candidate_pool_frontier_entries


def _build_frontier_expansion_entries(
    *,
    filters: dict[str, Any],
    prior_by_ticker: dict[str, dict[str, Any]],
    strategy_signals_by_ticker: dict[str, dict[str, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    short_trade_filter = dict(filters.get("short_trade_candidates") or {})
    promoted_entries, diagnostics = build_candidate_pool_frontier_entries(
        released_shadow_entries=list(short_trade_filter.get("released_shadow_entries") or []),
        shadow_observation_entries=list(short_trade_filter.get("shadow_observation_entries") or []),
    )
    promoted_entries = _attach_historical_prior_to_entries(promoted_entries, prior_by_ticker=prior_by_ticker)
    promoted_entries = _attach_strategy_signals_to_entries(promoted_entries, strategy_signals_by_ticker=strategy_signals_by_ticker)
    return promoted_entries, diagnostics


def rebuild_selection_targets_for_plan(...):
    ...
    promoted_frontier_entries, frontier_diagnostics = _build_frontier_expansion_entries(
        filters=filters,
        prior_by_ticker=historical_prior_by_ticker,
        strategy_signals_by_ticker=strategy_signals_by_ticker,
    )
    selection_targets, dual_target_summary = build_selection_targets(
        ...,
        supplemental_short_trade_entries=[
            *refreshed_short_trade_tickers,
            *refreshed_short_trade_released_shadow_entries,
            *refreshed_watchlist_released_shadow_entries,
            *refreshed_catalyst_theme_tickers,
            *promoted_frontier_entries,
        ],
        ...,
    )
    risk_metrics["candidate_pool_frontier_expansion"] = frontier_diagnostics
```

- [ ] **Step 4: Persist frontier diagnostics in refreshed artifacts**

```python
def _write_frontier_diagnostics_to_artifacts(
    *,
    snapshot_path: str | Path,
    replay_input_path: str | Path,
    frontier_diagnostics: dict[str, Any],
) -> None:
    for artifact_path in (Path(snapshot_path), Path(replay_input_path)):
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        payload["candidate_pool_frontier_expansion"] = frontier_diagnostics
        source_summary = dict(payload.get("source_summary") or {})
        source_summary["frontier_source_family_counts"] = dict(frontier_diagnostics.get("source_family_counts") or {})
        payload["source_summary"] = source_summary
        artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def refresh_selection_artifacts_for_report(report_dir: str | Path, trade_date: str | None = None) -> dict[str, Any]:
    ...
    frontier_diagnostics = dict(dict(refreshed_plan.risk_metrics or {}).get("candidate_pool_frontier_expansion") or {})
    refreshed_results.append(
        {
            "trade_date": trade_date_display,
            "snapshot_path": write_result.snapshot_path,
            "replay_input_path": write_result.replay_input_path,
            "write_status": write_result.write_status,
            "selection_target_count": len(refreshed_plan.selection_targets),
            "frontier_source_family_counts": dict(
                frontier_diagnostics.get("source_family_counts") or {}
            ),
        }
    )
    _write_frontier_diagnostics_to_artifacts(
        snapshot_path=write_result.snapshot_path,
        replay_input_path=write_result.replay_input_path,
        frontier_diagnostics=frontier_diagnostics,
    )
```

- [ ] **Step 5: Run the refresh-script regression bundle**

Run: `uv run pytest tests/test_refresh_selection_artifacts_from_daily_events_script.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/refresh_selection_artifacts_from_daily_events.py tests/test_refresh_selection_artifacts_from_daily_events_script.py
git commit -m "feat: promote btst candidate-pool frontier entries during refresh"
```

## Task 3: Surface source-family quality diagnostics in replay validation

**Files:**
- Modify: `scripts/btst_profile_replay_utils.py`
- Modify: `scripts/analyze_btst_multi_window_profile_validation.py`
- Create: `tests/test_btst_profile_replay_utils.py`
- Modify: `tests/test_analyze_btst_multi_window_profile_validation_script.py`

- [ ] **Step 1: Add failing replay-utils coverage for frontier-source summaries**

```python
from __future__ import annotations

from scripts.btst_profile_replay_utils import _summarize_rows_by_frontier_source_family


def test_summarize_rows_by_frontier_source_family_groups_tradeable_rows() -> None:
    rows = [
        {
            "decision": "selected",
            "candidate_source": "upstream_liquidity_corridor_shadow",
            "frontier_expansion_source_family": "upstream_liquidity_corridor_shadow",
            "next_close_return": 0.03,
            "next_high_return": 0.05,
            "cycle_status": "closed",
            "data_status": "complete",
        },
        {
            "decision": "near_miss",
            "candidate_source": "post_gate_liquidity_competition_shadow",
            "frontier_expansion_source_family": "post_gate_liquidity_competition_shadow",
            "next_close_return": -0.01,
            "next_high_return": 0.02,
            "cycle_status": "closed",
            "data_status": "complete",
        },
    ]

    summary = _summarize_rows_by_frontier_source_family(rows, next_high_hit_threshold=0.02)

    assert summary["upstream_liquidity_corridor_shadow"]["tradeable"]["total_count"] == 1
    assert summary["post_gate_liquidity_competition_shadow"]["tradeable"]["total_count"] == 1
```

- [ ] **Step 2: Add failing multi-window-report coverage**

```python
def test_render_btst_multi_window_profile_validation_markdown_includes_frontier_source_summary(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(multi_window_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])
    monkeypatch.setattr(
        multi_window_validation,
        "analyze_btst_profile_replay_window",
        lambda *_args, **_kwargs: {
            "profile_name": "btst_precision_v2",
            "trade_dates": ["2026-03-24"],
            "surface_summaries": {"tradeable": {"total_count": 1, "closed_cycle_count": 1, "next_high_hit_rate_at_threshold": 1.0, "next_close_positive_rate": 1.0, "t_plus_2_close_positive_rate": 1.0, "next_high_return_distribution": {"mean": 0.05}, "next_close_return_distribution": {"mean": 0.03, "median": 0.03, "p10": 0.01}, "t_plus_2_close_return_distribution": {"mean": 0.04, "median": 0.04, "p10": 0.02}}},
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
            "frontier_source_family_summaries": {"upstream_liquidity_corridor_shadow": {"tradeable": {"total_count": 1}}},
        },
    )

    analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile="btst_precision_v2",
        variant_profile="btst_candidate_pool_frontier",
    )

    markdown = multi_window_validation.render_btst_multi_window_profile_validation_markdown(analysis)
    assert "upstream_liquidity_corridor_shadow" in markdown
```

- [ ] **Step 3: Run the new diagnostics tests to verify they fail**

Run: `uv run pytest tests/test_btst_profile_replay_utils.py tests/test_analyze_btst_multi_window_profile_validation_script.py -q`

Expected: FAIL because `_summarize_rows_by_frontier_source_family` and frontier markdown output do not exist yet.

- [ ] **Step 4: Implement replay and report diagnostics**

```python
def _summarize_rows_by_frontier_source_family(rows: list[dict[str, Any]], *, next_high_hit_threshold: float) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        source_family = str(row.get("frontier_expansion_source_family") or "")
        if not source_family:
            continue
        grouped.setdefault(source_family, []).append(row)
    return {
        source_family: {
            "all": _build_surface_summary(source_rows, next_high_hit_threshold=next_high_hit_threshold),
            "tradeable": _build_surface_summary(
                [row for row in source_rows if row.get("decision") in {"selected", "near_miss"}],
                next_high_hit_threshold=next_high_hit_threshold,
            ),
        }
        for source_family, source_rows in grouped.items()
    }


def _build_profile_replay_analysis_payload(...):
    ...
    return {
        ...,
        "frontier_source_family_summaries": _summarize_rows_by_frontier_source_family(rows, next_high_hit_threshold=next_high_hit_threshold),
    }
```

```python
def _summarize_row(...):
    return {
        ...,
        "baseline_frontier_source_family_summaries": dict(baseline.get("frontier_source_family_summaries") or {}),
        "variant_frontier_source_family_summaries": dict(variant.get("frontier_source_family_summaries") or {}),
    }


def render_btst_multi_window_profile_validation_markdown(analysis: dict[str, Any]) -> str:
    ...
    for row in list(analysis.get("rows") or []):
        lines.append(f"- {row['report_label']}: recommendation={row['window_recommendation']}, baseline_tradeable={row['baseline_tradeable'].get('total_count')}, variant_tradeable={row['variant_tradeable'].get('total_count')}")
        for source_family, source_payload in dict(row.get("variant_frontier_source_family_summaries") or {}).items():
            lines.append(f"  - frontier_source={source_family}, tradeable={dict(source_payload.get('tradeable') or {}).get('total_count')}")
```

- [ ] **Step 5: Run the diagnostics test bundle**

Run: `uv run pytest tests/test_btst_profile_replay_utils.py tests/test_analyze_btst_multi_window_profile_validation_script.py tests/test_optimize_profile_script.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/btst_profile_replay_utils.py scripts/analyze_btst_multi_window_profile_validation.py tests/test_btst_profile_replay_utils.py tests/test_analyze_btst_multi_window_profile_validation_script.py
git commit -m "feat: report btst frontier quality by source family"
```

## Validation Checklist

- [ ] Run the focused implementation test bundle:

```bash
uv run pytest \
  tests/test_btst_candidate_pool_frontier_helpers.py \
  tests/test_refresh_selection_artifacts_from_daily_events_script.py \
  tests/test_btst_profile_replay_utils.py \
  tests/test_analyze_btst_multi_window_profile_validation_script.py \
  tests/test_optimize_profile_script.py \
  -q
```

- [ ] Run an activation probe on refreshed April reports and confirm the widened frontier now produces non-empty per-source diagnostics:

```bash
uv run python scripts/refresh_selection_artifacts_from_daily_events.py \
  data/reports/paper_trading_2026-04-06_2026-04-10_live_m2_7_short_trade_only_20260413_core6_today_btst

uv run python scripts/analyze_btst_micro_window_regression.py \
  --baseline-report-dir /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/paper_trading_2026-04-06_2026-04-10_live_m2_7_short_trade_only_20260413_core6_today_btst \
  --variant-report frontier-expanded=/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/.worktrees/btst-admission-edge-recovery/data/reports/btst_admission_edge_activation_probe_inputs/paper_trading_2026-04-06_2026-04-10_live_m2_7_short_trade_only_20260413_core6_today_btst \
  --output-json data/reports/btst_candidate_pool_frontier_probe.json \
  --output-md data/reports/btst_candidate_pool_frontier_probe.md
```

Expected: the refreshed replay artifacts include non-empty `candidate_pool_frontier_expansion.source_family_counts`, and the micro-window probe shows whether the expanded report produces additional actionable rows or only more rejected noise.
