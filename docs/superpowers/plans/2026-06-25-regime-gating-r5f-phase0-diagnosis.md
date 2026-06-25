# R-5.F Phase 0 (state_type 诊断) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建并运行 Phase 0 诊断，回答 R-5.F 设计 spec 的三个问题（state_type 是否 discriminative / 震荡市是否有可识别赢面子集 / 该子集是否样本外稳健），产出诊断结论决定 Phase 1 走 1A 精选 / 1B 保守 / 停止。

**Architecture:** 镜像现有 `src/screening/regime_calibration.py`（把 `regime_gate_level` 轴换成 `state_type` 轴），新增 score-bucket 细分（问2）与留一时段样本外验证（问3）。可测试的统计逻辑放永久模块 `src/screening/state_type_calibration.py`，一次性 CLI runner 放 `scripts/_diag_state_type_winrate.py`。诊断结论出来前不动任何 gate 代码（spec 铁律）。

**Tech Stack:** Python 3.11–3.12，pytest TDD，纯标准库统计（无 numpy/pandas 依赖），复用 `consecutive_recommendation.load_auto_screening_history` / `load_tracking_history`。

## Global Constraints

- **行宽 420**（black + flake8，CLAUDE.md 明确，勿改）
- **类型注解** PEP 484 全程；所有公共函数有签名
- **诊断纪律**：本计划只产出诊断脚本与结论；**不得修改 `investability.py` 的 `build_front_door_verdict` 或任何 gate 逻辑**（那是 Phase 1，另起计划）
- **样本诚实**：所有胜率同时报告 median（R-6/R-7 异常值教训）；任何分组 n < 20 标 "evidence_insufficient"，不强行下结论
- **state_type 归一化**：大小写不敏感，归一到 `{TREND, RANGE, MIXED, CRISIS}`，其余归 `OTHER`
- **TDD RED→GREEN**：每个统计函数先用合成数据写失败测试
- **回归底线**：每个 task 结束跑 `tests/screening/` 全绿（owner 因子改动后基线 1683 绿）

## File Structure

| 文件 | 职责 | 新建/修改 |
|---|---|---|
| `src/screening/state_type_calibration.py` | 可测试统计核心：date→state_type 映射、问1总体区分度、问2 bucket 细分、问3 留一时段验证、verdict 聚合 | 新建 |
| `tests/screening/test_state_type_calibration.py` | 合成数据 TDD（含已知分布验证留一时段逻辑正确） | 新建 |
| `scripts/_diag_state_type_winrate.py` | 一次性 CLI runner：加载数据→跑三问→打印+保存 JSON 报告（`_` 前缀惯例，诊断完可删） | 新建 |

**数据流**：`load_auto_screening_history` → `{date → state_type}` 映射；`load_tracking_history` → 记录（`recommended_date` + `score_b` + `next_30day_return`）；两者按 date join，按 state_type / bucket 分组算胜率。

---

### Task 1: date→state_type 映射 + 问1 总体区分度

**Files:**
- Create: `src/screening/state_type_calibration.py`
- Test: `tests/screening/test_state_type_calibration.py`

**Interfaces:**
- Consumes: `load_auto_screening_history` / `load_tracking_history` from `src.screening.consecutive_recommendation`（签名见 `regime_calibration.py:101-113`）
- Produces: `_build_date_state_type_map(history) -> dict[str,str]`；`compute_state_type_calibration(*, reports_dir, lookback_days) -> StateTypeCalibrationReport`；dataclass `StateTypeWinRate`、`StateTypeCalibrationReport`

- [ ] **Step 1: Write failing test — date→state_type map**

```python
# tests/screening/test_state_type_calibration.py
from src.screening.state_type_calibration import _build_date_state_type_map


def test_build_date_state_type_map_reads_state_type_from_payload():
    history = [
        {"date": "2025-06-01", "payload": {"market_state": {"state_type": "TREND"}}},
        {"date": "20250602", "payload": {"market_state": {"state_type": "range"}}},
        {"date": "20250603", "payload": {"market_state": {}}},  # 缺 state_type → OTHER
    ]
    mapping = _build_date_state_type_map(history)
    assert mapping == {"20250601": "TREND", "20250602": "RANGE", "20250603": "OTHER"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py::test_build_date_state_type_map_reads_state_type_from_payload -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.screening.state_type_calibration'`

- [ ] **Step 3: Implement map + normalization helper**

```python
# src/screening/state_type_calibration.py
"""R-5.F Phase 0: 按 state_type 分组的 T+30 条件胜率诊断.

镜像 src/screening/regime_calibration.py, 但把分组轴从 regime_gate_level
换成 market_state.state_type (TREND/RANGE/MIXED/CRISIS). R-5.D 多时段诊断
表明胜率由'上涨 vs 震荡'驱动; state_type (TREND=全面上涨) 是比 regime_gate_level
更 discriminative 的轴. 本模块为 R-5.F gate 提供诊断证据, 不改 gate 代码.

三问:
  Q1 state_type 总体区分度 (TREND vs RANGE/MIXED T+30 胜率差异)
  Q2 震荡市(RANGE/MIXED)内 score-bucket 细分, 是否有高胜率子集
  Q3 该子集留一时段样本外是否稳健 (防 in-sample 过拟合, v1/v2 教训)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_VALID_STATE_TYPES: tuple[str, ...] = ("TREND", "RANGE", "MIXED", "CRISIS")


def _normalize_state_type(raw: Any) -> str:
    """大小写不敏感归一到 {TREND,RANGE,MIXED,CRISIS}, 其余 OTHER."""
    s = str(raw or "").strip().upper()
    return s if s in _VALID_STATE_TYPES else "OTHER"


def _build_date_state_type_map(history: list[dict[str, Any]]) -> dict[str, str]:
    """从 auto_screening 历史构建 {date_compact → state_type} 映射."""
    mapping: dict[str, str] = {}
    for item in history:
        date_raw = str(item.get("date", "") or "").replace("-", "")
        payload = item.get("payload", {}) or {}
        market_state = payload.get("market_state") if isinstance(payload, dict) else {}
        market_state = market_state or {}
        if date_raw:
            mapping[date_raw] = _normalize_state_type(market_state.get("state_type"))
    return mapping
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py::test_build_date_state_type_map_reads_state_type_from_payload -v`
Expected: PASS

- [ ] **Step 5: Write failing test — Q1 overall discrimination (with median)**

```python
from src.screening.state_type_calibration import compute_state_type_calibration, StateTypeCalibrationReport


def test_q1_groups_t30_by_state_type_with_winrate_and_median(tmp_path):
    # 构造 1 份 auto_screening 历史 (2 个日期, 2 种 state_type)
    history = [
        {"date": "20250601", "payload": {"market_state": {"state_type": "TREND"}}},
        {"date": "20250602", "payload": {"market_state": {"state_type": "RANGE"}}},
    ]
    # tracking_history: 20250601(TREND) 两只都涨; 20250602(RANGE) 两只都跌
    records = [
        {"recommended_date": "20250601", "score_b": 0.5, "next_30day_return": 5.0},
        {"recommended_date": "20250601", "score_b": 0.4, "next_30day_return": 3.0},
        {"recommended_date": "20250602", "score_b": 0.5, "next_30day_return": -4.0},
        {"recommended_date": "20250602", "score_b": 0.4, "next_30day_return": -2.0},
    ]
    # 用 monkeypatch 替换数据加载, 避免依赖真实报告目录
    import src.screening.state_type_calibration as mod

    orig_history = mod._load_history_for_test  # 见 Step 6 注入点
    # (Step 6 会提供可注入的加载入口; 这里先通过 reports_dir 路径下的文件测试)
```

> 注：为避免测试依赖真实报告文件，Step 6 会把数据加载拆成可注入的纯函数 `_compute_from_loaded(history, records)`，测试直接喂合成数据。先写 Step 6 的注入入口再回来写本测试断言。**调整顺序：先做 Step 6 的纯函数 + 其测试，再做 reports_dir 包装。** 见下方 Step 6。

- [ ] **Step 6: Implement Q1 pure function (injectable) + dataclasses**

```python
# 追加到 src/screening/state_type_calibration.py

@dataclass
class StateTypeWinRate:
    state_type: str
    t30_win_rate: float | None = None
    t30_avg_return: float | None = None
    t30_median_return: float | None = None  # R-6/R-7: median 防 异常值污染
    sample_count: int = 0
    mature_t30_count: int = 0


@dataclass
class StateTypeCalibrationReport:
    rows: list[StateTypeWinRate] = field(default_factory=list)
    unknown_state_type_count: int = 0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _win_rate_or_none(returns: list[float]) -> float | None:
    return (sum(1 for x in returns if x > 0) / len(returns)) if returns else None


def _mean_or_none(returns: list[float]) -> float | None:
    return (sum(returns) / len(returns)) if returns else None


def _median_or_none(returns: list[float]) -> float | None:
    if not returns:
        return None
    s = sorted(returns)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def compute_state_type_calibration_from_loaded(
    history: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> StateTypeCalibrationReport:
    """纯函数: 用已加载的 history + tracking records 算问1报告 (可注入测试)."""
    date_st = _build_date_state_type_map(history)
    by_st_returns: dict[str, list[float]] = {}
    by_st_count: dict[str, int] = {}
    unknown = 0
    for rec in records:
        date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
        st = date_st.get(date_raw)
        if st is None:
            unknown += 1
            continue
        by_st_count[st] = by_st_count.get(st, 0) + 1
        t30 = _optional_float(rec.get("next_30day_return"))
        if t30 is not None:
            by_st_returns.setdefault(st, []).append(t30)
    ordered = list(_VALID_STATE_TYPES) + sorted(set(by_st_count) - set(_VALID_STATE_TYPES))
    rows: list[StateTypeWinRate] = []
    for st in ordered:
        if st not in by_st_count:
            continue
        rets = by_st_returns.get(st, [])
        rows.append(
            StateTypeWinRate(
                state_type=st,
                t30_win_rate=_win_rate_or_none(rets),
                t30_avg_return=_mean_or_none(rets),
                t30_median_return=_median_or_none(rets),
                sample_count=by_st_count[st],
                mature_t30_count=len(rets),
            )
        )
    return StateTypeCalibrationReport(rows=rows, unknown_state_type_count=unknown)


def compute_state_type_calibration(
    *,
    reports_dir: Path | None = None,
    lookback_days: int = 30,
) -> StateTypeCalibrationReport:
    """从报告目录加载数据算问1 (镜像 compute_regime_calibration 的 IO 包装)."""
    from src.screening.consecutive_recommendation import (
        load_auto_screening_history,
        load_tracking_history,
        resolve_report_dir,
    )

    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(lookback_days=lookback_days, report_dir=search_dir)
    records = load_tracking_history(search_dir)
    return compute_state_type_calibration_from_loaded(history, records)
```

对应测试（替换 Step 5 的占位，改测纯函数）：

```python
def test_q1_groups_t30_by_state_type_with_winrate_and_median():
    history = [
        {"date": "20250601", "payload": {"market_state": {"state_type": "TREND"}}},
        {"date": "20250602", "payload": {"market_state": {"state_type": "RANGE"}}},
    ]
    records = [
        {"recommended_date": "20250601", "score_b": 0.5, "next_30day_return": 5.0},
        {"recommended_date": "20250601", "score_b": 0.4, "next_30day_return": 3.0},
        {"recommended_date": "20250602", "score_b": 0.5, "next_30day_return": -4.0},
        {"recommended_date": "20250602", "score_b": 0.4, "next_30day_return": -2.0},
    ]
    report = compute_state_type_calibration_from_loaded(history, records)
    by_st = {r.state_type: r for r in report.rows}
    assert by_st["TREND"].t30_win_rate == 1.0
    assert by_st["TREND"].t30_median_return == 4.0
    assert by_st["RANGE"].t30_win_rate == 0.0
    assert by_st["RANGE"].t30_median_return == -3.0
```

- [ ] **Step 7: Run Q1 test to verify it passes**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add src/screening/state_type_calibration.py tests/screening/test_state_type_calibration.py
git commit -m "feat(R-5.F Phase0): state_type 条件胜率问1 — 总体区分度 (winrate+median)"
```

---

### Task 2: 问2 — 震荡市内 score-bucket 细分

**Files:**
- Modify: `src/screening/state_type_calibration.py`
- Test: `tests/screening/test_state_type_calibration.py`

**Interfaces:**
- Consumes: Task 1 的 `_build_date_state_type_map`、`_optional_float`、`_win_rate_or_none`、`_median_or_none`
- Produces: `_score_bucket(score_b) -> str`；`StateTypeBucketWinRate` dataclass；`compute_state_type_bucket_subdivision(history, records, target_state_types) -> list[StateTypeBucketWinRate]`

- [ ] **Step 1: Write failing test — score bucketing**

```python
from src.screening.state_type_calibration import _score_bucket


def test_score_bucket_bands():
    assert _score_bucket(None) == "unknown"
    assert _score_bucket(0.10) == "low"
    assert _score_bucket(0.29) == "low"
    assert _score_bucket(0.30) == "mid_low"
    assert _score_bucket(0.39) == "mid_low"
    assert _score_bucket(0.40) == "mid_high"
    assert _score_bucket(0.499) == "mid_high"
    assert _score_bucket(0.50) == "high"
    assert _score_bucket(0.90) == "high"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py::test_score_bucket_bands -v`
Expected: FAIL — `ImportError: cannot import name '_score_bucket'`

- [ ] **Step 3: Implement `_score_bucket`**

```python
# 追加到 src/screening/state_type_calibration.py

# bucket 边界对齐 dynamic_threshold.py 的 _DEFAULT_*_THRESHOLD (0.30/0.15/0.60)
# 与 BUY 门控 (composite >= 0.5). 实现时确认: grep "_DEFAULT_BASE_THRESHOLD\|0.5.*BUY" src/screening/
def _score_bucket(score_b: Any) -> str:
    s = _optional_float(score_b)
    if s is None:
        return "unknown"
    if s < 0.30:
        return "low"
    if s < 0.40:
        return "mid_low"
    if s < 0.50:
        return "mid_high"
    return "high"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py::test_score_bucket_bands -v`
Expected: PASS

- [ ] **Step 5: Write failing test — bucket subdivision within RANGE/MIXED**

```python
from src.screening.state_type_calibration import compute_state_type_bucket_subdivision


def test_q2_subdivides_target_state_types_by_score_bucket():
    history = [
        {"date": "20250601", "payload": {"market_state": {"state_type": "RANGE"}}},
    ]
    # RANGE 市内: high bucket 两只都涨, low bucket 两只都跌
    records = [
        {"recommended_date": "20250601", "score_b": 0.55, "next_30day_return": 6.0},
        {"recommended_date": "20250601", "score_b": 0.60, "next_30day_return": 4.0},
        {"recommended_date": "20250601", "score_b": 0.10, "next_30day_return": -5.0},
        {"recommended_date": "20250601", "score_b": 0.20, "next_30day_return": -3.0},
    ]
    rows = compute_state_type_bucket_subdivision(history, records, target_state_types=("RANGE",))
    by_bucket = {(r.state_type, r.bucket): r for r in rows}
    assert by_bucket[("RANGE", "high")].t30_win_rate == 1.0
    assert by_bucket[("RANGE", "low")].t30_win_rate == 0.0
    assert by_bucket[("RANGE", "high")].sample_count == 2
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py::test_q2_subdivides_target_state_types_by_score_bucket -v`
Expected: FAIL — `ImportError`

- [ ] **Step 7: Implement bucket subdivision**

```python
# 追加到 src/screening/state_type_calibration.py

@dataclass
class StateTypeBucketWinRate:
    state_type: str
    bucket: str
    t30_win_rate: float | None = None
    t30_avg_return: float | None = None
    t30_median_return: float | None = None
    sample_count: int = 0
    mature_t30_count: int = 0


def compute_state_type_bucket_subdivision(
    history: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    target_state_types: tuple[str, ...] = ("RANGE", "MIXED"),
) -> list[StateTypeBucketWinRate]:
    """问2: 在 target_state_types 子集内按 score bucket 细分算 T+30 胜率.

    找'震荡市里仍有高胜率'的 bucket (结构性机会). n < 20 的单元标 evidence_insufficient.
    """
    date_st = _build_date_state_type_map(history)
    target = {s.upper() for s in target_state_types}
    # key: (state_type, bucket) -> list[return]
    by_cell_returns: dict[tuple[str, str], list[float]] = {}
    by_cell_count: dict[tuple[str, str], int] = {}
    for rec in records:
        date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
        st = date_st.get(date_raw)
        if st is None or st not in target:
            continue
        bucket = _score_bucket(rec.get("score_b"))
        key = (st, bucket)
        by_cell_count[key] = by_cell_count.get(key, 0) + 1
        t30 = _optional_float(rec.get("next_30day_return"))
        if t30 is not None:
            by_cell_returns.setdefault(key, []).append(t30)
    rows: list[StateTypeBucketWinRate] = []
    for (st, bucket), count in sorted(by_cell_count.items()):
        rets = by_cell_returns.get((st, bucket), [])
        rows.append(
            StateTypeBucketWinRate(
                state_type=st,
                bucket=bucket,
                t30_win_rate=_win_rate_or_none(rets),
                t30_avg_return=_mean_or_none(rets),
                t30_median_return=_median_or_none(rets),
                sample_count=count,
                mature_t30_count=len(rets),
            )
        )
    return rows
```

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Commit**

```bash
git add src/screening/state_type_calibration.py tests/screening/test_state_type_calibration.py
git commit -m "feat(R-5.F Phase0): 问2 — 震荡市内 score-bucket 细分找结构性赢面子集"
```

---

### Task 3: 问3 — 留一时段样本外验证（防过拟合核心）

**Files:**
- Modify: `src/screening/state_type_calibration.py`
- Test: `tests/screening/test_state_type_calibration.py`

**Interfaces:**
- Consumes: Task 1 `_build_date_state_type_map`、`_optional_float`、`_win_rate_or_none`；Task 2 `_score_bucket`
- Produces: `LopoHeldoutResult` dataclass；`LopoReport` dataclass；`leave_one_period_out_validation(history, records, target_state_types, min_n) -> LopoReport`

**逻辑**：问2 在全样本上发现"震荡市某 bucket 胜率高"。问3 验证它不是 in-sample 假象：每次留出一个日期（时段），用**其余日期**重新发现胜率最高的 bucket，再在该留出日期上测该 bucket 的胜率。若同一 bucket 在多数留出日期上仍维持高胜率 → 稳健；否则 → 过拟合假象。

- [ ] **Step 1: Write failing test — known-distribution: real signal is rediscovered out-of-sample**

```python
from src.screening.state_type_calibration import leave_one_period_out_validation


def test_q3_lopo_rediscovers_real_signal_out_of_sample():
    # 3 个 RANGE 日期; 每个日期内 high bucket 涨、low bucket 跌 (跨所有日期一致)
    history = [
        {"date": f"2025060{d}", "payload": {"market_state": {"state_type": "RANGE"}}}
        for d in (1, 2, 3)
    ]
    records = []
    for d in (1, 2, 3):
        records += [
            {"recommended_date": f"2025060{d}", "score_b": 0.55, "next_30day_return": 6.0},
            {"recommended_date": f"2025060{d}", "score_b": 0.10, "next_30day_return": -5.0},
        ]
    report = leave_one_period_out_validation(history, records, target_state_types=("RANGE",), min_n=1)
    # 每次留出一个日期, 用其余两日发现 high 是赢家 → high 在留出日也应高胜率
    assert report.heldout_periods == 3
    assert report.rediscovered_winner_rate == 1.0  # 3/3 留出日 high 都被重新发现并维持
    assert report.robust is True


def test_q3_lopo_rejects_in_sample_artifact():
    # high bucket 只在整体均值上看起来好, 但逐留出日不稳定 (噪音)
    # 日期1: high 涨; 日期2: high 跌; 日期3: high 涨 → 留出时无法稳定重发现
    history = [
        {"date": f"2025060{d}", "payload": {"market_state": {"state_type": "RANGE"}}}
        for d in (1, 2, 3)
    ]
    records = []
    rets_by_day = {"1": 6.0, "2": -7.0, "3": 5.0}
    for d, ret in rets_by_day.items():
        records.append({"recommended_date": f"2025060{d}", "score_b": 0.55, "next_30day_return": ret})
        records.append({"recommended_date": f"2025060{d}", "score_b": 0.10, "next_30day_return": -1.0})
    report = leave_one_period_out_validation(history, records, target_state_types=("RANGE",), min_n=1)
    assert report.robust is False  # high 在留出日胜率不稳定
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py -k lopo -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement leave-one-period-out**

```python
# 追加到 src/screening/state_type_calibration.py

@dataclass
class LopoHeldoutResult:
    heldout_date: str
    rediscovered_winner_bucket: str | None  # 用非留出日数据发现的赢家 bucket
    heldout_winner_winrate: float | None    # 该赢家 bucket 在留出日的胜率
    heldout_n: int


@dataclass
class LopoReport:
    target_state_types: tuple[str, ...]
    heldout_periods: int = 0
    rediscovered_winner_rate: float = 0.0   # 留出日赢家仍维持高胜率(>=0.5)的比例
    robust: bool = False
    heldout_results: list[LopoHeldoutResult] = field(default_factory=list)


def _bucket_returns_by_date(
    records: list[dict[str, Any]], date_st: dict[str, str], target: set[str]
) -> dict[str, dict[str, list[float]]]:
    """→ {date: {bucket: [returns]}} 仅 target state_type."""
    out: dict[str, dict[str, list[float]]] = {}
    for rec in records:
        date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
        st = date_st.get(date_raw)
        if st is None or st not in target:
            continue
        bucket = _score_bucket(rec.get("score_b"))
        t30 = _optional_float(rec.get("next_30day_return"))
        if t30 is None:
            continue
        out.setdefault(date_raw, {}).setdefault(bucket, []).append(t30)
    return out


def leave_one_period_out_validation(
    history: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    target_state_types: tuple[str, ...] = ("RANGE", "MIXED"),
    min_n: int = 20,
    winner_winrate_floor: float = 0.5,
) -> LopoReport:
    """问3: 留一时段样本外验证问2发现的赢家 bucket 是否稳健.

    每次留出一个日期 d: 用其余日期数据找 (胜率最高 且 n>=min_n 的 bucket) 作'赢家',
    再在留出日 d 上测该赢家 bucket 胜率. 若留出日胜率 >= winner_winrate_floor 计'维持'.
    """
    date_st = _build_date_state_type_map(history)
    target = {s.upper() for s in target_state_types}
    by_date = _bucket_returns_by_date(records, date_st, target)
    dates = sorted(by_date.keys())
    heldout: list[LopoHeldoutResult] = []
    maintained = 0
    for d in dates:
        # 训练 = 所有非 d 日期的 bucket 汇总
        train: dict[str, list[float]] = {}
        for other, buckets in by_date.items():
            if other == d:
                continue
            for bucket, rets in buckets.items():
                train.setdefault(bucket, []).extend(rets)
        # 发现赢家: 胜率最高 且 样本 >= min_n
        winner: str | None = None
        winner_wr: float | None = None
        for bucket, rets in train.items():
            if len(rets) < min_n:
                continue
            wr = _win_rate_or_none(rets)
            if wr is not None and (winner_wr is None or wr > winner_wr):
                winner, winner_wr = bucket, wr
        # 在留出日测赢家
        heldout_rets = by_date[d].get(winner, []) if winner else []
        held_wr = _win_rate_or_none(heldout_rets)
        heldout.append(
            LopoHeldoutResult(
                heldout_date=d,
                rediscovered_winner_bucket=winner,
                heldout_winner_winrate=held_wr,
                heldout_n=len(heldout_rets),
            )
        )
        if held_wr is not None and held_wr >= winner_winrate_floor:
            maintained += 1
    rate = (maintained / len(dates)) if dates else 0.0
    return LopoReport(
        target_state_types=target_state_types,
        heldout_periods=len(dates),
        rediscovered_winner_rate=rate,
        robust=bool(dates) and rate >= 0.6,  # 60%+ 留出日维持才算稳健
        heldout_results=heldout,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/screening/state_type_calibration.py tests/screening/test_state_type_calibration.py
git commit -m "feat(R-5.F Phase0): 问3 — 留一时段样本外验证 (防 in-sample 过拟合)"
```

---

### Task 4: verdict 聚合 + CLI runner

**Files:**
- Modify: `src/screening/state_type_calibration.py`
- Create: `scripts/_diag_state_type_winrate.py`
- Test: `tests/screening/test_state_type_calibration.py`

**Interfaces:**
- Consumes: Task 1/2/3 全部产出
- Produces: `DiagnosisVerdict` dataclass；`run_state_type_diagnosis(*, reports_dir, lookback_days) -> DiagnosisVerdict`；CLI `scripts/_diag_state_type_winrate.py`

- [ ] **Step 1: Write failing test — verdict aggregation maps to 1A/1B/STOP**

```python
from src.screening.state_type_calibration import (
    StateTypeCalibrationReport, StateTypeWinRate, LopoReport, DiagnosisVerdict,
    aggregate_verdict,
)


def test_verdict_stop_when_state_type_not_discriminative():
    # 问1 no: TREND 与 RANGE 胜率接近 (< 10pp 差)
    q1 = StateTypeCalibrationReport(rows=[
        StateTypeWinRate("TREND", t30_win_rate=0.45, mature_t30_count=60),
        StateTypeWinRate("RANGE", t30_win_rate=0.43, mature_t30_count=80),
    ])
    verdict = aggregate_verdict(q1=q1, q2_best_bucket_winrate=None, q3=LopoReport(target_state_types=("RANGE",), robust=False))
    assert verdict.phase1_branch == "STOP"
    assert "state_type not discriminative" in verdict.reason.lower()


def test_verdict_1a_when_all_three_yes():
    q1 = StateTypeCalibrationReport(rows=[
        StateTypeWinRate("TREND", t30_win_rate=0.80, mature_t30_count=60),
        StateTypeWinRate("RANGE", t30_win_rate=0.25, mature_t30_count=80),
    ])
    q3 = LopoReport(target_state_types=("RANGE",), robust=True, rediscovered_winner_rate=0.8, heldout_periods=10)
    verdict = aggregate_verdict(q1=q1, q2_best_bucket_winrate=0.62, q3=q3)
    assert verdict.phase1_branch == "1A"
    assert verdict.reason  # non-empty


def test_verdict_1b_when_q1_yes_but_no_robust_subset():
    q1 = StateTypeCalibrationReport(rows=[
        StateTypeWinRate("TREND", t30_win_rate=0.80, mature_t30_count=60),
        StateTypeWinRate("RANGE", t30_win_rate=0.25, mature_t30_count=80),
    ])
    q3 = LopoReport(target_state_types=("RANGE",), robust=False)
    verdict = aggregate_verdict(q1=q1, q2_best_bucket_winrate=0.40, q3=q3)
    assert verdict.phase1_branch == "1B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py -k verdict -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement verdict aggregation**

```python
# 追加到 src/screening/state_type_calibration.py

@dataclass
class DiagnosisVerdict:
    phase1_branch: str  # "1A" | "1B" | "STOP"
    reason: str
    q1_trend_winrate: float | None = None
    q1_choppy_winrate: float | None = None
    q1_discriminative: bool = False
    q2_best_bucket: str | None = None
    q2_best_bucket_winrate: float | None = None
    q3_robust: bool = False


_Q1_MIN_GAP = 0.10   # TREND vs RANGE/MIXED 胜率差 >= 10pp 才算 discriminative
_Q1_MIN_N = 20
_Q2_WINNER_FLOOR = 0.50  # 震荡市赢家 bucket 胜率门槛


def _q1_is_discriminative(q1: StateTypeCalibrationReport) -> tuple[bool, float | None, float | None]:
    by_st = {r.state_type: r for r in q1.rows}
    trend = by_st.get("TREND")
    choppy_rows = [r for r in q1.rows if r.state_type in ("RANGE", "MIXED") and r.mature_t30_count >= _Q1_MIN_N]
    if not trend or trend.mature_t30_count < _Q1_MIN_N or not choppy_rows:
        return False, (trend.t30_win_rate if trend else None), None
    choppy_wr = min(r.t30_win_rate or 0.0 for r in choppy_rows)
    discriminative = (trend.t30_win_rate or 0.0) - choppy_wr >= _Q1_MIN_GAP
    return discriminative, trend.t30_win_rate, choppy_wr


def aggregate_verdict(
    *,
    q1: StateTypeCalibrationReport,
    q2_best_bucket_winrate: float | None,
    q3: LopoReport,
) -> DiagnosisVerdict:
    """按 spec §九 映射表聚合三问结论 → 1A / 1B / STOP."""
    discriminative, trend_wr, choppy_wr = _q1_is_discriminative(q1)
    if not discriminative:
        return DiagnosisVerdict(
            phase1_branch="STOP",
            reason="state_type not discriminative (TREND vs RANGE/MIXED 胜率差 < 10pp 或样本不足)",
            q1_trend_winrate=trend_wr, q1_choppy_winrate=choppy_wr, q1_discriminative=False,
        )
    q2_yes = q2_best_bucket_winrate is not None and q2_best_bucket_winrate >= _Q2_WINNER_FLOOR
    if q2_yes and q3.robust:
        return DiagnosisVerdict(
            phase1_branch="1A",
            reason="震荡市存在样本外稳健的赢面 bucket → regime-conditional 精选",
            q1_trend_winrate=trend_wr, q1_choppy_winrate=choppy_wr, q1_discriminative=True,
            q2_best_bucket_winrate=q2_best_bucket_winrate, q3_robust=True,
        )
    return DiagnosisVerdict(
        phase1_branch="1B",
        reason="震荡市无样本外稳健赢面子集 → 保守版 (禁 BUY + 砍 top-3)",
        q1_trend_winrate=trend_wr, q1_choppy_winrate=choppy_wr, q1_discriminative=True,
        q2_best_bucket_winrate=q2_best_bucket_winrate, q3_robust=q3.robust,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py -k verdict -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Implement orchestrator `run_state_type_diagnosis`**

```python
# 追加到 src/screening/state_type_calibration.py

def run_state_type_diagnosis(
    *,
    reports_dir: Path | None = None,
    lookback_days: int = 30,
    target_state_types: tuple[str, ...] = ("RANGE", "MIXED"),
) -> tuple[StateTypeCalibrationReport, list[StateTypeBucketWinRate], LopoReport, DiagnosisVerdict]:
    """跑完三问 + 聚合 verdict. 返回 (q1, q2_rows, q3, verdict)."""
    from src.screening.consecutive_recommendation import (
        load_auto_screening_history,
        load_tracking_history,
        resolve_report_dir,
    )

    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(lookback_days=lookback_days, report_dir=search_dir)
    records = load_tracking_history(search_dir)
    q1 = compute_state_type_calibration_from_loaded(history, records)
    q2_rows = compute_state_type_bucket_subdivision(history, records, target_state_types=target_state_types)
    # 问2赢家: target 内胜率最高 且 n>=20 的 bucket
    qualified = [r for r in q2_rows if r.mature_t30_count >= 20 and r.t30_win_rate is not None]
    q2_best = max(qualified, key=lambda r: r.t30_win_rate) if qualified else None
    # 留一时段 min_n: 真实日期数可能少, 用 max(2, min_n_per_period)
    q3 = leave_one_period_out_validation(
        history, records, target_state_types=target_state_types, min_n=2,
    )
    verdict = aggregate_verdict(
        q1=q1, q2_best_bucket_winrate=(q2_best.t30_win_rate if q2_best else None), q3=q3,
    )
    if q2_best is not None:
        verdict.q2_best_bucket = q2_best.bucket
    return q1, q2_rows, q3, verdict
```

- [ ] **Step 6: Create CLI runner**

```python
# scripts/_diag_state_type_winrate.py
"""R-5.F Phase 0 一次性诊断 runner: 跑三问 → 打印 + 保存 JSON 报告.

用法: .venv/bin/python scripts/_diag_state_type_winrate.py [--lookback-days N] [--reports-dir PATH]
诊断结论 (1A/1B/STOP) 决定 R-5.F Phase 1 走哪条路. 诊断完结论沉淀进产品文档后可删本脚本.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from src.screening.state_type_calibration import run_state_type_diagnosis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--reports-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("outputs/diag_state_type_winrate.json"))
    args = parser.parse_args()

    q1, q2_rows, q3, verdict = run_state_type_diagnosis(
        reports_dir=args.reports_dir, lookback_days=args.lookback_days,
    )
    print("=" * 60)
    print("R-5.F Phase 0 诊断 — state_type 条件胜率")
    print("=" * 60)
    print("\n[问1] state_type 总体区分度 (TREND vs 震荡):")
    for r in q1.rows:
        wr = f"{r.t30_win_rate:.0%}" if r.t30_win_rate is not None else "—"
        med = f"{r.t30_median_return:+.1f}%" if r.t30_median_return is not None else "—"
        print(f"  {r.state_type:<8} winrate={wr:<6} median={med:<8} n={r.mature_t30_count}")
    print(f"\n[问2] 震荡市内 score-bucket 细分 (target RANGE/MIXED):")
    for r in q2_rows:
        wr = f"{r.t30_win_rate:.0%}" if r.t30_win_rate is not None else "—"
        flag = " ⚠n<20" if r.mature_t30_count < 20 else ""
        print(f"  {r.state_type:<8} {r.bucket:<10} winrate={wr:<6} n={r.mature_t30_count}{flag}")
    print(f"\n[问3] 留一时段样本外验证: robust={q3.robust} maintained_rate={q3.rediscovered_winner_rate:.0%} ({q3.heldout_periods} periods)")
    print(f"\n>>> 裁决: Phase 1 = {verdict.phase1_branch} — {verdict.reason}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "q1": [asdict(r) for r in q1.rows],
        "q2": [asdict(r) for r in q2_rows],
        "q3": asdict(q3),
        "verdict": asdict(verdict),
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已保存: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run full module test suite + commit**

Run: `.venv/bin/python -m pytest tests/screening/test_state_type_calibration.py -v`
Expected: PASS (8 tests)

Run: `.venv/bin/python -m pytest tests/screening/ -q --no-header`
Expected: PASS (baseline 1683 + 8 new = 1691)

```bash
git add src/screening/state_type_calibration.py scripts/_diag_state_type_winrate.py tests/screening/test_state_type_calibration.py
git commit -m "feat(R-5.F Phase0): verdict 聚合 (1A/1B/STOP) + CLI 诊断 runner"
```

---

### Task 5: 在真实数据上运行诊断 + 记录结论（Phase 0 交付时刻）

**说明**：本 task 不是 TDD——它是诊断的**执行与观察**，产出决定 Phase 1 命运的结论。诚实记录，不预设结果。

- [ ] **Step 1: 确认回填数据就绪**

Run: `.venv/bin/python -c "from src.screening.consecutive_recommendation import load_tracking_history, resolve_report_dir; r=load_tracking_history(resolve_report_dir()); print(f'tracking records: {len(r)}'); print('with t30:', sum(1 for x in r if x.get('next_30day_return') is not None))"`
Expected: tracking records 数百条，其中 with t30 ≥ ~100（R-5.E 回填的 ~189 只成熟记录）。若 with t30 过少（< 60），先确认 R-5.E 回填状态再继续。

- [ ] **Step 2: 运行诊断**

Run: `.venv/bin/python scripts/_diag_state_type_winrate.py --lookback-days 400`
Expected: 控制台输出三问结果 + 裁决（1A / 1B / STOP），JSON 存到 `outputs/diag_state_type_winrate.json`。

> `--lookback-days 400` 覆盖 R-5.E 回填的 32 日期（跨 2024-2025）。若 `resolve_report_dir()` 不指向回填目录，用 `--reports-dir` 显式指定。

- [ ] **Step 3: 记录结论到产品文档**

根据裁决结果，在 `docs/cn/product/feature-proposals.md` §三·5 R-5.F 行追加一行诊断结论（日期 + 三问数字 + branch + 一句话理由），例：
```
| R-5.F | P0 | ❌→诊断完成 | **诊断 (2026-06-25): 问1 TREND XX% vs 震荡 YY% (ΔZZpp, n=..) [yes/no]; 问2 震荡赢家 bucket=high XX% [yes/no]; 问3 留一时段 robust=no; → Phase 1 = 1B** |
```

- [ ] **Step 4: Commit 结论 + 决定下一步**

```bash
git add docs/cn/product/feature-proposals.md outputs/diag_state_type_winrate.json
git commit -m "docs(R-5.F): Phase 0 诊断结论 — <1A/1B/STOP> + 三问证据"
```

**裁决映射（spec §九）决定下一步**：
- **1A** → 另起 Phase 1A 实现计划（regime-conditional 精选 gate）
- **1B** → 另起 Phase 1B 实现计划（震荡市禁 BUY + top-3）
- **STOP** → R-5.F 不做；诚实报告 state_type 也不 discriminative，回到 owner 决策其他方向

---

## Self-Review（写完计划后 fresh eyes 对照 spec）

**1. Spec coverage**：
- §四 Phase 0 诊断三问 → Task 1(问1) / Task 2(问2) / Task 3(问3) ✓
- §四.3 诊断脚本自验（合成数据验证留一时段）→ Task 3 Step1 两个合成数据测试（real signal / artifact）✓
- §四.2 median + n<20 诚实约束 → Task 1 `_median_or_none` + Task 2 `min_n` / Task 4 `_Q1_MIN_N` ✓
- §九 映射表 1A/1B/STOP → Task 4 `aggregate_verdict` 三测试 ✓
- §四 一次性脚本 `_` 前缀 → Task 4 `scripts/_diag_state_type_winrate.py` ✓
- §一.3 不造新信号/复用现有 → 全程读已存储 `payload.market_state.state_type`，无 `detect_market_state` 重算 ✓
- 纪律"诊断前不动 gate"→ Global Constraints + 全计划无 `investability.py` 改动 ✓

**2. Placeholder scan**：无 TBD/TODO；所有代码块完整；Step 3 记录结论用的是模板+实例而非占位 ✓

**3. Type consistency**：
- `compute_state_type_calibration_from_loaded` / `compute_state_type_bucket_subdivision` / `leave_one_period_out_validation` / `aggregate_verdict` / `run_state_type_diagnosis` 全计划签名一致 ✓
- dataclass 字段（`t30_win_rate` / `mature_t30_count` / `robust` / `phase1_branch`）跨 task 一致 ✓
- `_score_bucket` 返回值 `low/mid_low/mid_high/high/unknown` 与 Task 2 测试一致 ✓

无阻塞性问题。
