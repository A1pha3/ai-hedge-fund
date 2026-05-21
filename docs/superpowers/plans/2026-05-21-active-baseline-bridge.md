# Active Baseline Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a governed active-baseline bridge that lets the rollout recheck compare winner `trial_index=602` against the actual active runtime `btst_precision_v2` without publishing `btst_latest_optimized_profile.json`.

**Architecture:** Add one new input-only snapshot script that freezes the active runtime identity from the live `session_summary.json`, one new baseline-bridge script that converts `btst_v2_objective_alignment_primary.json` into a fail-closed baseline artifact, then extend the existing rollout pack/comparison scripts to consume those artifacts while preserving all existing guardrails and decision logic. Keep the chain narrow: winner/challengers stay unchanged, the decision script stays unchanged, and the final replay either resumes the blocked rollout decision or fails closed with a narrower measurement blocker.

**Tech Stack:** Python 3.11/3.12, existing `scripts/` CLI pattern, JSON/Markdown artifacts under `data/reports/`, pytest, existing rollout recheck scripts, existing optimized-profile manifest contract.

---

## Planned file structure

- Create: `scripts/btst_momentum_active_baseline_snapshot.py`
  - Read the live `session_summary.json`, require a valid `optimization_profile_resolution`, and emit an input-only active-baseline snapshot artifact.
- Create: `tests/test_btst_momentum_active_baseline_snapshot_script.py`
  - Verify snapshot creation, fail-closed missing-runtime handling, and CLI output writing.
- Modify: `scripts/btst_momentum_rollout_recheck_pack.py`
  - Add support for `--active-baseline-json` so the pack can consume a governed snapshot instead of a published manifest.
- Modify: `tests/test_btst_momentum_rollout_recheck_pack_script.py`
  - Verify snapshot-based pack builds and preserve the current manifest-based behavior.
- Create: `scripts/btst_momentum_active_baseline_bridge.py`
  - Read the snapshot plus `data/reports/btst_v2_objective_alignment_primary.json`, locate the exact BTST-v2 evidence row that matches the active profile overrides, and emit a normalized baseline artifact.
- Create: `tests/test_btst_momentum_active_baseline_bridge_script.py`
  - Verify exact-profile matching, missing-metric fail-closed behavior, and CLI output writing.
- Modify: `scripts/btst_momentum_rollout_recheck_comparison.py`
  - Accept `--baseline-bridge-json` and use it only when the source `comparison_summary` lacks the active baseline entry.
- Modify: `tests/test_btst_momentum_rollout_recheck_comparison_script.py`
  - Verify the new bridge path and preserve the current direct-source path.
- Verify reference only: `scripts/btst_momentum_rollout_recheck_decision.py`
  - Consume the merged comparison unchanged.
- Verify reference only: `data/reports/paper_trading_20260512_20260512_live_m2_7_short_trade_only_20260513_plan_optimized_verify/session_summary.json`
  - Current blocked live runtime source of truth. It contains `optimization_profile_resolution.profile_name = btst_precision_v2`.
- Verify reference only: `data/reports/btst_v2_objective_alignment_primary.json`
  - Baseline evidence source. The current active profile overrides match `core_btst`.
- Verify reference only: `data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json`
  - Winner `602` metrics source. `comparison_summary` and `baseline_verdicts` currently stop at `default` and `momentum_optimized`.

---

### Task 1: Add the active baseline snapshot artifact

**Files:**
- Create: `scripts/btst_momentum_active_baseline_snapshot.py`
- Create: `tests/test_btst_momentum_active_baseline_snapshot_script.py`
- Verify reference only: `data/reports/paper_trading_20260512_20260512_live_m2_7_short_trade_only_20260513_plan_optimized_verify/session_summary.json`
- Test: `tests/test_btst_momentum_active_baseline_snapshot_script.py`

- [ ] **Step 1: Write the failing snapshot tests**

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.btst_momentum_active_baseline_snapshot as snapshot


def test_build_active_baseline_snapshot_reads_optimization_profile_resolution() -> None:
    payload = snapshot.build_active_baseline_snapshot(
        session_summary={
            "optimization_profile_resolution": {
                "mode": "optimized",
                "profile_name": "btst_precision_v2",
                "profile_overrides": {"select_threshold": 0.34},
                "source_type": "approved_btst_research_backfill",
                "source_path": "/tmp/btst_v2_objective_alignment_primary.json",
                "validated_by": "objective_alignment_primary",
                "trade_date": None,
                "status": "ready",
                "fallback_reason": None,
                "manifest_path": "/tmp/btst_latest_optimized_profile.json",
            }
        }
    )

    assert payload["profile_name"] == "btst_precision_v2"
    assert payload["source_path"] == "/tmp/btst_v2_objective_alignment_primary.json"
    assert payload["release_posture"] == "hold"
    assert payload["guardrails"] == ["no_manifest_publication", "no_btst_skill_promotion"]
    assert payload["fail_closed"] is True


def test_build_active_baseline_snapshot_fails_closed_without_optimization_profile_resolution() -> None:
    with pytest.raises(SystemExit, match="optimization_profile_resolution"):
        snapshot.build_active_baseline_snapshot(session_summary={"short_trade_target_profile_name": "btst_precision_v2"})


def test_main_writes_active_baseline_snapshot_outputs(tmp_path: Path) -> None:
    session_summary_json = tmp_path / "session_summary.json"
    output_json = tmp_path / "active_baseline.json"
    output_md = tmp_path / "active_baseline.md"
    session_summary_json.write_text(
        json.dumps(
            {
                "optimization_profile_resolution": {
                    "mode": "optimized",
                    "profile_name": "btst_precision_v2",
                    "profile_overrides": {"select_threshold": 0.34},
                    "source_type": "approved_btst_research_backfill",
                    "source_path": "/tmp/btst_v2_objective_alignment_primary.json",
                    "validated_by": "objective_alignment_primary",
                    "trade_date": None,
                    "status": "ready",
                    "fallback_reason": None,
                    "manifest_path": "/tmp/btst_latest_optimized_profile.json",
                }
            }
        ),
        encoding="utf-8",
    )

    result = snapshot.main(
        [
            "--session-summary-json",
            str(session_summary_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["profile_name"] == "btst_precision_v2"
    assert output_md.exists()
```

- [ ] **Step 2: Run the snapshot test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_active_baseline_snapshot_script.py -v
```

Expected: FAIL with import or attribute errors because the snapshot script does not exist yet.

- [ ] **Step 3: Write the minimal snapshot implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

GUARDRAILS = ("no_manifest_publication", "no_btst_skill_promotion")
DEFAULT_SESSION_SUMMARY_JSON = Path(
    "data/reports/paper_trading_20260512_20260512_live_m2_7_short_trade_only_20260513_plan_optimized_verify/session_summary.json"
)
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_active_baseline_snapshot.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_active_baseline_snapshot.md")


def _require_object(name: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return dict(payload)


def _require_non_empty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{name} must be a non-empty string.")
    return value.strip()


def build_active_baseline_snapshot(*, session_summary: dict[str, object]) -> dict[str, object]:
    normalized_summary = _require_object("session_summary", session_summary)
    optimization_profile_resolution = _require_object(
        "optimization_profile_resolution", normalized_summary.get("optimization_profile_resolution")
    )
    if _require_non_empty_string("optimization_profile_resolution.mode", optimization_profile_resolution.get("mode")) != "optimized":
        raise SystemExit("optimization_profile_resolution.mode must be optimized.")
    if _require_non_empty_string("optimization_profile_resolution.status", optimization_profile_resolution.get("status")) != "ready":
        raise SystemExit("optimization_profile_resolution.status must be ready.")

    profile_name = _require_non_empty_string("optimization_profile_resolution.profile_name", optimization_profile_resolution.get("profile_name"))
    source_type = _require_non_empty_string("optimization_profile_resolution.source_type", optimization_profile_resolution.get("source_type"))
    source_path = _require_non_empty_string("optimization_profile_resolution.source_path", optimization_profile_resolution.get("source_path"))
    validated_by = _require_non_empty_string("optimization_profile_resolution.validated_by", optimization_profile_resolution.get("validated_by"))
    profile_overrides = _require_object("optimization_profile_resolution.profile_overrides", optimization_profile_resolution.get("profile_overrides"))

    if optimization_profile_resolution.get("fallback_reason") is not None:
        raise SystemExit("optimization_profile_resolution must not contain a fallback_reason.")

    return {
        "profile_name": profile_name,
        "profile_overrides": profile_overrides,
        "source_type": source_type,
        "source_path": source_path,
        "validated_by": validated_by,
        "trade_date": optimization_profile_resolution.get("trade_date"),
        "manifest_path": _require_non_empty_string("optimization_profile_resolution.manifest_path", optimization_profile_resolution.get("manifest_path")),
        "release_posture": "hold",
        "guardrails": list(GUARDRAILS),
        "fail_closed": True,
    }


def render_active_baseline_snapshot_markdown(payload: dict[str, object]) -> str:
    return "\n".join(
        [
            "# Active Baseline Snapshot",
            "",
            f"- profile_name: `{payload['profile_name']}`",
            f"- source_type: `{payload['source_type']}`",
            f"- source_path: `{payload['source_path']}`",
            f"- validated_by: `{payload['validated_by']}`",
            f"- release_posture: `{payload['release_posture']}`",
            f"- fail_closed: {payload['fail_closed']}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the governed active baseline snapshot.")
    parser.add_argument("--session-summary-json", default=str(DEFAULT_SESSION_SUMMARY_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    session_summary = json.loads(Path(args.session_summary_json).read_text(encoding="utf-8"))
    payload = build_active_baseline_snapshot(session_summary=_require_object("session_summary", session_summary))
    Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output_md).write_text(render_active_baseline_snapshot_markdown(payload), encoding="utf-8")
    return 0
```

- [ ] **Step 4: Run the snapshot test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_active_baseline_snapshot_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_active_baseline_snapshot.py tests/test_btst_momentum_active_baseline_snapshot_script.py
git commit -m "Add active baseline snapshot"
```

---

### Task 2: Teach the rollout pack to consume a governed active baseline snapshot

**Files:**
- Modify: `scripts/btst_momentum_rollout_recheck_pack.py`
- Modify: `tests/test_btst_momentum_rollout_recheck_pack_script.py`
- Verify reference only: `scripts/btst_momentum_active_baseline_snapshot.py`
- Test: `tests/test_btst_momentum_rollout_recheck_pack_script.py`

- [ ] **Step 1: Write the failing pack-extension tests**

```python
def test_build_rollout_recheck_pack_accepts_active_baseline_snapshot() -> None:
    payload = recheck_pack.build_momentum_rollout_recheck_pack(
        rerun_pack={
            "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
            "challengers": [],
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "dominant_family": "cross_window_stability",
            "missing_theme_exposure_window_count": 2,
            "fail_closed": True,
        },
        rerun_recommendation={
            "action": "advance_rollout_recheck",
            "release_posture": "hold",
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "dominant_family": "cross_window_stability",
            "missing_theme_exposure_window_count": 2,
            "fail_closed": True,
        },
        active_baseline_snapshot={
            "profile_name": "btst_precision_v2",
            "profile_overrides": {"select_threshold": 0.34},
            "source_type": "approved_btst_research_backfill",
            "source_path": "/tmp/btst_v2_objective_alignment_primary.json",
            "validated_by": "objective_alignment_primary",
            "manifest_path": "/tmp/btst_latest_optimized_profile.json",
            "release_posture": "hold",
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "fail_closed": True,
        },
    )

    assert payload["active_baseline"]["profile_name"] == "btst_precision_v2"


def test_build_rollout_recheck_pack_rejects_snapshot_guardrail_drift() -> None:
    with pytest.raises(SystemExit, match="active_baseline_snapshot.guardrails"):
        recheck_pack.build_momentum_rollout_recheck_pack(
            rerun_pack={
                "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "challengers": [],
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            rerun_recommendation={
                "action": "advance_rollout_recheck",
                "release_posture": "hold",
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
                "fail_closed": True,
            },
            active_baseline_snapshot={
                "profile_name": "btst_precision_v2",
                "profile_overrides": {"select_threshold": 0.34},
                "source_type": "approved_btst_research_backfill",
                "source_path": "/tmp/btst_v2_objective_alignment_primary.json",
                "validated_by": "objective_alignment_primary",
                "manifest_path": "/tmp/btst_latest_optimized_profile.json",
                "release_posture": "hold",
                "guardrails": ["no_manifest_publication", "unexpected_guardrail"],
                "fail_closed": True,
            },
        )


def test_main_prefers_active_baseline_snapshot_over_manifest(tmp_path: Path) -> None:
    rerun_pack_json = tmp_path / "rerun_pack.json"
    rerun_recommendation_json = tmp_path / "rerun_recommendation.json"
    active_baseline_json = tmp_path / "active_baseline.json"
    output_json = tmp_path / "rollout_pack.json"
    output_md = tmp_path / "rollout_pack.md"

    rerun_pack_json.write_text(json.dumps({"winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0}, "challengers": [], "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"], "release_posture": "hold", "dominant_family": "cross_window_stability", "missing_theme_exposure_window_count": 2, "fail_closed": True}), encoding="utf-8")
    rerun_recommendation_json.write_text(json.dumps({"action": "advance_rollout_recheck", "release_posture": "hold", "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"], "dominant_family": "cross_window_stability", "missing_theme_exposure_window_count": 2, "fail_closed": True}), encoding="utf-8")
    active_baseline_json.write_text(json.dumps({"profile_name": "btst_precision_v2", "profile_overrides": {"select_threshold": 0.34}, "source_type": "approved_btst_research_backfill", "source_path": "/tmp/btst_v2_objective_alignment_primary.json", "validated_by": "objective_alignment_primary", "manifest_path": "/tmp/btst_latest_optimized_profile.json", "release_posture": "hold", "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"], "fail_closed": True}), encoding="utf-8")

    result = recheck_pack.main(
        [
            "--rerun-pack-json",
            str(rerun_pack_json),
            "--rerun-recommendation-json",
            str(rerun_recommendation_json),
            "--active-baseline-json",
            str(active_baseline_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["active_baseline"]["profile_name"] == "btst_precision_v2"
```

- [ ] **Step 2: Run the pack test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_recheck_pack_script.py -v
```

Expected: FAIL because `build_momentum_rollout_recheck_pack()` and `main()` do not accept `active_baseline_snapshot` / `--active-baseline-json` yet.

- [ ] **Step 3: Extend the pack implementation with snapshot support**

```python
def _require_governed_active_baseline_snapshot(payload: Any) -> dict[str, Any]:
    snapshot = _require_object("active_baseline_snapshot", payload)
    if _require_string("active_baseline_snapshot.release_posture", snapshot.get("release_posture")) != "hold":
        raise SystemExit("active_baseline_snapshot.release_posture must be hold.")
    if _require_list("active_baseline_snapshot.guardrails", snapshot.get("guardrails")) != list(GUARDRAILS):
        raise SystemExit("active_baseline_snapshot.guardrails must preserve no_manifest_publication and no_btst_skill_promotion exactly.")
    if snapshot.get("fail_closed") is not True:
        raise SystemExit("active_baseline_snapshot.fail_closed must be true.")
    return snapshot


def build_momentum_rollout_recheck_pack(
    *,
    rerun_pack: dict[str, object],
    rerun_recommendation: dict[str, object],
    baseline_resolution: dict[str, object] | None = None,
    active_baseline_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized_pack = _require_object("rerun_pack", rerun_pack)
    normalized_recommendation = _require_object("rerun_recommendation", rerun_recommendation)

    if active_baseline_snapshot is not None:
        active_baseline = _require_governed_active_baseline_snapshot(active_baseline_snapshot)
    else:
        normalized_baseline = _require_object("baseline_resolution", baseline_resolution)
        if str(normalized_baseline.get("mode") or "").strip() != "optimized" or str(normalized_baseline.get("status") or "").strip() != "ready":
            raise SystemExit("baseline_resolution must be resolved to an optimized profile.")
        if normalized_baseline.get("fallback_reason") is not None:
            raise SystemExit("baseline_resolution must be resolved to an optimized profile.")
        active_baseline = normalized_baseline

    return {
        "winner": winner,
        "challengers": challengers,
        "active_baseline": active_baseline,
        "guardrails": list(GUARDRAILS),
        "release_posture": "hold",
        "dominant_family": str(normalized_pack.get("dominant_family") or "").strip(),
        "missing_theme_exposure_window_count": _require_non_negative_int(
            "missing_theme_exposure_window_count", normalized_pack.get("missing_theme_exposure_window_count")
        ),
        "fail_closed": True,
    }


parser.add_argument("--active-baseline-json", default=None)
active_baseline_snapshot = None
if args.active_baseline_json:
    active_baseline_snapshot = _require_object(
        "active_baseline_snapshot", _load_json_file(Path(args.active_baseline_json), label="active baseline snapshot")
    )
else:
    baseline_resolution = resolve_btst_optimized_profile_manifest(args.manifest_json)
```

- [ ] **Step 4: Run the pack test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_recheck_pack_script.py -v
```

Expected: PASS with the existing regressions plus the new snapshot-path coverage.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_rollout_recheck_pack.py tests/test_btst_momentum_rollout_recheck_pack_script.py
git commit -m "Add active baseline snapshot path"
```

---

### Task 3: Add the BTST-v2 baseline metrics bridge artifact

**Files:**
- Create: `scripts/btst_momentum_active_baseline_bridge.py`
- Create: `tests/test_btst_momentum_active_baseline_bridge_script.py`
- Verify reference only: `data/reports/btst_v2_objective_alignment_primary.json`
- Test: `tests/test_btst_momentum_active_baseline_bridge_script.py`

- [ ] **Step 1: Write the failing bridge tests**

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.btst_momentum_active_baseline_bridge as bridge


def test_build_active_baseline_bridge_extracts_matching_btst_metrics() -> None:
    payload = bridge.build_active_baseline_bridge(
        active_baseline_snapshot={
            "profile_name": "btst_precision_v2",
            "profile_overrides": {
                "near_miss_rank_cap_ratio": 0.3,
                "near_miss_threshold": 0.26,
                "select_threshold": 0.34,
                "selected_rank_cap_ratio": 0.16,
                "selected_rank_cap_relief_close_strength_max": 1.0,
                "selected_rank_cap_relief_rank_buffer_ratio": 0.003,
                "selected_rank_cap_relief_require_confirmed_breakout": 1,
                "selected_rank_cap_relief_require_t_plus_2_candidate": 0,
                "selected_rank_cap_relief_score_margin_min": 0.0,
                "selected_rank_cap_relief_sector_resonance_min": 0.0,
            },
            "source_type": "approved_btst_research_backfill",
            "source_path": "/tmp/btst_v2_objective_alignment_primary.json",
            "validated_by": "objective_alignment_primary",
            "release_posture": "hold",
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "fail_closed": True,
        },
        source_report={
            "extended_universe_btst": {
                "objective": "btst",
                "best_params": {"selected_rank_cap_ratio": 0.14},
                "best_metrics": {"next_close_positive_rate": 0.46, "next_close_payoff_ratio": 3.42, "next_close_expectancy": 0.007, "window_coverage": 1.0, "window_count": 7},
            },
            "core_btst": {
                "objective": "btst",
                "best_params": {
                    "near_miss_rank_cap_ratio": 0.3,
                    "near_miss_threshold": 0.26,
                    "select_threshold": 0.34,
                    "selected_rank_cap_ratio": 0.16,
                    "selected_rank_cap_relief_close_strength_max": 1.0,
                    "selected_rank_cap_relief_rank_buffer_ratio": 0.003,
                    "selected_rank_cap_relief_require_confirmed_breakout": 1,
                    "selected_rank_cap_relief_require_t_plus_2_candidate": 0,
                    "selected_rank_cap_relief_score_margin_min": 0.0,
                    "selected_rank_cap_relief_sector_resonance_min": 0.0,
                },
                "best_metrics": {
                    "next_close_positive_rate": 0.61332,
                    "next_close_payoff_ratio": 1.64004,
                    "next_close_expectancy": 0.01516,
                    "window_coverage": 1.0,
                    "window_count": 5,
                    "max_drawdown": -0.03218,
                },
            },
        },
    )

    assert payload["baseline_name"] == "btst_precision_v2"
    assert payload["report_key"] == "core_btst"
    assert payload["baseline_metrics"]["next_close_positive_rate"] == 0.61332
    assert payload["blockers"] == []


def test_build_active_baseline_bridge_fails_closed_when_required_metrics_are_missing() -> None:
    with pytest.raises(SystemExit, match="best_metrics.next_close_payoff_ratio"):
        bridge.build_active_baseline_bridge(
            active_baseline_snapshot={
                "profile_name": "btst_precision_v2",
                "profile_overrides": {"select_threshold": 0.34},
                "source_type": "approved_btst_research_backfill",
                "source_path": "/tmp/btst_v2_objective_alignment_primary.json",
                "validated_by": "objective_alignment_primary",
                "release_posture": "hold",
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "fail_closed": True,
            },
            source_report={
                "core_btst": {
                    "objective": "btst",
                    "best_params": {"select_threshold": 0.34},
                    "best_metrics": {"next_close_positive_rate": 0.61332, "window_count": 5},
                }
            },
        )


def test_main_writes_active_baseline_bridge_outputs(tmp_path: Path) -> None:
    active_baseline_json = tmp_path / "active_baseline.json"
    source_json = tmp_path / "btst_v2.json"
    output_json = tmp_path / "bridge.json"
    output_md = tmp_path / "bridge.md"

    active_baseline_json.write_text(json.dumps({"profile_name": "btst_precision_v2", "profile_overrides": {"select_threshold": 0.34}, "source_type": "approved_btst_research_backfill", "source_path": str(source_json), "validated_by": "objective_alignment_primary", "release_posture": "hold", "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"], "fail_closed": True}), encoding="utf-8")
    source_json.write_text(json.dumps({"core_btst": {"objective": "btst", "best_params": {"select_threshold": 0.34}, "best_metrics": {"next_close_positive_rate": 0.61332, "next_close_payoff_ratio": 1.64004, "next_close_expectancy": 0.01516, "window_coverage": 1.0, "window_count": 5, "max_drawdown": -0.03218}}}), encoding="utf-8")

    result = bridge.main(
        [
            "--active-baseline-json",
            str(active_baseline_json),
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
    assert data["report_key"] == "core_btst"
    assert output_md.exists()
```

- [ ] **Step 2: Run the bridge test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_active_baseline_bridge_script.py -v
```

Expected: FAIL with import or attribute errors because the bridge script does not exist yet.

- [ ] **Step 3: Write the minimal bridge implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

GUARDRAILS = ("no_manifest_publication", "no_btst_skill_promotion")
DEFAULT_ACTIVE_BASELINE_JSON = Path("data/reports/btst_momentum_active_baseline_snapshot.json")
DEFAULT_SOURCE_JSON = Path("data/reports/btst_v2_objective_alignment_primary.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_momentum_active_baseline_bridge.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_momentum_active_baseline_bridge.md")
REQUIRED_METRICS = (
    "next_close_positive_rate",
    "next_close_payoff_ratio",
    "next_close_expectancy",
    "window_coverage",
    "window_count",
    "max_drawdown",
)


def _require_object(name: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return dict(payload)


def _require_list(name: str, payload: Any) -> list[Any]:
    if not isinstance(payload, list):
        raise SystemExit(f"{name} must be a JSON list.")
    return list(payload)


def _require_non_empty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{name} must be a non-empty string.")
    return value.strip()


def _matching_btst_rows(source_report: dict[str, Any], profile_overrides: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    matches: list[tuple[str, dict[str, Any]]] = []
    for report_key, report_value in source_report.items():
        if not isinstance(report_value, dict):
            continue
        if report_value.get("objective") != "btst":
            continue
        if report_value.get("best_params") == profile_overrides:
            matches.append((str(report_key), report_value))
    return matches


def build_active_baseline_bridge(*, active_baseline_snapshot: dict[str, object], source_report: dict[str, object]) -> dict[str, object]:
    snapshot = _require_object("active_baseline_snapshot", active_baseline_snapshot)
    if _require_list("active_baseline_snapshot.guardrails", snapshot.get("guardrails")) != list(GUARDRAILS):
        raise SystemExit("active_baseline_snapshot.guardrails must preserve no_manifest_publication and no_btst_skill_promotion exactly.")
    if snapshot.get("fail_closed") is not True:
        raise SystemExit("active_baseline_snapshot.fail_closed must be true.")

    matches = _matching_btst_rows(_require_object("source_report", source_report), _require_object("profile_overrides", snapshot.get("profile_overrides")))
    if len(matches) != 1:
        raise SystemExit("source_report must contain exactly one btst row whose best_params match the active baseline profile_overrides.")
    report_key, report_payload = matches[0]
    best_metrics = _require_object(f"{report_key}.best_metrics", report_payload.get("best_metrics"))
    baseline_metrics = {metric_name: best_metrics.get(metric_name) for metric_name in REQUIRED_METRICS}
    for metric_name, metric_value in baseline_metrics.items():
        if metric_value is None:
            raise SystemExit(f"{report_key}.best_metrics.{metric_name} must be present.")

    return {
        "baseline_name": _require_non_empty_string("active_baseline_snapshot.profile_name", snapshot.get("profile_name")),
        "report_key": report_key,
        "baseline_metrics": baseline_metrics,
        "source_path": _require_non_empty_string("active_baseline_snapshot.source_path", snapshot.get("source_path")),
        "validated_by": _require_non_empty_string("active_baseline_snapshot.validated_by", snapshot.get("validated_by")),
        "release_posture": "hold",
        "guardrails": list(GUARDRAILS),
        "blockers": [],
        "fail_closed": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the BTST-v2 active baseline bridge artifact.")
    parser.add_argument("--active-baseline-json", default=str(DEFAULT_ACTIVE_BASELINE_JSON))
    parser.add_argument("--source-json", default=str(DEFAULT_SOURCE_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args(argv)

    active_baseline_snapshot = json.loads(Path(args.active_baseline_json).read_text(encoding="utf-8"))
    source_report = json.loads(Path(args.source_json).read_text(encoding="utf-8"))
    payload = build_active_baseline_bridge(
        active_baseline_snapshot=_require_object("active_baseline_snapshot", active_baseline_snapshot),
        source_report=_require_object("source_report", source_report),
    )
    Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output_md).write_text(
        "\n".join(
            [
                "# Active Baseline Bridge",
                "",
                f"- baseline_name: `{payload['baseline_name']}`",
                f"- report_key: `{payload['report_key']}`",
                f"- source_path: `{payload['source_path']}`",
                f"- validated_by: `{payload['validated_by']}`",
                f"- release_posture: `{payload['release_posture']}`",
                f"- fail_closed: {payload['fail_closed']}",
            ]
        ),
        encoding="utf-8",
    )
    return 0
```

- [ ] **Step 4: Run the bridge test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_active_baseline_bridge_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_active_baseline_bridge.py tests/test_btst_momentum_active_baseline_bridge_script.py
git commit -m "Add active baseline bridge"
```

---

### Task 4: Merge the bridged baseline into the rollout comparison artifact

**Files:**
- Modify: `scripts/btst_momentum_rollout_recheck_comparison.py`
- Modify: `tests/test_btst_momentum_rollout_recheck_comparison_script.py`
- Verify reference only: `scripts/btst_momentum_rollout_recheck_decision.py`
- Test: `tests/test_btst_momentum_rollout_recheck_comparison_script.py`

- [ ] **Step 1: Write the failing comparison-bridge tests**

```python
def test_build_rollout_recheck_comparison_uses_baseline_bridge_when_source_lacks_active_baseline() -> None:
    payload = comparison.build_momentum_rollout_recheck_comparison(
        rollout_pack={
            "winner": {"trial_index": 602},
            "challengers": [{"trial_index": 1226}],
            "active_baseline": {"profile_name": "btst_precision_v2"},
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "release_posture": "hold",
            "fail_closed": True,
        },
        source_report={
            "results": [
                {"trial_index": 602, "metrics": {"next_close_positive_rate": 0.5376712903562031, "next_close_payoff_ratio": 1.9198038674033149, "window_count": 24}},
                {"trial_index": 1226, "metrics": {"next_close_positive_rate": 0.52, "next_close_payoff_ratio": 1.70, "window_count": 24}},
            ],
            "comparison_summary": {"momentum_optimized": {}},
            "rollout_recommendation_details": {"baseline_verdicts": {"momentum_optimized": {"status": "blocked", "blockers": []}}},
        },
        baseline_bridge={
            "baseline_name": "btst_precision_v2",
            "report_key": "core_btst",
            "baseline_metrics": {
                "next_close_positive_rate": 0.61332,
                "next_close_payoff_ratio": 1.64004,
                "next_close_expectancy": 0.01516,
                "window_coverage": 1.0,
                "window_count": 5,
                "max_drawdown": -0.03218,
            },
            "release_posture": "hold",
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
            "blockers": [],
            "fail_closed": True,
        },
    )

    assert payload["winner_vs_active_baseline"]["baseline_name"] == "btst_precision_v2"
    assert payload["winner_vs_active_baseline"]["baseline"]["next_close_payoff_ratio"] == 1.64004
    assert payload["winner_vs_active_baseline"]["next_close_positive_rate_delta"] == pytest.approx(0.5376712903562031 - 0.61332)


def test_build_rollout_recheck_comparison_rejects_mismatched_bridge_name() -> None:
    with pytest.raises(SystemExit, match="baseline_bridge.baseline_name"):
        comparison.build_momentum_rollout_recheck_comparison(
            rollout_pack={
                "winner": {"trial_index": 602},
                "challengers": [],
                "active_baseline": {"profile_name": "btst_precision_v2"},
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "release_posture": "hold",
                "fail_closed": True,
            },
            source_report={"results": [{"trial_index": 602, "metrics": {"next_close_positive_rate": 0.5377, "next_close_payoff_ratio": 1.9198, "window_count": 24}}], "comparison_summary": {}, "rollout_recommendation_details": {"baseline_verdicts": {}}},
            baseline_bridge={
                "baseline_name": "default",
                "report_key": "core_btst",
                "baseline_metrics": {"next_close_positive_rate": 0.61332, "next_close_payoff_ratio": 1.64004, "next_close_expectancy": 0.01516, "window_coverage": 1.0, "window_count": 5, "max_drawdown": -0.03218},
                "release_posture": "hold",
                "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
                "blockers": [],
                "fail_closed": True,
            },
        )
```

- [ ] **Step 2: Run the comparison test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_recheck_comparison_script.py -v
```

Expected: FAIL because `build_momentum_rollout_recheck_comparison()` does not accept `baseline_bridge` yet.

- [ ] **Step 3: Extend the comparison implementation with bridge fallback**

```python
def _require_bridge_metrics(payload: Any) -> dict[str, Any]:
    bridge = _require_object("baseline_bridge", payload)
    if str(bridge.get("release_posture") or "").strip() != "hold":
        raise SystemExit("baseline_bridge.release_posture must be hold.")
    if _require_list("baseline_bridge.guardrails", bridge.get("guardrails")) != ["no_manifest_publication", "no_btst_skill_promotion"]:
        raise SystemExit("baseline_bridge.guardrails must preserve no_manifest_publication and no_btst_skill_promotion exactly.")
    if bridge.get("fail_closed") is not True:
        raise SystemExit("baseline_bridge.fail_closed must be true.")
    baseline_metrics = _require_object("baseline_bridge.baseline_metrics", bridge.get("baseline_metrics"))
    for metric_name in ("next_close_positive_rate", "next_close_payoff_ratio", "window_count"):
        if baseline_metrics.get(metric_name) is None:
            raise SystemExit(f"baseline_bridge.baseline_metrics.{metric_name} must be present.")
    return bridge


def build_momentum_rollout_recheck_comparison(
    *,
    rollout_pack: dict[str, object],
    source_report: dict[str, object],
    baseline_bridge: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized_pack = _require_object("rollout_pack", rollout_pack)
    normalized_source = _require_object("source_report", source_report)
    indexed_results = _index_results(normalized_source.get("results"))

    winner = _require_object("winner", normalized_pack.get("winner"))
    winner_trial_index = _require_non_negative_int("winner trial_index", winner.get("trial_index"))
    winner_result = indexed_results[winner_trial_index]
    winner_metrics = _require_result_metrics("winner metrics", winner_result)
    active_baseline = _require_object("active_baseline", normalized_pack.get("active_baseline"))
    baseline_name = str(active_baseline.get("profile_name") or "").strip()

    comparison_summary = _require_object("comparison_summary", normalized_source.get("comparison_summary"))
    baseline_summary = comparison_summary.get(baseline_name)
    if isinstance(baseline_summary, dict):
        baseline_verdicts = _load_baseline_verdicts(normalized_source)
        baseline_verdict = baseline_verdicts.get(baseline_name)
        if not isinstance(baseline_verdict, dict):
            raise SystemExit("baseline_verdicts must contain the active baseline entry.")
        winner_vs_active_baseline = {
            "baseline_name": baseline_name,
            "candidate": _require_baseline_summary_field(baseline_summary, "candidate"),
            "baseline": _require_baseline_summary_field(baseline_summary, "baseline"),
            "next_close_positive_rate_delta": _require_baseline_summary_field(baseline_summary, "next_close_positive_rate_delta"),
            "next_close_payoff_ratio_delta": _require_baseline_summary_field(baseline_summary, "next_close_payoff_ratio_delta"),
            "blockers": list(baseline_verdict.get("blockers") or []),
        }
    else:
        bridge = _require_bridge_metrics(baseline_bridge)
        if str(bridge.get("baseline_name") or "").strip() != baseline_name:
            raise SystemExit("baseline_bridge.baseline_name must match active_baseline.profile_name.")
        baseline_metrics = _require_object("baseline_bridge.baseline_metrics", bridge.get("baseline_metrics"))
        winner_vs_active_baseline = {
            "baseline_name": baseline_name,
            "candidate": {
                "next_close_positive_rate": winner_metrics["next_close_positive_rate"],
                "next_close_payoff_ratio": winner_metrics["next_close_payoff_ratio"],
                "window_count": winner_metrics["window_count"],
            },
            "baseline": {
                "next_close_positive_rate": baseline_metrics["next_close_positive_rate"],
                "next_close_payoff_ratio": baseline_metrics["next_close_payoff_ratio"],
                "window_count": baseline_metrics["window_count"],
            },
            "next_close_positive_rate_delta": float(winner_metrics["next_close_positive_rate"]) - float(baseline_metrics["next_close_positive_rate"]),
            "next_close_payoff_ratio_delta": float(winner_metrics["next_close_payoff_ratio"]) - float(baseline_metrics["next_close_payoff_ratio"]),
            "blockers": [str(blocker).strip() for blocker in list(bridge.get("blockers") or []) if str(blocker).strip()],
        }


parser.add_argument("--baseline-bridge-json", default=None)
baseline_bridge = None
if args.baseline_bridge_json:
    baseline_bridge = _require_object("baseline_bridge", _load_json_file(Path(args.baseline_bridge_json), label="baseline bridge"))
```

- [ ] **Step 4: Run the comparison test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_recheck_comparison_script.py -v
```

Expected: PASS with the current direct-source coverage plus the new bridge fallback coverage.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_rollout_recheck_comparison.py tests/test_btst_momentum_rollout_recheck_comparison_script.py
git commit -m "Bridge active baseline into rollout comparison"
```

---

### Task 5: Verify the bridged rollout recheck chain end-to-end

**Files:**
- Verify reference only: `scripts/btst_momentum_active_baseline_snapshot.py`
- Verify reference only: `scripts/btst_momentum_rollout_recheck_pack.py`
- Verify reference only: `scripts/btst_momentum_active_baseline_bridge.py`
- Verify reference only: `scripts/btst_momentum_rollout_recheck_comparison.py`
- Verify reference only: `scripts/btst_momentum_rollout_recheck_decision.py`
- Verify reference only: `tests/test_btst_momentum_active_baseline_snapshot_script.py`
- Verify reference only: `tests/test_btst_momentum_rollout_recheck_pack_script.py`
- Verify reference only: `tests/test_btst_momentum_active_baseline_bridge_script.py`
- Verify reference only: `tests/test_btst_momentum_rollout_recheck_comparison_script.py`
- Verify reference only: `tests/test_btst_momentum_rollout_recheck_decision_script.py`

- [ ] **Step 1: Run the focused bridge regression suite**

Run:

```bash
uv run pytest \
  tests/test_btst_momentum_active_baseline_snapshot_script.py \
  tests/test_btst_momentum_rollout_recheck_pack_script.py \
  tests/test_btst_momentum_active_baseline_bridge_script.py \
  tests/test_btst_momentum_rollout_recheck_comparison_script.py \
  tests/test_btst_momentum_rollout_recheck_decision_script.py \
  -q
```

Expected: PASS with all bridge-focused and existing rollout-recheck tests green.

- [ ] **Step 2: Generate the active baseline snapshot and baseline bridge artifacts**

Run:

```bash
uv run python scripts/btst_momentum_active_baseline_snapshot.py \
  --session-summary-json data/reports/paper_trading_20260512_20260512_live_m2_7_short_trade_only_20260513_plan_optimized_verify/session_summary.json \
  --output-json data/reports/btst_momentum_active_baseline_snapshot.json \
  --output-md data/reports/btst_momentum_active_baseline_snapshot.md && \
uv run python scripts/btst_momentum_active_baseline_bridge.py \
  --active-baseline-json data/reports/btst_momentum_active_baseline_snapshot.json \
  --source-json data/reports/btst_v2_objective_alignment_primary.json \
  --output-json data/reports/btst_momentum_active_baseline_bridge.json \
  --output-md data/reports/btst_momentum_active_baseline_bridge.md
```

Expected: PASS with both JSON/Markdown artifacts written under `data/reports/`.

- [ ] **Step 3: Replay the blocked rollout chain with the bridge artifacts**

Run:

```bash
uv run python scripts/btst_momentum_rollout_recheck_pack.py \
  --rerun-pack-json data/reports/btst_momentum_rerun_rollout_pack.json \
  --rerun-recommendation-json data/reports/btst_momentum_rerun_rollout_recommendation.json \
  --active-baseline-json data/reports/btst_momentum_active_baseline_snapshot.json \
  --output-json data/reports/btst_momentum_rollout_recheck_pack.json \
  --output-md data/reports/btst_momentum_rollout_recheck_pack.md && \
uv run python scripts/btst_momentum_rollout_recheck_comparison.py \
  --rollout-pack-json data/reports/btst_momentum_rollout_recheck_pack.json \
  --source-json data/reports/param_search_momentum_optimized_apr_may_coarse_v3.json \
  --baseline-bridge-json data/reports/btst_momentum_active_baseline_bridge.json \
  --output-json data/reports/btst_momentum_rollout_recheck_comparison.json \
  --output-md data/reports/btst_momentum_rollout_recheck_comparison.md && \
uv run python scripts/btst_momentum_rollout_recheck_decision.py \
  --comparison-json data/reports/btst_momentum_rollout_recheck_comparison.json \
  --output-json data/reports/btst_momentum_rollout_recheck_decision.json \
  --output-md data/reports/btst_momentum_rollout_recheck_decision.md
```

Expected: PASS with the pack, comparison, and decision artifacts regenerated without publishing `btst_latest_optimized_profile.json`.

- [ ] **Step 4: Inspect the final governed action**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("data/reports/btst_momentum_rollout_recheck_decision.json").read_text(encoding="utf-8"))
assert payload["action"] in {"retain_hold", "ready_for_release_review", "fallback_measurement_repair"}
assert payload["release_posture"] == "hold"
assert payload["guardrails"] == ["no_manifest_publication", "no_btst_skill_promotion"]
print(payload["action"])
PY
```

Expected: prints exactly one governed action. `ready_for_release_review` is acceptable only if both deltas are positive and blockers are empty; otherwise `retain_hold` or `fallback_measurement_repair` is the correct fail-closed outcome.
