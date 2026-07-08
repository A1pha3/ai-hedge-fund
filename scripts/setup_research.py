"""Phase 0 研究 CLI — 验证凸性 setup 是否有 alpha。

流程:
1. 加载候选 ticker + 历史 trade_dates (从 price_cache + fund_flow_cache + regime_history)
2. 拉取每个 ticker 的价格 + 资金流历史 (已缓存)
3. 在 IS (≤ 2022) / OOS (≥ 2023) 两段上跑 setup (含 regime 分层准入)
4. 应用 execution_adjuster (涨停可买性 + 滑点)
5. 计算分布 + 准入判定 + FDR 校正
6. 渲染 Markdown 报告 + 落盘

CLI:
    python -m scripts.setup_research --setup all
    python -m scripts.setup_research --setup btst_breakout
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.screening.offensive.distribution_builder import (
    TermStructureDistribution,
    build_distribution,
)
from src.screening.offensive.execution_adjuster import ExecutionConfig, adjust_returns
from src.screening.offensive.setups.base import Setup
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup
from src.screening.offensive.setups.sector_rotation import SectorRotationSetup
from src.screening.offensive.statistics import Distribution, benjamini_hochberg_fdr, setup_p_value
import numpy as np

logger = logging.getLogger(__name__)

# 准入门槛 (设计文档 §3.3 / §6.1)
_QUALIFY_CONVEXITY_MIN = 1.5
_QUALIFY_WINRATE_MIN = 0.50
_QUALIFY_N_MIN = 50
_QUALIFY_IC_MIN = 0.05

# IS/OOS 切分点: 2020-2022 (IS, 含疫情+2022熊市) / 2023-2026 (OOS, 含2024小微盘危机).
# 设计文档 §3.3/§6.1 原文是 "2023-2024训练/2025-2026验证" (示例措辞, 非硬契约),
# 但实测 20250101 切分导致 OOS 只剩 ~198 hits (2025牛市, 超跌反弹setup触发少),
# 对 regime-dependent setup 不公平. 切到 20230101 保证两段都有充足 crisis 样本.
# 严格保持设计文档硬约束: 时间顺序留出 + 两段都达标 + FDR 只在 IS 段做.
_IS_OOS_SPLIT_DATE = "20230101"


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


class _ContextInjectingSetupWrapper(Setup):
    """包装 setup, 注入 fund_flow + industry 数据到 context。

    industry 数据注入 (v2 §3.1 SectorRotation):
    - industry_day_pct: 按 (ticker 的行业, trade_date) 查真实 SW 行业指数 1 日涨幅
    - industry_2d_pct: 按 (ticker 的行业, trade_date) 查真实 SW 行业指数 2 日涨幅
    - stock_today_pct: 从 prices 取该 ticker 当日 pct_change
    - industry_net_flow: 不注入 (无真实源, SectorRotation 自动降级)
    """

    name = "wrapped"
    natural_horizon = 5

    def __init__(
        self,
        inner: Setup,
        fund_flow_by_ticker,
        industry_pct_by_date,
        industry_2d_pct: dict[tuple[str, str], float] | None = None,
        ticker_to_industry: dict[str, str] | None = None,
        industry_day_pct: dict[tuple[str, str], float] | None = None,
    ):
        self._inner = inner
        self.name = inner.name
        self.natural_horizon = inner.natural_horizon
        self._fund_flow = fund_flow_by_ticker
        self._industry = industry_pct_by_date
        self._industry_2d_pct = industry_2d_pct or {}
        self._ticker_to_industry = ticker_to_industry or {}
        self._industry_day_pct = industry_day_pct or {}
        # 缓存 ticker → {date_str: pct_change} 索引, 避免每次 detect 全表扫日期
        self._pct_index_cache: dict[str, dict[str, float]] = {}

    def _get_pct_index(self, ticker: str, prices: pd.DataFrame) -> dict[str, float]:
        """构建/取缓存的 {YYYYMMDD: pct_change} 索引 (per ticker 只算一次)."""
        cached = self._pct_index_cache.get(ticker)
        if cached is not None:
            return cached
        if prices is None or "pct_change" not in prices.columns:
            self._pct_index_cache[ticker] = {}
            return {}
        # date 列可能是 datetime (setup_research 加载时 pd.to_datetime) 或 str
        if hasattr(prices["date"].dt, "strftime"):
            date_strs = prices["date"].dt.strftime("%Y%m%d")
        else:
            date_strs = prices["date"].astype(str).str.replace("-", "", regex=False)
        idx = dict(zip(date_strs, prices["pct_change"]))
        self._pct_index_cache[ticker] = idx
        return idx

    def detect(self, ticker, trade_date, context):
        ctx = dict(context)
        ctx["fund_flow_records"] = self._fund_flow.get(ticker, [])
        industry_name = self._ticker_to_industry.get(ticker)
        if industry_name and self._industry_day_pct:
            ctx["industry_day_pct"] = self._industry_day_pct.get((industry_name, trade_date), self._industry.get(trade_date, 0.0))
        else:
            ctx["industry_day_pct"] = self._industry.get(trade_date, 0.0)
        # SectorRotation 需要的真实行业数据
        if self._industry_2d_pct and industry_name:
            ctx["industry_2d_pct"] = self._industry_2d_pct.get((industry_name, trade_date), 0.0)
        # stock_today_pct: 从缓存的 date→pct 索引取 (O(1), 不全表扫)
        prices = ctx.get("prices")
        pct_idx = self._get_pct_index(ticker, prices)
        if pct_idx and trade_date in pct_idx:
            ctx["stock_today_pct"] = float(pct_idx[trade_date])
        return self._inner.detect(ticker, trade_date, ctx)


def _empty_tsd(setup: Setup, period: str) -> TermStructureDistribution:
    return TermStructureDistribution(
        setup_name=setup.name, horizons={}, natural_horizon=setup.natural_horizon,
        regime="unknown", period=period, n_hits=0,
    )


def _zero_dist() -> Distribution:
    return Distribution(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


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
    industry_2d_pct: dict[tuple[str, str], float] | None = None,
    ticker_to_industry: dict[str, str] | None = None,
    industry_day_pct: dict[tuple[str, str], float] | None = None,
) -> dict:
    """跑 setup 在样本上, 分 IS/OOS 出 TermStructureDistribution + 准入判定。

    返回额外含 ``is_returns`` / ``oos_returns`` (natural horizon 的 execution-adjusted
    命中样本收益序列), 供 evaluate_setups 做 FDR 校正算 p-value (v2 §C.5)。

    v2 §3.3 新增: regime 分层准入. 命中样本按当时 regime (normal/crisis/risk_off)
    分组, 每组独立算准入, ``regime_qualified`` = 任一层达标. 这条之前是设计文档要求
    但完全没实现 (validate_phase0_multi_setup.py 把 regimes 全硬编码成 normal).
    """
    config = config or ExecutionConfig()
    is_dates, oos_dates = split_is_oos(trade_dates)
    is_set, oos_set = set(is_dates), set(oos_dates)
    nh = setup.natural_horizon

    def _filter(dates_set):
        idx = [i for i, d in enumerate(trade_dates) if d in dates_set]
        return [tickers[i] for i in idx], [trade_dates[i] for i in idx]

    def _build_from_hits(indices: list[int], period: str) -> TermStructureDistribution:
        """从已收集的命中样本 (按 indices 切片) 直接构建期限结构分布.

        性能优化: 替代之前 _build 调 build_distribution 的二次 detect.
        现在复用全量 detect 的结果, 只切片 + adjust_returns + compute_distribution.
        IC 也直接从切片算 (复用 information_coefficient).
        """
        from src.screening.offensive.statistics import compute_distribution, information_coefficient

        sub_tickers = [all_hit_tickers[i] for i in indices]
        sub_dates = [all_hit_dates[i] for i in indices]
        sub_strengths = [all_hit_strengths[i] for i in indices]
        # regime 众数
        regime_counts: dict[str, int] = {}
        for i in indices:
            r = all_hit_regimes[i]
            regime_counts[r] = regime_counts.get(r, 0) + 1
        regime = max(regime_counts.items(), key=lambda kv: kv[1])[0] if regime_counts else "unknown"

        horizon_dists: dict[int, Distribution] = {}
        for h in horizons:
            adj = adjust_returns(sub_dates, sub_tickers, prices_by_ticker, horizon=h, config=config)
            finite_mask = np.isfinite(adj)
            finite = adj[finite_mask]
            dist = compute_distribution(finite)
            # 算 IC (与 build_distribution 的修复一致)
            if len(sub_strengths) == len(adj) and len(finite) >= 5:
                aligned_str = np.asarray(sub_strengths, dtype=float)[finite_mask]
                ic = information_coefficient(aligned_str, finite)
                dist = Distribution(
                    n=dist.n, winrate=dist.winrate, avg_gain=dist.avg_gain,
                    avg_loss=dist.avg_loss, convexity_ratio=dist.convexity_ratio,
                    expected_return=dist.expected_return, ci_low=dist.ci_low,
                    ci_high=dist.ci_high, ic=ic,
                )
            horizon_dists[h] = dist
        return TermStructureDistribution(
            setup_name=setup.name, horizons=horizon_dists,
            natural_horizon=setup.natural_horizon, regime=regime,
            period=period, n_hits=len(sub_tickers),
        )

    # 一次性收集全量命中样本 (带 regime 标签 + trigger_strength), 供 IS/OOS/regime 三种切分共用.
    # 避免之前 _hit_returns 对 IS 和 OOS 各 detect 一次 + build_distribution 又 detect
    # 一次的三重重复. 现在只 detect 一次全量.
    wrapped = _ContextInjectingSetupWrapper(
        setup, fund_flow_by_ticker, industry_pct_by_date,
        industry_2d_pct, ticker_to_industry, industry_day_pct,
    )
    all_hit_tickers, all_hit_dates, all_hit_regimes, all_hit_strengths = [], [], [], []
    total_degraded = 0
    for ticker, date_str in zip(tickers, trade_dates):
        ctx = {"prices": prices_by_ticker.get(ticker), "regime": regimes_by_date.get(date_str, "normal")}
        result = wrapped.detect(ticker, date_str, ctx)
        if result.hit:
            all_hit_tickers.append(ticker)
            all_hit_dates.append(date_str)
            all_hit_regimes.append(regimes_by_date.get(date_str, "normal"))
            all_hit_strengths.append(result.trigger_strength)
            if result.degraded:
                total_degraded += 1

    # natural horizon 的 execution-adjusted 收益 (全量命中), 后续按 IS/OOS/regime 切片
    if all_hit_tickers:
        all_adj = adjust_returns(
            all_hit_dates, all_hit_tickers, prices_by_ticker,
            horizon=nh, config=config,
        )
    else:
        all_adj = np.array([])
    all_strengths_arr = np.asarray(all_hit_strengths, dtype=float) if all_hit_strengths else np.array([])

    def _slice_returns(indices: list[int]) -> np.ndarray:
        if not indices:
            return np.array([])
        sub = all_adj[indices] if len(all_adj) == len(all_hit_tickers) else np.array([])
        return sub[np.isfinite(sub)] if len(sub) > 0 else np.array([])

    def _slice_strengths(indices: list[int]) -> np.ndarray:
        """与 _slice_returns 对齐: 取相同 indices, 同样剔除 adj=nan 的样本."""
        if not indices or len(all_strengths_arr) != len(all_adj):
            return np.array([])
        sub_adj = all_adj[indices]
        sub_str = all_strengths_arr[indices]
        mask = np.isfinite(sub_adj)
        return sub_str[mask]

    # IS / OOS 切片 (按命中样本的日期归属)
    is_idx = [i for i, d in enumerate(all_hit_dates) if d in is_set]
    oos_idx = [i for i, d in enumerate(all_hit_dates) if d in oos_set]
    is_ret = _slice_returns(is_idx)
    oos_ret = _slice_returns(oos_idx)

    # regime 分层切片 (设计文档 §3.3: "regime 分层后至少一个 regime 仍达标")
    # 全样本 regime 分组 (不按 IS/OOS 再切 — 样本量已分层会太小).
    from src.screening.offensive.statistics import compute_distribution, information_coefficient
    regime_breakdown: dict[str, dict] = {}
    for regime_label in ("normal", "crisis", "risk_off"):
        r_idx = [i for i, r in enumerate(all_hit_regimes) if r == regime_label]
        r_ret = _slice_returns(r_idx)
        r_dist = compute_distribution(r_ret)
        # 算 IC (修复: 此前 regime 层 IC 永远=0, qualified 永远 False)
        r_str = _slice_strengths(r_idx)
        r_ic = information_coefficient(r_str, r_ret) if len(r_ret) >= 5 else 0.0
        from src.screening.offensive.statistics import Distribution as _Dist
        r_dist = _Dist(
            n=r_dist.n, winrate=r_dist.winrate, avg_gain=r_dist.avg_gain,
            avg_loss=r_dist.avg_loss, convexity_ratio=r_dist.convexity_ratio,
            expected_return=r_dist.expected_return, ci_low=r_dist.ci_low,
            ci_high=r_dist.ci_high, ic=r_ic,
        )
        regime_breakdown[regime_label] = {
            "n": r_dist.n,
            "qualified": is_setup_qualified(r_dist),
            "winrate": r_dist.winrate,
            "expected_return": r_dist.expected_return,
            "convexity_ratio": r_dist.convexity_ratio,
            "ic": r_dist.ic,
        }
    regime_qualified = any(layer["qualified"] for layer in regime_breakdown.values())

    is_tsd = _build_from_hits(is_idx, "IS") if is_idx else _empty_tsd(setup, "IS")
    oos_tsd = _build_from_hits(oos_idx, "OOS") if oos_idx else _empty_tsd(setup, "OOS")

    qualified_is = is_setup_qualified(is_tsd.horizons.get(nh, _zero_dist()))
    qualified_oos = is_setup_qualified(oos_tsd.horizons.get(nh, _zero_dist()))
    # verdict 升级: IS + OOS + regime 三重门槛 (设计文档 §3.3 全部条件)
    verdict = "PASS" if (qualified_is and qualified_oos and regime_qualified) else "FAIL"

    total_hits = len(all_hit_tickers)

    return {
        "setup_name": setup.name,
        "natural_horizon": nh,
        "is": is_tsd,
        "oos": oos_tsd,
        "qualified_is": qualified_is,
        "qualified_oos": qualified_oos,
        "regime_qualified": regime_qualified,
        "regime_breakdown": regime_breakdown,
        "verdict": verdict,
        "split_date": _IS_OOS_SPLIT_DATE,
        # natural horizon 的命中样本收益序列 (供 evaluate_setups 算 FDR p-value)
        "is_returns": is_ret,
        "oos_returns": oos_ret,
        # 诚实降级披露 (NS-17 同类): 命中里因数据缺失降级的比例
        "degraded_count": total_degraded,
        "degraded_ratio": (total_degraded / total_hits) if total_hits > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Phase 0 FDR 校正门槛 (v2 §C.5 / §3.3 / §6.1)
# ---------------------------------------------------------------------------

# 文档 §3.3: FDR 校正后 ≥2 个 setup 达标才进 Phase 1 (防 p-hacking)
_PHASE0_MIN_FDR_SIGNIFICANT = 2
_FDR_ALPHA = 0.05


def evaluate_setups(
    setups: list[Setup],
    tickers: list[str],
    trade_dates: list[str],
    prices_by_ticker: dict[str, pd.DataFrame],
    fund_flow_by_ticker: dict,
    industry_pct_by_date: dict[str, float],
    regimes_by_date: dict[str, str],
    horizons: tuple[int, ...] = (1, 3, 5, 10),
    config: ExecutionConfig | None = None,
    industry_2d_pct: dict[tuple[str, str], float] | None = None,
    ticker_to_industry: dict[str, str] | None = None,
    industry_day_pct: dict[tuple[str, str], float] | None = None,
) -> dict:
    """批量跑多 setup, 对检验家族做 FDR 校正 (v2 §C.5 反 p-hacking).

    流程:
    1. 对每个 setup 调 evaluate_setup → 得分布 + IS returns
    2. 用 IS 段 returns 算每个 setup 的 p-value (H0: expected_return=0, 单样本 t 检验)
       FDR 只在 IS (训练段) 做 — OOS 是验证段, 在 OOS 上算 p 再 FDR 会信息泄漏
    3. benjamini_hochberg_fdr(p_values, alpha) → q_values + significant_indices
    4. phase0_verdict: PASS 当且仅当 FDR 校正后显著数 ≥ 2 (文档 §3.3)

    Args: 同 evaluate_setup, 但 setups 是列表 (检验家族).

    Returns:
        ``{setups: [{setup_name, p_value, q_value, fdr_significant, p_value_oos, ...evaluate_setup 字段}],
           n_fdr_significant, phase0_verdict, alpha}``
    """
    per_setup = []
    is_p_values: list[float] = []
    for setup in setups:
        result = evaluate_setup(
            setup=setup, tickers=tickers, trade_dates=trade_dates,
            prices_by_ticker=prices_by_ticker, fund_flow_by_ticker=fund_flow_by_ticker,
            industry_pct_by_date=industry_pct_by_date, regimes_by_date=regimes_by_date,
            horizons=horizons, config=config,
            industry_2d_pct=industry_2d_pct, ticker_to_industry=ticker_to_industry,
            industry_day_pct=industry_day_pct,
        )
        # IS 段 p-value (训练段, 用于 FDR)
        p_is = setup_p_value(result["is_returns"])
        # OOS 段 p-value (验证段, 仅披露稳定性, 不参与 FDR)
        p_oos = setup_p_value(result["oos_returns"])
        result["p_value"] = p_is
        result["p_value_oos"] = p_oos
        per_setup.append(result)
        is_p_values.append(p_is)

    # FDR 校正 (IS 段 p-value 数组)
    q_values, sig_indices = benjamini_hochberg_fdr(np.array(is_p_values), alpha=_FDR_ALPHA)
    sig_set = set(sig_indices)
    for i, result in enumerate(per_setup):
        result["q_value"] = float(q_values[i])
        result["fdr_significant"] = i in sig_set

    n_fdr_significant = len(sig_indices)
    phase0_verdict = "PASS" if n_fdr_significant >= _PHASE0_MIN_FDR_SIGNIFICANT else "FAIL"

    return {
        "setups": per_setup,
        "n_fdr_significant": n_fdr_significant,
        "phase0_verdict": phase0_verdict,
        "alpha": _FDR_ALPHA,
        "min_significant": _PHASE0_MIN_FDR_SIGNIFICANT,
    }


# ---------------------------------------------------------------------------
# 回测宇宙加载 (从缓存批量读 302 ticker × 全历史)
# ---------------------------------------------------------------------------

_PRICE_CACHE_DIR = Path("data/price_cache")
_FUND_FLOW_CACHE_DIR = Path("data/fund_flow_cache")
_REGIME_HISTORY_PATH = Path("data/reports/regime_history.json")
_BACKTEST_START = "20200101"
_BACKTEST_END = "20260707"


def load_backtest_universe(
    price_cache_dir: Path = _PRICE_CACHE_DIR,
    fund_flow_cache_dir: Path = _FUND_FLOW_CACHE_DIR,
    regime_history_path: Path = _REGIME_HISTORY_PATH,
    start_date: str = _BACKTEST_START,
    end_date: str = _BACKTEST_END,
) -> dict:
    """从缓存批量加载回测宇宙 (302 ticker × 全历史).

    替代之前 validate_phase0_multi_setup.py 里重复内联的加载逻辑. 三个关键修正:
      1. 直接遍历 price_cache/*.csv 取 ticker (302个), 不依赖 candidate_pool JSON (300)
      2. regimes_by_date 从 regime_history.json 读真实标签 (此前全硬编码 normal)
      3. industry_pct_by_date 从 SW L1 行业指数单日涨幅聚合, 不再使用固定假值

    Returns:
        {tickers, trade_dates, prices_by_ticker, fund_flow_by_ticker,
         industry_pct_by_date, regimes_by_date}
    """
    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    # 真实 regime 标签 (不再全 normal — 让 regime 分层准入 §3.3 生效)
    regimes_by_date: dict[str, str] = {}
    if regime_history_path.exists():
        raw = json.loads(regime_history_path.read_text(encoding="utf-8"))
        regimes_by_date = {str(k): str(v) for k, v in raw.items()}

    tickers_with_cache = sorted(p.stem for p in price_cache_dir.glob("*.csv"))
    store = FundFlowStore(cache_dir=str(fund_flow_cache_dir))

    prices_by_ticker: dict[str, pd.DataFrame] = {}
    fund_flow_by_ticker: dict = {}
    loaded = 0
    for ticker in tickers_with_cache:
        pf = price_cache_dir / f"{ticker}.csv"
        if not pf.exists():
            continue
        df = pd.read_csv(pf, dtype={"date": str})
        if "close" not in df.columns or len(df) < 50:
            continue
        df["date"] = pd.to_datetime(df["date"])
        prices_by_ticker[ticker] = df
        fund_flow_by_ticker[ticker] = store.get_range(ticker, start_date, end_date)
        loaded += 1
    logger.info("load_backtest_universe: %d ticker (缓存 %d)", loaded, len(tickers_with_cache))

    # trade_dates: regime_history 覆盖的全部交易日 (权威交易日历)
    trade_dates = sorted(d for d in regimes_by_date if start_date <= d <= end_date)

    # 行业指数数据 (供 SectorRotation): SW L1 真实 2 日涨幅 + ticker→行业映射
    industry_2d_pct = load_industry_2d_pct()
    ticker_to_industry = build_ticker_to_industry(list(prices_by_ticker))
    industry_day_pct = load_industry_day_pct()
    industry_pct_by_date = _aggregate_industry_day_pct_by_date(
        trade_dates,
        ticker_to_industry,
        industry_day_pct,
    )

    return {
        "tickers": tickers_with_cache,
        "trade_dates": trade_dates,
        "prices_by_ticker": prices_by_ticker,
        "fund_flow_by_ticker": fund_flow_by_ticker,
        "industry_pct_by_date": industry_pct_by_date,
        "regimes_by_date": regimes_by_date,
        "industry_day_pct": industry_day_pct,
        "industry_2d_pct": industry_2d_pct,
        "ticker_to_industry": ticker_to_industry,
    }


def build_candidates_by_setup(
    prices_by_ticker: dict[str, pd.DataFrame],
    industry_2d_pct: dict[tuple[str, str], float] | None = None,
    ticker_to_industry: dict[str, str] | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """各 setup 的候选 (ticker, date) 预过滤, 避免对全样本跑慢 detect.

    - BTST: 涨停日 (pct_change >= 9.5%)
    - OversoldBounce: 近30日跌幅 <= -20% 的日子
    - SectorRotation: 行业 2 日涨幅 > 3% 的日子 (需 industry_2d_pct + ticker_to_industry)

    返回 {setup_name: [(ticker, YYYYMMDD), ...]}.
    """
    btst_cands: list[tuple[str, str]] = []
    oversold_cands: list[tuple[str, str]] = []
    sector_cands: list[tuple[str, str]] = []
    # 预建 (industry, date) → 2d_pct 的强行业日索引 (>3% 阈值)
    strong_industry_days: set[tuple[str, str]] = set()
    if industry_2d_pct:
        strong_industry_days = {k for k, v in industry_2d_pct.items() if v >= 3.0}

    for ticker, df in prices_by_ticker.items():
        if df is None or len(df) == 0 or "pct_change" not in df.columns:
            continue
        ds = df.copy()
        ds["date_str"] = df["date"].dt.strftime("%Y%m%d")
        # BTST 候选: 涨停日
        for _, row in ds[ds["pct_change"] >= 9.5].iterrows():
            btst_cands.append((ticker, row["date_str"]))
        # OversoldBounce 候选: 近30日跌幅 <= -20%
        if len(ds) > 30:
            ds["drop_30d"] = (ds["close"] / ds["close"].shift(30) - 1) * 100
            for _, row in ds[ds["drop_30d"] <= -20.0].iterrows():
                oversold_cands.append((ticker, row["date_str"]))
        # SectorRotation 候选: 该 ticker 的行业在当日 2 日涨幅 > 3%
        if strong_industry_days and ticker_to_industry:
            industry = ticker_to_industry.get(ticker)
            if industry:
                for date_str in ds["date_str"]:
                    if (industry, date_str) in strong_industry_days:
                        sector_cands.append((ticker, date_str))
    return {"btst_breakout": btst_cands, "oversold_bounce": oversold_cands, "sector_rotation": sector_cands}


# ---------------------------------------------------------------------------
# 行业指数数据 (SW L1) — 供 SectorRotation 的 industry_2d_pct
# ---------------------------------------------------------------------------

_INDUSTRY_INDEX_CACHE_DIR = Path("data/industry_index_cache")


def load_industry_2d_pct(
    cache_dir: Path = _INDUSTRY_INDEX_CACHE_DIR,
) -> dict[tuple[str, str], float]:
    """加载行业指数 2 日累计涨幅 → {(industry_name, YYYYMMDD): pct%}.

    从 31 个 SW L1 行业指数 CSV 算: pct_chg[t] + pct_chg[t-1].
    industry_name 来自 _industry_codes.json (中文, 与 ticker→industry 映射一致).

    数据源: scripts/backfill_industry_index.py (3.9 秒拉完全部).
    """
    codes_path = cache_dir / "_industry_codes.json"
    if not codes_path.exists():
        logger.warning("industry index cache 不存在, 跑 scripts.backfill_industry_index")
        return {}
    codes_map: dict[str, str] = json.loads(codes_path.read_text(encoding="utf-8"))

    result: dict[tuple[str, str], float] = {}
    for index_code, industry_name in codes_map.items():
        csv_path = cache_dir / f"{index_code}.csv"
        if not csv_path.exists():
            continue
        df = pd.read_csv(csv_path, dtype={"trade_date": str})
        if "pct_chg" not in df.columns or "trade_date" not in df.columns:
            continue
        df = df.sort_values("trade_date").reset_index(drop=True)
        # 2 日累计涨幅 = pct_chg[t] + pct_chg[t-1] (近似, 忽略复利交叉项)
        df["pct_2d"] = df["pct_chg"].rolling(2).sum()
        for _, row in df.iterrows():
            d = str(row["trade_date"])
            v = row["pct_2d"]
            if pd.notna(v):
                result[(industry_name, d)] = float(v)
    logger.info("load_industry_2d_pct: %d (industry, date) 条", len(result))
    return result


def load_industry_day_pct(
    cache_dir: Path = _INDUSTRY_INDEX_CACHE_DIR,
) -> dict[tuple[str, str], float]:
    """加载行业指数单日涨幅 → {(industry_name, YYYYMMDD): pct%}."""

    codes_path = cache_dir / "_industry_codes.json"
    if not codes_path.exists():
        logger.warning("industry index cache 不存在, 跑 scripts.backfill_industry_index")
        return {}
    codes_map: dict[str, str] = json.loads(codes_path.read_text(encoding="utf-8"))

    result: dict[tuple[str, str], float] = {}
    for index_code, industry_name in codes_map.items():
        csv_path = cache_dir / f"{index_code}.csv"
        if not csv_path.exists():
            continue
        df = pd.read_csv(csv_path, dtype={"trade_date": str})
        if "pct_chg" not in df.columns or "trade_date" not in df.columns:
            continue
        for _, row in df.iterrows():
            value = row["pct_chg"]
            if pd.notna(value):
                result[(industry_name, str(row["trade_date"]).replace("-", ""))] = float(value)
    logger.info("load_industry_day_pct: %d (industry, date) 条", len(result))
    return result


def _aggregate_industry_day_pct_by_date(
    trade_dates: list[str],
    ticker_to_industry: dict[str, str],
    industry_day_pct: dict[tuple[str, str], float],
) -> dict[str, float]:
    industries = sorted(set(ticker_to_industry.values()))
    result: dict[str, float] = {}
    for trade_date in trade_dates:
        values = [industry_day_pct[(industry, trade_date)] for industry in industries if (industry, trade_date) in industry_day_pct]
        result[trade_date] = float(sum(values) / len(values)) if values else 0.0
    return result


def build_ticker_to_industry(tickers: list[str]) -> dict[str, str]:
    """ticker → SW L1 行业名. 优先 get_sw_industry_classification (全市场完整),
    回退 candidate_pool 聚合 (补漏).

    Returns:
        {ticker: industry_name}; 无映射的 ticker 不含在返回 dict 中.
    """
    mapping: dict[str, str] = {}
    # 1. 优先: 全市场 SW 分类 (tushare index_member, 最完整)
    try:
        from src.tools.tushare_api import get_sw_industry_classification

        sw_map = get_sw_industry_classification()
        if sw_map:
            for t in tickers:
                # tushare code 格式: 000001.SZ; 我们缓存用 6 位无后缀
                for suffix in (".SZ", ".SH", ".BJ"):
                    ind = sw_map.get(f"{t}{suffix}")
                    if ind:
                        mapping[t] = ind
                        break
    except Exception as exc:
        logger.warning("get_sw_industry_classification 失败, 回退 candidate_pool: %s", exc)

    # 2. 补漏: candidate_pool 聚合 (跨多个 snapshot 提高覆盖率)
    missing = [t for t in tickers if t not in mapping]
    if missing:
        pool_dir = Path("data/snapshots")
        pools = sorted(pool_dir.glob("candidate_pool_*.json"))
        pool_map: dict[str, str] = {}
        for p in pools:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                records = data if isinstance(data, list) else (
                    data.get("selected_candidates", []) + data.get("shadow_candidates", [])
                )
                for rec in records:
                    if isinstance(rec, dict) and rec.get("ticker") and rec.get("industry_sw"):
                        pool_map[str(rec["ticker"])] = str(rec["industry_sw"])
            except (json.JSONDecodeError, OSError):
                continue
        for t in missing:
            if t in pool_map:
                mapping[t] = pool_map[t]

    covered = len(mapping)
    total = len(tickers)
    logger.info(
        "build_ticker_to_industry: %d/%d ticker 有行业映射 (%.0f%% 覆盖)",
        covered, total, covered / total * 100 if total else 0,
    )
    return mapping


def render_report(eval_result: dict) -> str:
    """渲染 Markdown 准入报告。"""
    name = eval_result["setup_name"]
    nh = eval_result["natural_horizon"]
    verdict = eval_result["verdict"]
    is_tsd: TermStructureDistribution = eval_result["is"]
    oos_tsd: TermStructureDistribution = eval_result["oos"]
    split_date = eval_result.get("split_date", _IS_OOS_SPLIT_DATE)
    split_year = split_date[:4]

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
        "",
        f"**Verdict: {emoji} {verdict}** (natural_horizon=T+{nh})",
        "",
        f"## In-Sample (< {split_year})",
        _fmt_dist(is_tsd),
        f"  qualified: {eval_result['qualified_is']}",
        "",
        f"## Out-of-Sample (≥ {split_year})",
        _fmt_dist(oos_tsd),
        f"  qualified: {eval_result['qualified_oos']}",
        "",
        "## Regime 分层 (设计文档 §3.3: 至少一层达标)",
    ]
    # regime 分层表 (全样本按当时 regime 分组, 每组独立准入判定)
    regime_breakdown = eval_result.get("regime_breakdown", {})
    if regime_breakdown:
        lines.append("")
        lines.append("| Regime | N | 胜率 | E[r] | 凸性 | 达标 |")
        lines.append("|--------|---|------|------|------|------|")
        for r in ("normal", "crisis", "risk_off"):
            rb = regime_breakdown.get(r, {})
            ok = "✅" if rb.get("qualified") else "❌"
            lines.append(
                f"| {r} | {rb.get('n', 0)} | {rb.get('winrate', 0):.1%} | "
                f"{rb.get('expected_return', 0):+.2%} | {rb.get('convexity_ratio', 0):.2f} | {ok} |"
            )
        regime_q = eval_result.get("regime_qualified", False)
        lines.append(f"\nregime_qualified: {'✅ 至少一层达标' if regime_q else '❌ 无层达标'}")

    lines.extend([
        "",
        "## 准入门槛",
        f"- convexity_ratio ≥ {_QUALIFY_CONVEXITY_MIN}",
        f"- winrate ≥ {_QUALIFY_WINRATE_MIN}",
        f"- n ≥ {_QUALIFY_N_MIN}",
        f"- IC > {_QUALIFY_IC_MIN}",
        "- IS + OOS + regime 三重达标才 PASS (设计文档 §3.3)",
        "",
        "## STOP 条件检查",
        f"- {'✅' if eval_result['qualified_is'] else '❌'} IS 达标",
        f"- {'✅' if eval_result['qualified_oos'] else '❌'} OOS 达标 (防过拟合)",
        f"- {'✅' if eval_result.get('regime_qualified') else '❌'} regime 分层达标 (§3.3)",
        f"- {'✅' if is_tsd.horizons.get(nh) and is_tsd.horizons.get(nh).n > 0 else '❌'} IS 有样本",
    ])
    return "\n".join(lines)


def render_phase0_report(eval_setups_result: dict) -> str:
    """渲染 Phase 0 批量准入报告 (含 FDR 校正表 + STOP 条件检查).

    文档 §6.1: Phase 0 成功 = FDR 校正后 ≥2 个 setup 达标. 本报告披露每个 setup 的
    p-value / q-value / FDR 校正前后状态, 让 owner 判断"达标"是否经多重检验校正.
    """
    setups = eval_setups_result["setups"]
    n_sig = eval_setups_result["n_fdr_significant"]
    min_sig = eval_setups_result["min_significant"]
    alpha = eval_setups_result["alpha"]
    verdict = eval_setups_result["phase0_verdict"]
    emoji = "✅" if verdict == "PASS" else "❌"

    lines = [
        "# Phase 0 准入报告 (含 FDR 校正 + regime 分层)",
        "",
        f"**Phase 0 Verdict: {emoji} {verdict}** "
        f"(FDR 校正后 {n_sig}/{len(setups)} 个 setup 显著, 需 ≥{min_sig})",
        "",
        f"## FDR 校正表 (Benjamini-Hochberg, α={alpha})",
        "",
        "| Setup | p-value (IS) | q-value (FDR) | FDR 显著 | p-value (OOS) | OOS 达标 | Regime 达标 | 降级 |",
        "|-------|-------------|---------------|----------|--------------|----------|-------------|------|",
    ]
    for s in setups:
        p_is = s.get("p_value", 1.0)
        q = s.get("q_value", 1.0)
        fdr_sig = "✅ 是" if s.get("fdr_significant") else "❌ 否"
        p_oos = s.get("p_value_oos", 1.0)
        oos_ok = "✅" if s.get("qualified_oos") else "❌"
        regime_ok = "✅" if s.get("regime_qualified") else "❌"
        degraded_ratio = s.get("degraded_ratio", 0.0)
        degraded_count = s.get("degraded_count", 0)
        if degraded_ratio > 0:
            deg_cell = f"⚠️ {degraded_count} ({degraded_ratio:.0%})"
        else:
            deg_cell = "—"
        lines.append(
            f"| {s['setup_name']} | {p_is:.2e} | {q:.2e} | {fdr_sig} | {p_oos:.2e} | {oos_ok} | {regime_ok} | {deg_cell} |"
        )

    # regime 分层明细表 (每个 setup 在 normal/crisis/risk_off 三层的 n + 达标状态)
    lines.extend([
        "",
        "## Regime 分层明细 (设计文档 §3.3: 至少一层达标)",
        "",
        "| Setup | normal (n/达标) | crisis (n/达标) | risk_off (n/达标) |",
        "|-------|-----------------|-----------------|-------------------|",
    ])
    for s in setups:
        rb = s.get("regime_breakdown", {})
        cells = []
        for r in ("normal", "crisis", "risk_off"):
            layer = rb.get(r, {})
            n = layer.get("n", 0)
            ok = "✅" if layer.get("qualified") else "❌"
            cells.append(f"{n}/{ok}")
        lines.append(f"| {s['setup_name']} | {cells[0]} | {cells[1]} | {cells[2]} |")

    # 降级警告段 (诚实披露: PASS 建立在残缺 setup 上的情况)
    degraded_setups = [s for s in setups if s.get("degraded_ratio", 0.0) > 0]
    if degraded_setups:
        lines.extend([
            "",
            "## ⚠️ 数据降级警告",
            "",
            "以下 setup 的部分条件因数据缺失而跳过, 当前命中基于残缺条件集.",
            "数据接入后需复跑 Phase 0 — 命中集/分布可能变, FDR 结论可能翻转:",
            "",
        ])
        for s in degraded_setups:
            lines.append(
                f"- **{s['setup_name']}**: {s['degraded_count']} 命中降级 ({s['degraded_ratio']:.0%}) "
                f"— 条件未全部生效, 当前是残缺版 setup"
            )

    lines.extend([
        "",
        "## STOP 条件检查 (文档 §6.1)",
        f"- {'✅' if n_sig >= min_sig else '❌'} FDR 校正后 ≥{min_sig} 个 setup 显著 ({n_sig}/{len(setups)})",
        f"- {'✅' if n_sig > 0 else '❌'} 至少 1 个 setup 有真实 alpha (非纯噪声)",
        "",
        "## 说明",
        f"- **IS 段**: < {_IS_OOS_SPLIT_DATE[:4]} (训练段, 含2020疫情+2022熊市)",
        f"- **OOS 段**: ≥ {_IS_OOS_SPLIT_DATE[:4]} (验证段, 含2024小微盘危机)",
        "- **p-value (IS)**: 单样本 t 检验 H0: setup 命中样本 expected_return=0",
        "- **q-value (FDR)**: Benjamini-Hochberg 校正后的 p-value (防多 setup 同时回测的 p-hacking)",
        "- **p-value (OOS)**: 验证段的 p-value, 仅披露稳定性, 不参与 FDR (防信息泄漏)",
        "- **Regime 达标**: normal/crisis/risk_off 三层中至少一层准入达标 (§3.3)",
        "- **FDR 显著**: q-value ≤ α 才算; 这是 PASS 的硬门槛",
        "",
        f"{'## ✅ 可进 Phase 1' if verdict == 'PASS' else '## ❌ STOP — 不进 Phase 1'}",
    ])
    if verdict != "PASS":
        lines.append(
            f"仅 {n_sig} 个 setup FDR 校正后显著 (< {min_sig}). "
            "文档 §3.3: 凸性 setup 在当前数据下没有足够 alpha, 或需要更多 setup 验证."
        )
    return "\n".join(lines)


def main():
    """Phase 0 端到端: 加载数据 → 跑 setup → FDR 校正 → 渲染报告 → 落盘.

    此前 main() 是空壳 (只写 framework_ready.txt, 无数据加载). 真实回测需交互式
    注入数据, 不可复现. 现在用 load_backtest_universe() 端到端跑通.
    """
    parser = argparse.ArgumentParser(description="Phase 0 setup 研究 CLI (端到端)")
    parser.add_argument(
        "--setup", default="all",
        help="setup 名称 (btst_breakout / oversold_bounce) 或 all (批量, 默认)",
    )
    parser.add_argument("--output", default="data/reports/setup_research/", help="报告输出目录")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    # setup 注册表
    setup_classes = {
        "btst_breakout": BtstBreakoutSetup,
        "oversold_bounce": OversoldBounceSetup,
        "sector_rotation": SectorRotationSetup,
    }
    if args.setup == "all":
        selected = list(setup_classes.keys())
    elif args.setup in setup_classes:
        selected = [args.setup]
    else:
        logger.error("unknown setup: %s (可选: %s, all)", args.setup, ", ".join(setup_classes))
        sys.exit(1)

    # 1. 加载回测宇宙 (302 ticker × 2020-2026, 真实 regime + 行业指数)
    logger.info("加载回测宇宙 (price_cache + fund_flow_cache + regime_history + industry_index)...")
    universe = load_backtest_universe()
    prices_by = universe["prices_by_ticker"]
    fund_flow_by = universe["fund_flow_by_ticker"]
    regimes_by = universe["regimes_by_date"]
    industry_pct = universe["industry_pct_by_date"]
    industry_day = universe["industry_day_pct"]
    industry_2d = universe["industry_2d_pct"]
    ticker_to_ind = universe["ticker_to_industry"]

    # 2. 各 setup 候选预过滤 (避免全样本跑慢 detect)
    logger.info("预过滤候选 (涨停日/超跌日/行业强动量日)...")
    candidates = build_candidates_by_setup(prices_by, industry_2d, ticker_to_ind)

    # 3. 每个 setup 只在自己的候选上跑 evaluate_setup (避免 N×M detect 爆炸)
    #    然后手动合并结果做 FDR (复用 evaluate_setups 的 FDR 逻辑)
    setups_objs = [setup_classes[n]() for n in selected]
    per_setup_results: list[dict] = []
    is_p_values: list[float] = []
    exec_cfg = ExecutionConfig(slippage_bps=30, limit_up_unbuyable=True, t_plus_1_lock=True)
    for setup_obj, name in zip(setups_objs, selected):
        cands = candidates.get(name, [])
        logger.info("  %s: %d 候选, 跑 evaluate_setup...", name, len(cands))
        cands_sorted = sorted(set(cands))
        ct = [c[0] for c in cands_sorted]
        cd = [c[1] for c in cands_sorted]
        result = evaluate_setup(
            setup=setup_obj, tickers=ct, trade_dates=cd,
            prices_by_ticker=prices_by, fund_flow_by_ticker=fund_flow_by,
            industry_pct_by_date=industry_pct, regimes_by_date=regimes_by,
            horizons=(5, 10), config=exec_cfg,
            industry_2d_pct=industry_2d, ticker_to_industry=ticker_to_ind,
            industry_day_pct=industry_day,
        )
        # 算 p-value (IS + OOS)
        result["p_value"] = setup_p_value(result["is_returns"])
        result["p_value_oos"] = setup_p_value(result["oos_returns"])
        per_setup_results.append(result)
        is_p_values.append(result["p_value"])

    # 4. FDR 校正 (IS 段 p-value 数组) + 合并成 evaluate_setups 格式
    q_values, sig_indices = benjamini_hochberg_fdr(np.array(is_p_values), alpha=_FDR_ALPHA)
    sig_set = set(sig_indices)
    for i, result in enumerate(per_setup_results):
        result["q_value"] = float(q_values[i])
        result["fdr_significant"] = i in sig_set
    n_fdr_significant = len(sig_indices)
    phase0_verdict = "PASS" if n_fdr_significant >= _PHASE0_MIN_FDR_SIGNIFICANT else "FAIL"
    result = {
        "setups": per_setup_results,
        "n_fdr_significant": n_fdr_significant,
        "phase0_verdict": phase0_verdict,
        "alpha": _FDR_ALPHA,
        "min_significant": _PHASE0_MIN_FDR_SIGNIFICANT,
    }

    # 5. 渲染 + 落盘
    report = render_phase0_report(result)
    print()
    print(report)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d")
    out_file = out_dir / f"phase0_report_{ts}.md"
    out_file.write_text(report, encoding="utf-8")
    logger.info("报告落盘 → %s", out_file)

    # 单 setup 时也输出详细单 setup 报告
    if len(selected) == 1:
        single = next(s for s in result["setups"])
        print()
        print(render_report(single))


if __name__ == "__main__":
    main()
