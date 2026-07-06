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
    """跑 setup 在样本上, 分 IS/OOS 出 TermStructureDistribution + 准入判定。"""
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
