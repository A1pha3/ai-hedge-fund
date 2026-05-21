# Momentum Rollout Blocker Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fail-closed triage pipeline that explains why the `momentum_optimized -> momentum_tuned` line is still blocked by rollout governance and reduces the next move to one governed recommendation.

**Architecture:** Add three small script surfaces around the existing optimized-profile artifacts. First, parse the current rollout blockers into a dossier grouped by blocker family. Second, build a window-level attribution artifact that maps the dominant blocker families back to specific windows and missing metrics. Third, combine both into a governed triage recommendation that decides whether the next cycle should be a measurement fix, a narrow retune, or a retained hold. No manifest, BTST skill, or Chinese validation-doc promotion is allowed in this cycle.

**Tech Stack:** Python 3.11+/3.13 runtime in repo, existing `scripts/` CLI pattern, JSON + Markdown artifacts under `data/reports/`, pytest.

---

## Planned file structure

- Create: `scripts/btst_momentum_rollout_blocker_dossier.py`
  - Parse the latest optimized-profile rollout report and group blockers into triage families.
- Create: `tests/test_btst_momentum_rollout_blocker_dossier_script.py`
  - Verify family grouping, dominant-family summary, CLI JSON/MD outputs.
- Create: `scripts/btst_momentum_rollout_window_attribution.py`
  - Read optimized-profile artifacts plus source reports and map blocker families back to windows / missing metric surfaces.
- Create: `tests/test_btst_momentum_rollout_window_attribution_script.py`
  - Verify dominant blocker attribution and missing-metric classification.
- Create: `scripts/btst_momentum_rollout_triage_recommendation.py`
  - Combine dossier + attribution into one governed recommendation artifact.
- Create: `tests/test_btst_momentum_rollout_triage_recommendation_script.py`
  - Verify fail-closed recommendation outcomes and CLI outputs.
- Modify: `docs/superpowers/specs/2026-05-21-momentum-rollout-blocker-triage-design.md`
  - Only if spec wording needs a tiny post-plan consistency fix during self-review.

---

### Task 1: Add the momentum rollout blocker dossier artifact

**Files:**
- Create: `scripts/btst_momentum_rollout_blocker_dossier.py`
- Create: `tests/test_btst_momentum_rollout_blocker_dossier_script.py`
- Test: `tests/test_btst_momentum_rollout_blocker_dossier_script.py`

- [ ] **Step 1: Write the failing dossier tests**

```python
import json
from pathlib import Path

import scripts.btst_momentum_rollout_blocker_dossier as dossier


def test_build_blocker_dossier_groups_blockers_by_family() -> None:
    payload = dossier.build_momentum_rollout_blocker_dossier(
        [
            "missing_projected_theme_exposure_delta_vs_default",
            "win_rate_window_trend_regressed_vs_momentum_optimized",
            "downside_p10_regressed_vs_default",
        ]
    )

    assert payload["blocker_count"] == 3
    assert payload["families"]["missing_observability"]["count"] == 1
    assert payload["families"]["cross_window_stability"]["count"] == 1
    assert payload["families"]["risk_payoff_regression"]["count"] == 1
    assert payload["dominant_family"] in {
        "missing_observability",
        "cross_window_stability",
        "risk_payoff_regression",
    }


def test_main_writes_json_and_markdown_outputs(tmp_path: Path) -> None:
    input_md = tmp_path / "btst_latest_optimized_profile.md"
    output_json = tmp_path / "dossier.json"
    output_md = tmp_path / "dossier.md"
    input_md.write_text(
        "# Parameter Search Report\\n\\nRollout Blockers:\\n- missing_projected_theme_exposure_delta_vs_default\\n- downside_p10_regressed_vs_default\\n",
        encoding="utf-8",
    )

    result = dossier.main(
        [
            "--input-md",
            str(input_md),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["blocker_count"] == 2
    assert "missing_observability" in data["families"]
    assert output_md.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_blocker_dossier_script.py -v
```

Expected: FAIL with import or attribute errors for the missing dossier script.

- [ ] **Step 3: Write the minimal dossier implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path


FAMILY_RULES = {
    "missing_observability": ("missing_projected_theme_exposure", "missing_incremental_theme_exposure"),
    "cross_window_stability": ("win_rate_window_", "win_rate_ci_width", "win_rate_cv", "param_drift_score", "factor_drift_score", "gate_above_threshold_cv"),
    "risk_payoff_regression": ("downside_p10", "liquidity_capacity_raw_100", "max_drawdown_simulated", "t_plus_3_close_payoff_ratio"),
}


def build_momentum_rollout_blocker_dossier(blockers: list[str]) -> dict[str, object]:
    families = {
        name: {
            "count": sum(1 for blocker in blockers if any(token in blocker for token in tokens)),
            "blockers": [blocker for blocker in blockers if any(token in blocker for token in tokens)],
        }
        for name, tokens in FAMILY_RULES.items()
    }
    dominant_family = max(families.items(), key=lambda item: item[1]["count"])[0] if blockers else None
    return {
        "blocker_count": len(blockers),
        "families": families,
        "dominant_family": dominant_family,
        "unclassified_blockers": [
            blocker
            for blocker in blockers
            if not any(blocker in family["blockers"] for family in families.values())
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-md", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)
    lines = Path(args.input_md).read_text(encoding="utf-8").splitlines()
    blockers = [line.removeprefix("- ").strip() for line in lines if line.startswith("- ")]
    payload = build_momentum_rollout_blocker_dossier(blockers)
    Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output_md).write_text(render_momentum_rollout_blocker_dossier_markdown(payload), encoding="utf-8")
    return 0
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_blocker_dossier_script.py -v
```

Expected: PASS with 2 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_rollout_blocker_dossier.py tests/test_btst_momentum_rollout_blocker_dossier_script.py
git commit -m "feat: add momentum rollout blocker dossier"
```

---

### Task 2: Add the momentum window-attribution artifact

**Files:**
- Create: `scripts/btst_momentum_rollout_window_attribution.py`
- Create: `tests/test_btst_momentum_rollout_window_attribution_script.py`
- Test: `tests/test_btst_momentum_rollout_window_attribution_script.py`

- [ ] **Step 1: Write the failing attribution tests**

```python
import json
from pathlib import Path

import scripts.btst_momentum_rollout_window_attribution as attribution


def test_build_window_attribution_flags_missing_metric_family() -> None:
    payload = attribution.build_momentum_rollout_window_attribution(
        rollout_blockers=[
            "missing_projected_theme_exposure_delta_vs_default",
            "missing_incremental_theme_exposure_delta_vs_default",
        ],
        window_rows=[
            {"report_label": "window_a", "projected_theme_exposure_delta": None, "incremental_theme_exposure_delta": None},
            {"report_label": "window_b", "projected_theme_exposure_delta": 0.01, "incremental_theme_exposure_delta": None},
        ],
    )

    assert payload["dominant_family"] == "missing_observability"
    assert payload["windows_missing_theme_exposure"] == ["window_a", "window_b"]


def test_main_writes_attribution_outputs(tmp_path: Path) -> None:
    rollout_json = tmp_path / "rollout.json"
    source_json = tmp_path / "source.json"
    output_json = tmp_path / "attribution.json"
    output_md = tmp_path / "attribution.md"
    rollout_json.write_text(json.dumps({"blockers": ["win_rate_window_trend_regressed_vs_default"]}), encoding="utf-8")
    source_json.write_text(json.dumps({"window_rows": [{"report_label": "window_a", "win_rate_window_trend_delta": -0.04}]}), encoding="utf-8")

    result = attribution.main(
        [
            "--rollout-json",
            str(rollout_json),
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
    assert data["window_count"] == 1
    assert output_md.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_window_attribution_script.py -v
```

Expected: FAIL with missing module or missing symbol errors.

- [ ] **Step 3: Write the minimal attribution implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_momentum_rollout_window_attribution(*, rollout_blockers: list[str], window_rows: list[dict[str, object]]) -> dict[str, object]:
    dominant_family = (
        "missing_observability"
        if any(blocker.startswith("missing_") for blocker in rollout_blockers)
        else "cross_window_stability"
    )
    windows_missing_theme_exposure = sorted(
        row["report_label"]
        for row in window_rows
        if row.get("projected_theme_exposure_delta") is None or row.get("incremental_theme_exposure_delta") is None
    )
    return {
        "dominant_family": dominant_family,
        "window_count": len(window_rows),
        "windows_missing_theme_exposure": windows_missing_theme_exposure,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollout-json", required=True)
    parser.add_argument("--source-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)
    rollout = json.loads(Path(args.rollout_json).read_text(encoding="utf-8"))
    source = json.loads(Path(args.source_json).read_text(encoding="utf-8"))
    payload = build_momentum_rollout_window_attribution(
        rollout_blockers=list(rollout.get("blockers") or []),
        window_rows=list(source.get("window_rows") or []),
    )
    Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output_md).write_text(render_momentum_rollout_window_attribution_markdown(payload), encoding="utf-8")
    return 0
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_window_attribution_script.py -v
```

Expected: PASS with 2 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_rollout_window_attribution.py tests/test_btst_momentum_rollout_window_attribution_script.py
git commit -m "feat: add momentum rollout window attribution"
```

---

### Task 3: Add the governed triage recommendation artifact

**Files:**
- Create: `scripts/btst_momentum_rollout_triage_recommendation.py`
- Create: `tests/test_btst_momentum_rollout_triage_recommendation_script.py`
- Test: `tests/test_btst_momentum_rollout_triage_recommendation_script.py`

- [ ] **Step 1: Write the failing recommendation tests**

```python
import json
from pathlib import Path

import scripts.btst_momentum_rollout_triage_recommendation as recommendation


def test_build_triage_recommendation_prefers_measurement_fix_when_missing_observability_dominates() -> None:
    payload = recommendation.build_momentum_rollout_triage_recommendation(
        dossier={"dominant_family": "missing_observability", "blocker_count": 4},
        attribution={"windows_missing_theme_exposure": ["window_a", "window_b"], "window_count": 2},
    )

    assert payload["action"] == "measurement_fix_next"
    assert payload["release_posture"] == "hold"


def test_build_triage_recommendation_retains_hold_when_risk_regression_dominates() -> None:
    payload = recommendation.build_momentum_rollout_triage_recommendation(
        dossier={"dominant_family": "risk_payoff_regression", "blocker_count": 5},
        attribution={"windows_missing_theme_exposure": [], "window_count": 4},
    )

    assert payload["action"] == "retain_hold"
    assert "no_manifest_publication" in payload["guardrails"]


def test_main_writes_recommendation_outputs(tmp_path: Path) -> None:
    dossier_json = tmp_path / "dossier.json"
    attribution_json = tmp_path / "attribution.json"
    output_json = tmp_path / "recommendation.json"
    output_md = tmp_path / "recommendation.md"
    dossier_json.write_text(json.dumps({"dominant_family": "cross_window_stability", "blocker_count": 3}), encoding="utf-8")
    attribution_json.write_text(json.dumps({"windows_missing_theme_exposure": [], "window_count": 3}), encoding="utf-8")

    result = recommendation.main(
        [
            "--dossier-json",
            str(dossier_json),
            "--attribution-json",
            str(attribution_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["action"] == "parameter_retune_next"
    assert output_md.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_triage_recommendation_script.py -v
```

Expected: FAIL with missing module or missing symbol errors.

- [ ] **Step 3: Write the minimal recommendation implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_momentum_rollout_triage_recommendation(*, dossier: dict[str, object], attribution: dict[str, object]) -> dict[str, object]:
    dominant_family = str(dossier.get("dominant_family") or "")
    if dominant_family == "missing_observability":
        action = "measurement_fix_next"
    elif dominant_family == "cross_window_stability":
        action = "parameter_retune_next"
    else:
        action = "retain_hold"
    return {
        "action": action,
        "release_posture": "hold",
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "dominant_family": dominant_family,
        "window_count": int(attribution.get("window_count") or 0),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dossier-json", required=True)
    parser.add_argument("--attribution-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args(argv)
    dossier = json.loads(Path(args.dossier_json).read_text(encoding="utf-8"))
    attribution = json.loads(Path(args.attribution_json).read_text(encoding="utf-8"))
    payload = build_momentum_rollout_triage_recommendation(dossier=dossier, attribution=attribution)
    Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output_md).write_text(render_momentum_rollout_triage_recommendation_markdown(payload), encoding="utf-8")
    return 0
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_rollout_triage_recommendation_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_rollout_triage_recommendation.py tests/test_btst_momentum_rollout_triage_recommendation_script.py
git commit -m "feat: add momentum rollout triage recommendation"
```

---

### Task 4: Run the final momentum triage verification flow

**Files:**
- Verify: `data/reports/btst_latest_optimized_profile.md`
- Verify: `data/reports/btst_latest_optimized_profile.json`
- Create locally: `data/reports/btst_momentum_rollout_blocker_dossier.json`
- Create locally: `data/reports/btst_momentum_rollout_blocker_dossier.md`
- Create locally: `data/reports/btst_momentum_rollout_window_attribution.json`
- Create locally: `data/reports/btst_momentum_rollout_window_attribution.md`
- Create locally: `data/reports/btst_momentum_rollout_triage_recommendation.json`
- Create locally: `data/reports/btst_momentum_rollout_triage_recommendation.md`
- Test: `tests/test_btst_momentum_rollout_blocker_dossier_script.py`
- Test: `tests/test_btst_momentum_rollout_window_attribution_script.py`
- Test: `tests/test_btst_momentum_rollout_triage_recommendation_script.py`

- [ ] **Step 1: Run the focused test suite**

Run:

```bash
uv run pytest \
  tests/test_btst_momentum_rollout_blocker_dossier_script.py \
  tests/test_btst_momentum_rollout_window_attribution_script.py \
  tests/test_btst_momentum_rollout_triage_recommendation_script.py -q
```

Expected: PASS with all new momentum triage tests green.

- [ ] **Step 2: Run the dossier artifact**

Run:

```bash
uv run python scripts/btst_momentum_rollout_blocker_dossier.py \
  --input-md data/reports/btst_latest_optimized_profile.md \
  --output-json data/reports/btst_momentum_rollout_blocker_dossier.json \
  --output-md data/reports/btst_momentum_rollout_blocker_dossier.md
```

Expected: creates blocker-family counts and a dominant-family summary.

- [ ] **Step 3: Run the attribution artifact**

Run:

```bash
uv run python scripts/btst_momentum_rollout_window_attribution.py \
  --rollout-json data/reports/btst_momentum_rollout_blocker_dossier.json \
  --source-json data/reports/btst_latest_optimized_profile_source.json \
  --output-json data/reports/btst_momentum_rollout_window_attribution.json \
  --output-md data/reports/btst_momentum_rollout_window_attribution.md
```

Expected: maps the dominant blocker family back to windows and missing-metric surfaces.

- [ ] **Step 4: Run the governed recommendation artifact**

Run:

```bash
uv run python scripts/btst_momentum_rollout_triage_recommendation.py \
  --dossier-json data/reports/btst_momentum_rollout_blocker_dossier.json \
  --attribution-json data/reports/btst_momentum_rollout_window_attribution.json \
  --output-json data/reports/btst_momentum_rollout_triage_recommendation.json \
  --output-md data/reports/btst_momentum_rollout_triage_recommendation.md
```

Expected: returns one governed next action among `measurement_fix_next`, `parameter_retune_next`, or `retain_hold`, always with `release_posture=hold`.

- [ ] **Step 5: Commit**

```bash
git add \
  scripts/btst_momentum_rollout_blocker_dossier.py \
  scripts/btst_momentum_rollout_window_attribution.py \
  scripts/btst_momentum_rollout_triage_recommendation.py \
  tests/test_btst_momentum_rollout_blocker_dossier_script.py \
  tests/test_btst_momentum_rollout_window_attribution_script.py \
  tests/test_btst_momentum_rollout_triage_recommendation_script.py
git commit -m "feat: add momentum rollout blocker triage pipeline"
```

---

## Self-review checklist

### Spec coverage

- blocker dossier artifact -> **Task 1**
- window-level attribution artifact -> **Task 2**
- governed next-action surface -> **Task 3**
- final verification and no promotion path -> **Task 4**

### Placeholder scan

- No `TBD`, `TODO`, or “implement later” placeholders remain.
- Each code-writing step includes concrete file paths and starter code.
- Each verification step includes exact commands and expected outcomes.

### Type consistency

- dossier outputs `dominant_family`
- attribution consumes rollout blockers and emits `window_count` plus missing-theme-exposure windows
- recommendation consumes `dominant_family` and `window_count`
- release posture stays `hold` through the full plan
