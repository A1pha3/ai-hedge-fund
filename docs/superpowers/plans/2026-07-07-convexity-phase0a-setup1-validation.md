# Convexity Setups Phase 0a — Setup-1 (BTST 突破) 端到端验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 验证 Setup-1（涨停突破）在 execution-adjusted + out-of-sample 纪律下是否有足够 alpha（convexity_ratio ≥ 1.5, winrate ≥ 50%, n ≥ 50, IC > 0.05），产出第一个 go/no-go 信号。

**Architecture:** 新建 `src/screening/offensive/` 包（与现有防守系统隔离）。Phase 0a 只建：资金流数据接入 + 统计/分布/执行调整框架 + BTST setup 实现 + 研究 CLI。**不写 live 前门**（`--top-setups` 留给 Phase 1）。框架是可复用 infra，Phase 0b/0c 加 Setup-2..5 时直接复用。

**Tech Stack:** Python 3.12 / pandas / numpy / akshare (`stock_individual_fund_flow`) / pytest / 现有 `src/tools/akshare_api.py` / 现有 `src/data/enhanced_cache.py` / 现有 `src/screening/candidate_pool.py` 价格数据

**设计文档:** `docs/superpowers/specs/2026-07-07-convexity-setups-offensive-alpha-design.md` (v2)

## Global Constraints

- **Python 3.11-3.12**（不兼容 3.13+）
- **行长度 420**（black + flake8，intentional，勿改）
- **所有 LLM 调用走 `src/utils/llm.call_llm()`**（本计划不涉及 LLM）
- **akshare 数据接入复用** `src/tools/akshare_api.py` 的 `is_ashare` / market 映射模式
- **缓存复用** `src/data/enhanced_cache.py`（`get_enhanced_cache()`）
- **TDD 纪律**：每步先写失败测试，再写最小实现
- **不修改现有防守系统**（`--top-picks` / composite_score / BUY gate 一行不改）
- **half-Kelly 默认**（v2 §C.2 + 设计讨论）：所有 Kelly 计算用 `0.5 × kelly_fraction`，不用 full Kelly
- **execution-adjusted 硬约束**（v2 §C.2）：所有分布必须经 execution_adjuster 处理才能进决策报告
- **out-of-sample 硬约束**（v2 §C.5）：分布必须分 IS (2023-2024) / OOS (2025-2026) 两段，OOS 不达标 = STOP
- **STOP 条件**（设计文档 §6.1）：Setup-1 经 execution-adjusted + OOS 后若不达标 → 报告如实写 "no alpha"，不强行通过

## File Structure

**新建包 `src/screening/offensive/`**（与防守系统物理隔离）：

```
src/screening/offensive/
  __init__.py
  data/
    __init__.py
    fund_flow_store.py        # 资金流数据: akshare 拉取 + 缓存 + 查询
  statistics.py               # IC / convexity / winrate / n / 分布计算
  execution_adjuster.py       # 涨停可买性 + T+1锁 + 滑点模型
  distribution_builder.py     # 给定 setup + universe → 期限结构分布
  setups/
    __init__.py
    base.py                   # Setup ABC (detect + invalidation 接口)
    btst_breakout.py          # Setup-1: 涨停突破
src/tools/
  akshare_fund_flow.py        # akshare stock_individual_fund_flow 封装
scripts/
  setup_research.py           # Phase 0 研究 CLI (整合所有模块)
tests/offensive/
  __init__.py
  test_fund_flow_store.py
  test_statistics.py
  test_execution_adjuster.py
  test_distribution_builder.py
  test_setups_base.py
  test_btst_breakout.py
  test_setup_research_cli.py
```

**职责边界**：
- `akshare_fund_flow.py` — 纯数据获取（akshare 调用 + 标准化 DataFrame）
- `fund_flow_store.py` — 缓存 + 查询（用 enhanced_cache）
- `statistics.py` — 纯数学（无 IO）
- `execution_adjuster.py` — 纯数学（输入价格序列 + 触发日，输出调整后收益）
- `distribution_builder.py` — 编排（调用 store + setup + execution_adjuster + statistics）
- `setups/base.py` — 接口定义
- `setups/btst_breakout.py` — Setup-1 触发逻辑
- `scripts/setup_research.py` — CLI 入口（编排 distribution_builder + 输出报告）

---

## Task 1: 资金流数据获取封装（akshare wrapper）

**Files:**
- Create: `src/tools/akshare_fund_flow.py`
- Test: `tests/tools/test_akshare_fund_flow.py`

**Interfaces:**
- Produces: `fetch_individual_fund_flow(ticker: str) -> pd.DataFrame`（标准化列：date, close, pct_change, main_net_inflow, main_net_pct, big_order_net, ...）

- [ ] **Step 1: 写失败测试**

```python
# tests/tools/test_akshare_fund_flow.py
"""资金流数据获取测试。网络调用全部 mock。"""
from __future__ import annotations

import pandas as pd
from unittest.mock import patch


def test_fetch_individual_fund_flow_normalizes_columns():
    """拉取后列名标准化为英文 snake_case, 日期列为 datetime。"""
    from src.tools.akshare_fund_flow import fetch_individual_fund_flow

    # Mock akshare 返回原始中文列名
    fake_df = pd.DataFrame({
        "日期": ["2026-07-01", "2026-07-02"],
        "收盘价": [10.0, 10.5],
        "涨跌幅": [1.0, 5.0],
        "主力净流入-净额": [1000000, -500000],
        "主力净流入-净占比": [5.0, -2.5],
    })
    with patch("src.tools.akshare_fund_flow.ak.stock_individual_fund_flow", return_value=fake_df):
        result = fetch_individual_fund_flow("300054")

    assert "date" in result.columns
    assert "main_net_inflow" in result.columns
    assert pd.api.types.is_datetime64_any_dtype(result["date"])
    assert len(result) == 2


def test_fetch_individual_fund_flow_market_mapping_sz():
    """深圳 ticker (0/3 开头) → market='sz'。"""
    from src.tools.akshare_fund_flow import _resolve_market

    assert _resolve_market("300054") == "sz"
    assert _resolve_market("000001") == "sz"
    assert _resolve_market("600519") == "sh"
    assert _resolve_market("688981") == "sh"


def test_fetch_individual_fund_flow_returns_empty_on_api_error():
    """akshare 抛异常时返回空 DataFrame, 不 crash。"""
    from src.tools.akshare_fund_flow import fetch_individual_fund_flow

    with patch("src.tools.akshare_fund_flow.ak.stock_individual_fund_flow", side_effect=Exception("network")):
        result = fetch_individual_fund_flow("300054")

    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/tools/test_akshare_fund_flow.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.tools.akshare_fund_flow'`

- [ ] **Step 3: 写最小实现**

```python
# src/tools/akshare_fund_flow.py
"""akshare 个股资金流数据封装。

封装 akshare.stock_individual_fund_flow, 标准化列名为英文 snake_case,
处理 market 映射 (sz/sh/bj), 网络/解析异常时返回空 DataFrame。
"""
from __future__ import annotations

import logging

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

# 中文列名 → 英文标准化 (akshare stock_individual_fund_flow 实际返回的列)
_COLUMN_MAP: dict[str, str] = {
    "日期": "date",
    "收盘价": "close",
    "涨跌幅": "pct_change",
    "主力净流入-净额": "main_net_inflow",
    "主力净流入-净占比": "main_net_pct",
    "超大单净流入-净额": "super_big_net_inflow",
    "超大单净流入-净占比": "super_big_net_pct",
    "大单净流入-净额": "big_net_inflow",
    "大单净流入-净占比": "big_net_pct",
    "中单净流入-净额": "medium_net_inflow",
    "中单净流入-净占比": "medium_net_pct",
    "小单净流入-净额": "small_net_inflow",
    "小单净流入-净占比": "small_net_pct",
}


def _resolve_market(ticker: str) -> str:
    """A股 ticker → akshare market 标识 (sz/sh/bj)。

    600/601/603/605/688/689 → sh (上海)
    000/001/002/003/300/301 → sz (深圳)
    4xx/8xx/92xx            → bj (北交所)
    """
    t = str(ticker).strip()
    if t.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh"
    if t.startswith(("000", "001", "002", "003", "300", "301")):
        return "sz"
    if t.startswith(("4", "8", "92")):
        return "bj"
    # 默认深圳 (绝大多数 A 股)
    return "sz"


def fetch_individual_fund_flow(ticker: str) -> pd.DataFrame:
    """拉取个股近期日度资金流数据。

    Args:
        ticker: 6 位 A 股代码 (e.g. "300054")

    Returns:
        标准化 DataFrame, 列: date(datetime) / close / pct_change /
        main_net_inflow / main_net_pct / ... 大单/中单/小单。
        akshare 异常时返回空 DataFrame (列同上)。
    """
    market = _resolve_market(ticker)
    try:
        raw = ak.stock_individual_fund_flow(stock=ticker, market=market)
    except Exception as exc:
        logger.warning("fund flow fetch failed for %s: %s", ticker, exc)
        return pd.DataFrame(columns=list(_COLUMN_MAP.values()))

    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=list(_COLUMN_MAP.values()))

    # 标准化列名 (只保留已知的中文列, 其余丢弃)
    renamed = raw.rename(columns=_COLUMN_MAP)
    known_cols = [c for c in _COLUMN_MAP.values() if c in renamed.columns]
    result = renamed[known_cols].copy()

    if "date" in result.columns:
        result["date"] = pd.to_datetime(result["date"], errors="coerce")
        result = result.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/tools/test_akshare_fund_flow.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/tools/akshare_fund_flow.py tests/tools/test_akshare_fund_flow.py
git commit -m "feat(offensive): 资金流数据获取 akshare 封装 (Phase 0a Task 1)"
```

---

## Task 2: 资金流数据存储 + 查询（fund_flow_store）

**Files:**
- Create: `src/screening/offensive/__init__.py` (空)
- Create: `src/screening/offensive/data/__init__.py` (空)
- Create: `src/screening/offensive/data/fund_flow_store.py`
- Test: `tests/offensive/__init__.py` (空)
- Test: `tests/offensive/test_fund_flow_store.py`

**Interfaces:**
- Consumes: `src.tools.akshare_fund_flow.fetch_individual_fund_flow`
- Produces:
  - `FundFlowRecord` (dataclass): `ticker: str, date: str(YYYYMMDD), main_net_inflow: float, main_net_pct: float, ...`
  - `FundFlowStore.save(ticker, df) -> int`（存入缓存, 返回行数）
  - `FundFlowStore.get(ticker, date) -> FundFlowRecord | None`
  - `FundFlowStore.get_range(ticker, start_date, end_date) -> list[FundFlowRecord]`

- [ ] **Step 1: 写失败测试**

```python
# tests/offensive/test_fund_flow_store.py
"""资金流数据存储测试。用 tmp_path 隔离缓存。"""
from __future__ import annotations

import pandas as pd
import pytest

from src.screening.offensive.data.fund_flow_store import FundFlowStore, FundFlowRecord


def _sample_df():
    return pd.DataFrame({
        "date": pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03"]),
        "close": [10.0, 10.5, 10.2],
        "pct_change": [1.0, 5.0, -2.86],
        "main_net_inflow": [1_000_000, -500_000, 200_000],
        "main_net_pct": [5.0, -2.5, 1.0],
    })


def test_save_and_get_roundtrip(tmp_path):
    store = FundFlowStore(cache_dir=tmp_path)
    n = store.save("300054", _sample_df())
    assert n == 3

    rec = store.get("300054", "20260701")
    assert rec is not None
    assert rec.ticker == "300054"
    assert rec.date == "20260701"
    assert rec.main_net_inflow == 1_000_000


def test_get_missing_returns_none(tmp_path):
    store = FundFlowStore(cache_dir=tmp_path)
    assert store.get("300054", "20260701") is None


def test_get_range_filters_by_date(tmp_path):
    store = FundFlowStore(cache_dir=tmp_path)
    store.save("300054", _sample_df())
    rng = store.get_range("300054", "20260702", "20260703")
    assert len(rng) == 2
    assert rng[0].date == "20260702"
    assert rng[1].date == "20260703"


def test_save_overwrites_idempotent(tmp_path):
    """重复 save 同一 ticker 不重复, 不报错。"""
    store = FundFlowStore(cache_dir=tmp_path)
    store.save("300054", _sample_df())
    n2 = store.save("300054", _sample_df())  # 同数据再存
    assert n2 == 3
    rng = store.get_range("300054", "20260701", "20260703")
    assert len(rng) == 3  # 不重复
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/offensive/test_fund_flow_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
# src/screening/offensive/data/fund_flow_store.py
"""资金流数据存储: 按 ticker 落盘 Parquet, 查询时按日期过滤。

Phase 0a 用文件存储 (Parquet per ticker); Phase 1+ 数据量上来后再迁 SQLite。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FundFlowRecord:
    ticker: str
    date: str  # YYYYMMDD
    close: float
    pct_change: float
    main_net_inflow: float
    main_net_pct: float
    big_net_inflow: float = 0.0
    super_big_net_inflow: float = 0.0
    medium_net_inflow: float = 0.0
    small_net_inflow: float = 0.0


class FundFlowStore:
    """per-ticker Parquet 存储。文件名: <cache_dir>/<ticker>.parquet"""

    def __init__(self, cache_dir: Path | str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker}.parquet"

    def save(self, ticker: str, df: pd.DataFrame) -> int:
        """存入 ticker 资金流数据。同 ticker 已有数据时 merge + 去重 (按 date)。"""
        if df is None or len(df) == 0:
            return 0
        df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["date"]):
            df["date"] = pd.to_datetime(df["date"])
        df["date"] = df["date"].dt.strftime("%Y%m%d")
        df["ticker"] = ticker

        path = self._path(ticker)
        if path.exists():
            old = pd.read_parquet(path)
            combined = pd.concat([old, df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date"], keep="last")
            combined = combined.sort_values("date").reset_index(drop=True)
        else:
            combined = df.sort_values("date").reset_index(drop=True)
        combined.to_parquet(path, index=False)
        return len(combined)

    def _load_all(self, ticker: str) -> pd.DataFrame:
        path = self._path(ticker)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    @staticmethod
    def _row_to_record(row: pd.Series) -> FundFlowRecord:
        return FundFlowRecord(
            ticker=str(row["ticker"]),
            date=str(row["date"]),
            close=float(row.get("close", 0.0) or 0.0),
            pct_change=float(row.get("pct_change", 0.0) or 0.0),
            main_net_inflow=float(row.get("main_net_inflow", 0.0) or 0.0),
            main_net_pct=float(row.get("main_net_pct", 0.0) or 0.0),
            big_net_inflow=float(row.get("big_net_inflow", 0.0) or 0.0),
            super_big_net_inflow=float(row.get("super_big_net_inflow", 0.0) or 0.0),
            medium_net_inflow=float(row.get("medium_net_inflow", 0.0) or 0.0),
            small_net_inflow=float(row.get("small_net_inflow", 0.0) or 0.0),
        )

    def get(self, ticker: str, date: str) -> FundFlowRecord | None:
        """date 格式 YYYYMMDD。"""
        df = self._load_all(ticker)
        if len(df) == 0:
            return None
        match = df[df["date"] == date]
        if len(match) == 0:
            return None
        return self._row_to_record(match.iloc[0])

    def get_range(self, ticker: str, start_date: str, end_date: str) -> list[FundFlowRecord]:
        """闭区间 [start_date, end_date], YYYYMMDD。"""
        df = self._load_all(ticker)
        if len(df) == 0:
            return []
        mask = (df["date"] >= start_date) & (df["date"] <= end_date)
        return [self._row_to_record(row) for _, row in df[mask].iterrows()]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/offensive/test_fund_flow_store.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
mkdir -p src/screening/offensive/data tests/offensive
touch src/screening/offensive/__init__.py src/screening/offensive/data/__init__.py tests/offensive/__init__.py
git add src/screening/offensive/ tests/offensive/
git commit -m "feat(offensive): 资金流数据存储 + 查询 (Phase 0a Task 2)"
```

---

## Task 3: 统计工具（IC / convexity / winrate / n）

**Files:**
- Create: `src/screening/offensive/statistics.py`
- Test: `tests/offensive/test_statistics.py`

**Interfaces:**
- Produces:
  - `Distribution` (dataclass): `n, winrate, avg_gain, avg_loss, convexity_ratio, expected_return, ci_low, ci_high, ic`
  - `compute_distribution(returns: np.ndarray, baseline_returns: np.ndarray | None = None) -> Distribution`
  - `information_coefficient(scores: np.ndarray, forward_returns: np.ndarray) -> float`

- [ ] **Step 1: 写失败测试**

```python
# tests/offensive/test_statistics.py
"""统计工具测试。纯数学, 无 IO。"""
from __future__ import annotations

import numpy as np

from src.screening.offensive.statistics import (
    Distribution,
    compute_distribution,
    information_coefficient,
)


def test_compute_distribution_basic_positive_convexity():
    """60% 赢 +20%, 40% 输 -8% → convexity_ratio > 1, winrate 0.6。"""
    returns = np.array([0.20, 0.25, 0.18, -0.08, -0.07, 0.22, -0.09, 0.20, -0.08, 0.21])
    dist = compute_distribution(returns)
    assert dist.n == 10
    assert abs(dist.winrate - 0.6) < 1e-9
    assert dist.avg_gain > 0.15
    assert dist.avg_loss < -0.05
    assert dist.convexity_ratio > 1.5  # (0.2×0.6)/(0.08×0.4) ≈ 3.75
    assert dist.expected_return > 0


def test_compute_distribution_all_wins():
    """全赢: avg_loss=0, convexity_ratio=inf (cap 到 999)。"""
    returns = np.array([0.1, 0.2, 0.15])
    dist = compute_distribution(returns)
    assert dist.winrate == 1.0
    assert dist.convexity_ratio >= 999  # capped sentinel


def test_compute_distribution_empty_returns_zero_n():
    dist = compute_distribution(np.array([]))
    assert dist.n == 0
    assert dist.winrate == 0.0


def test_information_coefficient_perfect_positive():
    """scores 与 forward_returns 完全正相关 → IC ≈ 1。"""
    scores = np.array([1, 2, 3, 4, 5])
    fwd = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
    ic = information_coefficient(scores, fwd)
    assert ic > 0.99


def test_information_coefficient_orthogonal_near_zero():
    """不相关 → IC ≈ 0。"""
    np.random.seed(42)
    scores = np.arange(100)
    fwd = np.random.randn(100)
    ic = information_coefficient(scores, fwd)
    assert abs(ic) < 0.2


def test_ci_bracket_contains_mean():
    """bootstrap CI 包含样本均值。"""
    np.random.seed(0)
    returns = np.random.randn(50) * 0.05 + 0.03
    dist = compute_distribution(returns)
    assert dist.ci_low <= dist.expected_return <= dist.ci_high
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/offensive/test_statistics.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
# src/screening/offensive/statistics.py
"""凸性 setup 统计工具: 分布计算 + IC + bootstrap CI。

纯数学, 无 IO, 无 LLM。可独立单测。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# 当 avg_loss==0 (全赢) 时 convexity_ratio 的上限哨兵
_CONVEXITY_CAP = 999.0


@dataclass(frozen=True)
class Distribution:
    """历史收益分布的统计摘要。"""

    n: int
    winrate: float
    avg_gain: float  # 正收益样本均值
    avg_loss: float  # 负收益样本均值 (负数)
    convexity_ratio: float  # (avg_gain × winrate) / (|avg_loss| × lossrate)
    expected_return: float  # = winrate × avg_gain + lossrate × avg_loss
    ci_low: float  # 95% bootstrap CI 下界 (expected_return)
    ci_high: float  # 95% bootstrap CI 上界
    ic: float = 0.0  # vs 全市场基线的 information coefficient (可选)


def _bootstrap_expected_return_ci(
    returns: np.ndarray, n_boot: int = 2000, seed: int = 42, alpha: float = 0.05
) -> tuple[float, float]:
    """Bootstrap expected_return (均值) 的双侧 CI。"""
    if len(returns) == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        sample = rng.choice(returns, size=len(returns), replace=True)
        boots[i] = sample.mean()
    return float(np.quantile(boots, alpha / 2)), float(np.quantile(boots, 1 - alpha / 2))


def compute_distribution(returns: np.ndarray) -> Distribution:
    """从收益序列计算分布摘要。

    Args:
        returns: T+N 收益率序列 (小数, e.g. 0.05 = +5%)。允许空。

    Returns:
        Distribution; n=0 时其余字段为 0。
    """
    returns = np.asarray(returns, dtype=float)
    returns = returns[np.isfinite(returns)]
    n = len(returns)
    if n == 0:
        return Distribution(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    winrate = len(wins) / n if n > 0 else 0.0
    lossrate = 1.0 - winrate
    avg_gain = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(losses.mean()) if len(losses) > 0 else 0.0

    if avg_loss == 0.0 and len(losses) == 0:
        convexity = _CONVEXITY_CAP  # 全赢, 凸性无穷 (capped)
    elif avg_loss == 0.0:
        convexity = _CONVEXITY_CAP  # losses 全是 0
    else:
        convexity = (avg_gain * winrate) / (abs(avg_loss) * lossrate)

    expected_return = float(returns.mean())
    ci_low, ci_high = _bootstrap_expected_return_ci(returns)

    return Distribution(
        n=n,
        winrate=winrate,
        avg_gain=avg_gain,
        avg_loss=avg_loss,
        convexity_ratio=convexity,
        expected_return=expected_return,
        ci_low=ci_low,
        ci_high=ci_high,
    )


def information_coefficient(scores: np.ndarray, forward_returns: np.ndarray) -> float:
    """Spearman rank IC: scores 与 forward_returns 的秩相关。

    Args:
        scores: setup 触发强度 / 信号分 (命中=1, 未命中=0 也可)
        forward_returns: 对应的 T+N 收益

    Returns:
        Spearman IC ∈ [-1, 1]; 输入长度不足或方差为 0 时返回 0。
    """
    scores = np.asarray(scores, dtype=float)
    forward_returns = np.asarray(forward_returns, dtype=float)
    mask = np.isfinite(scores) & np.isfinite(forward_returns)
    scores, forward_returns = scores[mask], forward_returns[mask]
    if len(scores) < 5 or scores.std() == 0 or forward_returns.std() == 0:
        return 0.0
    # Spearman = Pearson on ranks
    from scipy.stats import rankdata

    return float(np.corrcoef(rankdata(scores), rankdata(forward_returns))[0, 1])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/offensive/test_statistics.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/screening/offensive/statistics.py tests/offensive/test_statistics.py
git commit -m "feat(offensive): 统计工具 IC/convexity/winrate/bootstrap CI (Phase 0a Task 3)"
```

---

## Task 4: 执行成本调整器（execution_adjuster）— v2 P0 关键

**Files:**
- Create: `src/screening/offensive/execution_adjuster.py`
- Test: `tests/offensive/test_execution_adjuster.py`

**Interfaces:**
- Produces:
  - `ExecutionConfig` (dataclass): `slippage_bps=30` (0.3%), `limit_up_unbuyable=True`, `t_plus_1_lock=True`
  - `adjust_returns(trigger_dates, tickers, prices_by_ticker, horizon, config) -> np.ndarray`（返回 execution-adjusted T+N 收益）

- [ ] **Step 1: 写失败测试**

```python
# tests/offensive/test_execution_adjuster.py
"""执行成本调整测试 — v2 P0 关键模块。

验证: 涨停次日不可买 → 剔除样本; T+1 锁; 滑点扣减。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.screening.offensive.execution_adjuster import (
    ExecutionConfig,
    adjust_returns,
    is_limit_up_unbuyable_next_day,
)


def _prices(ticker, dates, closes):
    """构造价格 DataFrame: date, close, open, high, low, pct_change。"""
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "close": closes,
        "open": closes,  # 简化: open=close
        "high": [c * 1.02 for c in closes],
        "low": [c * 0.98 for c in closes],
        "pct_change": [0.0] + [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))],
    })


def test_limit_up_next_day_unbuyable_detected():
    """触发日涨停 (pct_change≈+10%) 且次日开盘仍涨停 → 不可买。"""
    # T 日 +10% (涨停), T+1 开盘 = T 收盘 × 1.10 (继续涨停)
    prices = _prices("X", ["2026-07-01", "2026-07-02"], [10.0, 11.0])
    prices.loc[0, "pct_change"] = 10.0  # T 日涨停
    # T+1 开盘 = 11.0 × 1.10 = 12.1 (继续涨停, 买不到)
    prices.loc[1, "open"] = 12.1
    assert is_limit_up_unbuyable_next_day(prices, trigger_idx=0) is True


def test_limit_up_but_next_day_buyable():
    """触发日涨停, 但次日开盘不涨停 → 可买 (低开/平开)。"""
    prices = _prices("X", ["2026-07-01", "2026-07-02"], [10.0, 11.0])
    prices.loc[0, "pct_change"] = 10.0  # T 涨停
    prices.loc[1, "open"] = 11.0  # T+1 平开 (没继续涨停)
    assert is_limit_up_unbuyable_next_day(prices, trigger_idx=0) is False


def test_adjust_returns_applies_slippage():
    """无涨停问题: T+5 收益扣 2× slippage (买卖两端)。"""
    # T=10.0, T+5=10.5 → 名义 +5%; slippage 0.3% × 2 = 0.6% → 实际 ~+4.4%
    prices = _prices("X", ["2026-07-0" + str(i) for i in range(1, 8)], [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.3])
    config = ExecutionConfig(slippage_bps=30, limit_up_unbuyable=False, t_plus_1_lock=False)
    result = adjust_returns(
        trigger_dates=["20260701"],
        tickers=["X"],
        prices_by_ticker={"X": prices},
        horizon=5,
        config=config,
    )
    assert len(result) == 1
    assert result[0] < 0.05  # 扣滑点后低于名义 +5%
    assert result[0] > 0.03   # 但仍为正


def test_adjust_returns_skips_unbuyable():
    """触发日涨停 + 次日继续涨停 → 样本被剔除 (返回 NaN → 过滤)。"""
    prices = _prices("X", ["2026-07-01", "2026-07-02"], [10.0, 11.0])
    prices.loc[0, "pct_change"] = 10.0
    prices.loc[1, "open"] = 12.1  # 次日继续涨停
    config = ExecutionConfig(slippage_bps=30, limit_up_unbuyable=True, t_plus_1_lock=False)
    result = adjust_returns(
        trigger_dates=["20260701"],
        tickers=["X"],
        prices_by_ticker={"X": prices},
        horizon=1,
        config=config,
    )
    # 不可买 → NaN
    assert len(result) == 1
    assert np.isnan(result[0])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/offensive/test_execution_adjuster.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
# src/screening/offensive/execution_adjuster.py
"""执行成本调整器 — v2 P0 关键。

回测名义收益 → 实际可执行收益, 三项调整:
1. limit_up_unbuyable: 触发日涨停且次日开盘继续涨停 → 剔除样本 (NaN)
2. t_plus_1_lock: T+1 交收, horizon=1 时不可卖 (退化处理: 仍算 T+1 收益但标注)
3. slippage: 买卖两端各扣 slippage_bps 个基点

这是 v2 §C.2 的核心模块 — 不经此调整的回测收益是幻觉。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# A 股涨跌停阈值 (主板 ±10%, 创业板/科创板 ±20%; 本期统一用 +9.5% 判定避免浮点)
_LIMIT_UP_PCT_THRESHOLD = 9.5


@dataclass(frozen=True)
class ExecutionConfig:
    slippage_bps: int = 30  # 单边滑点 (基点); 30bps = 0.3%
    limit_up_unbuyable: bool = True  # 触发日涨停+次日续涨停 → 剔除
    t_plus_1_lock: bool = True  # T+1 交收约束


def is_limit_up_unbuyable_next_day(prices: pd.DataFrame, trigger_idx: int) -> bool:
    """判定: 触发日涨停 (pct_change ≥ 9.5%) 且 次日开盘相对触发日收盘继续涨停。

    主板涨停 = +10%, 创业板/科创板 +20%; 用 9.5% 触发保守判定 (含 ST 5% 的极端
    情况会在 trigger 阶段被 candidate_pool 过滤)。

    Args:
        prices: 单 ticker 价格 DataFrame (date, close, open, pct_change)
        trigger_idx: 触发日在 prices 中的行号

    Returns:
        True = 次日开盘买不到 (继续涨停)
    """
    if trigger_idx + 1 >= len(prices):
        return False  # 没有次日数据
    trigger_pct = float(prices.iloc[trigger_idx].get("pct_change", 0.0) or 0.0)
    if trigger_pct < _LIMIT_UP_PCT_THRESHOLD:
        return False  # 触发日没涨停
    trigger_close = float(prices.iloc[trigger_idx]["close"])
    next_open = float(prices.iloc[trigger_idx + 1]["open"])
    # 次日开盘 = 触发日收盘 × 1.10 (再涨停) → 买不到
    return next_open >= trigger_close * 1.095


def adjust_returns(
    trigger_dates: list[str],
    tickers: list[str],
    prices_by_ticker: dict[str, pd.DataFrame],
    horizon: int,
    config: ExecutionConfig,
) -> np.ndarray:
    """对一批触发样本计算 execution-adjusted T+horizon 收益。

    Args:
        trigger_dates: 触发日列表 (YYYYMMDD)
        tickers: 对应 ticker 列表 (同长度)
        prices_by_ticker: {ticker: 价格 DataFrame}, 至少含 date/close/open/pct_change
        horizon: 持有期 (交易日)
        config: 执行配置

    Returns:
        np.ndarray[float], 每个样本的调整后收益率; 不可买/数据不足 → NaN
    """
    assert len(trigger_dates) == len(tickers)
    slippage = config.slippage_bps / 10_000.0
    out = np.full(len(trigger_dates), np.nan)

    for i, (date_str, ticker) in enumerate(zip(trigger_dates, tickers)):
        prices = prices_by_ticker.get(ticker)
        if prices is None or len(prices) == 0:
            continue
        prices = prices.copy()
        prices["date_str"] = pd.to_datetime(prices["date"]).dt.strftime("%Y%m%d")
        # 定位触发日
        trigger_rows = prices[prices["date_str"] == date_str]
        if len(trigger_rows) == 0:
            continue
        trigger_idx = trigger_rows.index[0]
        exit_idx = trigger_idx + horizon
        if exit_idx >= len(prices):
            continue  # 数据不足

        # 涨停不可买
        if config.limit_up_unbuyable and is_limit_up_unbuyable_next_day(prices, trigger_idx):
            continue  # NaN

        # 入口价 = 次日开盘 × (1 + slippage); 出口价 = T+horizon 收盘 × (1 - slippage)
        entry_idx = trigger_idx + 1  # 次日开盘买入 (T+1 settlement)
        if entry_idx >= len(prices):
            continue
        entry_price = float(prices.iloc[entry_idx]["open"]) * (1 + slippage)
        exit_price = float(prices.iloc[exit_idx]["close"]) * (1 - slippage)
        if entry_price <= 0:
            continue
        out[i] = (exit_price / entry_price) - 1.0

    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/offensive/test_execution_adjuster.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/screening/offensive/execution_adjuster.py tests/offensive/test_execution_adjuster.py
git commit -m "feat(offensive): execution_adjuster 涨停可买性+T+1锁+滑点 (v2 P0, Phase 0a Task 4)"
```

---

## Task 5: Setup 抽象基类 + 检测结果

**Files:**
- Create: `src/screening/offensive/setups/__init__.py` (空)
- Create: `src/screening/offensive/setups/base.py`
- Test: `tests/offensive/test_setups_base.py`

**Interfaces:**
- Produces:
  - `DetectionResult` (dataclass): `hit: bool, ticker: str, trade_date: str, trigger_strength: float, invalidation_condition: str, metadata: dict`
  - `Setup` (ABC): `name: str`, `detect(ticker, trade_date, context) -> DetectionResult`, `natural_horizon: int`

- [ ] **Step 1: 写失败测试**

```python
# tests/offensive/test_setups_base.py
"""Setup 抽象基类测试。"""
from __future__ import annotations

import pytest

from src.screening.offensive.setups.base import Setup, DetectionResult


class _FakeSetup(Setup):
    name = "fake"
    natural_horizon = 5

    def detect(self, ticker, trade_date, context):
        return DetectionResult(
            hit=True,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=0.8,
            invalidation_condition="价格跌破 entry × 0.92",
            metadata={"foo": "bar"},
        )


def test_detection_result_fields():
    r = DetectionResult(hit=True, ticker="X", trade_date="20260701", trigger_strength=0.5, invalidation_condition="c", metadata={})
    assert r.hit is True
    assert r.ticker == "X"


def test_setup_subclass_must_implement_detect():
    """Setup ABC 强制子类实现 detect。"""
    with pytest.raises(TypeError):
        Setup()  # 不能实例化 ABC


def test_setup_subclass_detect_returns_result():
    s = _FakeSetup()
    r = s.detect("300054", "20260701", context={})
    assert isinstance(r, DetectionResult)
    assert r.hit is True
    assert r.trigger_strength == 0.8
    assert "0.92" in r.invalidation_condition
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/offensive/test_setups_base.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
# src/screening/offensive/setups/base.py
"""Setup 抽象基类 — 所有凸性 setup 的统一接口。

v2 §C.6 关键: 每个 setup 必须返回 invalidation_condition (失效条件),
供 risk_framework 用作止损/退出依据。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DetectionResult:
    """Setup 检测结果。"""

    hit: bool
    ticker: str
    trade_date: str  # YYYYMMDD
    trigger_strength: float  # 0-1, 触发强度 (用于 IC 排序)
    invalidation_condition: str  # 失效条件描述 (trigger 反转判定)
    metadata: dict[str, Any] = field(default_factory=dict)


class Setup(ABC):
    """凸性 setup 抽象基类。子类实现 detect + 声明 natural_horizon。"""

    name: str = "abstract"
    natural_horizon: int = 5  # IC 最高的 horizon (子类覆盖)

    @abstractmethod
    def detect(self, ticker: str, trade_date: str, context: dict[str, Any]) -> DetectionResult:
        """检测 ticker 在 trade_date 是否命中本 setup。

        Args:
            ticker: 6 位代码
            trade_date: YYYYMMDD
            context: 共享上下文 (价格数据 / 资金流 / 行业信息 / regime)

        Returns:
            DetectionResult; hit=False 时其余字段填默认值
        """
        ...
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/offensive/test_setups_base.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
mkdir -p src/screening/offensive/setups
touch src/screening/offensive/setups/__init__.py
git add src/screening/offensive/setups/ tests/offensive/test_setups_base.py
git commit -m "feat(offensive): Setup ABC + DetectionResult (Phase 0a Task 5)"
```

---

## Task 6: 分布构建器（distribution_builder）— 编排模块

**Files:**
- Create: `src/screening/offensive/distribution_builder.py`
- Test: `tests/offensive/test_distribution_builder.py`

**Interfaces:**
- Consumes: `Setup.detect`, `adjust_returns`, `compute_distribution`, `information_coefficient`
- Produces:
  - `TermStructureDistribution` (dataclass): `setup_name, horizons: dict[int, Distribution], natural_horizon: int, regime: str, period: str` (period: "IS"/"OOS"/"ALL")
  - `build_distribution(setup, tickers, trade_dates, prices_by_ticker, regimes_by_date, horizons=(1,3,5,10), config=ExecutionConfig(), period="ALL") -> TermStructureDistribution`

- [ ] **Step 1: 写失败测试**

```python
# tests/offensive/test_distribution_builder.py
"""分布构建器测试 — 编排 setup + execution_adjuster + statistics。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.screening.offensive.distribution_builder import (
    build_distribution,
    TermStructureDistribution,
)
from src.screening.offensive.setups.base import Setup, DetectionResult
from src.screening.offensive.execution_adjuster import ExecutionConfig


class _AlwaysHitSetup(Setup):
    """测试用: 每个样本都命中。"""
    name = "test_always_hit"
    natural_horizon = 3

    def detect(self, ticker, trade_date, context):
        return DetectionResult(hit=True, ticker=ticker, trade_date=trade_date,
                               trigger_strength=1.0, invalidation_condition="n/a")


def _make_prices(ticker, start="2026-07-01", days=12, drift=0.01):
    dates = pd.bdate_range(start, periods=days)
    closes = [10.0]
    for _ in range(days - 1):
        closes.append(closes[-1] * (1 + drift))
    return pd.DataFrame({
        "date": dates,
        "close": closes,
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "pct_change": [0.0] + [drift * 100] * (days - 1),
    })


def test_build_distribution_returns_term_structure():
    setup = _AlwaysHitSetup()
    tickers = ["000001", "000002"]
    trade_dates = ["20260701", "20260701"]
    prices = {t: _make_prices(t) for t in tickers}

    tsd = build_distribution(
        setup=setup,
        tickers=tickers,
        trade_dates=trade_dates,
        prices_by_ticker=prices,
        regimes_by_date={"20260701": "normal"},
        horizons=(1, 3, 5),
    )
    assert isinstance(tsd, TermStructureDistribution)
    assert tsd.setup_name == "test_always_hit"
    assert set(tsd.horizons.keys()) == {1, 3, 5}
    assert tsd.horizons[5].n == 2  # 2 个样本


def test_build_distribution_skips_non_hits():
    """setup 命中率 < 100% 时, 未命中样本不进分布。"""
    class _SometimesHit(Setup):
        name = "sometimes"
        natural_horizon = 1
        def detect(self, ticker, trade_date, context):
            hit = ticker.endswith("1")  # 000001 命中, 000002 不命中
            return DetectionResult(hit=hit, ticker=ticker, trade_date=trade_date,
                                   trigger_strength=1.0 if hit else 0.0,
                                   invalidation_condition="n/a")

    prices = {t: _make_prices(t) for t in ("000001", "000002")}
    tsd = build_distribution(
        setup=_SometimesHit(),
        tickers=["000001", "000002"],
        trade_dates=["20260701", "20260701"],
        prices_by_ticker=prices,
        regimes_by_date={"20260701": "normal"},
        horizons=(1,),
    )
    assert tsd.horizons[1].n == 1  # 只有 000001


def test_build_distribution_period_label():
    """period 参数 ('IS'/'OOS'/'ALL') 写入 TermStructureDistribution。"""
    setup = _AlwaysHitSetup()
    prices = {"000001": _make_prices("000001")}
    tsd = build_distribution(
        setup=setup, tickers=["000001"], trade_dates=["20260701"],
        prices_by_ticker=prices, regimes_by_date={"20260701": "normal"},
        horizons=(1,), period="OOS",
    )
    assert tsd.period == "OOS"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/offensive/test_distribution_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
# src/screening/offensive/distribution_builder.py
"""分布构建器 — 编排 setup 检测 + execution_adjuster + statistics。

给定 setup + 一批 (ticker, trade_date) 样本 + 价格数据, 产出期限结构分布
(T+1/T+3/T+5/T+10 各一个 Distribution)。

Phase 0a 核心: 所有分布都经 execution_adjuster 处理 (v2 §C.2 硬约束)。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.screening.offensive.execution_adjuster import (
    ExecutionConfig,
    adjust_returns,
)
from src.screening.offensive.setups.base import Setup
from src.screening.offensive.statistics import Distribution, compute_distribution


@dataclass(frozen=True)
class TermStructureDistribution:
    """单 setup 在某 regime + 某时段的完整期限结构。"""

    setup_name: str
    horizons: dict[int, Distribution]  # {1: dist, 3: dist, 5: dist, ...}
    natural_horizon: int
    regime: str
    period: str  # "IS" / "OOS" / "ALL"
    n_hits: int  # 命中样本总数 (跨 horizon 一致)


def build_distribution(
    setup: Setup,
    tickers: list[str],
    trade_dates: list[str],
    prices_by_ticker: dict[str, pd.DataFrame],
    regimes_by_date: dict[str, str],
    horizons: tuple[int, ...] = (1, 3, 5, 10),
    config: ExecutionConfig | None = None,
    period: str = "ALL",
) -> TermStructureDistribution:
    """对一批样本回测 setup 的期限结构分布。

    流程:
    1. setup.detect 过滤命中样本
    2. 对每个 horizon, execution-adjusted 计算 T+horizon 收益
    3. compute_distribution 算 winrate/convexity/IC/CI
    4. 取所有样本的 regime (假设同批次同 regime; 不同则取众数)

    Args:
        setup: Setup 实例
        tickers / trade_dates: 同长度样本列表
        prices_by_ticker: {ticker: 价格 DataFrame}
        regimes_by_date: {YYYYMMDD: regime}
        horizons: 要回测的 T+N 列表
        config: 执行配置 (默认 ExecutionConfig())
        period: "IS"/"OOS"/"ALL" 标签 (调用方负责切分数据)

    Returns:
        TermStructureDistribution
    """
    assert len(tickers) == len(trade_dates)
    config = config or ExecutionConfig()

    # 1. 过滤命中样本
    hit_tickers, hit_dates = [], []
    for ticker, date_str in zip(tickers, trade_dates):
        ctx = {"prices": prices_by_ticker.get(ticker), "regime": regimes_by_date.get(date_str, "normal")}
        result = setup.detect(ticker, date_str, ctx)
        if result.hit:
            hit_tickers.append(ticker)
            hit_dates.append(date_str)

    # 2. 每 horizon 算 execution-adjusted 分布
    horizon_dists: dict[int, Distribution] = {}
    for h in horizons:
        adj = adjust_returns(hit_dates, hit_tickers, prices_by_ticker, horizon=h, config=config)
        finite = adj[np.isfinite(adj)]
        horizon_dists[h] = compute_distribution(finite)

    # 3. regime 众数 (假设批次内同 regime)
    regime = max(
        {r: sum(1 for d in hit_dates if regimes_by_date.get(d) == r) for r in set(regimes_by_date.values())}.items(),
        key=lambda kv: kv[1],
        default=("unknown", 0),
    )[0] if hit_dates else "unknown"

    return TermStructureDistribution(
        setup_name=setup.name,
        horizons=horizon_dists,
        natural_horizon=setup.natural_horizon,
        regime=regime,
        period=period,
        n_hits=len(hit_tickers),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/offensive/test_distribution_builder.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/screening/offensive/distribution_builder.py tests/offensive/test_distribution_builder.py
git commit -m "feat(offensive): distribution_builder 期限结构编排 (Phase 0a Task 6)"
```

---

## Task 7: Setup-1 BTST 突破（涨停 + 主力净流入 + 板块效应）

**Files:**
- Create: `src/screening/offensive/setups/btst_breakout.py`
- Test: `tests/offensive/test_btst_breakout.py`

**Interfaces:**
- Consumes: `Setup`, `DetectionResult`, `FundFlowStore`（context 传入）, 候选池价格数据
- Produces: `BtstBreakoutSetup` (Setup 子类), `name="btst_breakout"`, `natural_horizon=3`

**触发规则**（设计文档 §3.1 Setup-1）：
- 今日涨停（pct_change ≥ 9.5%）
- 主力净流入 > 0 且 > 过去 20 日均值
- 所属行业当日涨幅 > 2%（板块效应，context 传入）

- [ ] **Step 1: 写失败测试**

```python
# tests/offensive/test_btst_breakout.py
"""Setup-1 BTST 突破触发逻辑测试。"""
from __future__ import annotations

import pandas as pd
import pytest

from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.data.fund_flow_store import FundFlowRecord


def _ctx(prices, fund_flow_records=None, industry_pct=3.0, regime="normal"):
    return {
        "prices": prices,
        "fund_flow_records": fund_flow_records or [],
        "industry_day_pct": industry_pct,  # 行业当日涨幅
        "regime": regime,
    }


def _prices_with_limit_up_today():
    """今天涨停 (+10%), 主力净流入强, 行业涨 3%。"""
    dates = pd.bdate_range("2026-06-01", periods=22)
    closes = [10.0] * 21 + [11.0]  # 前 21 日平盘, 今日涨停
    pct = [0.0] * 20 + [0.0, 10.0]  # 今日 +10%
    return pd.DataFrame({"date": dates, "close": closes, "open": closes,
                         "high": closes, "low": closes, "pct_change": pct})


def test_hit_when_all_conditions_met():
    prices = _prices_with_limit_up_today()
    # 主力净流入: 今日大额, 前 20 日均值小
    today = "202606" + prices.iloc[-1]["date"].strftime("%d")
    recs_today = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0,
                                  main_net_inflow=5_000_000, main_net_pct=8.0)]
    # 前 20 日小净流入
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0,
                                        main_net_inflow=100_000, main_net_pct=0.5))
    ctx = _ctx(prices, fund_flow_records=recs_today + old_recs, industry_pct=3.0)
    setup = BtstBreakoutSetup()
    result = setup.detect("X", today, ctx)
    assert result.hit is True
    assert result.trigger_strength > 0
    assert "跌破" in result.invalidation_condition or "破" in result.invalidation_condition


def test_miss_when_no_limit_up():
    """今天没涨停 → 不命中。"""
    prices = _prices_with_limit_up_today()
    prices.loc[prices.index[-1], "pct_change"] = 2.0  # 改成 +2% (没涨停)
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    ctx = _ctx(prices, industry_pct=3.0)
    setup = BtstBreakoutSetup()
    result = setup.detect("X", today, ctx)
    assert result.hit is False


def test_miss_when_industry_weak():
    """涨停 + 主力强, 但行业涨幅 < 2% → 不命中 (无板块效应)。"""
    prices = _prices_with_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    recs = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0,
                            main_net_inflow=5_000_000, main_net_pct=8.0)]
    ctx = _ctx(prices, fund_flow_records=recs, industry_pct=1.0)  # 行业弱
    setup = BtstBreakoutSetup()
    result = setup.detect("X", today, ctx)
    assert result.hit is False


def test_miss_when_main_inflow_weak():
    """涨停 + 行业强, 但主力净流入 < 20 日均值 → 不命中。"""
    prices = _prices_with_limit_up_today()
    today = prices.iloc[-1]["date"].strftime("%Y%m%d")
    # 今日主力净流入很小, 跟历史均值差不多
    recs = [FundFlowRecord(ticker="X", date=today, close=11.0, pct_change=10.0,
                            main_net_inflow=100_000, main_net_pct=0.5)]
    old_recs = []
    for i in range(1, 21):
        d = (prices.iloc[-1 - i]["date"]).strftime("%Y%m%d")
        old_recs.append(FundFlowRecord(ticker="X", date=d, close=10.0, pct_change=0.0,
                                        main_net_inflow=200_000, main_net_pct=1.0))
    ctx = _ctx(prices, fund_flow_records=recs + old_recs, industry_pct=3.0)
    setup = BtstBreakoutSetup()
    result = setup.detect("X", today, ctx)
    assert result.hit is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/offensive/test_btst_breakout.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
# src/screening/offensive/setups/btst_breakout.py
"""Setup-1: 涨停突破 (BTST Breakout)。

触发条件 (设计文档 §3.1):
1. 今日涨停 (pct_change ≥ 9.5%)
2. 主力净流入 > 0 且 > 过去 20 日均值
3. 所属行业当日涨幅 > 2% (板块效应)

失效条件: 价格跌破触发日收盘 × 0.92 (即 -8% 止损线)

依赖:
- context["prices"]: 单 ticker 价格 DataFrame
- context["fund_flow_records"]: list[FundFlowRecord] (含历史)
- context["industry_day_pct"]: float, 行业当日涨幅
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.screening.offensive.data.fund_flow_store import FundFlowRecord
from src.screening.offensive.setups.base import DetectionResult, Setup

_LIMIT_UP_PCT = 9.5
_INDUSTRY_PCT_MIN = 2.0
_MAIN_FLOW_LOOKBACK_DAYS = 20
_STOP_LOSS_PCT = -8.0  # 跌破 -8% 失效


class BtstBreakoutSetup(Setup):
    name = "btst_breakout"
    natural_horizon = 3  # 涨停动量爆发短, T+1~T+3 最强

    def detect(self, ticker: str, trade_date: str, context: dict[str, Any]) -> DetectionResult:
        prices: pd.DataFrame | None = context.get("prices")
        if prices is None or len(prices) == 0:
            return self._miss(ticker, trade_date)

        prices = prices.copy()
        prices["date_str"] = pd.to_datetime(prices["date"]).dt.strftime("%Y%m%d")
        trigger_rows = prices[prices["date_str"] == trade_date]
        if len(trigger_rows) == 0:
            return self._miss(ticker, trade_date)
        trigger_idx = trigger_rows.index[0]
        trigger_row = prices.iloc[trigger_idx]

        # 条件 1: 今日涨停
        pct_change = float(trigger_row.get("pct_change", 0.0) or 0.0)
        if pct_change < _LIMIT_UP_PCT:
            return self._miss(ticker, trade_date)

        # 条件 2: 主力净流入 > 0 且 > 20 日均值
        records: list[FundFlowRecord] = context.get("fund_flow_records") or []
        today_flow = next((r.main_net_inflow for r in records if r.date == trade_date), None)
        if today_flow is None or today_flow <= 0:
            return self._miss(ticker, trade_date)
        historical = [r.main_net_inflow for r in records if r.date < trade_date]
        if len(historical) >= 5:  # 至少 5 日历史才有均值意义
            hist_mean = sum(historical[-_MAIN_FLOW_LOOKBACK_DAYS:]) / len(historical[-_MAIN_FLOW_LOOKBACK_DAYS:])
            if today_flow <= hist_mean:
                return self._miss(ticker, trade_date)

        # 条件 3: 行业板块效应
        industry_pct = float(context.get("industry_day_pct") or 0.0)
        if industry_pct < _INDUSTRY_PCT_MIN:
            return self._miss(ticker, trade_date)

        trigger_close = float(trigger_row["close"])
        invalidation = f"价格跌破 {trigger_close * 0.92:.2f} (-8% 止损线)"
        # trigger_strength: 标准化的涨停强度 + 主力流入强度
        strength = min(1.0, (pct_change / 10.0) * 0.5 + min(today_flow / 5_000_000, 1.0) * 0.5)

        return DetectionResult(
            hit=True,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=strength,
            invalidation_condition=invalidation,
            metadata={
                "pct_change": pct_change,
                "main_net_inflow": today_flow,
                "industry_pct": industry_pct,
            },
        )

    @staticmethod
    def _miss(ticker: str, trade_date: str) -> DetectionResult:
        return DetectionResult(
            hit=False, ticker=ticker, trade_date=trade_date,
            trigger_strength=0.0, invalidation_condition="",
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/offensive/test_btst_breakout.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/screening/offensive/setups/btst_breakout.py tests/offensive/test_btst_breakout.py
git commit -m "feat(offensive): Setup-1 BTST 涨停突破触发逻辑 (Phase 0a Task 7)"
```

---

## Task 8: Phase 0 研究 CLI + IS/OOS 切分 + 决策报告

**Files:**
- Create: `scripts/setup_research.py`
- Test: `tests/offensive/test_setup_research_cli.py`

**Interfaces:**
- Consumes: `FundFlowStore`, `BtstBreakoutSetup`, `build_distribution`, `fetch_individual_fund_flow`, candidate_pool tickers, 价格数据 (复用 `src.tools.akshare_api.get_prices`)
- Produces:
  - `split_is_oos(trade_dates, split_date="20250101") -> tuple[list, list]`
  - `evaluate_setup(setup, tickers, trade_dates, ...) -> dict`（含 IS/OOS/ALL 分布 + 准入判定）
  - `render_report(eval_result) -> str`（Markdown 报告）
  - CLI: `python scripts/setup_research.py --setup btst_breakout --start 20230101 --end 20260630`

- [ ] **Step 1: 写失败测试**

```python
# tests/offensive/test_setup_research_cli.py
"""Phase 0 研究 CLI 测试 — IS/OOS 切分 + 准入判定 + 报告渲染。"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.setup_research import (
    split_is_oos,
    evaluate_setup,
    render_report,
    is_setup_qualified,
)
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup


def test_split_is_oos_by_date():
    dates = ["20240101", "20240601", "20250101", "20250601", "20260101"]
    is_dates, oos_dates = split_is_oos(dates, split_date="20250101")
    assert is_dates == ["20240101", "20240601"]
    assert oos_dates == ["20250101", "20250601", "20260101"]


def test_is_setup_qualified_passes_strong_setup():
    """convexity 2.0 + winrate 0.6 + n 60 + ic 0.08 → qualified。"""
    from src.screening.offensive.statistics import Distribution
    dist = Distribution(n=60, winrate=0.6, avg_gain=0.2, avg_loss=-0.05,
                        convexity_ratio=3.0, expected_return=0.1,
                        ci_low=0.05, ci_high=0.15, ic=0.08)
    assert is_setup_qualified(dist) is True


def test_is_setup_qualified_fails_low_n():
    from src.screening.offensive.statistics import Distribution
    dist = Distribution(n=40, winrate=0.6, avg_gain=0.2, avg_loss=-0.05,
                        convexity_ratio=3.0, expected_return=0.1,
                        ci_low=0.05, ci_high=0.15, ic=0.08)
    assert is_setup_qualified(dist) is False  # n < 50


def test_is_setup_qualified_fails_low_convexity():
    from src.screening.offensive.statistics import Distribution
    dist = Distribution(n=60, winrate=0.55, avg_gain=0.1, avg_loss=-0.1,
                        convexity_ratio=1.2, expected_return=0.005,
                        ci_low=-0.02, ci_high=0.03, ic=0.06)
    assert is_setup_qualified(dist) is False  # convexity < 1.5


def test_render_report_contains_verdict_and_stats():
    """报告含 PASS/FAIL verdict + 分布数字 + IS vs OOS 对比。"""
    from src.screening.offensive.distribution_builder import TermStructureDistribution
    from src.screening.offensive.statistics import Distribution
    dist_is = Distribution(n=60, winrate=0.6, avg_gain=0.2, avg_loss=-0.05,
                           convexity_ratio=3.0, expected_return=0.1, ci_low=0.05, ci_high=0.15, ic=0.08)
    dist_oos = Distribution(n=55, winrate=0.55, avg_gain=0.15, avg_loss=-0.06,
                            convexity_ratio=2.5, expected_return=0.07, ci_low=0.02, ci_high=0.12, ic=0.06)
    eval_result = {
        "setup_name": "btst_breakout",
        "is": TermStructureDistribution("btst_breakout", {3: dist_is}, 3, "ALL", "IS", 60),
        "oos": TermStructureDistribution("btst_breakout", {3: dist_oos}, 3, "ALL", "OOS", 55),
        "qualified_is": True,
        "qualified_oos": True,
        "verdict": "PASS",
    }
    report = render_report(eval_result)
    assert "PASS" in report
    assert "btst_breakout" in report
    assert "IS" in report and "OOS" in report
    assert "60" in report  # n


def test_evaluate_setup_integration(tmp_path, monkeypatch):
    """端到端: evaluate_setup 跑 setup 在样本上, 返回 IS/OOS/ALL 分布。"""
    # 构造 mock 数据 (3 个 ticker × 12 日价格)
    tickers = ["000001", "000002", "000003"]
    prices_by_ticker = {}
    for t in tickers:
        dates = pd.bdate_range("2024-01-01", periods=15)
        closes = [10.0 + i * 0.1 for i in range(15)]
        # 第 5 日涨停
        closes[5] = closes[4] * 1.10
        pct = [0.0] * 5 + [10.0] + [0.0] * 9
        prices_by_ticker[t] = pd.DataFrame({
            "date": dates, "close": closes, "open": closes,
            "high": closes, "low": closes, "pct_change": pct,
        })

    # mock FundFlowStore: 涨停日主力净流入大
    from src.screening.offensive.data.fund_flow_store import FundFlowRecord
    fund_flow = {}
    for t in tickers:
        trigger_date = prices_by_ticker[t].iloc[5]["date"].strftime("%Y%m%d")
        fund_flow[t] = [
            FundFlowRecord(ticker=t, date=trigger_date, close=closes[5], pct_change=10.0,
                           main_net_inflow=5_000_000, main_net_pct=8.0),
        ]

    trade_dates = [prices_by_ticker[t].iloc[5]["date"].strftime("%Y%m%d") for t in tickers]

    result = evaluate_setup(
        setup=BtstBreakoutSetup(),
        tickers=tickers,
        trade_dates=trade_dates,
        prices_by_ticker=prices_by_ticker,
        fund_flow_by_ticker=fund_flow,
        industry_pct_by_date={d: 3.0 for d in trade_dates},
        regimes_by_date={d: "normal" for d in trade_dates},
    )
    assert "is" in result and "oos" in result
    assert result["setup_name"] == "btst_breakout"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/offensive/test_setup_research_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写最小实现**

```python
# scripts/setup_research.py
"""Phase 0 研究 CLI — 验证凸性 setup 是否有 alpha。

流程:
1. 加载候选 ticker + 历史 trade_dates (从 auto_screening 报告 + trading calendar)
2. 拉取每个 ticker 的价格 + 资金流历史
3. 在 IS (≤ 2024) / OOS (≥ 2025) 两段上跑 setup
4. 应用 execution_adjuster (涨停可买性 + 滑点)
5. 计算分布 + 准入判定
6. 渲染 Markdown 报告 + 落盘

CLI:
    python scripts/setup_research.py --setup btst_breakout --start 20230101 --end 20260630
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from src.screening.offensive.distribution_builder import (
    TermStructureDistribution,
    build_distribution,
)
from src.screening.offensive.execution_adjuster import ExecutionConfig
from src.screening.offensive.setups.base import Setup
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.statistics import Distribution

logger = logging.getLogger(__name__)

# 准入门槛 (设计文档 §3.3 / §6.1)
_QUALIFY_CONVEXITY_MIN = 1.5
_QUALIFY_WINRATE_MIN = 0.50
_QUALIFY_N_MIN = 50
_QUALIFY_IC_MIN = 0.05

_IS_OOS_SPLIT_DATE = "20250101"


def split_is_oos(trade_dates: list[str], split_date: str = _IS_OOS_SPLIT_DATE) -> tuple[list[str], list[str]]:
    """按日期切 IS (in-sample) / OOS (out-of-sample)。"""
    is_dates = [d for d in trade_dates if d < split_date]
    oos_dates = [d for d in trade_dates if d >= split_date]
    return is_dates, oos_dates


def is_setup_qualified(dist: Distribution) -> bool:
    """单分布准入判定 (设计文档 §3.3 全部条件)。"""
    return (
        dist.n >= _QUALIFY_N_MIN
        and dist.winrate >= _QUALIFY_WINRATE_MIN
        and dist.convexity_ratio >= _QUALIFY_CONVEXITY_MIN
        and dist.ic >= _QUALIFY_IC_MIN
    )


def evaluate_setup(
    setup: Setup,
    tickers: list[str],
    trade_dates: list[str],
    prices_by_ticker: dict[str, pd.DataFrame],
    fund_flow_by_ticker: dict,
    industry_pct_by_date: dict[str, float],
    regimes_by_date: dict[str, str],
    horizons: tuple[int, ...] = (1, 3, 5, 10),
    config: ExecutionConfig | None = None,
) -> dict:
    """跑 setup 在样本上, 分 IS/OOS 出 TermStructureDistribution + 准入判定。"""
    config = config or ExecutionConfig()
    is_dates, oos_dates = split_is_oos(trade_dates)

    def _filter(dates):
        idx = [i for i, d in enumerate(trade_dates) if d in set(dates)]
        return [tickers[i] for i in idx], [trade_dates[i] for i in idx]

    def _build(dates_list, period):
        tk, td = _filter(dates_list)
        if not tk:
            return None
        # 注入 fund_flow + industry 到 context
        ctx_prices = prices_by_ticker
        # build_distribution 调用 setup.detect 时构造 context; 我们需要在 detect 里能拿到
        # fund_flow / industry — 这里通过 monkey-patch setup 的 context 构造
        # 简化: build_distribution 内部 ctx 只含 prices + regime; 我们包装 setup
        wrapped = _ContextInjectingSetupWrapper(
            setup, fund_flow_by_ticker, industry_pct_by_date,
        )
        return build_distribution(
            setup=wrapped, tickers=tk, trade_dates=td,
            prices_by_ticker=ctx_prices, regimes_by_date=regimes_by_date,
            horizons=horizons, config=config, period=period,
        )

    is_tsd = _build(is_dates, "IS") or _empty_tsd(setup, "IS")
    oos_tsd = _build(oos_dates, "OOS") or _empty_tsd(setup, "OOS")

    # 用 natural_horizon 的分布判准入
    nh = setup.natural_horizon
    qualified_is = is_setup_qualified(is_tsd.horizons.get(nh, _zero_dist()))
    qualified_oos = is_setup_qualified(oos_tsd.horizons.get(nh, _zero_dist()))

    # verdict: PASS 需 IS 和 OOS 都 qualified
    verdict = "PASS" if (qualified_is and qualified_oos) else "FAIL"

    return {
        "setup_name": setup.name,
        "natural_horizon": nh,
        "is": is_tsd,
        "oos": oos_tsd,
        "qualified_is": qualified_is,
        "qualified_oos": qualified_oos,
        "verdict": verdict,
    }


class _ContextInjectingSetupWrapper(Setup):
    """包装 setup, 注入 fund_flow + industry_pct 到 context。"""

    name = "wrapped"
    natural_horizon = 5

    def __init__(self, inner: Setup, fund_flow_by_ticker, industry_pct_by_date):
        self._inner = inner
        self.name = inner.name
        self.natural_horizon = inner.natural_horizon
        self._fund_flow = fund_flow_by_ticker
        self._industry = industry_pct_by_date

    def detect(self, ticker, trade_date, context):
        ctx = dict(context)
        ctx["fund_flow_records"] = self._fund_flow.get(ticker, [])
        ctx["industry_day_pct"] = self._industry.get(trade_date, 0.0)
        return self._inner.detect(ticker, trade_date, ctx)


def _empty_tsd(setup: Setup, period: str) -> TermStructureDistribution:
    return TermStructureDistribution(
        setup_name=setup.name, horizons={}, natural_horizon=setup.natural_horizon,
        regime="unknown", period=period, n_hits=0,
    )


def _zero_dist() -> Distribution:
    return Distribution(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def render_report(eval_result: dict) -> str:
    """渲染 Markdown 准入报告。"""
    name = eval_result["setup_name"]
    nh = eval_result["natural_horizon"]
    verdict = eval_result["verdict"]
    is_tsd: TermStructureDistribution = eval_result["is"]
    oos_tsd: TermStructureDistribution = eval_result["oos"]

    def _fmt_dist(tsd: TermStructureDistribution) -> str:
        d = tsd.horizons.get(nh)
        if d is None or d.n == 0:
            return f"  n=0 (无样本)"
        return (f"  n={d.n}  winrate={d.winrate:.1%}  E[r]={d.expected_return:+.2%}  "
                f"convexity={d.convexity_ratio:.2f}  IC={d.ic:.3f}  "
                f"CI=[{d.ci_low:+.2%}, {d.ci_high:+.2%}]")

    emoji = "✅" if verdict == "PASS" else "❌"
    lines = [
        f"# Setup 准入报告: {name}",
        f"",
        f"**Verdict: {emoji} {verdict}** (natural_horizon=T+{nh})",
        f"",
        f"## In-Sample (≤ {_IS_OOS_SPLIT_DATE[:4]})",
        _fmt_dist(is_tsd),
        f"  qualified: {eval_result['qualified_is']}",
        f"",
        f"## Out-of-Sample (≥ {_IS_OOS_SPLIT_DATE[:4]})",
        _fmt_dist(oos_tsd),
        f"  qualified: {eval_result['qualified_oos']}",
        f"",
        f"## 准入门槛",
        f"- convexity_ratio ≥ {_QUALIFY_CONVEXITY_MIN}",
        f"- winrate ≥ {_QUALIFY_WINRATE_MIN}",
        f"- n ≥ {_QUALIFY_N_MIN}",
        f"- IC > {_QUALIFY_IC_MIN}",
        f"- IS 和 OOS 都达标才 PASS",
        f"",
        f"## STOP 条件检查",
        f"- {'✅' if eval_result['qualified_oos'] else '❌'} OOS 达标 (防过拟合)",
        f"- {'✅' if is_tsd.horizons.get(nh) and is_tsd.horizons.get(nh).n > 0 else '❌'} IS 有样本",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Phase 0 setup 研究 CLI")
    parser.add_argument("--setup", default="btst_breakout", help="setup 名称")
    parser.add_argument("--start", default="20230101", help="回测起始日 YYYYMMDD")
    parser.add_argument("--end", default="20260630", help="回测结束日 YYYYMMDD")
    parser.add_argument("--output", default="data/reports/setup_research/", help="报告输出目录")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    # TODO Task 8 Step 6: 加载真实 tickers + 拉数据. 本期先输出"框架就绪"占位报告.
    # 真实数据加载留给执行阶段 (依赖网络 + 缓存, 不在单测范围).
    setups = {"btst_breakout": BtstBreakoutSetup}
    if args.setup not in setups:
        logger.error("unknown setup: %s", args.setup)
        sys.exit(1)

    logger.info("Phase 0 setup research framework ready. Setup=%s", args.setup)
    logger.info("真实数据加载 + 回测执行需在交互式 shell 中调用 evaluate_setup() (见 tests 示例)")
    # 占位输出: 证明 CLI 可调用
    Path(args.output).mkdir(parents=True, exist_ok=True)
    Path(args.output, f"{args.setup}_framework_ready.txt").write_text(
        f"framework ready for {args.setup}\nuse evaluate_setup() interactively with real data\n",
        encoding="utf-8",
    )
    logger.info("framework ready marker → %s", args.output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/offensive/test_setup_research_cli.py -v`
Expected: 6 passed

- [ ] **Step 5: 验证 CLI 可执行（框架就绪）**

Run: `uv run python scripts/setup_research.py --setup btst_breakout`
Expected: 输出 "framework ready" + 在 `data/reports/setup_research/` 落 `btst_breakout_framework_ready.txt`

- [ ] **Step 6: 提交**

```bash
git add scripts/setup_research.py tests/offensive/test_setup_research_cli.py
git commit -m "feat(offensive): Phase 0 研究 CLI + IS/OOS 切分 + 准入报告 (Phase 0a Task 8)"
```

---

## Phase 0a 完成准则（Definition of Done）

完成 Task 1-8 后，Phase 0a 交付：

1. **可复用 infra**（Phase 0b/0c 加 Setup-2..5 直接复用）：
   - `akshare_fund_flow.py` 资金流获取
   - `fund_flow_store.py` 存储 + 查询
   - `statistics.py` 分布 + IC + CI
   - `execution_adjuster.py` 执行成本调整（v2 P0）
   - `distribution_builder.py` 期限结构编排
   - `setups/base.py` Setup ABC
   - `scripts/setup_research.py` 研究 CLI

2. **Setup-1 (BTST 突破) 端到端可验证**：detect 逻辑 + execution-adjusted + IS/OOS 切分 + 准入判定 + 报告渲染

3. **测试覆盖**：全部模块 TDD，`uv run pytest tests/offensive/ tests/tools/test_akshare_fund_flow.py -v` 全绿

4. **第一个 go/no-go 信号**（执行 owner 自己跑，因为依赖真实数据 + 网络）：
   ```bash
   # 在交互式 Python 里 (网络可用时):
   # 1. backfill 资金流: for t in candidate_pool_tickers: store.save(t, fetch_individual_fund_flow(t))
   # 2. 拉价格: get_prices per ticker
   # 3. 跑 evaluate_setup(BtstBreakoutSetup(), ...) → verdict
   ```
   - **PASS** → 进 Phase 0b（加 Setup-2..5 + 龙虎榜 + FDR 多重检验）
   - **FAIL** → 报告如实记录，回到设计桌（可能 setup 选择不对，或执行成本吃掉了 alpha）

## 后续计划（不在本 plan 范围）

- **Phase 0b**: 龙虎榜数据接入 + Setup-2 (超跌反弹) / Setup-3 (板块轮动) / Setup-4 (龙虎榜共振) 验证 + FDR 多重检验（v2 §C.5）
- **Phase 0c**: Setup DISCOVERY（系统化扫描 setup 假设，v2 设计讨论遗留）+ 朴素基线对比（随机选股/指数定投，v2 §C.7）
- **Phase 1**: `--top-setups` live 前门（Kelly 排序 + 相关性折价 + 市场温度 + 风险框架 + shadow 模式）
- **Phase 2**: Kelly 仓位 + portfolio 约束 + drawdown 熔断上线
