# BTST Single-Date Output Dirs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BTST daily runs require only `signal_date`, infer `next_trade_date` via SSE trading calendar, write a `manifest.json`, and default outputs to `outputs/<signal_yyyymm>/<signal_yyyymmdd>[_scheme_a]/` (signal-date anchored).

**Architecture:** Add a strict CN-SSE calendar resolver (Tushare trade_cal with Akshare fallback) and reuse it inside `generate_btst_doc_bundle.py` for (1) date validation, (2) default output-dir resolution, and (3) manifest emission. Update user docs/templates to match the new contract.

**Tech Stack:** Python 3.11+, pandas, Tushare (`trade_cal`) via `src.tools.tushare_api`, Akshare fallback (`tool_trade_date_hist_sina`), pytest.

---

## File / Responsibility Map (locked)

- **Create:** `src/paper_trading/btst_trade_calendar.py`
  - Strict CN-SSE trading-day utilities: normalize, load open trading days (tushare→akshare fallback), validate `signal_date` is open day, infer `next_trade_date`.

- **Modify:** `scripts/generate_btst_doc_bundle.py`
  - Use strict calendar resolver to validate dates.
  - Change default output directory naming to the new convention.
  - Add `--scheme-a` CLI flag (directory marker only).
  - Emit `manifest.json` into bundle output directory.

- **Modify:** `src/paper_trading/btst_reporting_utils.py`
  - Reuse strict resolver for `infer_next_trade_date()` (or introduce a strict variant) so follow-up card scripts share the same calendar logic.

- **Modify docs:**
  - `docs/prompt/often/btst_daily_report.md`
  - `docs/plans/2026-05-27-early-runner-scheme-a-operations.md`

- **Modify tests:**
  - `tests/test_generate_btst_doc_bundle_script.py`
  - `tests/test_generate_btst_next_day_trade_brief_script.py` (only if it asserts old `infer_next_trade_date` behavior)

---

### Task 1: Add strict CN-SSE trading calendar resolver

**Files:**
- Create: `src/paper_trading/btst_trade_calendar.py`
- Test: `tests/test_btst_trade_calendar.py`

- [ ] **Step 1: Write failing tests for strict next-trade-date inference**

Create `tests/test_btst_trade_calendar.py`:

```python
from __future__ import annotations

import pandas as pd
import pytest


def test_resolve_next_trade_date_strict_handles_weekend(monkeypatch):
    # Friday -> Monday
    from src.paper_trading import btst_trade_calendar as cal

    monkeypatch.setattr(cal, "_load_open_trade_dates_cn_sse", lambda *_args, **_kwargs: (["20260605", "20260608"], "tushare_trade_cal"))

    resolved = cal.resolve_next_trade_date_cn_sse_strict("2026-06-05")
    assert resolved.next_trade_date_iso == "2026-06-08"
    assert resolved.calendar_source == "tushare_trade_cal"


def test_resolve_next_trade_date_strict_rejects_non_trading_day(monkeypatch):
    from src.paper_trading import btst_trade_calendar as cal

    monkeypatch.setattr(cal, "_load_open_trade_dates_cn_sse", lambda *_args, **_kwargs: (["20260605", "20260608"], "tushare_trade_cal"))

    with pytest.raises(ValueError, match="not an SSE open trading day"):
        cal.resolve_next_trade_date_cn_sse_strict("2026-06-07")


def test_resolve_next_trade_date_strict_falls_back_to_akshare_when_tushare_missing(monkeypatch):
    from src.paper_trading import btst_trade_calendar as cal

    # Simulate tushare failure by making the loader raise, then provide akshare fallback dates.
    def _fake_loader(start_compact: str, end_compact: str):
        if start_compact == "tushare":
            raise RuntimeError("tushare down")
        return (["20260605", "20260608"], "akshare_sina")

    monkeypatch.setattr(cal, "_load_open_trade_dates_cn_sse", _fake_loader)

    resolved = cal.resolve_next_trade_date_cn_sse_strict("2026-06-05")
    assert resolved.next_trade_date_iso == "2026-06-08"
    assert resolved.calendar_source in {"akshare_sina", "tushare_trade_cal"}
```

- [ ] **Step 2: Run tests to confirm they fail (module not found)**

Run:

```bash
uv run pytest tests/test_btst_trade_calendar.py -v
```

Expected: FAIL with `ImportError` for `btst_trade_calendar`.

- [ ] **Step 3: Implement `btst_trade_calendar.py` (minimal to pass tests)**

Create `src/paper_trading/btst_trade_calendar.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd


CalendarSource = Literal["tushare_trade_cal", "akshare_sina"]


@dataclass(frozen=True)
class NextTradeDateResolution:
    signal_date_iso: str
    signal_date_compact: str
    next_trade_date_iso: str
    next_trade_date_compact: str
    calendar_source: CalendarSource


def _normalize_iso_date(value: str) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    raise ValueError(f"unsupported date: {value!r}")


def _compact(value: str) -> str:
    return _normalize_iso_date(value).replace("-", "")


def _extract_open_dates_from_frame(df: pd.DataFrame, start_compact: str, end_compact: str) -> list[str]:
    if df is None or df.empty:
        return []
    if "cal_date" in df.columns:
        values = [str(v) for v in df["cal_date"].tolist()]
    elif "trade_date" in df.columns:
        values = [pd.to_datetime(v).strftime("%Y%m%d") for v in df["trade_date"].tolist()]
    else:
        return []
    return sorted({v.replace("-", "")[:8] for v in values if v and start_compact <= v.replace("-", "")[:8] <= end_compact})


def _load_open_trade_dates_cn_sse(start_compact: str, end_compact: str) -> tuple[list[str], CalendarSource]:
    # Primary: tushare trade_cal (open days)
    try:
        from src.tools.tushare_api import _cached_tushare_dataframe_call, _get_pro

        pro = _get_pro()
        if pro is not None:
            df = _cached_tushare_dataframe_call(
                pro,
                "trade_cal",
                exchange="SSE",
                start_date=start_compact,
                end_date=end_compact,
                is_open=1,
                fields="cal_date,is_open",
            )
            dates = _extract_open_dates_from_frame(df, start_compact, end_compact)
            if dates:
                return dates, "tushare_trade_cal"
    except Exception:
        pass

    # Fallback: akshare sina trade-date history
    import akshare as ak

    df = ak.tool_trade_date_hist_sina()
    dates = _extract_open_dates_from_frame(df, start_compact, end_compact)
    if not dates:
        raise ValueError(f"Unable to load SSE open trade dates between {start_compact} and {end_compact}")
    return dates, "akshare_sina"


def resolve_next_trade_date_cn_sse_strict(signal_date: str, lookahead_days: int = 20) -> NextTradeDateResolution:
    signal_date_iso = _normalize_iso_date(signal_date)
    signal_compact = signal_date_iso.replace("-", "")
    start = signal_compact
    end = (datetime.strptime(signal_date_iso, "%Y-%m-%d") + timedelta(days=lookahead_days)).strftime("%Y%m%d")
    open_dates, source = _load_open_trade_dates_cn_sse(start, end)

    if signal_compact not in open_dates:
        raise ValueError(f"signal_date={signal_date_iso} is not an SSE open trading day")

    cursor_index = open_dates.index(signal_compact)
    if cursor_index + 1 >= len(open_dates):
        raise ValueError(f"Unable to resolve next trade date after {signal_date_iso}")

    next_compact = open_dates[cursor_index + 1]
    next_iso = f"{next_compact[:4]}-{next_compact[4:6]}-{next_compact[6:8]}"
    return NextTradeDateResolution(
        signal_date_iso=signal_date_iso,
        signal_date_compact=signal_compact,
        next_trade_date_iso=next_iso,
        next_trade_date_compact=next_compact,
        calendar_source=source,
    )
```

- [ ] **Step 4: Re-run tests and ensure pass**

Run:

```bash
uv run pytest tests/test_btst_trade_calendar.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paper_trading/btst_trade_calendar.py tests/test_btst_trade_calendar.py
git commit -m "feat: add strict CN-SSE next trade date resolver"
```

---

### Task 2: Update doc bundle default output directory + scheme_a flag + manifest

**Files:**
- Modify: `scripts/generate_btst_doc_bundle.py`
- Test: `tests/test_generate_btst_doc_bundle_script.py`

- [ ] **Step 1: Add a failing test for default output-dir naming + manifest emission**

Append to `tests/test_generate_btst_doc_bundle_script.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_generate_btst_doc_bundle_default_output_dir_uses_next_trade_date_and_manifest(tmp_path: Path, monkeypatch):
    import scripts.generate_btst_doc_bundle as bundle

    # Keep outputs under tmp_path
    monkeypatch.setattr(bundle, "OUTPUTS_DIR", tmp_path / "outputs")

    # Stub strict calendar resolution: 2026-05-26 -> 2026-05-27
    from src.paper_trading import btst_trade_calendar as cal

    monkeypatch.setattr(
        cal,
        "resolve_next_trade_date_cn_sse_strict",
        lambda *_args, **_kwargs: cal.NextTradeDateResolution(
            signal_date_iso="2026-05-26",
            signal_date_compact="20260526",
            next_trade_date_iso="2026-05-27",
            next_trade_date_compact="20260527",
            calendar_source="tushare_trade_cal",
        ),
    )

    # Reuse an existing fixture builder from this test file: we only need a minimal report_dir with brief + full_report.
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_20260526_20260526_live_m2_7_short_trade_only_20260527_plan"
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"

    def _write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    _write_json(
        report_dir / "session_summary.json",
        {
            "trade_date": "2026-05-26",
            "selection_target": "short_trade_only",
            "btst_followup": {"brief_json": brief_path.as_posix()},
        },
    )
    _write_json(
        brief_path,
        {
            "trade_date": "2026-05-26",
            "next_trade_date": "2026-05-27",
            "selection_target": "short_trade_only",
            "primary_action": {"ticker": "300054", "name": "鼎龙股份", "preferred_entry_mode": "confirm_then_hold_breakout"},
            "selected_actions": [{"ticker": "300054", "name": "鼎龙股份", "action_tier": "primary_entry", "preferred_entry_mode": "confirm_then_hold_breakout", "score_target": 0.55, "historical_prior": {"applied_scope": "same_ticker", "evaluable_count": 10, "next_close_positive_rate": 0.6, "next_close_payoff_ratio": 1.2, "next_close_expectancy": 0.01, "sample_count": 12}}],
            "watch_actions": [],
            "opportunity_actions": [],
        },
    )
    _write_json(
        reports_root / "btst_full_report_20260526.json",
        {"trade_date": "20260526", "next_date": "20260527", "pool_size": 1, "selected_count": 1, "near_miss_count": 0, "high_confidence": []},
    )
    _write_json(
        reports_root / "btst_early_runner_v1_latest.json",
        {"daily_boards": [], "status": "unavailable"},
    )

    result = bundle.generate_btst_doc_bundle(
        "20260526",
        reports_root=reports_root,
        output_dir=None,
        refresh_early_runner=False,
        include_extra_warning_docs=True,
        scheme_a_active=True,
    )

    expected_dir = (tmp_path / "outputs" / "202605" / "20260526_scheme_a")
    assert Path(result["output_dir"]) == expected_dir.resolve()

    manifest_path = expected_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["signal_date"] == "20260526"
    assert manifest["next_trade_date"] == "20260527"
    assert manifest["scheme_a_active"] is True
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run:

```bash
uv run pytest tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_default_output_dir_uses_next_trade_date_and_manifest -v
```

Expected: FAIL because `scheme_a_active` doesn’t exist, default output dir naming is old, and manifest is missing.

- [ ] **Step 3: Implement output-dir resolver + scheme_a flag + strict date validation + manifest**

Modify `scripts/generate_btst_doc_bundle.py`:

1) Extend signature:

```python
def generate_btst_doc_bundle(
    signal_date: str,
    *,
    ...,
    include_extra_warning_docs: bool = True,
    strategy_thresholds_config_path: str | Path | None = None,
    strategy_thresholds_profile: str = DEFAULT_STRATEGY_THRESHOLDS_PROFILE,
    write_review_ledger: bool = False,
    scheme_a_active: bool = False,
) -> dict[str, Any]:
```

2) Right after `signal_date_iso` is known and `brief` is loaded, validate and canonicalize dates:

```python
from src.paper_trading.btst_trade_calendar import resolve_next_trade_date_cn_sse_strict

resolution = resolve_next_trade_date_cn_sse_strict(signal_date_iso)
expected_next_iso = resolution.next_trade_date_iso
brief_next_iso = str(brief.get("next_trade_date") or "").strip()
if brief_next_iso and brief_next_iso != expected_next_iso:
    raise ValueError(f"next_trade_date mismatch: brief={brief_next_iso} calendar={expected_next_iso}")
```

3) Replace default output dir computation with new naming:

```python
if output_dir:
    target_output_dir = Path(output_dir).expanduser().resolve()
else:
    month_prefix = signal_date_compact[:6]
    leaf = f"{signal_date_compact}_scheme_a" if scheme_a_active else signal_date_compact
    target_output_dir = (OUTPUTS_DIR / month_prefix / leaf).resolve()
```

4) Emit `manifest.json` after writing docs:

```python
from datetime import datetime

primary = _resolve_primary_semantic_action(semantic_selected, report_mode=report_mode)
manifest = {
    "signal_date": signal_date_compact,
    "next_trade_date": resolution.next_trade_date_compact,
    "signal_date_iso": signal_date_iso,
    "next_trade_date_iso": resolution.next_trade_date_iso,
    "market": "CN-SSE",
    "calendar_source": resolution.calendar_source,
    "scheme_a_active": bool(scheme_a_active),
    "output_dir": target_output_dir.as_posix(),
    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "execution_contract_summary": {
        "effective_trade_bias": control_tower.get("effective_trade_bias"),
        "report_mode": report_mode,
        "release_authority": primary.get("release_authority"),
    },
}
_write_text(target_output_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
```

5) Wire CLI `--scheme-a` into `main()`:

```python
parser.add_argument("--scheme-a", action="store_true", help="Mark output dir as scheme_a when using default output dir")
...
result = generate_btst_doc_bundle(
    ...,
    scheme_a_active=bool(args.scheme_a),
)
```

- [ ] **Step 4: Re-run the failing test and ensure it passes**

Run:

```bash
uv run pytest tests/test_generate_btst_doc_bundle_script.py::test_generate_btst_doc_bundle_default_output_dir_uses_next_trade_date_and_manifest -v
```

Expected: PASS.

- [ ] **Step 5: Run the focused existing suite to ensure no regression**

Run:

```bash
uv run pytest tests/test_generate_btst_doc_bundle_script.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_btst_doc_bundle.py tests/test_generate_btst_doc_bundle_script.py
git commit -m "feat: default BTST outputs by next trade date with manifest"
```

---

### Task 3: Align follow-up next-trade-date inference with strict calendar resolver

**Files:**
- Modify: `src/paper_trading/btst_reporting_utils.py`
- Test: `tests/test_generate_btst_next_day_trade_brief_script.py`

- [ ] **Step 1: Add a failing test that weekend inference uses calendar (not weekday-only fallback)**

In `tests/test_generate_btst_next_day_trade_brief_script.py`, add:

```python
import pytest


def test_infer_next_trade_date_uses_strict_calendar_when_available(monkeypatch):
    from src.paper_trading import btst_reporting_utils as utils
    from src.paper_trading import btst_trade_calendar as cal

    monkeypatch.setattr(
        cal,
        "resolve_next_trade_date_cn_sse_strict",
        lambda *_args, **_kwargs: cal.NextTradeDateResolution(
            signal_date_iso="2026-06-05",
            signal_date_compact="20260605",
            next_trade_date_iso="2026-06-08",
            next_trade_date_compact="20260608",
            calendar_source="tushare_trade_cal",
        ),
    )

    assert utils.infer_next_trade_date("2026-06-05") == "2026-06-08"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py::test_infer_next_trade_date_uses_strict_calendar_when_available -v
```

Expected: FAIL until implementation updated.

- [ ] **Step 3: Update `infer_next_trade_date()` to prefer strict resolver when possible**

Modify `src/paper_trading/btst_reporting_utils.py`:

```python
def infer_next_trade_date(trade_date: str | None, lookahead_days: int = 14) -> str | None:
    normalized = _normalize_trade_date(trade_date)
    if not normalized:
        return None

    try:
        from src.paper_trading.btst_trade_calendar import resolve_next_trade_date_cn_sse_strict

        return resolve_next_trade_date_cn_sse_strict(normalized, lookahead_days=lookahead_days).next_trade_date_iso
    except Exception:
        pass

    # Keep legacy fallback logic as last resort
    ...
```

- [ ] **Step 4: Re-run the new test and the existing brief suite**

Run:

```bash
uv run pytest tests/test_generate_btst_next_day_trade_brief_script.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paper_trading/btst_reporting_utils.py tests/test_generate_btst_next_day_trade_brief_script.py
git commit -m "feat: infer next trade date via strict SSE calendar"
```

---

### Task 4: Update user-facing docs to new single-date + directory rules

**Files:**
- Modify: `docs/prompt/often/btst_daily_report.md`
- Modify: `docs/plans/2026-05-27-early-runner-scheme-a-operations.md`

- [ ] **Step 1: Update `docs/prompt/often/btst_daily_report.md` templates**

Replace the “推荐默认模板” with the single-date template and remove the requirement to type both dates and explicit paths.

Example block to insert:

```text
使用 ai-hedge-fund-btst skill，基于 YYYY-MM-DD 收盘数据，为下一交易日生成 BTST 全套中文文档，并继续生成 opening watch card 和 premarket execution card。保存到默认推荐目录；如果方案 A 当前激活，自动输出到 scheme_a 目录。
（可选一致性校验：目标交易日=YYYY-MM-DD）
```

- [ ] **Step 2: Update scheme_a operations doc directory section**

In `docs/plans/2026-05-27-early-runner-scheme-a-operations.md`, replace:

- `outputs/YYYYMM/YYYYMMDD_scheme_a/`

with:

- `outputs/<signal_yyyymm>/<signal_yyyymmdd>_scheme_a/`

And update the command examples accordingly.

- [ ] **Step 3: Commit**

```bash
git add docs/prompt/often/btst_daily_report.md docs/plans/2026-05-27-early-runner-scheme-a-operations.md
git commit -m "docs: switch BTST daily templates to single-date output dirs"
```

---

## Plan Self-Review (run after writing code)

- Spec coverage:
  - Single required date: Task 2 + docs updates.
  - Strict calendar + weekend/holiday: Task 1 + Task 3.
  - New output dirs by next_trade_date + scheme_a marker: Task 2.
  - manifest.json: Task 2.
  - Docs updates: Task 4.

- Placeholder scan: none (no TODO/TBD).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-02-btst-single-date-output-dirs.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks
2. **Inline Execution** - execute tasks in this session with checkpoints
