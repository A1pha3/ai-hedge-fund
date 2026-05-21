# Trend Continuation Activation-Delta Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explain and repair why `trend_continuation_strength_v3` produces no runtime activation delta versus `trend_continuation_strength_v2`, then only promote the branch if governed validation shows execution-eligible uplift without win-rate / payoff / downside regression.

**Architecture:** Reuse the existing multi-window validation and trend-continuation rollout stack instead of inventing a new BTST pipeline. Add one diagnostics artifact for zero-delta attribution, one narrow calibration runner around the existing `v3` shrink-gate parameters, and then feed those richer artifacts back into the rollout decision so the hold/promote outcome is evidence-first and fail-closed.

**Tech Stack:** Python 3.11/3.12, pytest, repository BTST replay/validation scripts, JSON/Markdown report artifacts under `data/reports/`, Chinese validation docs under `docs/prompt/generate_file/`

---

## File structure and responsibilities

- `scripts/btst_trend_continuation_activation_delta_diagnostics.py`
  - New diagnostics entrypoint/helper that consumes a `btst_multi_window_profile_validation` JSON payload and emits a focused explanation of why `v3` did or did not create runtime activation delta.

- `tests/test_btst_trend_continuation_activation_delta_diagnostics.py`
  - New focused tests for diagnostics classification, summary counts, and CLI output.

- `scripts/btst_trend_continuation_activation_delta_calibration.py`
  - New orchestration script that evaluates a small set of explainable `trend_continuation_strength_v3` shrink-gate override candidates via `analyze_btst_multi_window_profile_validation(...)`.

- `tests/test_btst_trend_continuation_activation_delta_calibration_script.py`
  - New tests for candidate ranking, override propagation, and JSON/Markdown output.

- `scripts/btst_trend_continuation_rollout_helpers.py`
  - Existing rollout helper to extend so activation-delta diagnostics and calibration evidence become explicit blockers / evidence in the final rollout payload.

- `scripts/btst_trend_continuation_rollout_assessment.py`
  - Existing CLI wrapper to extend with an optional diagnostics JSON input and richer persisted output.

- `tests/test_btst_trend_continuation_rollout_helpers.py`
  - Existing test file to extend with new blockers and rendered evidence sections.

- `docs/prompt/generate_file/trend-continuation-activation-delta-governance-2026-05-21.md`
  - Write only if the calibrated candidate clears the rollout gate and is validated for BTST report usage.

- `skills/ai-hedge-fund-btst/SKILL.md`
  - Update only if the final rollout assessment switches from `hold` to `promote`.

---

### Task 1: Add the activation-delta diagnostics artifact

**Files:**
- Create: `scripts/btst_trend_continuation_activation_delta_diagnostics.py`
- Create: `tests/test_btst_trend_continuation_activation_delta_diagnostics.py`
- Test: `tests/test_btst_trend_continuation_activation_delta_diagnostics.py`

- [ ] **Step 1: Write the failing diagnostics tests**

```python
from scripts.btst_trend_continuation_activation_delta_diagnostics import (
    build_trend_continuation_activation_delta_diagnostics,
)


def _analysis_with_rows(*rows: dict) -> dict:
    return {
        "baseline_profile": "trend_continuation_strength_v2",
        "variant_profile": "trend_continuation_strength_v3",
        "report_dir_count": len(rows),
        "rows": list(rows),
    }


def test_build_activation_delta_diagnostics_summarizes_zero_delta_reasons() -> None:
    payload = build_trend_continuation_activation_delta_diagnostics(
        _analysis_with_rows(
            {
                "report_label": "window_a",
                "runtime_activation_attribution": {
                    "selected_count_delta": 0,
                    "near_miss_count_delta": 0,
                    "execution_eligible_count_delta": 0,
                    "zero_delta_reason": "profile_variant_without_runtime_activation_delta",
                    "watchlist_shrink_guard_applied_count": 0,
                    "watchlist_shrink_selected_boundary_overlap_count": 0,
                },
            },
            {
                "report_label": "window_b",
                "runtime_activation_attribution": {
                    "selected_count_delta": 0,
                    "near_miss_count_delta": 0,
                    "execution_eligible_count_delta": 0,
                    "zero_delta_reason": "watchlist_shrink_guard_without_selected_boundary_overlap",
                    "watchlist_shrink_guard_applied_count": 1,
                    "watchlist_shrink_selected_boundary_overlap_count": 0,
                },
            },
        )
    )

    assert payload["report_dir_count"] == 2
    assert payload["zero_delta_reason_counts"] == {
        "profile_variant_without_runtime_activation_delta": 1,
        "watchlist_shrink_guard_without_selected_boundary_overlap": 1,
    }
    assert payload["execution_eligible_positive_window_count"] == 0
    assert payload["dominant_zero_delta_reason"] in payload["zero_delta_reason_counts"]


def test_build_activation_delta_diagnostics_flags_execution_eligible_surface_when_present() -> None:
    payload = build_trend_continuation_activation_delta_diagnostics(
        _analysis_with_rows(
            {
                "report_label": "window_a",
                "runtime_activation_attribution": {
                    "selected_count_delta": 0,
                    "near_miss_count_delta": 1,
                    "execution_eligible_count_delta": 1,
                    "activation_change_labels": ["near_miss_surface", "execution_eligible_surface"],
                    "zero_delta_reason": None,
                    "watchlist_shrink_guard_applied_count": 1,
                    "watchlist_shrink_selected_boundary_overlap_count": 1,
                },
            }
        )
    )

    assert payload["execution_eligible_positive_window_count"] == 1
    assert payload["windows_with_activation_change"] == ["window_a"]
    assert payload["all_windows_zero_delta"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_trend_continuation_activation_delta_diagnostics.py -v
```

Expected: FAIL with `ModuleNotFoundError` or missing symbol `build_trend_continuation_activation_delta_diagnostics`.

- [ ] **Step 3: Add the minimal diagnostics implementation**

```python
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


def build_trend_continuation_activation_delta_diagnostics(analysis: Mapping[str, Any]) -> dict[str, Any]:
    rows = [dict(row) for row in list(analysis.get("rows") or []) if isinstance(row, Mapping)]
    zero_delta_reason_counts: Counter[str] = Counter()
    windows_with_activation_change: list[str] = []
    execution_eligible_positive_window_count = 0
    shrink_guard_applied_window_count = 0
    shrink_boundary_overlap_window_count = 0

    for row in rows:
        label = str(row.get("report_label") or row.get("report_dir") or "")
        attribution = dict(row.get("runtime_activation_attribution") or {})
        zero_delta_reason = str(attribution.get("zero_delta_reason") or "").strip()
        if zero_delta_reason:
            zero_delta_reason_counts[zero_delta_reason] += 1
        if int(attribution.get("execution_eligible_count_delta") or 0) > 0:
            execution_eligible_positive_window_count += 1
        if attribution.get("activation_change_labels"):
            windows_with_activation_change.append(label)
        if int(attribution.get("watchlist_shrink_guard_applied_count") or 0) > 0:
            shrink_guard_applied_window_count += 1
        if int(attribution.get("watchlist_shrink_selected_boundary_overlap_count") or 0) > 0:
            shrink_boundary_overlap_window_count += 1

    dominant_zero_delta_reason = None
    if zero_delta_reason_counts:
        dominant_zero_delta_reason = max(zero_delta_reason_counts.items(), key=lambda item: item[1])[0]

    return {
        "baseline_profile": str(analysis.get("baseline_profile") or "trend_continuation_strength_v2"),
        "candidate_profile": str(analysis.get("variant_profile") or "trend_continuation_strength_v3"),
        "report_dir_count": int(analysis.get("report_dir_count") or len(rows)),
        "zero_delta_reason_counts": dict(zero_delta_reason_counts),
        "dominant_zero_delta_reason": dominant_zero_delta_reason,
        "execution_eligible_positive_window_count": execution_eligible_positive_window_count,
        "windows_with_activation_change": sorted(label for label in windows_with_activation_change if label),
        "shrink_guard_applied_window_count": shrink_guard_applied_window_count,
        "shrink_boundary_overlap_window_count": shrink_boundary_overlap_window_count,
        "all_windows_zero_delta": bool(rows) and len(windows_with_activation_change) == 0,
    }


def render_trend_continuation_activation_delta_diagnostics_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Trend Continuation Activation Delta Diagnostics",
        "",
        f"- baseline_profile: {payload['baseline_profile']}",
        f"- candidate_profile: {payload['candidate_profile']}",
        f"- report_dir_count: {payload['report_dir_count']}",
        f"- all_windows_zero_delta: {payload['all_windows_zero_delta']}",
        f"- dominant_zero_delta_reason: {payload['dominant_zero_delta_reason']}",
        f"- execution_eligible_positive_window_count: {payload['execution_eligible_positive_window_count']}",
        "",
        "## Zero Delta Reasons",
        "",
    ]
    reason_counts = dict(payload.get("zero_delta_reason_counts") or {})
    if reason_counts:
        for key, value in sorted(reason_counts.items()):
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    return "\\n".join(lines).rstrip() + "\\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize why trend continuation validation did or did not create runtime activation delta.")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)

    analysis = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    payload = build_trend_continuation_activation_delta_diagnostics(analysis)

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_trend_continuation_activation_delta_diagnostics_markdown(payload), encoding="utf-8")
    return 0
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_trend_continuation_activation_delta_diagnostics.py -v
```

Expected: PASS with the new diagnostics tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_trend_continuation_activation_delta_diagnostics.py tests/test_btst_trend_continuation_activation_delta_diagnostics.py
git commit -m "feat: add trend activation delta diagnostics"
```

---

### Task 2: Add the controlled `v3` shrink-gate calibration runner

**Files:**
- Create: `scripts/btst_trend_continuation_activation_delta_calibration.py`
- Create: `tests/test_btst_trend_continuation_activation_delta_calibration_script.py`
- Test: `tests/test_btst_trend_continuation_activation_delta_calibration_script.py`

- [ ] **Step 1: Write the failing calibration tests**

```python
import scripts.btst_trend_continuation_activation_delta_calibration as calibration


def test_rank_calibration_candidates_prefers_execution_eligible_activation_then_t1_support() -> None:
    ranked = calibration.rank_calibration_candidates(
        [
            {
                "candidate_name": "tight",
                "diagnostics": {"execution_eligible_positive_window_count": 0, "all_windows_zero_delta": True},
                "analysis": {"variant_supports_t1_count": 0, "mixed_count": 2},
            },
            {
                "candidate_name": "balanced",
                "diagnostics": {"execution_eligible_positive_window_count": 2, "all_windows_zero_delta": False},
                "analysis": {"variant_supports_t1_count": 1, "mixed_count": 1},
            },
        ]
    )

    assert ranked[0]["candidate_name"] == "balanced"


def test_build_candidate_overrides_keeps_scope_inside_v3_shrink_parameters() -> None:
    candidate = calibration.CALIBRATION_CANDIDATES[0]

    assert set(candidate["profile_overrides"].keys()) <= {
        "watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift",
        "watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max",
        "watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max",
        "watchlist_filter_diagnostics_selected_only_shrink_close_strength_max",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_trend_continuation_activation_delta_calibration_script.py -v
```

Expected: FAIL with missing module / missing symbol errors.

- [ ] **Step 3: Add the minimal calibration runner**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_multi_window_profile_validation import analyze_btst_multi_window_profile_validation
from scripts.btst_trend_continuation_activation_delta_diagnostics import (
    build_trend_continuation_activation_delta_diagnostics,
)

CALIBRATION_CANDIDATES = [
    {
        "candidate_name": "lift_0p04",
        "profile_overrides": {
            "watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift": 0.04,
            "watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max": 0.10,
            "watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max": 0.40,
            "watchlist_filter_diagnostics_selected_only_shrink_close_strength_max": 0.58,
        },
    },
    {
        "candidate_name": "lift_0p03_relaxed_close",
        "profile_overrides": {
            "watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift": 0.03,
            "watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max": 0.10,
            "watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max": 0.40,
            "watchlist_filter_diagnostics_selected_only_shrink_close_strength_max": 0.62,
        },
    },
    {
        "candidate_name": "lift_0p03_relaxed_trend",
        "profile_overrides": {
            "watchlist_filter_diagnostics_selected_only_shrink_select_threshold_lift": 0.03,
            "watchlist_filter_diagnostics_selected_only_shrink_catalyst_freshness_max": 0.10,
            "watchlist_filter_diagnostics_selected_only_shrink_trend_acceleration_max": 0.45,
            "watchlist_filter_diagnostics_selected_only_shrink_close_strength_max": 0.58,
        },
    },
]


def rank_calibration_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        results,
        key=lambda item: (
            -(int(dict(item["diagnostics"]).get("execution_eligible_positive_window_count") or 0)),
            -(int(dict(item["analysis"]).get("variant_supports_t1_count") or 0)),
            int(dict(item["analysis"]).get("mixed_count") or 0),
            item["candidate_name"],
        ),
    )


def run_calibration(*, reports_root: str | Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for candidate in CALIBRATION_CANDIDATES:
        analysis = analyze_btst_multi_window_profile_validation(
            reports_root,
            baseline_profile="trend_continuation_strength_v2",
            variant_profile="trend_continuation_strength_v3",
            variant_profile_overrides=dict(candidate["profile_overrides"]),
        )
        diagnostics = build_trend_continuation_activation_delta_diagnostics(analysis)
        results.append(
            {
                "candidate_name": candidate["candidate_name"],
                "profile_overrides": dict(candidate["profile_overrides"]),
                "analysis": analysis,
                "diagnostics": diagnostics,
            }
        )
    ranked = rank_calibration_candidates(results)
    return {
        "baseline_profile": "trend_continuation_strength_v2",
        "candidate_profile": "trend_continuation_strength_v3",
        "ranked_candidates": ranked,
        "best_candidate": ranked[0] if ranked else None,
    }
```

- [ ] **Step 4: Add CLI output coverage**

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a narrow activation-delta calibration grid for trend continuation v3.")
    parser.add_argument("--reports-root", default="data/reports")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)

    payload = run_calibration(reports_root=args.reports_root)

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Trend Continuation Activation Delta Calibration",
        "",
        f"- best_candidate: {dict(payload.get('best_candidate') or {}).get('candidate_name')}",
        "",
        "## Ranked Candidates",
        "",
    ]
    for item in list(payload.get("ranked_candidates") or []):
        diagnostics = dict(item.get("diagnostics") or {})
        analysis = dict(item.get("analysis") or {})
        lines.append(
            f"- {item['candidate_name']}: execution_eligible_positive_window_count={diagnostics.get('execution_eligible_positive_window_count')}, "
            f"variant_supports_t1_count={analysis.get('variant_supports_t1_count')}, mixed_count={analysis.get('mixed_count')}"
        )
    output_md.write_text("\\n".join(lines).rstrip() + "\\n", encoding="utf-8")
    return 0
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_trend_continuation_activation_delta_calibration_script.py -v
```

Expected: PASS with ranking and CLI tests green.

- [ ] **Step 6: Commit**

```bash
git add scripts/btst_trend_continuation_activation_delta_calibration.py tests/test_btst_trend_continuation_activation_delta_calibration_script.py
git commit -m "feat: add trend activation delta calibration runner"
```

---

### Task 3: Feed diagnostics and calibration evidence into the rollout gate

**Files:**
- Modify: `scripts/btst_trend_continuation_rollout_helpers.py`
- Modify: `scripts/btst_trend_continuation_rollout_assessment.py`
- Modify: `tests/test_btst_trend_continuation_rollout_helpers.py`
- Test: `tests/test_btst_trend_continuation_rollout_helpers.py`

- [ ] **Step 1: Write the failing rollout-helper tests**

```python
from scripts.btst_trend_continuation_rollout_helpers import build_trend_continuation_rollout_assessment


def test_build_trend_continuation_rollout_assessment_flags_cosmetic_only_activation_delta() -> None:
    analysis = {
        "baseline_profile": "trend_continuation_strength_v2",
        "variant_profile": "trend_continuation_strength_v3",
        "keep_baseline_count": 0,
        "variant_supports_t1_count": 1,
        "variant_improves_t2_only_count": 0,
        "mixed_count": 1,
        "recommendation": "Mixed windows.",
        "rows": [
            {
                "runtime_activation_attribution": {
                    "execution_eligible_count_delta": 0,
                    "activation_change_labels": ["near_miss_surface"],
                    "zero_delta_reason": None,
                }
            }
        ],
    }
    diagnostics = {
        "all_windows_zero_delta": False,
        "execution_eligible_positive_window_count": 0,
        "dominant_zero_delta_reason": None,
    }

    payload = build_trend_continuation_rollout_assessment(
        analysis,
        activation_delta_diagnostics=diagnostics,
    )

    assert payload["action"] == "hold"
    assert "activation_delta_without_execution_eligible_support" in payload["blockers"]


def test_build_trend_continuation_rollout_assessment_includes_diagnostics_summary() -> None:
    analysis = {
        "baseline_profile": "trend_continuation_strength_v2",
        "variant_profile": "trend_continuation_strength_v3",
        "keep_baseline_count": 0,
        "variant_supports_t1_count": 1,
        "variant_improves_t2_only_count": 0,
        "mixed_count": 0,
        "recommendation": "Promising.",
        "rows": [
            {
                "runtime_activation_attribution": {
                    "execution_eligible_count_delta": 1,
                    "activation_change_labels": ["execution_eligible_surface"],
                    "zero_delta_reason": None,
                }
            }
        ],
    }
    diagnostics = {
        "all_windows_zero_delta": False,
        "execution_eligible_positive_window_count": 1,
        "dominant_zero_delta_reason": None,
    }

    payload = build_trend_continuation_rollout_assessment(
        analysis,
        activation_delta_diagnostics=diagnostics,
    )

    assert payload["activation_delta_diagnostics"]["execution_eligible_positive_window_count"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_btst_trend_continuation_rollout_helpers.py -v
```

Expected: FAIL because `build_trend_continuation_rollout_assessment(...)` does not yet accept `activation_delta_diagnostics` and does not emit the new blocker / summary.

- [ ] **Step 3: Extend the helper with diagnostics-aware blockers**

```python
def build_trend_continuation_rollout_assessment(
    analysis: Mapping[str, Any],
    *,
    baseline_profile: str = "trend_continuation_strength_v2",
    candidate_profile: str = "trend_continuation_strength_v3",
    activation_delta_diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [dict(row) for row in list(analysis.get("rows") or []) if isinstance(row, Mapping)]
    diagnostics = dict(activation_delta_diagnostics or {})
    keep_baseline_count = _coerce_int(analysis.get("keep_baseline_count"))
    variant_supports_t1_count = _coerce_int(analysis.get("variant_supports_t1_count"))
    variant_improves_t2_only_count = _coerce_int(analysis.get("variant_improves_t2_only_count"))
    mixed_count = _coerce_int(analysis.get("mixed_count"))
    execution_eligible_evidence = _build_execution_eligible_evidence(rows)
    runtime_activation_summary = _build_runtime_activation_summary(rows)

    blockers: list[str] = []
    if keep_baseline_count > 0:
        blockers.append("keep_baseline_window_present")
    if variant_supports_t1_count <= 0:
        blockers.append("no_window_supports_t1_edge")
    if not execution_eligible_evidence["has_positive_execution_eligible_evidence"]:
        blockers.append("no_execution_eligible_activation_evidence")
    if runtime_activation_summary["all_windows_zero_delta"]:
        blockers.append("no_runtime_activation_delta")
    if diagnostics and not diagnostics.get("all_windows_zero_delta") and int(diagnostics.get("execution_eligible_positive_window_count") or 0) <= 0:
        blockers.append("activation_delta_without_execution_eligible_support")
    if variant_improves_t2_only_count > 0 and variant_supports_t1_count <= 0:
        blockers.append("t2_only_tradeoff_without_t1_upgrade")

    return {
        "baseline_profile": str(analysis.get("baseline_profile") or baseline_profile),
        "candidate_profile": str(analysis.get("variant_profile") or candidate_profile),
        "report_dir_count": _coerce_int(analysis.get("report_dir_count")),
        "keep_baseline_count": keep_baseline_count,
        "variant_supports_t1_count": variant_supports_t1_count,
        "variant_improves_t2_only_count": variant_improves_t2_only_count,
        "mixed_count": mixed_count,
        "recommendation": str(analysis.get("recommendation") or ""),
        "execution_eligible_evidence": execution_eligible_evidence,
        "runtime_activation_summary": runtime_activation_summary,
        "activation_delta_diagnostics": diagnostics,
        "blockers": blockers,
        "action": "hold" if blockers else "promote",
    }
```

- [ ] **Step 4: Extend the CLI wrapper with an optional diagnostics input**

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a governed rollout assessment for BTST trend continuation strength variants.")
    parser.add_argument("--input-json", required=True, help="Path to the multi-window validation JSON")
    parser.add_argument("--diagnostics-json", default=None, help="Optional activation-delta diagnostics JSON")
    parser.add_argument("--output-json", required=True, help="Path to write the rollout assessment JSON")
    parser.add_argument("--output-md", required=True, help="Path to write the rollout assessment Markdown")
    args = parser.parse_args(argv)

    analysis = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    diagnostics = None
    if args.diagnostics_json:
        diagnostics = json.loads(Path(args.diagnostics_json).read_text(encoding="utf-8"))
    payload = build_trend_continuation_rollout_assessment(
        analysis,
        activation_delta_diagnostics=diagnostics,
    )
    ...
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_btst_trend_continuation_rollout_helpers.py -v
```

Expected: PASS with the new diagnostics-aware rollout behavior covered.

- [ ] **Step 6: Commit**

```bash
git add scripts/btst_trend_continuation_rollout_helpers.py scripts/btst_trend_continuation_rollout_assessment.py tests/test_btst_trend_continuation_rollout_helpers.py
git commit -m "feat: govern trend activation delta rollout"
```

---

### Task 4: Wire post-validation docs and BTST skill updates behind a promotion gate

**Files:**
- Create conditionally: `docs/prompt/generate_file/trend-continuation-activation-delta-governance-2026-05-21.md`
- Modify conditionally: `skills/ai-hedge-fund-btst/SKILL.md`
- Test / verify: final artifact outputs in `data/reports/`

- [ ] **Step 1: Write the Chinese validation note template only if rollout promotes**

```markdown
# 趋势延续 activation-delta 治理验证（2026-05-21）

## 因子/机制原理

- 基线：`trend_continuation_strength_v2`
- 候选：`trend_continuation_strength_v3`
- 本轮目标不是直接放宽 runtime，而是验证 shrink gate 是否真的能产生 execution-eligible activation delta

## 如何验证

1. 先生成 activation-delta diagnostics
2. 再跑小网格 calibration
3. 再跑 multi-window validation
4. 最后跑 rollout assessment

## 验证结论

- 只有当 activation delta、T+1、payoff、downside 同时过关时，才允许 skill 引用该路线为已验证
```

- [ ] **Step 2: Update the BTST skill only if the final rollout artifact promotes**

```markdown
- Before describing trend-continuation activation-delta variants as production-ready, read:
  - `data/reports/btst_trend_continuation_activation_delta_diagnostics.json`
  - `data/reports/btst_trend_continuation_activation_delta_calibration.json`
  - `data/reports/btst_trend_continuation_rollout_assessment.json`
- If the rollout assessment says `hold`, describe the line as governed research evidence only.
```

- [ ] **Step 3: Run the final focused verification suite**

Run:

```bash
uv run pytest \
  tests/test_btst_trend_continuation_activation_delta_diagnostics.py \
  tests/test_btst_trend_continuation_activation_delta_calibration_script.py \
  tests/test_btst_trend_continuation_rollout_helpers.py \
  tests/test_analyze_btst_multi_window_profile_validation_script.py -q
```

Expected: PASS with all new and touched trend-continuation governance tests green.

- [ ] **Step 4: Run the artifact pipeline manually**

Run:

```bash
uv run python scripts/btst_trend_continuation_activation_delta_calibration.py \
  --reports-root data/reports \
  --output-json data/reports/btst_trend_continuation_activation_delta_calibration.json \
  --output-md data/reports/btst_trend_continuation_activation_delta_calibration.md

uv run python scripts/btst_trend_continuation_activation_delta_diagnostics.py \
  --input-json data/reports/btst_multi_window_profile_validation_latest.json \
  --output-json data/reports/btst_trend_continuation_activation_delta_diagnostics.json \
  --output-md data/reports/btst_trend_continuation_activation_delta_diagnostics.md

uv run python scripts/btst_trend_continuation_rollout_assessment.py \
  --input-json data/reports/btst_multi_window_profile_validation_latest.json \
  --diagnostics-json data/reports/btst_trend_continuation_activation_delta_diagnostics.json \
  --output-json data/reports/btst_trend_continuation_rollout_assessment.json \
  --output-md data/reports/btst_trend_continuation_rollout_assessment.md
```

Expected:

- diagnostics JSON/MD created
- calibration JSON/MD created
- rollout assessment refreshed
- only if rollout action is `promote`, then proceed with the Chinese note + BTST skill update

- [ ] **Step 5: Commit**

```bash
git add data/reports/btst_trend_continuation_activation_delta_* \
  scripts/ \
  tests/ \
  docs/prompt/generate_file/trend-continuation-activation-delta-governance-2026-05-21.md \
  skills/ai-hedge-fund-btst/SKILL.md
git commit -m "feat: add trend activation delta governance workflow"
```

If rollout remains `hold`, omit the doc/skill files from the commit and keep the commit message focused on the diagnostics/calibration/governance runtime.
