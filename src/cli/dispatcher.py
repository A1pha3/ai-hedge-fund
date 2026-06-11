"""统一 CLI 分发器 — 集中管理所有早期命令入口。

设计目标:
- 100% 保留现有 CLI 行为 (不破坏任何现有 flag)
- 将 ``src/main.py`` ``__main__`` 块中约 340 行的 ``if "--xxx" in sys.argv`` 重复模式集中管理
- 早期分发 (early dispatch): 这些命令在 ``parse_cli_inputs`` 之前执行, 避免与
  ``argparse`` 的 required 校验冲突 (如 tickers)
- 每个 handler 返回 ``int`` (退出码) 或 ``None`` (不匹配)

使用::

    from src.cli.dispatcher import dispatch
    if __name__ == "__main__":
        rc = dispatch()
        if rc is not None:
            raise SystemExit(rc)
        # ... 走主 parser 流程

新增长期命令: 在 ``COMMAND_REGISTRY`` 注册 flag + handler 即可。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

# 这些是早期分发的所有命令。每个 flag 在 ``COMMAND_REGISTRY`` 中
# 映射到一个 handler 函数。handler 签名: (argv: list[str]) -> int | None
#
# 返回 ``None`` 表示该 flag 不在 argv 中 (继续下一个候选)
# 返回 ``int`` 表示已执行命令, 直接返回该退出码


def _has_flag(argv: list[str], flag: str) -> bool:
    """检查 ``--flag`` 或 ``--flag=value`` 形式是否在 argv 中。"""
    if flag in argv:
        return True
    prefix = flag + "="
    return any(a.startswith(prefix) for a in argv)


def _get_kv(argv: list[str], prefix: str) -> str | None:
    """从 argv 中提取 ``--key=value`` 形式参数的值。"""
    for a in argv:
        if a.startswith(prefix + "="):
            return a.split("=", 1)[1]
    return None


def _next_arg(argv: list[str], flag: str) -> str | None:
    """获取 ``--flag VALUE`` 紧邻的下一个 argv (VALUE 不以 ``-`` 开头)。"""
    try:
        idx = argv.index(flag)
    except ValueError:
        return None
    if idx + 1 < len(argv) and not argv[idx + 1].startswith("-"):
        return argv[idx + 1]
    return None


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _parse_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _normalize_date(value: str | None, default_today: bool = True) -> str:
    """将 ``YYYY-MM-DD`` 标准化为 ``YYYYMMDD``。"""
    if not value:
        return datetime.now().strftime("%Y%m%d") if default_today else ""
    if len(value) == 10 and value[4] == "-":
        return value.replace("-", "")
    return value


# ---- handler imports (延迟导入避免循环依赖) ----
def _resolve_preheat(argv: list[str]) -> int | None:
    from src.main import run_preheat

    if not _has_flag(argv, "--preheat"):
        return None
    trade_date = _get_kv(argv, "--preheat-date")
    tasks_raw = _get_kv(argv, "--preheat-tasks")
    tasks = [t.strip() for t in tasks_raw.split(",") if t.strip()] if tasks_raw else None
    if trade_date:
        trade_date = trade_date.strip().replace("-", "")
    force = "--force" in argv
    list_tasks = "--list-tasks" in argv
    return run_preheat(trade_date=trade_date, tasks=tasks, force=force, list_tasks=list_tasks)


def _resolve_daily_gainers(argv: list[str]) -> int | None:
    from src.main import run_daily_gainers_cli

    if "--daily-gainers" not in argv:
        return None
    return run_daily_gainers_cli()


def _resolve_macro(argv: list[str]) -> int | None:
    if "--macro" not in argv:
        return None
    from src.data.macro_data import run_macro_cli

    return run_macro_cli()


def _resolve_performance_report(argv: list[str]) -> int | None:
    from src.main import run_performance_report_cli

    if "--performance-report" not in argv:
        return None
    period_raw = _get_kv(argv, "--period")
    period = (period_raw.strip().lower() if period_raw else "weekly")
    if period not in ("weekly", "monthly"):
        period = "weekly"
    end_date_raw = _get_kv(argv, "--pr-end-date")
    end_date = end_date_raw.strip().replace("-", "") if end_date_raw else None
    return run_performance_report_cli(period=period, end_date=end_date)


def _resolve_market_status(argv: list[str]) -> int | None:
    from src.main import run_market_status

    if "--market-status" not in argv:
        return None
    trade_date = _get_kv(argv, "--market-date") or datetime.now().strftime("%Y%m%d")
    if len(trade_date) == 10 and trade_date[4] == "-":
        trade_date = trade_date.replace("-", "")
    return run_market_status(trade_date)


def _resolve_pipeline(argv: list[str]) -> int | None:
    from src.main import run_pipeline_mode, run_screen_only_mode

    if "--pipeline" not in argv and "--screen-only" not in argv:
        return None
    parser = argparse.ArgumentParser(description="Institutional multi-strategy pipeline runner")
    parser.add_argument("--pipeline", action="store_true", help="运行全流水线模式")
    parser.add_argument("--screen-only", action="store_true", help="仅运行 Layer A + Layer B")
    parser.add_argument("--trade-date", required=True, help="交易日期 YYYYMMDD")
    args = parser.parse_args()
    if args.pipeline:
        return run_pipeline_mode(args.trade_date)
    if args.screen_only:
        return run_screen_only_mode(args.trade_date)
    return 1


def _resolve_industry_rotation(argv: list[str]) -> int | None:
    from src.main import run_industry_rotation

    if "--industry-rotation" not in argv:
        return None
    trade_date = _get_kv(argv, "--ir-date")
    top_n = _parse_int(_get_kv(argv, "--ir-top"), 5)
    bottom_n = _parse_int(_get_kv(argv, "--ir-bottom"), 3)
    return run_industry_rotation(trade_date, top_n=top_n, bottom_n=bottom_n)


def _resolve_tracking_summary(argv: list[str]) -> int | None:
    from src.main import run_tracking_summary

    if "--tracking-summary" not in argv:
        return None
    lookback = _parse_int(_get_kv(argv, "--tracking-lookback"), 30)
    return run_tracking_summary(lookback_days=lookback)


def _resolve_export_pdf(argv: list[str]) -> int | None:
    from src.main import run_export_pdf

    if "--export-pdf" not in argv:
        return None
    trade_date_raw = _get_kv(argv, "--pdf-date")
    trade_date = trade_date_raw.strip().replace("-", "") if trade_date_raw else None
    output = _get_kv(argv, "--pdf-output")
    output = output.strip() if output else None
    return run_export_pdf(trade_date=trade_date, output_path=output)


def _resolve_attribution_daily(argv: list[str]) -> int | None:
    from src.main import run_attribution_daily

    if "--attribution-daily" not in argv:
        return None
    trade_date = _normalize_date(_get_kv(argv, "--date"))
    positions_raw = _get_kv(argv, "--positions")
    positions_path = Path(positions_raw).expanduser() if positions_raw else None
    return run_attribution_daily(trade_date, positions_path=positions_path)


def _resolve_factor_ic(argv: list[str]) -> int | None:
    if "--factor-ic" not in argv:
        return None
    lookback = _parse_int(_get_kv(argv, "--ic-lookback"), 30)
    method_raw = _get_kv(argv, "--ic-method")
    method = method_raw.strip().lower() if method_raw else "spearman"
    from src.research.factor_ic_analysis import run_factor_ic

    return run_factor_ic(lookback_days=lookback, method=method)


def _resolve_rebalance(argv: list[str]) -> int | None:
    from src.main import run_rebalance

    if "--rebalance" not in argv:
        return None
    positions_raw = _get_kv(argv, "--positions-path") or _get_kv(argv, "--positions")
    positions_path = Path(positions_raw).expanduser() if positions_raw else None
    drift = _parse_float(_get_kv(argv, "--drift-threshold"), 0.05)
    return run_rebalance(positions_path=positions_path, drift_threshold=drift)


def _resolve_conditional_orders(argv: list[str]) -> int | None:
    if "--conditional-orders" not in argv:
        return None
    top_n = _parse_int(_get_kv(argv, "--top-n"), 20)
    atr_period = _parse_int(_get_kv(argv, "--atr-period"), 14)
    lookback = _parse_int(_get_kv(argv, "--co-lookback"), 60)
    from src.screening.conditional_order_advisor import run_conditional_orders_cli

    return run_conditional_orders_cli(
        top_n=top_n,
        atr_period=atr_period,
        lookback_sessions=lookback,
    )


def _resolve_push_test(argv: list[str]) -> int | None:
    from src.main import run_push_test

    if "--push-test" not in argv:
        return None
    channel = _get_kv(argv, "--channel")
    if channel:
        channel = channel.strip()
    else:
        channel = _next_arg(argv, "--channel")
    config_raw = _get_kv(argv, "--push-config")
    config_path = Path(config_raw).expanduser() if config_raw else None
    init = "--init" in argv
    return run_push_test(channel=channel, config_path=config_path, init=init)


def _resolve_winrate_dashboard(argv: list[str]) -> int | None:
    from src.main import run_winrate_dashboard

    if "--winrate-dashboard" not in argv:
        return None
    lookback = _parse_int(_get_kv(argv, "--winrate-lookback"), 30)
    return run_winrate_dashboard(lookback_days=lookback)


def _resolve_verify_recommendations(argv: list[str]) -> int | None:
    """P3-1 推荐闭环验证 — 自动回测每日推荐实际收益。

    Args:
        argv: 完整 CLI 参数列表
        支持: --verify-recommendations, --verify-lookback=<N>, --verify-detail
    """
    from src.main import run_verify_recommendations

    if "--verify-recommendations" not in argv:
        return None
    lookback = _parse_int(_get_kv(argv, "--verify-lookback"), 30)
    detail = "--verify-detail" in argv
    return run_verify_recommendations(lookback_days=lookback, include_detail=detail)


def _resolve_industry_cross_picks(argv: list[str]) -> int | None:
    """P3-3 行业 + 个股交叉选择 — 强势行业 Top N + 行业最优个股。"""
    from src.main import run_industry_cross_picks

    if "--cross-picks" not in argv:
        return None
    trade_date = _get_kv(argv, "--cp-date")
    top_ind = _parse_int(_get_kv(argv, "--cp-top-industries"), 5)
    picks = _parse_int(_get_kv(argv, "--cp-picks-per-industry"), 3)
    return run_industry_cross_picks(
        trade_date=trade_date,
        top_industries=top_ind,
        picks_per_industry=picks,
    )


def _resolve_portfolio_builder(argv: list[str]) -> int | None:
    """P3-4 推荐组合构建器 — Top N 推荐 → 优化权重组合。"""
    from src.main import run_portfolio_builder

    if "--build-portfolio" not in argv:
        return None
    trade_date = _get_kv(argv, "--pf-date")
    top_n = _parse_int(_get_kv(argv, "--pf-top-n"), 10)
    pos_cap = _parse_float(_get_kv(argv, "--pf-position-cap"), 0.20)
    ind_cap = _parse_float(_get_kv(argv, "--pf-industry-cap"), 0.30)
    return run_portfolio_builder(
        trade_date=trade_date,
        top_n=top_n,
        position_cap=pos_cap,
        industry_cap=ind_cap,
    )


def _resolve_weight_calibration(argv: list[str]) -> int | None:
    """P3-2 策略动态权重校准 — 基于因子 IC 自动调权。"""
    from src.main import run_weight_calibration

    if "--calibrate-weights" not in argv:
        return None
    lookback = _parse_int(_get_kv(argv, "--calibrate-lookback"), 30)
    return run_weight_calibration(lookback_days=lookback)


def _resolve_stock_detail(argv: list[str]) -> int | None:
    if not _has_flag(argv, "--stock-detail"):
        return None
    # 支持 ``--stock-detail=300750`` 或 ``--stock-detail 300750`` 两种形式
    ticker = _get_kv(argv, "--stock-detail")
    if ticker is None:
        ticker = _next_arg(argv, "--stock-detail")
    if not ticker:
        from colorama import Fore, Style

        print(
            f"{Fore.RED}[StockDetail] 用法: --stock-detail 300750 [--sd-date YYYYMMDD]"
            f"{Style.RESET_ALL}"
        )
        return 1
    trade_date = _get_kv(argv, "--sd-date")
    if trade_date:
        trade_date = trade_date.strip()
    from src.screening.stock_detail import run_stock_detail_cli

    return run_stock_detail_cli(ticker, trade_date=trade_date)


def _resolve_custom_weights(argv: list[str]) -> int | None:
    from src.main import run_custom_weights

    if "--custom-weights" not in argv:
        return None
    trend = _parse_float(_get_kv(argv, "--trend"), 0.25)
    mr = _parse_float(_get_kv(argv, "--mean-reversion"), 0.25)
    fund = _parse_float(_get_kv(argv, "--fundamental"), 0.25)
    es = _parse_float(_get_kv(argv, "--event-sentiment"), 0.25)
    top_n = _parse_int(_get_kv(argv, "--top-n"), 10)
    trade_date_raw = _get_kv(argv, "--trade-date")
    trade_date = trade_date_raw.strip() or None if trade_date_raw else None
    return run_custom_weights(
        trend=trend,
        mean_reversion=mr,
        fundamental=fund,
        event_sentiment=es,
        top_n=top_n,
        trade_date=trade_date,
    )


def _resolve_compare(argv: list[str]) -> int | None:
    if not (_has_flag(argv, "--compare")):
        return None
    tickers_arg = _get_kv(argv, "--compare") or _next_arg(argv, "--compare")
    if not tickers_arg:
        from colorama import Fore, Style

        print(
            f"{Fore.RED}[Compare] 用法: --compare 300750,600519,000001 "
            f"[--metrics trend_score,score_b] [--no-radar]{Style.RESET_ALL}"
        )
        return 1
    metrics_arg = _get_kv(argv, "--metrics")
    no_radar = "--no-radar" in argv
    from src.screening.compare_tool import run_compare_cli

    return run_compare_cli(
        tickers_arg=tickers_arg,
        metrics_arg=metrics_arg,
        show_radar=not no_radar,
    )


def _resolve_watchlist(argv: list[str]) -> int | None:
    from src.main import run_watchlist_add, run_watchlist_list, run_watchlist_remove, run_watchlist_status

    flags = ("--watchlist-add", "--watchlist-remove", "--watchlist-list", "--watchlist-status")
    if not any(f in argv for f in flags):
        return None
    parser = argparse.ArgumentParser(description="Watchlist management (P0-5)")
    parser.add_argument("--watchlist-add", type=str, default=None, metavar="TICKER", help="添加标的到自选池")
    parser.add_argument("--watchlist-remove", type=str, default=None, metavar="TICKER", help="从自选池移除标的")
    parser.add_argument("--watchlist-list", action="store_true", help="列出自选池所有标的")
    parser.add_argument("--watchlist-status", action="store_true", help="展示自选池最新评分 + 信号")
    parser.add_argument("--name", type=str, default="", help="标的名称 (与 --watchlist-add 配合)")
    parser.add_argument("--tags", type=str, nargs="*", default=None, help="标签列表 (空格分隔)")
    parser.add_argument("--note", type=str, default="", help="备注 (可选)")
    parser.add_argument("--filter-tag", type=str, default=None, help="--watchlist-list 时按标签过滤")
    args, _ = parser.parse_known_args()

    if args.watchlist_add:
        return run_watchlist_add(
            ticker=args.watchlist_add,
            name=args.name,
            tags=list(args.tags) if args.tags else None,
            note=args.note,
        )
    if args.watchlist_remove:
        return run_watchlist_remove(args.watchlist_remove)
    if args.watchlist_list:
        return run_watchlist_list(tag=args.filter_tag)
    if args.watchlist_status:
        return run_watchlist_status()
    return None


def _resolve_daily_brief(argv: list[str]) -> int | None:
    """``--daily-brief`` — 盘前 5 分钟「今日 Top 3 决策卡」(P0-7)。

    早期分发 — 不走主 parser, 避免 ``--tickers required`` 冲突。
    """
    if "--daily-brief" not in argv:
        return None
    from src.cli.daily_brief import run_daily_brief

    return run_daily_brief()


def _resolve_why_not(argv: list[str]) -> int | None:
    """``--why-not <ticker>`` — 反事实解释 (P0-8)。

    早期分发 — 不走主 parser, 避免 ``--tickers required`` 冲突。
    支持 ``--why-not=000001`` 和 ``--why-not 000001`` 两种形式。
    """
    ticker = _get_kv(argv, "--why-not") or _next_arg(argv, "--why-not")
    if ticker is None:
        return None
    from src.cli.why_not import run_why_not

    return run_why_not(ticker)


def _resolve_explain(argv: list[str]) -> int | None:
    """``--explain <ticker>`` — 单票推荐解释 (R20.14 修复, 避免主 parser ``--tickers required`` 冲突)。

    早期分发 — 不走主 parser。
    """
    ticker = _get_kv(argv, "--explain") or _next_arg(argv, "--explain")
    if ticker is None:
        return None
    from src.main import run_explain

    return run_explain(ticker)


def _resolve_export_conditional_orders(argv: list[str]) -> int | None:
    """``--export-conditional-orders [--broker=huatai|gtja|ths]`` — 导出券商条件单格式 (P1-13)。"""
    if "--export-conditional-orders" not in argv:
        return None
    broker_raw = _get_kv(argv, "--broker")
    broker = broker_raw.strip().lower() if broker_raw else "huatai"
    from src.screening.conditional_order_export import run_export_conditional_orders_cli

    return run_export_conditional_orders_cli(broker=broker)


def _resolve_weekly_report(argv: list[str]) -> int | None:
    """``--weekly-report`` — P2-10 组合体检周报推送。

    支持 ``--start-date`` / ``--end-date`` (缺省本周一/五), ``--channel`` (缺省 wecom)。
    """
    if "--weekly-report" not in argv:
        return None
    from src.notification.weekly_report import push_weekly_report

    start_date = _get_kv(argv, "--start-date")
    end_date = _get_kv(argv, "--end-date")
    channel = _get_kv(argv, "--channel") or "wecom"
    positions_raw = _get_kv(argv, "--positions")
    positions_path = Path(positions_raw).expanduser() if positions_raw else None
    config_raw = _get_kv(argv, "--push-config")
    config_path = Path(config_raw).expanduser() if config_raw else None

    return push_weekly_report(
        start_date=start_date.strip().replace("-", "") if start_date else None,
        end_date=end_date.strip().replace("-", "") if end_date else None,
        channel=channel.strip(),
        positions_path=positions_path,
        config_path=config_path,
    )


def _resolve_data_quality_audit(argv: list[str]) -> int | None:
    """``--data-quality-audit`` — P0-10 推荐标的的数据完整性审计。

    支持 ``--top-n`` (缺省 10) 和 ``--threshold`` (缺省 0.6)。
    """
    if "--data-quality-audit" not in argv:
        return None
    top_n = _parse_int(_get_kv(argv, "--top-n"), 10)
    threshold = _parse_float(_get_kv(argv, "--threshold"), 0.6)
    from src.screening.data_quality_audit import run_data_quality_audit

    return run_data_quality_audit(top_n=top_n, threshold=threshold)


def _resolve_confidence_calibration(argv: list[str]) -> int | None:
    """``--confidence-calibration`` — P0-9 score 校准为历史命中率/预期收益。

    支持 ``--top-n`` (缺省 10) 和 ``--lookback`` (缺省 60)。
    """
    if "--confidence-calibration" not in argv:
        return None
    top_n = _parse_int(_get_kv(argv, "--top-n"), 10)
    lookback = _parse_int(_get_kv(argv, "--lookback"), 60)
    from src.screening.confidence_calibration import run_confidence_calibration

    return run_confidence_calibration(top_n=top_n, lookback_days=lookback)


def _resolve_conviction_ranking(argv: list[str]) -> int | None:
    """``--conviction-ranking`` — P0-11 综合信心排名 (Score + 连续 + 质量 + 校准)。

    支持 ``--top-n`` (缺省 10) 和 ``--lookback`` (缺省 60)。
    可调权重: ``--score-weight`` / ``--consecutive-weight`` / ``--quality-weight`` / ``--calibration-weight``
    (缺省 0.40 / 0.20 / 0.20 / 0.20, 和须为 1.0 ± 0.01)。
    """
    if "--conviction-ranking" not in argv:
        return None
    top_n = _parse_int(_get_kv(argv, "--top-n"), 10)
    lookback = _parse_int(_get_kv(argv, "--lookback"), 60)
    score_w = _parse_float(_get_kv(argv, "--score-weight"), 0.40)
    consec_w = _parse_float(_get_kv(argv, "--consecutive-weight"), 0.20)
    quality_w = _parse_float(_get_kv(argv, "--quality-weight"), 0.20)
    calib_w = _parse_float(_get_kv(argv, "--calibration-weight"), 0.20)

    weights = {
        "score": score_w,
        "consecutive": consec_w,
        "quality": quality_w,
        "calibration": calib_w,
    }
    total = sum(weights.values())
    if not (0.99 <= total <= 1.01):
        print(
            f"Error: weights must sum to 1.0 (got {total:.3f} = "
            f"{score_w} + {consec_w} + {quality_w} + {calib_w}). "
            f"Adjust --score-weight / --consecutive-weight / --quality-weight / --calibration-weight.",
            file=sys.stderr,
        )
        return 2  # CLI 错误退出码

    from src.screening.conviction_ranking import run_conviction_ranking

    return run_conviction_ranking(top_n=top_n, lookback_days=lookback, weights=weights)


def _resolve_top(argv: list[str]) -> int | None:
    """``--top [N] [--filter KEY=VALUE ...]`` — 显示最近一次 ``--auto`` 运行的 Top N 推荐 (无需重跑)。

    支持的过滤参数:
      --industry=电子        申万行业 (子串匹配)
      --min-score=0.5        最低 score_b
      --max-score=0.8        最高 score_b
      --min-market-cap=100e8 最低市值 (元)
      --max-market-cap=500e8 最高市值 (元)
      --exclude-st           排除 ST/*ST
      --min-consecutive=2    最低连续推荐天数
      --ticker=000001        精确匹配 ticker
      --name-contains=银行    名称包含子串
    """
    if "--top" not in argv:
        return None
    from src.main import run_top

    # Parse optional N: --top 20 or --top=20
    top_n = 10
    idx = argv.index("--top")
    if idx + 1 < len(argv) and argv[idx + 1].isdigit():
        top_n = int(argv[idx + 1])
    else:
        for a in argv:
            if a.startswith("--top="):
                val = a.split("=", 1)[1]
                if val.isdigit():
                    top_n = int(val)
    # ALPHA-R20.9: --top 0 silently returns empty; clamp to 1 with a warning.
    if top_n < 1:
        print(f"[Top] --top N 必须 >= 1, 收到 {top_n}, 已调整为 1")
        top_n = 1

    # Parse filter parameters
    filters: dict = {}
    filter_keys = {
        "--industry": "industry",
        "--min-score": "min_score",
        "--max-score": "max_score",
        "--min-market-cap": "min_market_cap",
        "--max-market-cap": "max_market_cap",
        "--min-consecutive": "min_consecutive",
        "--ticker": "ticker",
        "--name-contains": "name_contains",
    }
    for flag, key in filter_keys.items():
        val = _get_kv(argv, flag)
        if val is not None:
            # Convert numeric filters
            if key in ("min_score", "max_score", "min_market_cap", "max_market_cap"):
                try:
                    filters[key] = float(val)
                except ValueError:
                    pass
            elif key == "min_consecutive":
                try:
                    filters[key] = int(val)
                except ValueError:
                    pass
            else:
                filters[key] = val

    if "--exclude-st" in argv:
        filters["exclude_st"] = True

    return run_top(top_n=top_n, filters=filters or None)


# 命令注册表: flag -> handler function
# 顺序敏感 — 越靠前越先匹配。``--auto`` 走主 parser (它本来 require_tickers=False)

def _resolve_check_freshness(argv: list[str]) -> int | None:
    """P6-1 data freshness check. Supports --trade-date."""
    if "--check-freshness" not in argv:
        return None
    trade_date = _get_kv(argv, "--trade-date") or ""
    if not trade_date:
        from datetime import date
        trade_date = date.today().strftime("%Y%m%d")
    from src.screening.data_freshness_guard import check_data_freshness, _render_freshness_summary
    reports_dir = None
    try:
        from src.screening.consecutive_recommendation import resolve_report_dir
        reports_dir = resolve_report_dir()
    except Exception:
        pass
    report = check_data_freshness(trade_date=trade_date, reports_dir=reports_dir)
    print(_render_freshness_summary(report["fresh"], report["warnings"]))
    status = "PASS" if report["fresh"] else "WARNING"
    return 0


def _resolve_daily_delta(argv: list[str]) -> int | None:
    """P6-2 daily recommendation delta. Supports --top-n, --delta-lookback."""
    if "--daily-delta" not in argv:
        return None
    top_n = _parse_int(_get_kv(argv, "--top-n"), 20)
    lookback = _parse_int(_get_kv(argv, "--delta-lookback"), 5)
    from src.screening.daily_delta import compute_daily_delta, render_daily_delta
    delta = compute_daily_delta(top_n=top_n, lookback_days=lookback)
    print(render_daily_delta(delta))
    return 0


def _resolve_signal_consistency(argv: list[str]) -> int | None:
    """P7-1 signal consistency cross-check. Supports --top-n."""
    if "--signal-consistency" not in argv:
        return None
    top_n = _parse_int(_get_kv(argv, "--top-n"), 20)
    from src.screening.signal_consistency import run_consistency_check
    return run_consistency_check(top_n=top_n)


def _resolve_dynamic_threshold(argv: list[str]) -> int | None:
    """P7-2 dynamic recommendation threshold. Supports --lookback, --target-hit-rate."""
    if "--dynamic-threshold" not in argv:
        return None
    from src.screening.dynamic_threshold import run_dynamic_threshold
    return run_dynamic_threshold(argv)

COMMAND_REGISTRY: list[tuple[str, Callable[[list[str]], int | None]]] = [
    ("--preheat", _resolve_preheat),
    ("--daily-gainers", _resolve_daily_gainers),
    ("--macro", _resolve_macro),
    ("--performance-report", _resolve_performance_report),
    ("--market-status", _resolve_market_status),
    ("--pipeline", _resolve_pipeline),
    ("--screen-only", _resolve_pipeline),
    ("--industry-rotation", _resolve_industry_rotation),
    ("--tracking-summary", _resolve_tracking_summary),
    ("--export-pdf", _resolve_export_pdf),
    ("--attribution-daily", _resolve_attribution_daily),
    ("--factor-ic", _resolve_factor_ic),
    ("--rebalance", _resolve_rebalance),
    ("--conditional-orders", _resolve_conditional_orders),
    ("--push-test", _resolve_push_test),
    ("--winrate-dashboard", _resolve_winrate_dashboard),
    ("--verify-recommendations", _resolve_verify_recommendations),
    ("--cross-picks", _resolve_industry_cross_picks),
    ("--build-portfolio", _resolve_portfolio_builder),
    ("--calibrate-weights", _resolve_weight_calibration),
    ("--stock-detail", _resolve_stock_detail),
    ("--custom-weights", _resolve_custom_weights),
    ("--compare", _resolve_compare),
    ("--watchlist-add", _resolve_watchlist),
    ("--watchlist-remove", _resolve_watchlist),
    ("--watchlist-list", _resolve_watchlist),
    ("--watchlist-status", _resolve_watchlist),
    ("--daily-brief", _resolve_daily_brief),
    ("--why-not", _resolve_why_not),
    ("--explain", _resolve_explain),
    ("--export-conditional-orders", _resolve_export_conditional_orders),
    ("--weekly-report", _resolve_weekly_report),
    ("--data-quality-audit", _resolve_data_quality_audit),
    ("--confidence-calibration", _resolve_confidence_calibration),
    ("--conviction-ranking", _resolve_conviction_ranking),
    ("--top", _resolve_top),
    ("--check-freshness", _resolve_check_freshness),
    ("--daily-delta", _resolve_daily_delta),
    ("--signal-consistency", _resolve_signal_consistency),
    ("--dynamic-threshold", _resolve_dynamic_threshold),
]


def dispatch(sys_argv: list[str] | None = None) -> int | None:
    """检查 sys.argv 并分发到对应 early-dispatch handler。

    返回:
    - ``None``: 没有匹配的早期命令, 让主 parser 继续
    - ``int``: 已执行命令的退出码, 调用方应 ``SystemExit(rc)``
    """
    argv = sys_argv if sys_argv is not None else sys.argv[1:]

    for _flag, handler in COMMAND_REGISTRY:
        try:
            rc = handler(argv)
        except SystemExit as e:
            code = e.code
            return code if isinstance(code, int) else 1
        except Exception as e:  # noqa: BLE001 — 保持与原行为一致: 错误打印 + 返回 1
            flag = _flag
            print(f"Error in {flag}: {e}", file=sys.stderr)
            return 1
        if rc is not None:
            return rc
    return None


__all__ = ["COMMAND_REGISTRY", "dispatch"]
