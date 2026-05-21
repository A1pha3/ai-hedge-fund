# Momentum Cross-Window Stability Retune Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a narrow, fail-closed momentum retune pipeline that mines a local parameter neighborhood around the current candidate, scores it against cross-window stability regressions, and emits one governed next-step decision.

**Architecture:** Add three small script surfaces around the existing momentum triage artifacts and the current param-search report. First, define the bounded local retune surface around the current best parameters. Second, shortlist local candidates and score them against the dominant cross-window stability blockers. Third, emit a governed retune decision that either justifies a later rollout re-check, falls back to measurement repair, or retains hold.

**Tech Stack:** Python 3.11+/3.13 runtime in repo, existing `scripts/` CLI pattern, JSON + Markdown artifacts under `data/reports/`, pytest.

---

## Planned file structure

- Create: `scripts/btst_momentum_stability_retune_surface.py`
  - Read the current param-search report and triage recommendation; emit the local parameter neighborhood and fixed/frozen knobs.
- Create: `tests/test_btst_momentum_stability_retune_surface_script.py`
  - Verify the retune surface stays local, preserves fixed zero-weight knobs, and fails closed on malformed source artifacts.
- Create: `scripts/btst_momentum_stability_retune_shortlist.py`
  - Filter local candidates from the param-search report and rank them by cross-window stability pressure vs. risk regression pressure.
- Create: `tests/test_btst_momentum_stability_retune_shortlist_script.py`
  - Verify neighborhood filtering, stability-first ranking, and fail-closed behavior when no governed candidate exists.
- Create: `scripts/btst_momentum_stability_retune_decision.py`
  - Combine the shortlist artifact and current momentum triage outputs into one governed retune decision.
- Create: `tests/test_btst_momentum_stability_retune_decision_script.py`
  - Verify `rerun_rollout_check`, `retain_hold`, and `fallback_measurement_repair` decisions.
- Verify existing: `scripts/optimize_profile.py`
  - Use as the authoritative source for metric semantics only; do not widen or refactor it in this cycle.
- Modify: `docs/superpowers/specs/2026-05-21-momentum-cross-window-stability-retune-design.md`
  - Only if the written spec needs a tiny consistency fix during self-review.

---

### Task 1: Add the local momentum retune surface artifact

**Files:**
- Create: `scripts/btst_momentum_stability_retune_surface.py`
- Create: `tests/test_btst_momentum_stability_retune_surface_script.py`
- Verify reference only: `data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json`
- Verify reference only: `data/reports/btst_momentum_rollout_triage_recommendation.json`
- Test: `tests/test_btst_momentum_stability_retune_surface_script.py`

- [ ] **Step 1: Write the failing surface tests**

```python
import json
from pathlib import Path

import pytest

import scripts.btst_momentum_stability_retune_surface as surface


def test_build_retune_surface_keeps_search_local_and_freezes_zero_weights() -> None:
    payload = surface.build_momentum_stability_retune_surface(
        best_params={
            "select_threshold": 0.46,
            "recency_half_life_days": 180,
            "trend_acceleration_weight": 0.22,
            "close_strength_weight": 0.12,
            "volume_expansion_quality_weight": 0.16,
            "catalyst_freshness_weight": 0.14,
            "momentum_strength_weight": 0.0,
            "short_term_reversal_weight": 0.0,
        },
        triage={"action": "parameter_retune_next", "dominant_family": "cross_window_stability"},
    )

    assert payload["retune_allowed"] is True
    assert payload["fixed_params"] == {
        "momentum_strength_weight": 0.0,
        "short_term_reversal_weight": 0.0,
    }
    assert payload["grid"]["select_threshold"] == [0.42, 0.46, 0.5]
    assert payload["grid"]["recency_half_life_days"] == [120, 180, 240]


def test_build_retune_surface_fails_closed_when_triage_does_not_allow_parameter_retune() -> None:
    with pytest.raises(SystemExit, match="parameter_retune_next"):
        surface.build_momentum_stability_retune_surface(
            best_params={"select_threshold": 0.46},
            triage={"action": "retain_hold", "dominant_family": "risk_payoff_regression"},
        )


def test_main_writes_surface_outputs(tmp_path: Path) -> None:
    source_json = tmp_path / "param_search.json"
    triage_json = tmp_path / "triage.json"
    output_json = tmp_path / "surface.json"
    output_md = tmp_path / "surface.md"
    source_json.write_text(
        json.dumps({"best_params": {"select_threshold": 0.46, "recency_half_life_days": 180, "trend_acceleration_weight": 0.22, "close_strength_weight": 0.12, "volume_expansion_quality_weight": 0.16, "catalyst_freshness_weight": 0.14, "momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}}),
        encoding="utf-8",
    )
    triage_json.write_text(json.dumps({"action": "parameter_retune_next", "dominant_family": "cross_window_stability"}), encoding="utf-8")

    result = surface.main(
        [
            "--source-json",
            str(source_json),
            "--triage-json",
            str(triage_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["retune_allowed"] is True
    assert output_md.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_stability_retune_surface_script.py -v
```

Expected: FAIL with import or attribute errors for the missing surface script.

- [ ] **Step 3: Write the minimal surface implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


LOCAL_GRID = {
    "select_threshold": [-0.04, 0.0, 0.04],
    "recency_half_life_days": [-60, 0, 60],
    "trend_acceleration_weight": [-0.04, 0.0, 0.04],
    "close_strength_weight": [-0.04, 0.0, 0.04],
    "volume_expansion_quality_weight": [-0.04, 0.0, 0.04],
    "catalyst_freshness_weight": [-0.04, 0.0, 0.04],
}
FIXED_ZERO_PARAMS = ("momentum_strength_weight", "short_term_reversal_weight")


def build_momentum_stability_retune_surface(*, best_params: dict[str, object], triage: dict[str, object]) -> dict[str, object]:
    if str(triage.get("action") or "") != "parameter_retune_next":
        raise SystemExit("triage action must be parameter_retune_next before building a retune surface.")

    normalized_best_params = {key: float(value) for key, value in best_params.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
    fixed_params = {key: normalized_best_params.get(key, 0.0) for key in FIXED_ZERO_PARAMS}
    if any(value != 0.0 for value in fixed_params.values()):
        raise SystemExit("fixed zero-weight parameters must stay disabled for this retune cycle.")

    grid = {
        "select_threshold": [round(normalized_best_params["select_threshold"] + delta, 2) for delta in LOCAL_GRID["select_threshold"]],
        "recency_half_life_days": [int(normalized_best_params["recency_half_life_days"] + delta) for delta in LOCAL_GRID["recency_half_life_days"]],
        "trend_acceleration_weight": [round(normalized_best_params["trend_acceleration_weight"] + delta, 2) for delta in LOCAL_GRID["trend_acceleration_weight"]],
        "close_strength_weight": [round(normalized_best_params["close_strength_weight"] + delta, 2) for delta in LOCAL_GRID["close_strength_weight"]],
        "volume_expansion_quality_weight": [round(normalized_best_params["volume_expansion_quality_weight"] + delta, 2) for delta in LOCAL_GRID["volume_expansion_quality_weight"]],
        "catalyst_freshness_weight": [round(normalized_best_params["catalyst_freshness_weight"] + delta, 2) for delta in LOCAL_GRID["catalyst_freshness_weight"]],
    }
    return {
        "retune_allowed": True,
        "dominant_family": str(triage.get("dominant_family") or ""),
        "best_params": normalized_best_params,
        "fixed_params": fixed_params,
        "grid": grid,
        "fail_closed": True,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_stability_retune_surface_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_stability_retune_surface.py tests/test_btst_momentum_stability_retune_surface_script.py
git commit -m "feat: add momentum retune surface"
```

---

### Task 2: Add the local momentum retune shortlist artifact

**Files:**
- Create: `scripts/btst_momentum_stability_retune_shortlist.py`
- Create: `tests/test_btst_momentum_stability_retune_shortlist_script.py`
- Verify reference only: `scripts/optimize_profile.py`
- Verify reference only: `data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json`
- Test: `tests/test_btst_momentum_stability_retune_shortlist_script.py`

- [ ] **Step 1: Write the failing shortlist tests**

```python
import json
from pathlib import Path

import pytest

import scripts.btst_momentum_stability_retune_shortlist as shortlist


def test_build_retune_shortlist_prefers_lower_stability_pressure_without_worsening_risk() -> None:
    payload = shortlist.build_momentum_stability_retune_shortlist(
        results=[
            {
                "trial_index": 10,
                "params": {"select_threshold": 0.46},
                "comparison_summary": {
                    "momentum_optimized": {"win_rate_window_trend_delta": -0.02, "gate_above_threshold_cv_delta": 0.0, "max_drawdown_simulated_delta": 0.0},
                    "default": {"win_rate_cv_delta": -0.01, "t_plus_3_close_payoff_ratio_delta": 0.0},
                },
            },
            {
                "trial_index": 11,
                "params": {"select_threshold": 0.46},
                "comparison_summary": {
                    "momentum_optimized": {"win_rate_window_trend_delta": 0.01, "gate_above_threshold_cv_delta": 0.0, "max_drawdown_simulated_delta": 0.0},
                    "default": {"win_rate_cv_delta": 0.0, "t_plus_3_close_payoff_ratio_delta": 0.0},
                },
            },
        ],
        surface={"grid": {"select_threshold": [0.42, 0.46, 0.5]}, "fixed_params": {"momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}},
    )

    assert payload["candidate_count"] == 2
    assert payload["best_candidate"]["trial_index"] == 11
    assert payload["best_candidate"]["cross_window_blocker_count"] == 0


def test_build_retune_shortlist_fails_closed_when_no_local_candidates_match_surface() -> None:
    with pytest.raises(SystemExit, match="local retune candidates"):
        shortlist.build_momentum_stability_retune_shortlist(
            results=[{"trial_index": 1, "params": {"select_threshold": 0.6}, "comparison_summary": {}}],
            surface={"grid": {"select_threshold": [0.42, 0.46, 0.5]}, "fixed_params": {"momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}},
        )


def test_main_writes_shortlist_outputs(tmp_path: Path) -> None:
    source_json = tmp_path / "source.json"
    surface_json = tmp_path / "surface.json"
    output_json = tmp_path / "shortlist.json"
    output_md = tmp_path / "shortlist.md"
    source_json.write_text(json.dumps({"results": [{"trial_index": 11, "params": {"select_threshold": 0.46, "momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}, "comparison_summary": {"momentum_optimized": {"win_rate_window_trend_delta": 0.01}, "default": {"win_rate_cv_delta": 0.0}}}]}), encoding="utf-8")
    surface_json.write_text(json.dumps({"grid": {"select_threshold": [0.42, 0.46, 0.5]}, "fixed_params": {"momentum_strength_weight": 0.0, "short_term_reversal_weight": 0.0}}), encoding="utf-8")

    result = shortlist.main(
        [
            "--source-json",
            str(source_json),
            "--surface-json",
            str(surface_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["candidate_count"] == 1
    assert output_md.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_stability_retune_shortlist_script.py -v
```

Expected: FAIL with import or attribute errors for the missing shortlist script.

- [ ] **Step 3: Write the minimal shortlist implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CROSS_WINDOW_METRICS = (
    "win_rate_window_trend_delta",
    "win_rate_window_volatility_delta",
    "win_rate_ci_width_delta",
    "win_rate_cv_delta",
    "factor_drift_score_delta",
    "param_drift_score_delta",
    "gate_above_threshold_cv_delta",
)
RISK_METRICS = (
    "max_drawdown_simulated_delta",
    "downside_p10_delta",
    "liquidity_capacity_raw_100_delta",
    "t_plus_3_close_payoff_ratio_delta",
)


def _count_regressions(comparison_summary: dict[str, Any], metric_names: tuple[str, ...]) -> int:
    count = 0
    for payload in comparison_summary.values():
        if not isinstance(payload, dict):
            continue
        for metric_name in metric_names:
            value = payload.get(metric_name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) < 0:
                count += 1
    return count


def build_momentum_stability_retune_shortlist(*, results: list[dict[str, object]], surface: dict[str, object]) -> dict[str, object]:
    allowed_thresholds = set(surface["grid"]["select_threshold"])
    fixed_params = dict(surface["fixed_params"])
    local_candidates = []
    for row in results:
        params = dict(row.get("params") or {})
        if params.get("select_threshold") not in allowed_thresholds:
            continue
        if any(params.get(name) != expected for name, expected in fixed_params.items()):
            continue
        comparison_summary = dict(row.get("comparison_summary") or {})
        local_candidates.append(
            {
                "trial_index": int(row["trial_index"]),
                "params": params,
                "cross_window_blocker_count": _count_regressions(comparison_summary, CROSS_WINDOW_METRICS),
                "risk_blocker_count": _count_regressions(comparison_summary, RISK_METRICS),
            }
        )
    if not local_candidates:
        raise SystemExit("No governed local retune candidates matched the declared surface.")

    ordered = sorted(local_candidates, key=lambda item: (item["risk_blocker_count"], item["cross_window_blocker_count"], item["trial_index"]))
    return {
        "candidate_count": len(local_candidates),
        "best_candidate": ordered[0],
        "candidates": ordered,
        "fail_closed": True,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_stability_retune_shortlist_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_stability_retune_shortlist.py tests/test_btst_momentum_stability_retune_shortlist_script.py
git commit -m "feat: add momentum retune shortlist"
```

---

### Task 3: Add the governed momentum retune decision artifact

**Files:**
- Create: `scripts/btst_momentum_stability_retune_decision.py`
- Create: `tests/test_btst_momentum_stability_retune_decision_script.py`
- Verify reference only: `scripts/btst_momentum_rollout_triage_recommendation.py`
- Test: `tests/test_btst_momentum_stability_retune_decision_script.py`

- [ ] **Step 1: Write the failing decision tests**

```python
import json
from pathlib import Path

import scripts.btst_momentum_stability_retune_decision as decision


def test_build_retune_decision_requests_rollout_recheck_when_stability_blockers_drop() -> None:
    payload = decision.build_momentum_stability_retune_decision(
        shortlist={"best_candidate": {"trial_index": 11, "cross_window_blocker_count": 2, "risk_blocker_count": 0}, "candidate_count": 3},
        triage={"dominant_family": "cross_window_stability", "blocker_count": 27, "missing_theme_exposure_window_count": 2},
    )

    assert payload["action"] == "rerun_rollout_check"
    assert payload["release_posture"] == "hold"


def test_build_retune_decision_falls_back_to_measurement_repair_when_observability_dominates_again() -> None:
    payload = decision.build_momentum_stability_retune_decision(
        shortlist={"best_candidate": {"trial_index": 11, "cross_window_blocker_count": 1, "risk_blocker_count": 0}, "candidate_count": 2},
        triage={"dominant_family": "missing_observability", "blocker_count": 8, "missing_theme_exposure_window_count": 4},
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_main_writes_retune_decision_outputs(tmp_path: Path) -> None:
    shortlist_json = tmp_path / "shortlist.json"
    triage_json = tmp_path / "triage.json"
    output_json = tmp_path / "decision.json"
    output_md = tmp_path / "decision.md"
    shortlist_json.write_text(json.dumps({"best_candidate": {"trial_index": 11, "cross_window_blocker_count": 4, "risk_blocker_count": 1}, "candidate_count": 2}), encoding="utf-8")
    triage_json.write_text(json.dumps({"dominant_family": "cross_window_stability", "blocker_count": 27, "missing_theme_exposure_window_count": 2}), encoding="utf-8")

    result = decision.main(
        [
            "--shortlist-json",
            str(shortlist_json),
            "--triage-json",
            str(triage_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["action"] == "retain_hold"
    assert output_md.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_stability_retune_decision_script.py -v
```

Expected: FAIL with import or attribute errors for the missing decision script.

- [ ] **Step 3: Write the minimal decision implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_momentum_stability_retune_decision(*, shortlist: dict[str, object], triage: dict[str, object]) -> dict[str, object]:
    best_candidate = dict(shortlist.get("best_candidate") or {})
    dominant_family = str(triage.get("dominant_family") or "")
    if dominant_family == "missing_observability":
        action = "fallback_measurement_repair"
    elif int(best_candidate.get("cross_window_blocker_count") or 0) < int(triage.get("blocker_count") or 0) and int(best_candidate.get("risk_blocker_count") or 0) == 0:
        action = "rerun_rollout_check"
    else:
        action = "retain_hold"
    return {
        "action": action,
        "release_posture": "hold",
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "candidate_count": int(shortlist.get("candidate_count") or 0),
        "best_candidate": best_candidate,
        "dominant_family": dominant_family,
        "fail_closed": True,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_stability_retune_decision_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_stability_retune_decision.py tests/test_btst_momentum_stability_retune_decision_script.py
git commit -m "feat: add momentum retune decision artifact"
```

---

### Task 4: Run the final momentum stability retune verification flow

**Files:**
- Verify input: `data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json`
- Verify input: `data/reports/btst_momentum_rollout_triage_recommendation.json`
- Create locally: `data/reports/btst_momentum_stability_retune_surface.json`
- Create locally: `data/reports/btst_momentum_stability_retune_surface.md`
- Create locally: `data/reports/btst_momentum_stability_retune_shortlist.json`
- Create locally: `data/reports/btst_momentum_stability_retune_shortlist.md`
- Create locally: `data/reports/btst_momentum_stability_retune_decision.json`
- Create locally: `data/reports/btst_momentum_stability_retune_decision.md`
- Test: `tests/test_btst_momentum_stability_retune_surface_script.py`
- Test: `tests/test_btst_momentum_stability_retune_shortlist_script.py`
- Test: `tests/test_btst_momentum_stability_retune_decision_script.py`

- [ ] **Step 1: Run the focused test suite**

Run:

```bash
uv run pytest \
  tests/test_btst_momentum_stability_retune_surface_script.py \
  tests/test_btst_momentum_stability_retune_shortlist_script.py \
  tests/test_btst_momentum_stability_retune_decision_script.py -q
```

Expected: PASS with all retune-cycle tests green.

- [ ] **Step 2: Run the local retune surface artifact**

Run:

```bash
uv run python scripts/btst_momentum_stability_retune_surface.py \
  --source-json data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json \
  --triage-json data/reports/btst_momentum_rollout_triage_recommendation.json \
  --output-json data/reports/btst_momentum_stability_retune_surface.json \
  --output-md data/reports/btst_momentum_stability_retune_surface.md
```

Expected: creates a narrow local grid and fixed zero-weight parameter set.

- [ ] **Step 3: Run the shortlist artifact**

Run:

```bash
uv run python scripts/btst_momentum_stability_retune_shortlist.py \
  --source-json data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json \
  --surface-json data/reports/btst_momentum_stability_retune_surface.json \
  --output-json data/reports/btst_momentum_stability_retune_shortlist.json \
  --output-md data/reports/btst_momentum_stability_retune_shortlist.md
```

Expected: emits a governed local candidate shortlist and one best candidate.

- [ ] **Step 4: Run the governed retune decision artifact**

Run:

```bash
uv run python scripts/btst_momentum_stability_retune_decision.py \
  --shortlist-json data/reports/btst_momentum_stability_retune_shortlist.json \
  --triage-json data/reports/btst_momentum_rollout_triage_recommendation.json \
  --output-json data/reports/btst_momentum_stability_retune_decision.json \
  --output-md data/reports/btst_momentum_stability_retune_decision.md
```

Expected: returns one governed next action among `rerun_rollout_check`, `retain_hold`, or `fallback_measurement_repair`, always with `release_posture=hold`.

- [ ] **Step 5: Commit**

```bash
git add \
  scripts/btst_momentum_stability_retune_surface.py \
  scripts/btst_momentum_stability_retune_shortlist.py \
  scripts/btst_momentum_stability_retune_decision.py \
  tests/test_btst_momentum_stability_retune_surface_script.py \
  tests/test_btst_momentum_stability_retune_shortlist_script.py \
  tests/test_btst_momentum_stability_retune_decision_script.py
git commit -m "feat: add momentum stability retune pipeline"
```

---

## Self-review checklist

### Spec coverage

- local retune surface around current momentum candidate -> **Task 1**
- stability-focused evaluation / shortlist -> **Task 2**
- governed retune next-step decision -> **Task 3**
- final live verification under `hold` posture -> **Task 4**

### Placeholder scan

- No `TBD`, `TODO`, or “implement later” placeholders remain.
- Each code-writing step includes concrete file paths and starter code.
- Each verification step includes exact commands and expected outcomes.

### Type consistency

- surface outputs `grid`, `fixed_params`, and `best_params`
- shortlist consumes `grid` / `fixed_params` and emits `candidate_count` plus `best_candidate`
- decision consumes `best_candidate`, `candidate_count`, and current triage `dominant_family`
- release posture stays `hold` through the full plan
