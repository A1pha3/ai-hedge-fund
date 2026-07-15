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
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

# BH-021 family: freshness 子命令此前吞掉所有 reports_dir 解析错误,
# 运维无法区分 "默认 reports/" vs "resolve_report_dir 失败回退默认"。
logger = logging.getLogger(__name__)

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
    period = period_raw.strip().lower() if period_raw else "weekly"
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

        print(f"{Fore.RED}[StockDetail] 用法: --stock-detail 300750 [--sd-date YYYYMMDD]" f"{Style.RESET_ALL}")
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

        print(f"{Fore.RED}[Compare] 用法: --compare 300750,600519,000001 " f"[--metrics trend_score,score_b] [--no-radar]{Style.RESET_ALL}")
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
    from src.main import (
        run_watchlist_add,
        run_watchlist_list,
        run_watchlist_remove,
        run_watchlist_status,
    )

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
    """``--export-conditional-orders [--broker=huatai|gtja|ths] [--nav=N]`` — 导出券商条件单格式 (P1-13)。

    NS-15(2): ``--nav=N`` 提供总资产 (元) 时, 按等权公式 ``compute_equal_weight_quantities``
    计算每票委托手数 (向下取整到 1 手 = 100 股); 缺省所有票用 ``DEFAULT_QUANTITY=100``。
    """
    if "--export-conditional-orders" not in argv:
        return None
    broker_raw = _get_kv(argv, "--broker")
    broker = broker_raw.strip().lower() if broker_raw else "huatai"
    nav_raw = _get_kv(argv, "--nav")
    nav: float | None = None
    if nav_raw:
        try:
            nav = float(nav_raw)
        except ValueError:
            nav = None
    from src.screening.conditional_order_export import run_export_conditional_orders_cli

    return run_export_conditional_orders_cli(broker=broker, nav=nav)


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
            f"Error: weights must sum to 1.0 (got {total:.3f} = " f"{score_w} + {consec_w} + {quality_w} + {calib_w}). " f"Adjust --score-weight / --consecutive-weight / --quality-weight / --calibration-weight.",
            file=sys.stderr,
        )
        return 2  # CLI 错误退出码

    from src.screening.conviction_ranking import run_conviction_ranking

    return run_conviction_ranking(top_n=top_n, lookback_days=lookback, weights=weights)


def _resolve_top(argv: list[str]) -> int | None:
    """``--top [N] [filter flags]`` — 显示最近一次 ``--auto`` 运行的 Top N 推荐 (无需重跑)。

    过滤参数直接追加到 --top 之后:
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
    from src.screening.data_freshness_guard import (
        _render_freshness_summary,
        check_data_freshness,
    )

    reports_dir = None
    try:
        from src.screening.consecutive_recommendation import resolve_report_dir

        reports_dir = resolve_report_dir()
    except Exception as exc:
        # BH-021 family: reports_dir 解析失败时静默回退 None, 运维无法区分
        # "用默认目录" vs "resolve_report_dir 抛异常"。
        logger.debug("dispatcher: resolve_report_dir 失败, 回退默认 reports 目录: %s", exc)
    report = check_data_freshness(trade_date=trade_date, reports_dir=reports_dir)
    print(_render_freshness_summary(report["fresh"], report["warnings"]))
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


def _resolve_decision_flow(argv: list[str]) -> int | None:
    """P8-1 one-command decision flow. Supports --top-n, --lookback."""
    if "--decision-flow" not in argv:
        return None
    top_n = _parse_int(_get_kv(argv, "--top-n"), 10)
    lookback = _parse_int(_get_kv(argv, "--lookback"), 30)
    from src.screening.decision_flow import run_decision_flow

    run_decision_flow(top_n=top_n, lookback_days=lookback)
    return 0


def _resolve_outlier_detect(argv: list[str]) -> int | None:
    """P8-2 outlier detection. Supports --top-n, --threshold."""
    if "--outlier-detect" not in argv:
        return None
    from src.screening.outlier_detect import run_outlier_detect

    return run_outlier_detect(argv)


def _resolve_expected_returns(argv: list[str]) -> int | None:
    """P9-1 expected return estimation. Uses historical calibration."""
    if "--expected-returns" not in argv:
        return None
    top_n = _parse_int(_get_kv(argv, "--top-n"), 20)
    lookback = _parse_int(_get_kv(argv, "--lookback"), 60)
    from src.screening.consecutive_recommendation import resolve_report_dir
    from src.screening.consecutive_recommendation import load_tracking_history
    from src.screening.data_quality_audit import _find_latest_report
    from src.screening.expected_return import (
        compute_expected_returns,
        render_expected_returns,
    )
    from src.utils.display import Fore, Style

    reports_dir = resolve_report_dir()
    report_path = _find_latest_report(reports_dir)
    if report_path is None:
        print(f"{Fore.RED}No auto_screening report found. Run --auto first.{Style.RESET_ALL}")
        return 1
    import json

    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"{Fore.RED}Latest auto_screening report is unreadable.{Style.RESET_ALL}")
        return 1
    recs = list(payload.get("recommendations") or [])[:top_n]
    if not recs:
        print(f"{Fore.RED}No recommendations found.{Style.RESET_ALL}")
        return 1
    trade_date = str(payload.get("date") or "")
    model_version = str(payload.get("model_version") or "")
    history_records = load_tracking_history(reports_dir)
    report = compute_expected_returns(
        recommendations=recs,
        as_of=trade_date,
        model_version=model_version,
        history_records=history_records,
        lookback_days=lookback,
    )
    print(render_expected_returns(report))
    return 0


def _resolve_signal_momentum(argv: list[str]) -> int | None:
    """P10-1 signal momentum scoring. Tracks score_b trajectory over time."""
    if "--signal-momentum" not in argv:
        return None
    from src.screening.signal_momentum import run_signal_momentum

    return run_signal_momentum(argv)


def _resolve_sector_strength(argv: list[str]) -> int | None:
    """P10-2 sector rotation weighting. Shows sector momentum for recommendations."""
    if "--sector-strength" not in argv:
        return None
    from src.screening.sector_strength import run_sector_strength

    return run_sector_strength(argv)


def _resolve_composite_score(argv: list[str]) -> int | None:
    """P11-1 composite confidence score. Unified score combining all signals."""
    if "--composite-score" not in argv:
        return None
    from src.screening.composite_score import run_composite_score

    return run_composite_score(argv)


def _resolve_volume_confirm(argv: list[str]) -> int | None:
    """P11-2 volume-price confirmation. Checks if volume supports price moves."""
    if "--volume-confirm" not in argv:
        return None
    from src.screening.volume_confirmation import run_volume_confirm

    return run_volume_confirm(argv)


def _resolve_trend_resonance(argv: list[str]) -> int | None:
    """P14-1 multi-timeframe trend resonance. Checks 5d/20d/60d alignment."""
    if "--trend-resonance" not in argv:
        return None
    from src.screening.trend_resonance import run_trend_resonance

    return run_trend_resonance(argv)


def _resolve_position_check(argv: list[str]) -> int | None:
    """P15-1 position health check. Monitors held stocks for sell signals."""
    if "--position-check" not in argv:
        return None
    from src.screening.position_health import run_position_check

    return run_position_check(argv)


def _resolve_strategy_report(argv: list[str]) -> int | None:
    """P15-2 strategy performance report. Shows which strategies are working."""
    if "--strategy-report" not in argv:
        return None
    from src.screening.strategy_report import run_strategy_report

    return run_strategy_report(argv)


def _resolve_top_picks(argv: list[str]) -> int | None:
    """P12-2 one-command top picks. Shows today's best buys."""
    if "--top-picks" not in argv:
        return None
    count = _parse_int(_get_kv(argv, "--count"), 5)
    lookback = _parse_int(_get_kv(argv, "--lookback"), 5)
    profit_aware = "--profit-aware" in argv  # C273: opt-in empirical-winrate ranking (backtested 47%→62%)
    from src.screening.top_picks import run_top_picks

    return run_top_picks(count=count, lookback_days=lookback, profit_aware=profit_aware)


def _resolve_top_setups(argv: list[str]) -> int | None:
    """Phase 1 凸性 setup 检测器 (进攻型 alpha, shadow 模式)。
    ⚠ SHADOW: setup 未经验证 (Phase 0 IS/OOS), 仅供观察。
    完整使用需先 backfill 资金流 + 跑 Phase 0 build_distribution。
    """
    if "--top-setups" not in argv:
        return None
    from colorama import Fore, Style

    from src.screening.consecutive_recommendation import resolve_report_dir
    from src.screening.data_quality_audit import _find_latest_report

    # 最新报告
    report_dir = resolve_report_dir()
    latest_path = _find_latest_report(report_dir)
    if latest_path is None:
        print(f"{Fore.RED}[TopSetups] 未找到 auto_screening 报告。请先运行 --auto{Style.RESET_ALL}")
        return 1

    import json

    with open(latest_path, encoding="utf-8") as f:
        report = json.loads(f.read())
    recs = report.get("recommendations", [])
    trade_date = str(report.get("date", ""))
    if not recs:
        print(f"{Fore.YELLOW}[TopSetups] 最新报告无推荐, 跳过 setup 检测{Style.RESET_ALL}")
        return 0

    tickers = [str(r.get("ticker", "")) for r in recs[:30]]  # 扫前 30 (性能)

    # 构造每 ticker 的 context (从报告字段 + 资金流 store 若有)
    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    store = FundFlowStore(cache_dir="data/fund_flow_cache/")
    context_by_ticker: dict[str, dict] = {}
    for rec in recs[:30]:
        t = str(rec.get("ticker", ""))
        if not t:
            continue
        # 资金流历史 (若 backfill 过)
        flow_records = store.get_range(t, "20230101", trade_date) if trade_date else []
        context_by_ticker[t] = {
            "fund_flow_records": flow_records,
            "industry_day_pct": float(rec.get("industry_pct_change", 0.0) or 0.0),
            "industry_2d_pct": float(rec.get("industry_2d_pct", 0.0) or 0.0),
            "industry_net_flow": float(rec.get("industry_net_flow", 0.0) or 0.0),
            "stock_today_pct": float(rec.get("pct_change", 0.0) or 0.0),
        }

    # 分布 lookup: Phase 0 产出前为空 → run_top_setups 会过滤掉无分布的命中
    # (shadow 模式诚实: 没验证过的 setup 不输出 Kelly 仓位)
    from src.screening.offensive.top_setups import run_top_setups, render_top_setups

    distribution_lookup: dict = {}  # TODO Phase 0: 用 evaluate_setup 产出填充

    market_temp_inputs = {
        "n_limit_up": int(report.get("market_state", {}).get("limit_up_count", 0) or 0),
        "n_total": int(report.get("layer_a_count", 3000) or 3000),
        "turnover_ratio": 1.0,
    }

    picks = run_top_setups(
        tickers=tickers,
        trade_date=trade_date,
        context_by_ticker=context_by_ticker,
        distribution_lookup=distribution_lookup,
        market_temp_inputs=market_temp_inputs,
        top_n=10,
        shadow=True,  # 强制 shadow (Phase 0 未跑)
    )
    print(render_top_setups(picks, trade_date or "????????"))

    # 若无 picks (分布未填充), 额外提示下一步
    if not picks:
        print(f"{Fore.CYAN}下一步:{Style.RESET_ALL}")
        print(f"  1. backfill 资金流: 循环 fetch_individual_fund_flow + store.save")
        print(f"  2. 跑 Phase 0: scripts/setup_research.py evaluate_setup() 产 distribution_lookup")
        print(f"  3. 把分布填回本命令的 distribution_lookup → 自动出 Kelly picks")
    return 0


def _cached_daily_action_market_bar(cache, trade_date):
    """Read an exact cached bar without inventing execution-state fields."""
    import pandas as pd

    from src.screening.offensive.daily_action_service import MarketBar

    if not cache.exists():
        return None
    frame = pd.read_csv(cache)
    dates = pd.to_datetime(frame.get("date"), format="mixed", errors="coerce").dt.date
    rows = frame.loc[dates == trade_date]
    if len(rows) != 1:
        return None
    row = rows.iloc[0]

    def positive(name):
        if name not in row or pd.isna(row[name]):
            return None
        value = float(row[name])
        return value if value > 0 else None

    suspended = None
    if "suspended" in row and pd.notna(row["suspended"]):
        raw = row["suspended"]
        if isinstance(raw, bool) or raw in (0, 1):
            suspended = bool(raw)
    return MarketBar(
        positive("open"),
        positive("close"),
        positive("limit_down"),
        positive("limit_up"),
        suspended,
        positive("high"),
        positive("low"),
    )


# Task 9: Chinese operator-readable reason codes for daily action blocks.
# Maps internal reason strings to human-readable Chinese explanations.
# Unknown codes get a fail-closed fallback that remains visible under --verbose.
_DAILY_ACTION_BLOCK_REASONS_ZH = {
    "daily_action_readiness_missing": "就绪清单缺失：未找到当日 Daily Action 就绪清单，无法验证扫描数据完整性",
    "readiness_manifest_invalid": "就绪清单无效：清单格式损坏或校验失败",
    "readiness_date_mismatch": "日期不匹配：就绪清单的交易日期与请求的信号日不一致",
    "readiness_manifest_not_healthy": "就绪清单不健康：清单结构验证未通过",
    "readiness_identity_mismatch": "身份不匹配：就绪清单的宇宙指纹与缓存数据不一致",
    "snapshot_fingerprint_mismatch": "指纹不匹配：缓存数据与就绪清单记录的指纹不符",
    "calendar_unavailable": "交易日历不可用：无法确定信号日或下一交易日",
}


def _resolve_daily_action(
    argv: list[str], *, open_sessions=None, ledger_path=None
) -> int | None:
    """Run cached setup scanning through the auditable v2 simulation ledger.

    Flow (Task 8):
    1. Resolve signal_date from the authoritative open-session calendar and the
       shared fixed 17:00 policy. An ``--end-date`` override must be a member of
       that same calendar.
    2. Try to load a verified PIT snapshot. If available, run
       ``scan_from_verified_snapshot`` to produce candidates from the immutable
       snapshot (no cache files reopened by the scanner).
    3. If no verified snapshot exists (readiness manifest missing/unhealthy):
       new entries are BLOCKED. We still open the ledger, advance lifecycle
       (settle due entries/exits, mark to market), and render the output so the
       operator sees existing positions + the block reason. The dispatcher MUST
       NOT return early in this branch.
    4. The legacy ``scan_daily_action_candidates`` + manifest gate path is
       preserved for callers without a verified snapshot (e.g. research/tests).
       When the snapshot path is taken, the legacy candidate tuple is discarded.
    """
    if "--daily-action" not in argv:
        return None
    from pathlib import Path

    from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
    from src.screening.offensive.daily_action import (
        BlockedCandidate,
        DailyActionScan,
        render_daily_action_v2,
        resolve_daily_action_signal,
        run_daily_action_v2,
        scan_from_verified_snapshot,
    )
    from src.screening.offensive.daily_action_service import (
        DailyActionService,
        PlanCandidate,
        RegimeAuthorization,
    )
    from src.screening.offensive.daily_action_snapshot import (
        load_verified_daily_action_snapshot,
    )
    from src.screening.offensive.execution_adjuster import ExecutionCosts
    from src.screening.offensive.ledger_repository import LedgerRepository

    # --end-date YYYY-MM-DD (或 YYYYMMDD): 显式信号日仍必须属于权威开市日集合。
    # 支持 `--end-date=VALUE` 和 `--end-date VALUE` 两种形式. 默认 None → 走 17:00 规则.
    end_date_raw = _get_kv(argv, "--end-date") or _next_arg(argv, "--end-date")
    end_date = end_date_raw.strip().replace("-", "") if end_date_raw else None

    if open_sessions is None:
        from src.screening.offensive.daily_action import _load_authoritative_session_dates

        open_sessions = _load_authoritative_session_dates()
    open_sessions = tuple(open_sessions)
    # Task 8: resolve the signal date + regime with the lightweight resolver
    # instead of running the legacy full-market scan (which reopened cache files
    # for up to 30 tickers just to read the resolved date). Candidates now come
    # exclusively from the verified PIT snapshot below.
    signal_date, regime = resolve_daily_action_signal(
        end_date=end_date,
        open_sessions=open_sessions,
    )
    from src.screening.consecutive_recommendation import resolve_report_dir

    reports_dir = resolve_report_dir()
    data_dir = Path("data")

    # NEW (Task 8): load the verified PIT snapshot. When present, the scanner
    # consumes only the snapshot — no cache files reopened. The resolved regime
    # from regime_history.json seeds crisis/risk_off sizing (spec 8.3); the
    # snapshot's own regime is authoritative once loaded.
    verified = load_verified_daily_action_snapshot(
        signal_date,
        reports_dir=reports_dir,
        data_dir=data_dir,
        regime=regime,
    )

    if verified.snapshot is not None:
        snapshot_candidates, snapshot_blocked = scan_from_verified_snapshot(
            verified.snapshot
        )
        regime = verified.snapshot.regime
        # Best-effort: persist the full setup output (candidates + filtered-out,
        # with strength / fund-flow / pre-runup diagnostics) for out-of-sample
        # accumulation. Never breaks the trading path.
        try:
            from src.screening.offensive.setup_output_log import log_setup_outputs

            log_setup_outputs(
                verified.snapshot.signal_date,
                snapshot_candidates,
                snapshot_blocked,
                regime=regime,
            )
        except Exception:
            pass
        authorization = {
            "crisis": RegimeAuthorization.BTST_CRISIS,
            "risk_off": RegimeAuthorization.BTST_RISK_OFF,
        }.get(regime, RegimeAuthorization.NORMAL)
        candidates = DailyActionScan(
            verified.snapshot.signal_date,
            tuple(
                PlanCandidate(
                    action.ticker,
                    action.setup,
                    "v2",
                    action.kelly_pct,
                    priority,
                    authorization,
                )
                for priority, action in enumerate(snapshot_candidates, 1)
            ),
            tuple(
                BlockedCandidate(
                    action.ticker,
                    action.block_reason or "verified_snapshot_block",
                    action.entry_price,
                )
                for action in snapshot_blocked
            ),
            tuple(
                (action.ticker, action.entry_price)
                for action in snapshot_candidates
            ),
        )
        # Task 8 (deep): the service gates on the verified snapshot itself
        # (per-ticker plan_eligible + consumed fingerprint), NOT the Auto
        # data-quality manifest. This admits valid BTST tickers outside Auto's
        # 300 scoring pool (spec 12.3.2) instead of blocking them as
        # manifest_ticker_absent.
        snapshot_block_reason: str | None = None
    else:
        # FALLBACK: no verified readiness snapshot. Per spec section 10 and
        # invariant 8, new entries are BLOCKED. The legacy Auto manifest MUST
        # NOT be used as a substitute (spec: "不把旧 Auto manifest 自动升级为新域").
        # Candidates are empty — no new BUY_PLAN can be generated.
        candidates = DailyActionScan(signal_date, (), (), ())
        snapshot_block_reason = verified.global_reason or "daily_action_readiness_missing"

    def cached_prices(ticker, trade_date):
        cache = Path("data/price_cache") / f"{ticker}.csv"
        return _cached_daily_action_market_bar(cache, trade_date)

    def cached_shadow_history(ticker):
        import pandas as pd

        cache = Path("data/price_cache") / f"{ticker}.csv"
        if not cache.exists():
            return None
        return pd.read_csv(cache, dtype={"date": str})

    resolved_ledger_path = Path(ledger_path or "data/paper_trading_v2/ledger.sqlite3")
    execution_costs = ExecutionCosts(version="daily-action-v2")
    with LedgerRepository(
        resolved_ledger_path,
        "daily-action-v2",
        100_000.0,
        execution_costs=execution_costs,
    ) as repository:
        service = DailyActionService(
            repository,
            TradingSessionCalendar(open_sessions),
            cached_prices,
            execution_costs,
            shadow_history=cached_shadow_history,
        )
        v2_run = run_daily_action_v2(
            service, candidates, verified_snapshot=verified.snapshot
        )
        verbose = "--verbose" in argv
        rendered = render_daily_action_v2(v2_run, verbose=verbose)
        if snapshot_block_reason:
            # Surface the readiness block reason so the operator understands
            # why no new entries appeared (manifest missing/unhealthy/etc).
            # Lifecycle output (open positions, exits) is still rendered above.
            reason_zh = _DAILY_ACTION_BLOCK_REASONS_ZH.get(
                snapshot_block_reason,
                f"数据护栏阻断（{snapshot_block_reason}）",
            )
            rendered = (
                rendered
                + f"\n"
                + f"结论：⛔ 今日未生成新的次日买入计划\n"
                + f"原因：{reason_zh}\n"
                + f"影响：新候选无法进入计划，但已有持仓的估值和退出仍正常执行\n"
                + f"建议：收盘后运行 uv run python src/main.py --auto 刷新缓存和就绪清单，"
                + f"再运行 --daily-action 获取次日信号"
            )
        elif not v2_run.plans:
            # Readiness is healthy but produced no plan-eligible candidate.
            # Distinguish "healthy but no signal" from "diagnostic-only degraded
            # setups exist" so the operator never reads a data block as a normal
            # no-signal day (spec section 9).
            if v2_run.blocked_candidates:
                rendered = rendered + "\n结论：ℹ️ 存在仅供诊断的残缺 setup，无可交易候选"
            else:
                rendered = (
                    rendered
                    + "\n结论：ℹ️ 今日无符合条件的次日买入信号（系统运行正常）"
                )
        print(rendered)
    return 0


def _resolve_reconcile(argv: list[str]) -> int | None:
    """P-3 实盘对账 — trade log vs 模型预测 (realized-evidence path).

    Usage: ``--reconcile trade_log.csv``
    Trade-log v1 format (CSV): ticker,buy_date,buy_price,sell_date,sell_price
    """
    if "--reconcile" not in argv:
        return None
    from pathlib import Path

    from src.utils.display import Fore, Style

    trade_path_raw = _get_kv(argv, "--reconcile")
    if not trade_path_raw:
        try:
            idx = argv.index("--reconcile")
            trade_path_raw = argv[idx + 1] if idx + 1 < len(argv) else ""
        except (ValueError, IndexError):
            trade_path_raw = ""
    if not trade_path_raw:
        print(f"{Fore.RED}Usage: --reconcile <trade_log.csv>{Style.RESET_ALL}\n" f"  v1 format: ticker,buy_date,buy_price,sell_date,sell_price")
        return 1
    trade_path = Path(trade_path_raw).expanduser()
    if not trade_path.exists():
        print(f"{Fore.RED}交易日志不存在: {trade_path}{Style.RESET_ALL}")
        return 1
    from src.screening.reconciliation import (
        compute_reconciliation,
        render_reconciliation,
    )

    report = compute_reconciliation(trade_log_path=trade_path)
    print(render_reconciliation(report))
    return 0


def _resolve_refresh_regime_winrates(argv: list[str]) -> int | None:
    """NS-5 (C237): ``--refresh-regime-winrates`` — daily scheduling 重算 regime 历史胜率.

    Usage:
        --refresh-regime-winrates                  # 输出 JSON 到 stdout
        --refresh-regime-winrates --output=path    # 写入文件
        --refresh-regime-winrates --min-samples=10 # 覆盖默认阈值
    """
    if "--refresh-regime-winrates" not in argv:
        return None
    from pathlib import Path

    from src.screening.regime_winrate_recompute import run_refresh_cli

    output_raw = _get_kv(argv, "--output")
    output_path = Path(output_raw).expanduser() if output_raw else None
    min_samples = _parse_int(_get_kv(argv, "--min-samples"), 10)
    return run_refresh_cli(output_path=output_path, min_samples=min_samples)


def _resolve_flywheel_health(argv: list[str]) -> int | None:
    """NS-5: on-demand data-flywheel health check.

    Surfaces the silent-stall antidote (:func:`assess_tracking_history`) to the
    CLI so the owner can check whether the daily auto_screening job is actually
    accumulating tracking_history — without reading the boot-volume launchd log.
    The whole point of c256: silent 6-day stalls must become OBSERVABLE.
    """
    if "--flywheel-health" not in argv:
        return None
    import json as _json

    from src.screening.flywheel_health import assess_tracking_history

    result = assess_tracking_history()
    # human-readable + machine-parseable (JSON) so scripts/cron can grep it
    print(_json.dumps(result, ensure_ascii=False))
    return 0


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
    ("--daily-action", _resolve_daily_action),
    ("--export-conditional-orders", _resolve_export_conditional_orders),
    ("--weekly-report", _resolve_weekly_report),
    ("--data-quality-audit", _resolve_data_quality_audit),
    ("--confidence-calibration", _resolve_confidence_calibration),
    ("--conviction-ranking", _resolve_conviction_ranking),
    ("--top", _resolve_top),
    ("--check-freshness", _resolve_check_freshness),
    ("--flywheel-health", _resolve_flywheel_health),
    ("--daily-delta", _resolve_daily_delta),
    ("--signal-consistency", _resolve_signal_consistency),
    ("--dynamic-threshold", _resolve_dynamic_threshold),
    ("--decision-flow", _resolve_decision_flow),
    ("--outlier-detect", _resolve_outlier_detect),
    ("--expected-returns", _resolve_expected_returns),
    ("--signal-momentum", _resolve_signal_momentum),
    ("--sector-strength", _resolve_sector_strength),
    ("--composite-score", _resolve_composite_score),
    ("--volume-confirm", _resolve_volume_confirm),
    ("--trend-resonance", _resolve_trend_resonance),
    ("--position-check", _resolve_position_check),
    ("--strategy-report", _resolve_strategy_report),
    ("--top-picks", _resolve_top_picks),
    ("--top-setups", _resolve_top_setups),
    ("--reconcile", _resolve_reconcile),
    ("--refresh-regime-winrates", _resolve_refresh_regime_winrates),
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
