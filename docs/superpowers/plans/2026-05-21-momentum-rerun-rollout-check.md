# Momentum Rerun Rollout Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a narrow rerun-rollout validation pipeline that turns the completed retune shortlist into a winner-plus-neighbors cohort, packages that cohort for rollout recheck, and emits one governed post-check recommendation.

**Architecture:** Add three small script surfaces around the completed shortlist and decision artifacts. First, extract the winner plus its nearest low-blocker challengers into a rerun cohort artifact. Second, build a rollout recheck input pack that freezes the current governance state and candidate metadata. Third, emit one governed rerun recommendation that either advances the rollout recheck, retains hold, or falls back to measurement repair. The cycle stays fail-closed and does not publish anything.

**Tech Stack:** Python 3.11+/3.12, existing `scripts/` CLI pattern, JSON + Markdown artifacts under `data/reports/`, pytest.

---

## Planned file structure

- Create: `scripts/btst_momentum_rerun_rollout_cohort.py`
  - Read the completed shortlist and decision artifacts, then emit the fixed winner plus a tiny challenger cohort.
- Create: `tests/test_btst_momentum_rerun_rollout_cohort_script.py`
  - Verify winner preservation, challenger selection, cohort caps, and fail-closed behavior.
- Create: `scripts/btst_momentum_rerun_rollout_pack.py`
  - Read the cohort and current decision / triage context, then emit a rollout-check-ready input pack with guardrails.
- Create: `tests/test_btst_momentum_rerun_rollout_pack_script.py`
  - Verify governance propagation, guardrail preservation, and malformed-input handling.
- Create: `scripts/btst_momentum_rerun_rollout_recommendation.py`
  - Read the cohort pack and emit one governed next-step recommendation.
- Create: `tests/test_btst_momentum_rerun_rollout_recommendation_script.py`
  - Verify `advance_rollout_recheck`, `retain_hold`, and `fallback_measurement_repair`.
- Verify reference only: `data/reports/btst_momentum_stability_retune_shortlist.json`
- Verify reference only: `data/reports/btst_momentum_stability_retune_decision.json`

---

### Task 1: Add the rerun cohort artifact

**Files:**
- Create: `scripts/btst_momentum_rerun_rollout_cohort.py`
- Create: `tests/test_btst_momentum_rerun_rollout_cohort_script.py`
- Verify reference only: `data/reports/btst_momentum_stability_retune_shortlist.json`
- Verify reference only: `data/reports/btst_momentum_stability_retune_decision.json`
- Test: `tests/test_btst_momentum_rerun_rollout_cohort_script.py`

- [ ] **Step 1: Write the failing cohort tests**

```python
import json
from pathlib import Path

import pytest

import scripts.btst_momentum_rerun_rollout_cohort as cohort


def test_build_rerun_cohort_keeps_winner_first_and_caps_challengers() -> None:
    payload = cohort.build_momentum_rerun_rollout_cohort(
        shortlist={
            "best_candidate": {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
            "candidates": [
                {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                {"trial_index": 1226, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 1, "risk_blocker_count": 1},
                {"trial_index": 74, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 2, "risk_blocker_count": 1},
                {"trial_index": 361, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 2, "risk_blocker_count": 1},
                {"trial_index": 938, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 2, "risk_blocker_count": 1},
            ],
        },
        decision={"action": "rerun_rollout_check", "best_candidate": {"trial_index": 602}},
    )

    assert payload["winner"]["trial_index"] == 602
    assert [row["trial_index"] for row in payload["challengers"]] == [1226, 74, 361]
    assert payload["challenger_count"] == 3


def test_build_rerun_cohort_fails_closed_when_decision_does_not_target_shortlist_winner() -> None:
    with pytest.raises(SystemExit, match="decision winner"):
        cohort.build_momentum_rerun_rollout_cohort(
            shortlist={"best_candidate": {"trial_index": 602}, "candidates": [{"trial_index": 602}]},
            decision={"action": "rerun_rollout_check", "best_candidate": {"trial_index": 700}},
        )


def test_main_writes_rerun_cohort_outputs(tmp_path: Path) -> None:
    shortlist_json = tmp_path / "shortlist.json"
    decision_json = tmp_path / "decision.json"
    output_json = tmp_path / "cohort.json"
    output_md = tmp_path / "cohort.md"
    shortlist_json.write_text(
        json.dumps(
            {
                "best_candidate": {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                "candidates": [
                    {"trial_index": 602, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
                    {"trial_index": 1226, "params": {"select_threshold": 0.46}, "cross_window_blocker_count": 1, "risk_blocker_count": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    decision_json.write_text(json.dumps({"action": "rerun_rollout_check", "best_candidate": {"trial_index": 602}}), encoding="utf-8")

    result = cohort.main(
        [
            "--shortlist-json",
            str(shortlist_json),
            "--decision-json",
            str(decision_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["winner"]["trial_index"] == 602
    assert output_md.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_rerun_rollout_cohort_script.py -v
```

Expected: FAIL with import or attribute errors for the missing cohort script.

- [ ] **Step 3: Write the minimal cohort implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CHALLENGER_LIMIT = 3


def _load_json_file(path: Path, *, label: str) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"{label} file not found: {path}") from exc
    except OSError as exc:
        raise SystemExit(f"unable to read {label} file: {path}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {label} file: {path}") from exc


def _write_output_file(path: Path, *, content: str, label: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"unable to write {label}: {path}") from exc


def _require_object(name: str, payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return dict(payload)


def _require_candidate(name: str, payload: object) -> dict[str, Any]:
    candidate = _require_object(name, payload)
    trial_index = candidate.get("trial_index")
    if isinstance(trial_index, bool) or not isinstance(trial_index, int) or trial_index < 0:
        raise SystemExit(f"{name} must include a non-negative integer trial_index.")
    return candidate


def build_momentum_rerun_rollout_cohort(*, shortlist: dict[str, object], decision: dict[str, object]) -> dict[str, object]:
    shortlist_obj = _require_object("shortlist", shortlist)
    decision_obj = _require_object("decision", decision)
    if str(decision_obj.get("action") or "") != "rerun_rollout_check":
        raise SystemExit("decision action must be rerun_rollout_check before building a rerun cohort.")

    winner = _require_candidate("shortlist best_candidate", shortlist_obj.get("best_candidate"))
    decision_winner = _require_candidate("decision best_candidate", decision_obj.get("best_candidate"))
    if int(decision_winner["trial_index"]) != int(winner["trial_index"]):
        raise SystemExit("decision winner must match the shortlist winner trial_index.")

    candidates = shortlist_obj.get("candidates")
    if not isinstance(candidates, list):
        raise SystemExit("shortlist must include a candidates list.")

    normalized_candidates = [_require_candidate("shortlist candidate", row) for row in candidates]
    challengers = [row for row in normalized_candidates if int(row["trial_index"]) != int(winner["trial_index"])]
    ordered = sorted(
        challengers,
        key=lambda row: (
            int(row.get("risk_blocker_count") or 0),
            int(row.get("cross_window_blocker_count") or 0),
            int(row["trial_index"]),
        ),
    )
    limited = ordered[:CHALLENGER_LIMIT]

    return {
        "winner": winner,
        "challenger_count": len(limited),
        "challengers": limited,
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "fail_closed": True,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_rerun_rollout_cohort_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_rerun_rollout_cohort.py tests/test_btst_momentum_rerun_rollout_cohort_script.py
git commit -m "feat: add momentum rerun rollout cohort"
```

---

### Task 2: Add the rollout recheck input-pack artifact

**Files:**
- Create: `scripts/btst_momentum_rerun_rollout_pack.py`
- Create: `tests/test_btst_momentum_rerun_rollout_pack_script.py`
- Verify reference only: `data/reports/btst_momentum_stability_retune_decision.json`
- Test: `tests/test_btst_momentum_rerun_rollout_pack_script.py`

- [ ] **Step 1: Write the failing input-pack tests**

```python
import json
from pathlib import Path

import pytest

import scripts.btst_momentum_rerun_rollout_pack as pack


def test_build_rerun_pack_carries_winner_challengers_and_guardrails() -> None:
    payload = pack.build_momentum_rerun_rollout_pack(
        cohort={
            "winner": {"trial_index": 602, "params": {"select_threshold": 0.46}},
            "challengers": [{"trial_index": 1226, "params": {"select_threshold": 0.46}}],
            "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        },
        decision={"action": "rerun_rollout_check", "release_posture": "hold", "dominant_family": "cross_window_stability", "missing_theme_exposure_window_count": 2},
    )

    assert payload["winner"]["trial_index"] == 602
    assert payload["release_posture"] == "hold"
    assert payload["guardrails"] == ["no_manifest_publication", "no_btst_skill_promotion"]


def test_build_rerun_pack_fails_closed_when_release_posture_is_not_hold() -> None:
    with pytest.raises(SystemExit, match="release_posture"):
        pack.build_momentum_rerun_rollout_pack(
            cohort={"winner": {"trial_index": 602}, "challengers": [], "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"]},
            decision={"action": "rerun_rollout_check", "release_posture": "ready", "dominant_family": "cross_window_stability", "missing_theme_exposure_window_count": 2},
        )


def test_main_writes_rerun_pack_outputs(tmp_path: Path) -> None:
    cohort_json = tmp_path / "cohort.json"
    decision_json = tmp_path / "decision.json"
    output_json = tmp_path / "pack.json"
    output_md = tmp_path / "pack.md"
    cohort_json.write_text(json.dumps({"winner": {"trial_index": 602}, "challengers": [], "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"]}), encoding="utf-8")
    decision_json.write_text(json.dumps({"action": "rerun_rollout_check", "release_posture": "hold", "dominant_family": "cross_window_stability", "missing_theme_exposure_window_count": 2}), encoding="utf-8")

    result = pack.main(
        [
            "--cohort-json",
            str(cohort_json),
            "--decision-json",
            str(decision_json),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    assert result == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["release_posture"] == "hold"
    assert output_md.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_btst_momentum_rerun_rollout_pack_script.py -v
```

Expected: FAIL with import or attribute errors for the missing pack script.

- [ ] **Step 3: Write the minimal input-pack implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXPECTED_GUARDRAILS = ("no_manifest_publication", "no_btst_skill_promotion")


def _load_json_file(path: Path, *, label: str) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"{label} file not found: {path}") from exc
    except OSError as exc:
        raise SystemExit(f"unable to read {label} file: {path}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {label} file: {path}") from exc


def _write_output_file(path: Path, *, content: str, label: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"unable to write {label}: {path}") from exc


def _require_object(name: str, payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return dict(payload)


def build_momentum_rerun_rollout_pack(*, cohort: dict[str, object], decision: dict[str, object]) -> dict[str, object]:
    cohort_obj = _require_object("cohort", cohort)
    decision_obj = _require_object("decision", decision)

    if str(decision_obj.get("action") or "") != "rerun_rollout_check":
        raise SystemExit("decision action must be rerun_rollout_check before building a rerun pack.")
    if str(decision_obj.get("release_posture") or "") != "hold":
        raise SystemExit("release_posture must remain hold for the rerun rollout pack.")

    guardrails = cohort_obj.get("guardrails")
    if list(guardrails or []) != list(EXPECTED_GUARDRAILS):
        raise SystemExit("cohort guardrails must preserve the no-publication / no-skill-promotion boundary.")

    return {
        "winner": _require_object("winner", cohort_obj.get("winner")),
        "challengers": list(cohort_obj.get("challengers") or []),
        "guardrails": list(EXPECTED_GUARDRAILS),
        "release_posture": "hold",
        "dominant_family": str(decision_obj.get("dominant_family") or ""),
        "missing_theme_exposure_window_count": int(decision_obj.get("missing_theme_exposure_window_count") or 0),
        "fail_closed": True,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_rerun_rollout_pack_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_rerun_rollout_pack.py tests/test_btst_momentum_rerun_rollout_pack_script.py
git commit -m "feat: add momentum rerun rollout pack"
```

---

### Task 3: Add the governed rerun recommendation artifact

**Files:**
- Create: `scripts/btst_momentum_rerun_rollout_recommendation.py`
- Create: `tests/test_btst_momentum_rerun_rollout_recommendation_script.py`
- Test: `tests/test_btst_momentum_rerun_rollout_recommendation_script.py`

- [ ] **Step 1: Write the failing rerun recommendation tests**

```python
import json
from pathlib import Path

import scripts.btst_momentum_rerun_rollout_recommendation as recommendation


def test_build_rerun_recommendation_advances_rollout_recheck_when_winner_stays_clear() -> None:
    payload = recommendation.build_momentum_rerun_rollout_recommendation(
        pack={
            "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
            "challengers": [{"trial_index": 1226, "cross_window_blocker_count": 1, "risk_blocker_count": 1}],
            "release_posture": "hold",
            "dominant_family": "cross_window_stability",
            "missing_theme_exposure_window_count": 2,
        }
    )

    assert payload["action"] == "advance_rollout_recheck"
    assert payload["release_posture"] == "hold"


def test_build_rerun_recommendation_falls_back_to_measurement_repair_when_observability_dominates() -> None:
    payload = recommendation.build_momentum_rerun_rollout_recommendation(
        pack={
            "winner": {"trial_index": 602, "cross_window_blocker_count": 0, "risk_blocker_count": 0},
            "challengers": [],
            "release_posture": "hold",
            "dominant_family": "missing_observability",
            "missing_theme_exposure_window_count": 4,
        }
    )

    assert payload["action"] == "fallback_measurement_repair"


def test_main_writes_rerun_recommendation_outputs(tmp_path: Path) -> None:
    pack_json = tmp_path / "pack.json"
    output_json = tmp_path / "recommendation.json"
    output_md = tmp_path / "recommendation.md"
    pack_json.write_text(
        json.dumps(
            {
                "winner": {"trial_index": 602, "cross_window_blocker_count": 1, "risk_blocker_count": 1},
                "challengers": [{"trial_index": 1226, "cross_window_blocker_count": 1, "risk_blocker_count": 1}],
                "release_posture": "hold",
                "dominant_family": "cross_window_stability",
                "missing_theme_exposure_window_count": 2,
            }
        ),
        encoding="utf-8",
    )

    result = recommendation.main(
        [
            "--pack-json",
            str(pack_json),
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
uv run pytest tests/test_btst_momentum_rerun_rollout_recommendation_script.py -v
```

Expected: FAIL with import or attribute errors for the missing recommendation script.

- [ ] **Step 3: Write the minimal rerun recommendation implementation**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json_file(path: Path, *, label: str) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"{label} file not found: {path}") from exc
    except OSError as exc:
        raise SystemExit(f"unable to read {label} file: {path}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {label} file: {path}") from exc


def _write_output_file(path: Path, *, content: str, label: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"unable to write {label}: {path}") from exc


def _require_object(name: str, payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return dict(payload)


def build_momentum_rerun_rollout_recommendation(*, pack: dict[str, object]) -> dict[str, object]:
    pack_obj = _require_object("pack", pack)
    winner = _require_object("winner", pack_obj.get("winner"))
    if str(pack_obj.get("release_posture") or "") != "hold":
        raise SystemExit("release_posture must remain hold for the rerun recommendation.")

    dominant_family = str(pack_obj.get("dominant_family") or "")
    missing_theme_exposure_window_count = int(pack_obj.get("missing_theme_exposure_window_count") or 0)
    cross_window_blocker_count = int(winner.get("cross_window_blocker_count") or 0)
    risk_blocker_count = int(winner.get("risk_blocker_count") or 0)

    if dominant_family == "missing_observability" and missing_theme_exposure_window_count > 0:
        action = "fallback_measurement_repair"
    elif cross_window_blocker_count == 0 and risk_blocker_count == 0:
        action = "advance_rollout_recheck"
    else:
        action = "retain_hold"

    return {
        "action": action,
        "release_posture": "hold",
        "guardrails": ["no_manifest_publication", "no_btst_skill_promotion"],
        "winner": winner,
        "dominant_family": dominant_family,
        "missing_theme_exposure_window_count": missing_theme_exposure_window_count,
        "fail_closed": True,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_btst_momentum_rerun_rollout_recommendation_script.py -v
```

Expected: PASS with 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/btst_momentum_rerun_rollout_recommendation.py tests/test_btst_momentum_rerun_rollout_recommendation_script.py
git commit -m "feat: add momentum rerun rollout recommendation"
```

---

### Task 4: Run the final rerun-rollout verification flow

**Files:**
- Verify input: `data/reports/btst_momentum_stability_retune_shortlist.json`
- Verify input: `data/reports/btst_momentum_stability_retune_decision.json`
- Create locally: `data/reports/btst_momentum_rerun_rollout_cohort.json`
- Create locally: `data/reports/btst_momentum_rerun_rollout_cohort.md`
- Create locally: `data/reports/btst_momentum_rerun_rollout_pack.json`
- Create locally: `data/reports/btst_momentum_rerun_rollout_pack.md`
- Create locally: `data/reports/btst_momentum_rerun_rollout_recommendation.json`
- Create locally: `data/reports/btst_momentum_rerun_rollout_recommendation.md`
- Test: `tests/test_btst_momentum_rerun_rollout_cohort_script.py`
- Test: `tests/test_btst_momentum_rerun_rollout_pack_script.py`
- Test: `tests/test_btst_momentum_rerun_rollout_recommendation_script.py`

- [ ] **Step 1: Run the focused test suite**

Run:

```bash
uv run pytest \
  tests/test_btst_momentum_rerun_rollout_cohort_script.py \
  tests/test_btst_momentum_rerun_rollout_pack_script.py \
  tests/test_btst_momentum_rerun_rollout_recommendation_script.py -q
```

Expected: PASS with all rerun-rollout-cycle tests green.

- [ ] **Step 2: Run the rerun cohort artifact**

Run:

```bash
uv run python scripts/btst_momentum_rerun_rollout_cohort.py \
  --shortlist-json data/reports/btst_momentum_stability_retune_shortlist.json \
  --decision-json data/reports/btst_momentum_stability_retune_decision.json \
  --output-json data/reports/btst_momentum_rerun_rollout_cohort.json \
  --output-md data/reports/btst_momentum_rerun_rollout_cohort.md
```

Expected: winner `trial_index=602` remains fixed and challengers are capped.

- [ ] **Step 3: Run the rollout input-pack artifact**

Run:

```bash
uv run python scripts/btst_momentum_rerun_rollout_pack.py \
  --cohort-json data/reports/btst_momentum_rerun_rollout_cohort.json \
  --decision-json data/reports/btst_momentum_stability_retune_decision.json \
  --output-json data/reports/btst_momentum_rerun_rollout_pack.json \
  --output-md data/reports/btst_momentum_rerun_rollout_pack.md
```

Expected: release posture stays `hold` and guardrails are preserved.

- [ ] **Step 4: Run the governed rerun recommendation artifact**

Run:

```bash
uv run python scripts/btst_momentum_rerun_rollout_recommendation.py \
  --pack-json data/reports/btst_momentum_rerun_rollout_pack.json \
  --output-json data/reports/btst_momentum_rerun_rollout_recommendation.json \
  --output-md data/reports/btst_momentum_rerun_rollout_recommendation.md
```

Expected: returns one governed next action among `advance_rollout_recheck`, `retain_hold`, or `fallback_measurement_repair`, always with `release_posture=hold`.

- [ ] **Step 5: Commit**

```bash
git add \
  scripts/btst_momentum_rerun_rollout_cohort.py \
  scripts/btst_momentum_rerun_rollout_pack.py \
  scripts/btst_momentum_rerun_rollout_recommendation.py \
  tests/test_btst_momentum_rerun_rollout_cohort_script.py \
  tests/test_btst_momentum_rerun_rollout_pack_script.py \
  tests/test_btst_momentum_rerun_rollout_recommendation_script.py
git commit -m "feat: add momentum rerun rollout check pipeline"
```

---

## Self-review checklist

### Spec coverage

- winner-plus-neighbors rerun cohort -> **Task 1**
- rollout recheck input pack -> **Task 2**
- governed rerun recommendation -> **Task 3**
- final live verification under `hold` posture -> **Task 4**

### Placeholder scan

- No `TBD`, `TODO`, or “implement later” placeholders remain.
- Each code-writing step includes concrete file paths and starter code.
- Each verification step includes exact commands and expected outcomes.

### Type consistency

- cohort outputs `winner`, `challenger_count`, `challengers`, and `guardrails`
- pack consumes `winner` / `challengers` and emits `release_posture`, `dominant_family`, and `missing_theme_exposure_window_count`
- recommendation consumes `winner`, `release_posture`, `dominant_family`, and `missing_theme_exposure_window_count`
- release posture stays `hold` through the full plan
