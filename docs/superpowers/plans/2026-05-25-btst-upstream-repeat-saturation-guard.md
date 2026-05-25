# BTST Upstream Repeat Saturation Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repeat-ticker saturation guard so corridor focus tickers like `300683` and `003036` stop receiving relaxed upstream-shadow focus treatment after they flip from repeated false negatives into false positives.

**Architecture:** Keep the existing corridor focus mechanism, but insert one narrow data-driven guardrail in front of it. First, generate a small repeat-saturation board from the refreshed upstream-shadow FN/FP dossier; then make `candidate_pool.py` subtract those blocked tickers from the corridor focus set so `primary_shadow_replay` cannot keep amplifying already-saturated names.

**Tech Stack:** Python 3.11+, pytest, existing screening pipeline under `src/screening/`, BTST dossier scripts under `scripts/`

---

## File structure

- Create: `scripts/analyze_btst_upstream_shadow_repeat_saturation.py`
  - Reads the refreshed upstream-shadow FN/FP dossier and produces a compact board of focus-blocked tickers.
- Modify: `src/screening/candidate_pool.py`
  - Load the repeat-saturation board and subtract blocked tickers from the corridor focus path.
- Modify: `tests/screening/test_candidate_pool.py`
  - Lock the corridor focus path behavior with targeted unit tests.
- Create: `tests/test_analyze_btst_upstream_shadow_repeat_saturation_script.py`
  - Verify the new board-building script with realistic FN→FP flip fixtures.

### Task 1: Create the repeat-saturation board script with red-green tests

**Files:**
- Create: `scripts/analyze_btst_upstream_shadow_repeat_saturation.py`
- Create: `tests/test_analyze_btst_upstream_shadow_repeat_saturation_script.py`

- [ ] **Step 1: Write the failing script contract test**

```python
from pathlib import Path
import json

from scripts.analyze_btst_upstream_shadow_repeat_saturation import analyze_upstream_shadow_repeat_saturation


def test_analyze_upstream_shadow_repeat_saturation_flags_fn_to_fp_flip(tmp_path):
    dossier_path = tmp_path / "fnfp.json"
    dossier_path.write_text(
        json.dumps(
            {
                "false_negative_rows": [
                    {"trade_date": "2026-03-27", "ticker": "300683", "score_target": 0.3883, "trend_acceleration": 0.7097, "close_strength": 0.8779},
                    {"trade_date": "2026-03-31", "ticker": "300683", "score_target": 0.3910, "trend_acceleration": 0.7543, "close_strength": 0.8775},
                ],
                "false_positive_rows": [
                    {"trade_date": "2026-04-06", "ticker": "300683", "score_target": 0.4183, "trend_acceleration": 0.7872, "close_strength": 0.8936},
                    {"trade_date": "2026-03-31", "ticker": "003036", "score_target": 0.4561, "trend_acceleration": 0.8578, "close_strength": 0.8802},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    analysis = analyze_upstream_shadow_repeat_saturation(dossier_path)

    assert analysis["focus_blocked_tickers"] == ["300683"]
    assert analysis["blocked_rows"][0]["ticker"] == "300683"
    assert analysis["blocked_rows"][0]["block_reason"] == "fn_to_fp_flip_after_repeat_shadow_hits"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_analyze_btst_upstream_shadow_repeat_saturation_script.py::test_analyze_upstream_shadow_repeat_saturation_flags_fn_to_fp_flip -v
```

Expected: FAIL with `ModuleNotFoundError` or missing function error because the script does not exist yet.

- [ ] **Step 3: Implement the minimal board builder**

```python
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def analyze_upstream_shadow_repeat_saturation(dossier_path: str | Path) -> dict[str, Any]:
    resolved_path = Path(dossier_path).expanduser().resolve()
    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    per_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in list(payload.get("false_negative_rows") or []):
        per_ticker[str(row.get("ticker") or "")].append({**dict(row), "classification": "false_negative"})
    for row in list(payload.get("false_positive_rows") or []):
        per_ticker[str(row.get("ticker") or "")].append({**dict(row), "classification": "false_positive"})

    blocked_rows: list[dict[str, Any]] = []
    for ticker, rows in per_ticker.items():
        if not ticker or len(rows) < 3:
            continue
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))
        classifications = [str(row.get("classification") or "") for row in rows]
        if "false_negative" not in classifications or "false_positive" not in classifications:
            continue
        first_fp_index = classifications.index("false_positive")
        if first_fp_index == 0 or all(label != "false_negative" for label in classifications[:first_fp_index]):
            continue
        blocked_rows.append(
            {
                "ticker": ticker,
                "block_reason": "fn_to_fp_flip_after_repeat_shadow_hits",
                "event_count": len(rows),
                "first_false_positive_trade_date": rows[first_fp_index].get("trade_date"),
                "rows": rows,
            }
        )

    blocked_rows.sort(key=lambda row: (-int(row.get("event_count") or 0), str(row.get("ticker") or "")))
    return {
        "dossier_path": str(resolved_path),
        "blocked_rows": blocked_rows,
        "focus_blocked_tickers": [str(row.get("ticker") or "") for row in blocked_rows],
    }
```

- [ ] **Step 4: Add a CLI entry point and artifact writer**

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Build upstream-shadow repeat-saturation board from FN/FP dossier.")
    parser.add_argument("--dossier-json", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    analysis = analyze_upstream_shadow_repeat_saturation(args.dossier_json)
    output_path = Path(args.output_json).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the script test to verify it passes**

Run:

```bash
uv run pytest tests/test_analyze_btst_upstream_shadow_repeat_saturation_script.py -q
```

Expected: PASS

- [ ] **Step 6: Commit Task 1**

```bash
git add scripts/analyze_btst_upstream_shadow_repeat_saturation.py tests/test_analyze_btst_upstream_shadow_repeat_saturation_script.py
git commit -m "feat: add upstream shadow repeat saturation board"
```

### Task 2: Block saturated tickers from corridor focus-relaxed admission

**Files:**
- Modify: `src/screening/candidate_pool.py`
- Modify: `tests/screening/test_candidate_pool.py`

- [ ] **Step 1: Write the failing corridor focus guard test**

```python
def test_resolve_shadow_focus_tickers_excludes_repeat_saturation_blocked_primary(tmp_path):
    from src.screening.candidate_pool import _resolve_shadow_focus_tickers

    corridor_pack = tmp_path / "corridor_shadow_pack.json"
    saturation_board = tmp_path / "repeat_saturation_board.json"
    corridor_pack.write_text(
        json.dumps(
            {
                "shadow_status": "diagnostic_primary_shadow_replay_only",
                "primary_shadow_replay": {"ticker": "300683"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    saturation_board.write_text(
        json.dumps({"focus_blocked_tickers": ["300683"]}, ensure_ascii=False),
        encoding="utf-8",
    )

    with patch("src.screening.candidate_pool._CORRIDOR_SHADOW_PACK_PATH", corridor_pack), patch(
        "src.screening.candidate_pool._UPSTREAM_REPEAT_SATURATION_BOARD_PATH", saturation_board
    ):
        focus_tickers = _resolve_shadow_focus_tickers(lane="layer_a_liquidity_corridor")

    assert "300683" not in focus_tickers
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/screening/test_candidate_pool.py::test_resolve_shadow_focus_tickers_excludes_repeat_saturation_blocked_primary -v
```

Expected: FAIL because `_resolve_shadow_focus_tickers()` still includes `300683`.

- [ ] **Step 3: Add a board loader and apply it only to corridor focus tickers**

```python
_UPSTREAM_REPEAT_SATURATION_BOARD_PATH = _PROJECT_ROOT / "data" / "reports" / "btst_upstream_shadow_repeat_saturation_board_latest.json"


def _load_upstream_repeat_saturation_blocked_tickers(board_path: Path) -> set[str]:
    try:
        data = json.loads(board_path.read_text(encoding="utf-8"))
        blocked = data.get("focus_blocked_tickers")
        if not isinstance(blocked, list):
            return set()
        return {str(item).strip() for item in blocked if str(item or "").strip()}
    except (OSError, json.JSONDecodeError, ValueError):
        return set()


def _resolve_shadow_focus_tickers(*, lane: str) -> set[str]:
    lane_specific_focus: set[str] = set()
    blocked_tickers = _load_upstream_repeat_saturation_blocked_tickers(_UPSTREAM_REPEAT_SATURATION_BOARD_PATH)
    if lane == "layer_a_liquidity_corridor":
        lane_specific_focus = SHADOW_FOCUS_LIQUIDITY_CORRIDOR_TICKERS | _load_active_corridor_primary_shadow_focus(_CORRIDOR_SHADOW_PACK_PATH)
        lane_specific_focus -= blocked_tickers
    elif lane == "post_gate_liquidity_competition":
        lane_specific_focus = SHADOW_FOCUS_REBUCKET_TICKERS
    return set(SHADOW_FOCUS_TICKERS) | set(lane_specific_focus)
```

- [ ] **Step 4: Add a focused overflow-classification regression**

```python
def test_classify_overflow_candidate_does_not_use_focus_relaxation_for_blocked_repeat_ticker():
    candidate = CandidateStock(
        ticker="300683",
        name="示例",
        industry_sw="电子",
        avg_volume_20d=900.0,
        market_cap=80.0,
        listing_date="20180101",
    )

    result = candidate_pool_module.classify_overflow_candidate(
        candidate=candidate,
        rank=1600,
        cutoff_share=0.28,
        min_gate_share=2.6,
        corridor_focus_tickers=set(),
        rebucket_focus_tickers=set(),
        corridor_visibility_gap_tickers=set(),
        rebucket_visibility_gap_tickers=set(),
        corridor_min_gate_share=3.0,
        corridor_max_cutoff_share=0.20,
        corridor_focus_min_gate_share=2.5,
        corridor_focus_max_cutoff_share=0.30,
        corridor_focus_low_gate_max_cutoff_share=0.075,
        corridor_visibility_gap_max_cutoff_share=0.35,
        rebucket_min_gate_share=8.0,
        rebucket_min_cutoff_share=0.35,
        rebucket_max_cutoff_share=0.80,
        rebucket_focus_min_cutoff_share=0.25,
        rebucket_visibility_gap_min_cutoff_share=0.25,
    )

    assert result is None
```

- [ ] **Step 5: Run the focused candidate-pool tests**

Run:

```bash
uv run pytest \
  tests/screening/test_candidate_pool.py::test_resolve_shadow_focus_tickers_excludes_repeat_saturation_blocked_primary \
  tests/screening/test_candidate_pool.py::test_classify_overflow_candidate_does_not_use_focus_relaxation_for_blocked_repeat_ticker \
  -v
```

Expected: PASS

- [ ] **Step 6: Commit Task 2**

```bash
git add src/screening/candidate_pool.py tests/screening/test_candidate_pool.py
git commit -m "feat: guard corridor focus with repeat saturation board"
```

### Task 3: Verify the real 300683/003036 board and end-to-end wiring

**Files:**
- Modify: `tests/test_analyze_btst_upstream_shadow_repeat_saturation_script.py`
- Test: `tests/test_analyze_btst_upstream_shadow_repeat_saturation_script.py`
- Test: `tests/screening/test_candidate_pool.py`

- [ ] **Step 1: Add a real-shape regression for the refreshed dossier**

```python
def test_analyze_upstream_shadow_repeat_saturation_blocks_real_flip_tickers(tmp_path):
    dossier_path = tmp_path / "fnfp.json"
    dossier_path.write_text(
        json.dumps(
            {
                "false_negative_rows": [
                    {"trade_date": "2026-03-27", "ticker": "300683"},
                    {"trade_date": "2026-03-30", "ticker": "300683"},
                    {"trade_date": "2026-03-23", "ticker": "003036"},
                    {"trade_date": "2026-03-27", "ticker": "003036"},
                ],
                "false_positive_rows": [
                    {"trade_date": "2026-04-06", "ticker": "300683"},
                    {"trade_date": "2026-04-07", "ticker": "300683"},
                    {"trade_date": "2026-03-31", "ticker": "003036"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    analysis = analyze_upstream_shadow_repeat_saturation(dossier_path)

    assert analysis["focus_blocked_tickers"] == ["300683", "003036"]
```

- [ ] **Step 2: Generate the real board artifact from the refreshed dossier**

Run:

```bash
uv run python scripts/analyze_btst_upstream_shadow_repeat_saturation.py \
  --dossier-json /Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/upstream_shadow_fnfp_dossier_2026-05-25.json \
  --output-json /Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/btst_upstream_shadow_repeat_saturation_board_2026-05-25.json
```

Expected: JSON artifact lists `300683` and `003036` in `focus_blocked_tickers`.

- [ ] **Step 3: Run the regression pack**

Run:

```bash
uv run pytest \
  tests/test_analyze_btst_upstream_shadow_repeat_saturation_script.py \
  tests/screening/test_candidate_pool.py -q
```

Expected: PASS

- [ ] **Step 4: Commit Task 3**

```bash
git add tests/test_analyze_btst_upstream_shadow_repeat_saturation_script.py /Users/matrix/.copilot/session-state/359fb789-0911-44b2-900a-26f7e4891fab/files/btst_upstream_shadow_repeat_saturation_board_2026-05-25.json
git commit -m "test: verify upstream repeat saturation guard"
```

## Self-review

- Spec coverage: the plan covers the approved direction exactly — add a repeat-saturation guard to the corridor focus path, not a global threshold retune.
- Placeholder scan: no TBD/TODO placeholders; every task includes concrete files, tests, code, and commands.
- Type consistency: the plan uses one board format (`focus_blocked_tickers`) from script generation through runtime loading, so the runtime seam and test seam stay aligned.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-25-btst-upstream-repeat-saturation-guard.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints
