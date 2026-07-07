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
import logging
import sys
from pathlib import Path

import pandas as pd

from src.screening.offensive.distribution_builder import (
    TermStructureDistribution,
    build_distribution,
)
from src.screening.offensive.execution_adjuster import ExecutionConfig, adjust_returns
from src.screening.offensive.setups.base import Setup
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.statistics import Distribution, benjamini_hochberg_fdr, setup_p_value
import numpy as np

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
    """跑 setup 在样本上, 分 IS/OOS 出 TermStructureDistribution + 准入判定。

    返回额外含 ``is_returns`` / ``oos_returns`` (natural horizon 的 execution-adjusted
    命中样本收益序列), 供 evaluate_setups 做 FDR 校正算 p-value (v2 §C.5)。
    """
    config = config or ExecutionConfig()
    is_dates, oos_dates = split_is_oos(trade_dates)
    is_set, oos_set = set(is_dates), set(oos_dates)

    def _filter(dates_set):
        idx = [i for i, d in enumerate(trade_dates) if d in dates_set]
        return [tickers[i] for i in idx], [trade_dates[i] for i in idx]

    def _build(dates_set, period):
        tk, td = _filter(dates_set)
        if not tk:
            return None
        wrapped = _ContextInjectingSetupWrapper(setup, fund_flow_by_ticker, industry_pct_by_date)
        return build_distribution(
            setup=wrapped, tickers=tk, trade_dates=td,
            prices_by_ticker=prices_by_ticker, regimes_by_date=regimes_by_date,
            horizons=horizons, config=config, period=period,
        )

    def _hit_returns(dates_set) -> np.ndarray:
        """复现 hit 过滤 + adjust_returns, 拿 natural horizon 的命中样本收益序列.

        供 FDR p-value 计算. 与 build_distribution 内部逻辑一致 (同 wrapped setup +
        同 adjust_returns), 有一次重复计算, 但避免改 build_distribution 签名.
        """
        tk, td = _filter(dates_set)
        if not tk:
            return np.array([])
        wrapped = _ContextInjectingSetupWrapper(setup, fund_flow_by_ticker, industry_pct_by_date)
        hit_tickers, hit_dates = [], []
        for ticker, date_str in zip(tk, td):
            ctx = {"prices": prices_by_ticker.get(ticker), "regime": regimes_by_date.get(date_str, "normal")}
            if wrapped.detect(ticker, date_str, ctx).hit:
                hit_tickers.append(ticker)
                hit_dates.append(date_str)
        if not hit_tickers:
            return np.array([])
        adj = adjust_returns(hit_dates, hit_tickers, prices_by_ticker, horizon=setup.natural_horizon, config=config)
        return adj[np.isfinite(adj)]

    is_tsd = _build(is_set, "IS") or _empty_tsd(setup, "IS")
    oos_tsd = _build(oos_set, "OOS") or _empty_tsd(setup, "OOS")

    nh = setup.natural_horizon
    qualified_is = is_setup_qualified(is_tsd.horizons.get(nh, _zero_dist()))
    qualified_oos = is_setup_qualified(oos_tsd.horizons.get(nh, _zero_dist()))
    verdict = "PASS" if (qualified_is and qualified_oos) else "FAIL"

    return {
        "setup_name": setup.name,
        "natural_horizon": nh,
        "is": is_tsd,
        "oos": oos_tsd,
        "qualified_is": qualified_is,
        "qualified_oos": qualified_oos,
        "verdict": verdict,
        # natural horizon 的命中样本收益序列 (供 evaluate_setups 算 FDR p-value)
        "is_returns": _hit_returns(is_set),
        "oos_returns": _hit_returns(oos_set),
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
        "",
        f"**Verdict: {emoji} {verdict}** (natural_horizon=T+{nh})",
        "",
        f"## In-Sample (≤ {_IS_OOS_SPLIT_DATE[:4]})",
        _fmt_dist(is_tsd),
        f"  qualified: {eval_result['qualified_is']}",
        "",
        f"## Out-of-Sample (≥ {_IS_OOS_SPLIT_DATE[:4]})",
        _fmt_dist(oos_tsd),
        f"  qualified: {eval_result['qualified_oos']}",
        "",
        "## 准入门槛",
        f"- convexity_ratio ≥ {_QUALIFY_CONVEXITY_MIN}",
        f"- winrate ≥ {_QUALIFY_WINRATE_MIN}",
        f"- n ≥ {_QUALIFY_N_MIN}",
        f"- IC > {_QUALIFY_IC_MIN}",
        "- IS 和 OOS 都达标才 PASS",
        "",
        "## STOP 条件检查",
        f"- {'✅' if eval_result['qualified_oos'] else '❌'} OOS 达标 (防过拟合)",
        f"- {'✅' if is_tsd.horizons.get(nh) and is_tsd.horizons.get(nh).n > 0 else '❌'} IS 有样本",
    ]
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
        "# Phase 0 准入报告 (含 FDR 校正)",
        "",
        f"**Phase 0 Verdict: {emoji} {verdict}** "
        f"(FDR 校正后 {n_sig}/{len(setups)} 个 setup 显著, 需 ≥{min_sig})",
        "",
        f"## FDR 校正表 (Benjamini-Hochberg, α={alpha})",
        "",
        "| Setup | p-value (IS) | q-value (FDR) | FDR 显著 | p-value (OOS) | OOS 达标 |",
        "|-------|-------------|---------------|----------|--------------|----------|",
    ]
    for s in setups:
        p_is = s.get("p_value", 1.0)
        q = s.get("q_value", 1.0)
        fdr_sig = "✅ 是" if s.get("fdr_significant") else "❌ 否"
        p_oos = s.get("p_value_oos", 1.0)
        oos_ok = "✅" if s.get("qualified_oos") else "❌"
        lines.append(
            f"| {s['setup_name']} | {p_is:.2e} | {q:.2e} | {fdr_sig} | {p_oos:.2e} | {oos_ok} |"
        )

    lines.extend([
        "",
        "## STOP 条件检查 (文档 §6.1)",
        f"- {'✅' if n_sig >= min_sig else '❌'} FDR 校正后 ≥{min_sig} 个 setup 显著 ({n_sig}/{len(setups)})",
        f"- {'✅' if n_sig > 0 else '❌'} 至少 1 个 setup 有真实 alpha (非纯噪声)",
        "",
        "## 说明",
        "- **p-value (IS)**: 单样本 t 检验 H0: setup 命中样本 expected_return=0 (训练段, ≤2024)",
        "- **q-value (FDR)**: Benjamini-Hochberg 校正后的 p-value (防多 setup 同时回测的 p-hacking)",
        "- **p-value (OOS)**: 验证段 (≥2025) 的 p-value, 仅披露稳定性, 不参与 FDR (防信息泄漏)",
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
    parser = argparse.ArgumentParser(description="Phase 0 setup 研究 CLI")
    parser.add_argument("--setup", default="btst_breakout", help="setup 名称")
    parser.add_argument("--start", default="20230101", help="回测起始日 YYYYMMDD")
    parser.add_argument("--end", default="20260630", help="回测结束日 YYYYMMDD")
    parser.add_argument("--output", default="data/reports/setup_research/", help="报告输出目录")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    setups = {"btst_breakout": BtstBreakoutSetup}
    if args.setup not in setups:
        logger.error("unknown setup: %s", args.setup)
        sys.exit(1)

    logger.info("Phase 0 setup research framework ready. Setup=%s", args.setup)
    logger.info("真实数据加载 + 回测执行需在交互式 shell 中调用 evaluate_setup() (见 tests 示例)")
    Path(args.output).mkdir(parents=True, exist_ok=True)
    Path(args.output, f"{args.setup}_framework_ready.txt").write_text(
        f"framework ready for {args.setup}\nuse evaluate_setup() interactively with real data\n",
        encoding="utf-8",
    )
    logger.info("framework ready marker → %s", args.output)


if __name__ == "__main__":
    main()
