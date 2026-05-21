# Momentum Rollout Recheck Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a governed rollout recheck pipeline that compares winner `trial_index=602` against the current active BTST runtime using existing historical backtest evidence, carries challengers as context, and emits one governed next-step decision.

**Architecture:** Reuse the rerun-rollout winner/challenger pack as the upstream contract. Add three small script surfaces: one to freeze the active baseline alongside the winner, one to extract paired historical comparison evidence from the existing param-search artifact, and one to collapse that evidence into a governed rollout decision. Keep the entire cycle fail-closed and promotion-blocked until both win rate and payoff improve without unacceptable regressions.

**Tech Stack:** Python 3.11+/3.12, existing `scripts/` CLI pattern, `src/paper_trading/optimized_profile_resolution.py`, JSON + Markdown artifacts under `data/reports/`, pytest.

---

## Planned file structure

- Create: `scripts/btst_momentum_rollout_recheck_pack.py`
  - Resolve the active BTST baseline from the optimized-profile manifest and combine it with the rerun winner/challenger pack.
- Create: `tests/test_btst_momentum_rollout_recheck_pack_script.py`
  - Verify winner preservation, baseline resolution wiring, guardrail propagation, and fail-closed behavior.
- Create: `scripts/btst_momentum_rollout_recheck_comparison.py`
  - Read the rollout recheck pack plus the historical source report, extract winner-vs-baseline evidence from the source `comparison_summary`, and attach challenger metrics as context.
- Create: `tests/test_btst_momentum_rollout_recheck_comparison_script.py`
  - Verify winner extraction, active-baseline lookup, challenger-context wiring, and fail-closed missing-baseline handling.
- Create: `scripts/btst_momentum_rollout_recheck_decision.py`
  - Read the comparison artifact and emit `retain_hold`, `ready_for_release_review`, or `fallback_measurement_repair`.
- Create: `tests/test_btst_momentum_rollout_recheck_decision_script.py`
  - Verify the three governed decision paths and markdown output.
- Verify reference only: `scripts/btst_momentum_rerun_rollout_pack.py`
- Verify reference only: `scripts/btst_momentum_rerun_rollout_recommendation.py`
- Verify reference only: `src/paper_trading/optimized_profile_resolution.py`
- Verify reference only: `/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json`

---

### Task 1: Add the rollout recheck pack artifact

**Files:**
- Create: `scripts/btst_momentum_rollout_recheck_pack.py`
- Create: `tests/test_btst_momentum_rollout_recheck_pack_script.py`
- Verify reference only: `scripts/btst_momentum_rerun_rollout_pack.py`
- Verify reference only: `src/paper_trading/optimized_profile_resolution.py`
- Test: `tests/test_btst_momentum_rollout_recheck_pack_script.py`

- [ ] **Step 1: Write the failing pack tests**

```python
import json
from pathlib import Path

import pytest

import scripts.btst_momentum_rollout_recheck_pack as pack


def test_build_rollout_recheck_pack_preserves_winner_and_resolved_baseline() -> None:
    payload = pack.build_momentum_rollout_recheck_pack(
        rerun_pack={
            "winner": {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
            "challengers": [{"trial_index": 1226, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 1, "risk_blocker_count": 1}],
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "dominant_family": "cross_window_stability",
            "missing_theme_exposure_window_count": 2,
            "fail_closed": True,
        },
        rerun_recommendation={"action": "advance_rollout_recheck", "release_posture": "hold", "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"]},
        baseline_resolution={
            "mode": "optimized",
            "profile_name": "momentum_optimized",
            "profile_overrides": {"select_threshold": 0.46},
            "source_type": "report",
            "source_path": "/tmp/source.json",
            "validated_by": "paper_trading",
            "trade_date": "2026-05-21",
            "status": "ready",
            "fallback_reason": None,
            "manifest_path": "/tmp/manifest.json",
        },
    )

    assert payload["winner"]["trial_index"] == 602
    assert payload["active_baseline"]["profile_name"] == "momentum_optimized"
    assert payload["release_posture"] == "hold"
    assert payload["guardrails"] == ["no_manifest_publication", "no_btst_skill_promotion"]


def test_build_rollout_recheck_pack_fails_closed_when_rerun_action_is_not_advance_rollout_recheck() -> None:
    with pytest.raises(SystemExit, match="advance_rollout_recheck"):
        pack.build_momentum_rollout_recheck_pack(
            rerun_pack={"winner": {"trial_index": 602}, "challengers": [], "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"], "release_posture": "hold", "dominant_family": "cross_window_stability", "missing_theme_exposure_window_count": 2, "fail_closed": True},
            rerun_recommendation={"action": "retain_hold", "release_posture": "hold", "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"]},
            baseline_resolution={"mode": "default_fallback", "profile_name": "default", "profile_overrides": {}, "source_type": None, "source_path": None, "validated_by": None, "trade_date": None, "status": "missing", "fallback_reason": "optimized_profile_manifest_missing", "manifest_path": "/tmp/missing.json"},
        )


def test_main_writes_rollout_recheck_pack_outputs(tmp_path: Path) -> None:
    rerun_pack_json = tmp_path / "rerun_pack.json"
    rerun_recommendation_json = tmp_path / "rerun_recommendation.json"
    manifest_json = tmp_path / "manifest.json"
    output_json = tmp_path / "rollout_pack.json"
    output_md = tmp_path / "rollout_pack.md"

    rerun_pack_json.write_text(
        json.dumps(
            {
                "winner": {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "challengers": [],
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            }
        ),
        encoding="utf-8",
    )
    rerun_recommendation_json.write_text(json.dumps({"action": "advance_rollout_recheck", "release_posture": "hold", "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"]}), encoding="utf-8")
    manifest_json.write_text(json.dumps({"profile_name": "momentum_optimized", "profile_overrides": {"select_threshold": 0.46}, "source_type": "report", "source_path": "source.json", "validated_by": "paper_trading", "trade_date": "2026-05-21", "status": "ready"}), encoding="utf-8")
    (tmp_path / "source.json").write_text("{}", encoding="utf-8")

    result = pack.main(
        [
            "--rerun-pack-json",
            str(rerun_pack_json),
            "--rerun-recommendation-json",
            str(rerun_recommendation_json),
            "--manifest-json",
            str(manifest_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["active_baseline"]["profile_name"] == "momentum_optimized"
    assert output_md.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_recheck_pack_script.py -v
```

Expected: FAIL with import or attribute errors for the missing rollout recheck pack script.

- [ ] **Step 3: Write the minimal pack implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.paper_trading.optimized_profile_resolution import resolve_btst_optimized_profile_manifest


DEFAULT_RERUN_PACK_JSON = Path("data/reports/btst_momentum_rerun_rollout_pack.json")
DEFAULT_RERUN_RECOMMENDATION_JSON = Path("data/reports/btst_momentum_rerun_rollout_recommendation.json")
DEFAULT_MANIFEST_JSON = Path("data/reports/btst_latest_optimized_profile.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rollout_recheck_pack.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rollout_recheck_pack.md")
GUARDRAILS = ("no_manifest_publication", "no_btst_skill_promotion")


def _require_object(name: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return dict(payload)


def _require_non_negative_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SystemExit(f"{name} must be a non-negative integer.")
    return value


def _normalize_candidate(name: str, candidate: Any) -> dict[str, Any]:
    normalized = _require_object(name, candidate)
    normalized["trial_index"] = _require_non_negative_int(f"{name} trial_index", normalized.get("trial_index"))
    normalized["cross_window_blocker_count"] = _require_non_negative_int(f"{name} cross_window_blocker_count", normalized.get("cross_window_blocker_count"))
    normalized["risk_blocker_count"] = _require_non_negative_int(f"{name} risk_blocker_count", normalized.get("risk_blocker_count"))
    return normalized


def build_momentum_rollout_recheck_pack(*, rerun_pack: dict[str, object], rerun_recommendation: dict[str, object], baseline_resolution: dict[str, object]) -> dict[str, object]:
    normalized_pack = _require_object("rerun_pack", rerun_pack)
    normalized_recommendation = _require_object("rerun_recommendation", rerun_recommendation)
    normalized_baseline = _require_object("baseline_resolution", baseline_resolution)

    if str(normalized_recommendation.get("action") or "").strip() != "advance_rollout_recheck":
        raise SystemExit("rerun_recommendation.action must be advance_rollout_recheck.")
    if str(normalized_pack.get("release_posture") or "").strip() != "hold":
        raise SystemExit("rerun_pack.release_posture must be hold.")
    if list(normalized_pack.get("guardrails") or []) != list(GUARDRAILS):
        raise SystemExit("rerun_pack.guardrails must preserve no_manifest_publication and no_btst_skill_promotion exactly.")

    return {
        "winner": _normalize_candidate("winner", normalized_pack.get("winner")),
        "challengers": [_normalize_candidate(f"challengers[{index}]", item) for index, item in enumerate(list(normalized_pack.get("challengers") or []))],
        "active_baseline": normalized_baseline,
        "release_posture": "hold",
        "guardrails": list(GUARDRAILS),
        "dominant_family": str(normalized_pack.get("dominant_family") or "").strip(),
        "missing_theme_exposure_window_count": _require_non_negative_int("missing_theme_exposure_window_count", normalized_pack.get("missing_theme_exposure_window_count")),
        "fail_closed": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the momentum rollout recheck pack.")
    parser.add_argument("--rerun-pack-json", default=str(DEFAULT_RERUN_PACK_JSON))
    parser.add_argument("--rerun-recommendation-json", default=str(DEFAULT_RERUN_RECOMMENDATION_JSON))
    parser.add_argument("--manifest-json", default=str(DEFAULT_MANIFEST_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    rerun_pack = json.loads(Path(args.rerun_pack_json).read_text(encoding="utf-8"))
    rerun_recommendation = json.loads(Path(args.rerun_recommendation_json).read_text(encoding="utf-8"))
    baseline_resolution = resolve_btst_optimized_profile_manifest(args.manifest_json)
    payload = build_momentum_rollout_recheck_pack(rerun_pack=rerun_pack, rerun_recommendation=rerun_recommendation, baseline_resolution=baseline_resolution)

    Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output_md).write_text("# Momentum Rollout Recheck Pack\n", encoding="utf-8")
    return 0
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_recheck_pack_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_rollout_recheck_pack.py tests/test_btst_momentum_rollout_recheck_pack_script.py
git commit -m "Add momentum rollout recheck pack"
```

---

### Task 2: Add the paired historical comparison artifact

**Files:**
- Create: `scripts/btst_momentum_rollout_recheck_comparison.py`
- Create: `tests/test_btst_momentum_rollout_recheck_comparison_script.py`
- Verify reference only: `scripts/optimize_profile.py:7420-7488`
- Verify reference only: `/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json`
- Test: `tests/test_btst_momentum_rollout_recheck_comparison_script.py`

- [ ] **Step 1: Write the failing comparison tests**

```python
import json
from pathlib import Path

import pytest

import scripts.btst_momentum_rollout_recheck_comparison as comparison


def test_build_rollout_recheck_comparison_extracts_winner_baseline_and_challenger_context() -> None:
    payload = comparison.build_momentum_rollout_recheck_comparison(
        rollout_pack={
            "winner": {"trial_index": 602},
            "challengers": [{"trial_index": 1226}, {"trial_index": 74}],
            "active_baseline": {"profile_name": "momentum_optimized"},
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        },
        source_report={
            "results": [
                {"trial_index": 602, "metrics": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24}},
                {"trial_index": 1226, "metrics": {"next_close_positive_rate": 0.5200, "next_close_payoff_ratio": 1.7000, "window_count": 24}},
                {"trial_index": 74, "metrics": {"next_close_positive_rate": 0.5100, "next_close_payoff_ratio": 1.6500, "window_count": 24}},
            ],
            "comparison_summary": {
                "momentum_optimized": {
                    "candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24},
                    "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24},
                    "next_close_positive_rate_delta": -0.0063,
                    "next_close_payoff_ratio_delta": 0.1398,
                }
            },
            "baseline_verdicts": {"momentum_optimized": {"status": "blocked", "blockers": ["next_close_positive_rate_regressed_vs_momentum_optimized"]}},
        },
    )

    assert payload["winner"]["trial_index"] == 602
    assert payload["winner_vs_active_baseline"]["baseline_name"] == "momentum_optimized"
    assert payload["winner_vs_active_baseline"]["blockers"] == ["next_close_positive_rate_regressed_vs_momentum_optimized"]
    assert payload["challenger_context"][0]["trial_index"] == 1226


def test_build_rollout_recheck_comparison_fails_closed_when_active_baseline_missing_from_summary() -> None:
    with pytest.raises(SystemExit, match="comparison_summary"):
        comparison.build_momentum_rollout_recheck_comparison(
            rollout_pack={"winner": {"trial_index": 602}, "challengers": [], "active_baseline": {"profile_name": "btst_precision_v2"}, "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"], "release_posture": "hold", "fail_closed": True},
            source_report={"results": [{"trial_index": 602, "metrics": {"next_close_positive_rate": 0.5377}}], "comparison_summary": {"momentum_optimized": {}}},
        )


def test_main_writes_rollout_recheck_comparison_outputs(tmp_path: Path) -> None:
    rollout_pack_json = tmp_path / "rollout_pack.json"
    source_json = tmp_path / "source.json"
    output_json = tmp_path / "comparison.json"
    output_md = tmp_path / "comparison.md"

    rollout_pack_json.write_text(json.dumps({"winner": {"trial_index": 602}, "challengers": [], "active_baseline": {"profile_name": "momentum_optimized"}, "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"], "release_posture": "hold", "fail_closed": True}), encoding="utf-8")
    source_json.write_text(json.dumps({"results": [{"trial_index": 602, "metrics": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24}}], "comparison_summary": {"momentum_optimized": {"candidate": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24}, "baseline": {"next_close_positive_rate": 0.5440, "next_close_payoff_ratio": 1.7800, "window_count": 24}, "next_close_positive_rate_delta": -0.0063, "next_close_payoff_ratio_delta": 0.1398}}, "baseline_verdicts": {"momentum_optimized": {"status": "blocked", "blockers": ["next_close_positive_rate_regressed_vs_momentum_optimized"]}}}), encoding="utf-8")

    result = comparison.main(
        [
            "--rollout-pack-json",
            str(rollout_pack_json),
            "--source-json",
            str(source_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["winner_vs_active_baseline"]["baseline_name"] == "momentum_optimized"
    assert output_md.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_recheck_comparison_script.py -v
```

Expected: FAIL with import or attribute errors for the missing rollout recheck comparison script.

- [ ] **Step 3: Write the minimal comparison implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_ROLLOUT_PACK_JSON = Path("data/reports/btst_momentum_rollout_recheck_pack.json")
DEFAULT_SOURCE_JSON = Path("/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rollout_recheck_comparison.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rollout_recheck_comparison.md")


def _require_object(name: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return dict(payload)


def _index_results(results: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(results, list):
        raise SystemExit("source_report.results must be a list.")
    indexed: dict[int, dict[str, Any]] = {}
    for row in results:
        normalized = _require_object("source_report result", row)
        trial_index = normalized.get("trial_index")
        if isinstance(trial_index, bool) or not isinstance(trial_index, int) or trial_index < 0:
            raise SystemExit("source_report result trial_index must be a non-negative integer.")
        indexed[trial_index] = normalized
    return indexed


def build_momentum_rollout_recheck_comparison(*, rollout_pack: dict[str, object], source_report: dict[str, object]) -> dict[str, object]:
    normalized_pack = _require_object("rollout_pack", rollout_pack)
    normalized_source = _require_object("source_report", source_report)
    indexed_results = _index_results(normalized_source.get("results"))

    winner = _require_object("winner", normalized_pack.get("winner"))
    winner_trial_index = int(winner["trial_index"])
    if winner_trial_index not in indexed_results:
        raise SystemExit("winner trial_index must exist in source_report.results.")

    baseline_name = str(_require_object("active_baseline", normalized_pack.get("active_baseline")).get("profile_name") or "").strip()
    comparison_summary = _require_object("comparison_summary", normalized_source.get("comparison_summary"))
    baseline_verdicts = _require_object("baseline_verdicts", normalized_source.get("baseline_verdicts"))
    baseline_entry = comparison_summary.get(baseline_name)
    if not isinstance(baseline_entry, dict):
        raise SystemExit("comparison_summary must contain the active baseline entry.")
    baseline_verdict = baseline_verdicts.get(baseline_name)
    if not isinstance(baseline_verdict, dict):
        raise SystemExit("baseline_verdicts must contain the active baseline entry.")

    challenger_context = []
    for challenger in list(normalized_pack.get("challengers") or []):
        normalized_challenger = _require_object("challenger", challenger)
        challenger_trial_index = int(normalized_challenger["trial_index"])
        if challenger_trial_index not in indexed_results:
            raise SystemExit("challenger trial_index must exist in source_report.results.")
        challenger_metrics = _require_object("challenger metrics", _require_object("source_result", indexed_results[challenger_trial_index]).get("metrics"))
        challenger_context.append({"trial_index": challenger_trial_index, "metrics": challenger_metrics})

    return {
        "winner": indexed_results[winner_trial_index],
        "winner_vs_active_baseline": {
            "baseline_name": baseline_name,
            "candidate": _require_object("candidate", baseline_entry.get("candidate")),
            "baseline": _require_object("baseline", baseline_entry.get("baseline")),
            "next_close_positive_rate_delta": baseline_entry.get("next_close_positive_rate_delta"),
            "next_close_payoff_ratio_delta": baseline_entry.get("next_close_payoff_ratio_delta"),
            "blockers": list(baseline_verdict.get("blockers") or []),
        },
        "challenger_context": challenger_context,
        "guardrails": list(normalized_pack.get("guardrails") or []),
        "release_posture": str(normalized_pack.get("release_posture") or "").strip(),
        "fail_closed": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the momentum rollout recheck comparison artifact.")
    parser.add_argument("--rollout-pack-json", default=str(DEFAULT_ROLLOUT_PACK_JSON))
    parser.add_argument("--source-json", default=str(DEFAULT_SOURCE_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    rollout_pack = json.loads(Path(args.rollout_pack_json).read_text(encoding="utf-8"))
    source_report = json.loads(Path(args.source_json).read_text(encoding="utf-8"))
    payload = build_momentum_rollout_recheck_comparison(rollout_pack=rollout_pack, source_report=source_report)

    Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output_md).write_text("# Momentum Rollout Recheck Comparison\n", encoding="utf-8")
    return 0
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_recheck_comparison_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_rollout_recheck_comparison.py tests/test_btst_momentum_rollout_recheck_comparison_script.py
git commit -m "Add momentum rollout recheck comparison"
```

---

### Task 3: Add the governed rollout recheck decision artifact

**Files:**
- Create: `scripts/btst_momentum_rollout_recheck_decision.py`
- Create: `tests/test_btst_momentum_rollout_recheck_decision_script.py`
- Verify reference only: `scripts/btst_momentum_rerun_rollout_recommendation.py`
- Verify reference only: `scripts/optimize_profile.py:7420-7488`
- Test: `tests/test_btst_momentum_rollout_recheck_decision_script.py`

- [ ] **Step 1: Write the failing decision tests**

```python
import json
from pathlib import Path

import pytest

import scripts.btst_momentum_rollout_recheck_decision as decision


def test_build_rollout_recheck_decision_returns_ready_for_release_review_when_win_rate_and_payoff_improve() -> None:
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"window_count": 24},
                "baseline": {"window_count": 24},
                "next_close_positive_rate_delta": 0.012,
                "next_close_payoff_ratio_delta": 0.18,
                "blockers": [],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "ready_for_release_review"
    assert payload["release_posture"] == "hold"


def test_build_rollout_recheck_decision_falls_back_to_measurement_repair_when_required_deltas_are_missing() -> None:
    payload = decision.build_momentum_rollout_recheck_decision(
        comparison={
            "winner": {"trial_index": 602},
            "winner_vs_active_baseline": {
                "baseline_name": "momentum_optimized",
                "candidate": {"window_count": 24},
                "baseline": {"window_count": 24},
                "next_close_positive_rate_delta": None,
                "next_close_payoff_ratio_delta": 0.18,
                "blockers": ["missing_next_close_positive_rate_delta_vs_momentum_optimized"],
            },
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_main_writes_rollout_recheck_decision_outputs(tmp_path: Path) -> None:
    comparison_json = tmp_path / "comparison.json"
    output_json = tmp_path / "decision.json"
    output_md = tmp_path / "decision.md"

    comparison_json.write_text(
        json.dumps(
            {
                "winner": {"trial_index": 602},
                "winner_vs_active_baseline": {
                    "baseline_name": "momentum_optimized",
                    "candidate": {"window_count": 24},
                    "baseline": {"window_count": 24},
                    "next_close_positive_rate_delta": -0.0063,
                    "next_close_payoff_ratio_delta": 0.1398,
                    "blockers": ["next_close_positive_rate_regressed_vs_momentum_optimized"],
                },
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "hold",
                "fail_closed": True,
            }
        ),
        encoding="utf-8",
    )

    result = decision.main(
        [
            "--comparison-json",
            str(comparison_json),
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
uv run pytest tests/test_btst_momentum_rollout_recheck_decision_script.py -v
```

Expected: FAIL with import or attribute errors for the missing rollout recheck decision script.

- [ ] **Step 3: Write the minimal decision implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_COMPARISON_JSON = Path("data/reports/btst_momentum_rollout_recheck_comparison.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_rollout_recheck_decision.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_rollout_recheck_decision.md")
GUARDRAILS = ("no_manifest_publication", "no_btst_skill_promotion")


def _require_object(name: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return dict(payload)


def build_momentum_rollout_recheck_decision(*, comparison: dict[str, object]) -> dict[str, object]:
    normalized = _require_object("comparison", comparison)
    winner_vs_baseline = _require_object("winner_vs_active_baseline", normalized.get("winner_vs_active_baseline"))
    blockers = list(winner_vs_baseline.get("blockers") or [])
    win_rate_delta = winner_vs_baseline.get("next_close_positive_rate_delta")
    payoff_delta = winner_vs_baseline.get("next_close_payoff_ratio_delta")

    if win_rate_delta is None or payoff_delta is None:
        action = "fallback_measurement_repair"
    elif blockers:
        action = "retain_hold"
    elif float(win_rate_delta) > 0.0 and float(payoff_delta) > 0.0:
        action = "ready_for_release_review"
    else:
        action = "retain_hold"

    return {
        "action": action,
        "release_posture": "hold",
        "guardrails": list(GUARDRAILS),
        "winner": _require_object("winner", normalized.get("winner")),
        "baseline_name": str(winner_vs_baseline.get("baseline_name") or "").strip(),
        "blockers": blockers,
        "fail_closed": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the governed momentum rollout recheck decision artifact.")
    parser.add_argument("--comparison-json", default=str(DEFAULT_COMPARISON_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    comparison = json.loads(Path(args.comparison_json).read_text(encoding="utf-8"))
    payload = build_momentum_rollout_recheck_decision(comparison=comparison)

    Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output_md).write_text("# Momentum Rollout Recheck Decision\n", encoding="utf-8")
    return 0
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_recheck_decision_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_rollout_recheck_decision.py tests/test_btst_momentum_rollout_recheck_decision_script.py
git commit -m "Add momentum rollout recheck decision"
```

---

### Task 4: Run the full rollout recheck verification flow

**Files:**
- Verify reference only: `scripts/btst_momentum_rollout_recheck_pack.py`
- Verify reference only: `scripts/btst_momentum_rollout_recheck_comparison.py`
- Verify reference only: `scripts/btst_momentum_rollout_recheck_decision.py`
- Verify reference only: `data/reports/btst_momentum_rerun_rollout_pack.json`
- Verify reference only: `/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json`
- Test: `tests/test_btst_momentum_rollout_recheck_pack_script.py`
- Test: `tests/test_btst_momentum_rollout_recheck_comparison_script.py`
- Test: `tests/test_btst_momentum_rollout_recheck_decision_script.py`

- [ ] **Step 1: Run the focused rollout recheck test suite**

Run:

```bash
uv run pytest \
  tests/test_btst_momentum_rollout_recheck_pack_script.py \
  tests/test_btst_momentum_rollout_recheck_comparison_script.py \
  tests/test_btst_momentum_rollout_recheck_decision_script.py -q
```

Expected: PASS with all rollout recheck tests green.

- [ ] **Step 2: Generate the rollout recheck artifacts**

Run:

```bash
uv run python scripts/btst_momentum_rollout_recheck_pack.py \
  --rerun-pack-json data/reports/btst_momentum_rerun_rollout_pack.json \
  --rerun-recommendation-json data/reports/btst_momentum_rerun_rollout_recommendation.json \
  --manifest-json data/reports/btst_latest_optimized_profile.json \
  --output-json data/reports/btst_momentum_rollout_recheck_pack.json \
  --output-md data/reports/btst_momentum_rollout_recheck_pack.md

uv run python scripts/btst_momentum_rollout_recheck_comparison.py \
  --rollout-pack-json data/reports/btst_momentum_rollout_recheck_pack.json \
  --source-json /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json \
  --output-json data/reports/btst_momentum_rollout_recheck_comparison.json \
  --output-md data/reports/btst_momentum_rollout_recheck_comparison.md

uv run python scripts/btst_momentum_rollout_recheck_decision.py \
  --comparison-json data/reports/btst_momentum_rollout_recheck_comparison.json \
  --output-json data/reports/btst_momentum_rollout_recheck_decision.json \
  --output-md data/reports/btst_momentum_rollout_recheck_decision.md
```

Expected: three JSON/Markdown artifacts written under `data/reports/`.

- [ ] **Step 3: Inspect the governed live outcome**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("data/reports/btst_momentum_rollout_recheck_decision.json").read_text(encoding="utf-8"))
print({
    "action": payload["action"],
    "release_posture": payload["release_posture"],
    "winner_trial_index": payload["winner"]["trial_index"],
    "blocker_count": len(payload["blockers"]),
})
PY
```

Expected: a governed outcome for winner `602`; likely `retain_hold` unless both win-rate and payoff evidence clear without blockers.

- [ ] **Step 4: Commit the implementation**

```bash
git add \
  scripts/btst_momentum_rollout_recheck_pack.py \
  scripts/btst_momentum_rollout_recheck_comparison.py \
  scripts/btst_momentum_rollout_recheck_decision.py \
  tests/test_btst_momentum_rollout_recheck_pack_script.py \
  tests/test_btst_momentum_rollout_recheck_comparison_script.py \
  tests/test_btst_momentum_rollout_recheck_decision_script.py
git commit -m "Add momentum rollout recheck pipeline"
```
