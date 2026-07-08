"""--daily-action — Phase A 核心: 每日机械交易动作 (移除情绪决策)。

输入: 全市场 price_cache + fund_flow store + paper_trading 状态
输出: 今日的具体动作 (BUY/EXIT/SKIP) + 入场价 + 止损 + 仓位 + 风险计划

设计原则 (Phase A "稳定小 edge"):
- 用 Phase 0 验证过的 setup 分布作 Kelly 先验 (不动态拟合, 防过拟合)
- 全市场扫描 (不依赖 --auto 的 score_b 候选池 — 凸性 setup 要极端股票, 不是"好股票")
- drawdown 熔断自动降仓/清仓 (移除"亏时恐慌" 的情绪)
- 预提交止损 + 时间退出 (移除"希望/恐惧")
- 每笔写入 paper_trading journal (暴露行为偏差, 30 天后复盘)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.screening.offensive.kelly import compute_kelly_size
from src.screening.offensive.known_distributions import get_known_distribution
from src.screening.offensive.paper_tracker import PaperTracker, TradeAction
from src.screening.offensive.risk_framework import build_risk_plan
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup

logger = logging.getLogger(__name__)

# Phase A: 多 setup (BTST T+10 + OversoldBounce T+5), 单仓位上限, 严格风控
_MAX_POSITION_PCT = 0.10  # 单票 ≤ 10%
_MAX_PORTFOLO_PCT = 0.60  # 组合 ≤ 60%
_USE_TUSHARE_PRICES = True  # akshare 在本 env 代理封了
_CN_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
_ENTRY_WINDOW_CUTOFF = time(9, 30)

# 已验证的 setup 配置 (Phase 0 通过的 setup + 对应 known_distribution)
# (setup_name, setup_class, horizon)
_VERIFIED_SETUPS = [
    ("btst_breakout", BtstBreakoutSetup, 10),
    ("oversold_bounce", OversoldBounceSetup, 5),
]


def _load_st_tickers() -> set[str]:
    """加载 ST/*ST 股票集合 (6位代码), 用于 full_market 扫描时过滤.

    --auto 的候选池在 Layer A 第一步就过滤 ST (candidate_pool_compute_pipeline_helpers.py:159),
    但 --daily-action 的 full_market 直扫 price_cache (不经候选池), 需独立过滤.
    ST 股超跌常见, OversoldBounce 容易误命中 (如 002217 ST合力泰).

    数据源: tushare stock_basic (name 含 ST). 失败时空集 (不阻塞).
    """
    import os

    token = ""
    if os.path.exists(".env"):
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("TUSHARE_TOKEN="):
                token = line.split("=", 1)[1].strip().strip("'\"")
    if not token:
        return set()
    try:
        import tushare as ts

        pro = ts.pro_api()
        basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
        st_codes: set[str] = set()
        for _, row in basic.iterrows():
            name = str(row.get("name", ""))
            if "ST" in name.upper():  # 含 ST, *ST
                st_codes.add(str(row["ts_code"])[:6])
        return st_codes
    except Exception:
        return set()


def _resolve_trade_date_and_regime() -> tuple[str, str]:
    """从 price_cache + regime_history 确定 trade_date 和 regime.

    不依赖 --auto 报告 (报告的候选池是 score_b 排序, 与凸性 setup 脱节).
    trade_date = price_cache 最新有数据的交易日; regime = regime_history.json 的标签.
    """
    price_dir = Path("data/price_cache")
    regime_path = Path("data/reports/regime_history.json")
    regimes_by_date: dict[str, str] = {}
    if regime_path.exists():
        regimes_by_date = {str(k): str(v) for k, v in json.loads(regime_path.read_text(encoding="utf-8")).items()}

    # 从任意一个 price_cache CSV 取最新日期
    latest_date = ""
    for csv in price_dir.glob("*.csv"):
        try:
            df = pd.read_csv(csv, dtype={"date": str}, usecols=["date"])
            d = str(df["date"].max()).replace("-", "")
            if d > latest_date:
                latest_date = d
        except Exception:
            continue
    if not latest_date:
        latest_date = pd.Timestamp.now().strftime("%Y%m%d")
    regime = regimes_by_date.get(latest_date, "normal")
    return latest_date, regime


def _latest_auto_report_date() -> str:
    """返回最新 auto_screening 报告日期; 缺失/解析失败时返回空字符串."""
    try:
        from src.screening.consecutive_recommendation import resolve_report_dir
        from src.screening.data_quality_audit import _find_latest_report

        latest = _find_latest_report(resolve_report_dir())
        if latest is None:
            return ""
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
            date = str(payload.get("date", "") or "").replace("-", "")
            if len(date) == 8 and date.isdigit():
                return date
        except Exception:
            pass
        stem_date = latest.stem.replace("auto_screening_", "")[:8]
        return stem_date if stem_date.isdigit() else ""
    except Exception:
        return ""


def _load_industry_day_pct_by_ticker(trade_date: str, tickers: list[str]) -> dict[str, float]:
    """Load real SW L1 one-day pct change for the scan date, keyed by ticker."""

    if not tickers:
        return {}
    try:
        from scripts.setup_research import build_ticker_to_industry, load_industry_day_pct

        ticker_to_industry = build_ticker_to_industry(tickers)
        industry_day_pct = load_industry_day_pct()
    except Exception as exc:  # noqa: BLE001 - missing context should block BTST, not crash daily action
        logger.warning("加载行业日涨幅失败, BTST 行业过滤将按 0%% 处理: %s", exc)
        return {}

    result: dict[str, float] = {}
    for ticker, industry in ticker_to_industry.items():
        value = industry_day_pct.get((industry, trade_date))
        if value is not None:
            result[ticker] = float(value)
    return result


def _weekday_next_trade_date(trade_date: str) -> str:
    """Fallback next open day: weekday-only approximation, compact YYYYMMDD."""
    text = str(trade_date or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return ""
    try:
        day = datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return ""
    while True:
        day += timedelta(days=1)
        if day.weekday() < 5:
            return day.strftime("%Y%m%d")


def _resolve_next_trade_date(trade_date: str) -> str:
    """Resolve the next A-share trading day after ``trade_date``.

    Prefer the shared BTST SSE calendar resolver, then fall back to weekday-only
    approximation so the CLI can still render when calendar APIs are unavailable.
    """
    try:
        from src.paper_trading.btst_trade_calendar import resolve_next_trade_date_cn_sse_strict

        return resolve_next_trade_date_cn_sse_strict(trade_date).next_trade_date_compact
    except Exception:
        logger.debug("next trade date calendar resolution failed for %s; using weekday fallback", trade_date, exc_info=True)
        return _weekday_next_trade_date(trade_date)


def _current_cn_datetime() -> datetime:
    """Current wall time in the A-share operating timezone."""
    return datetime.now(_CN_TZ)


def _normalize_now_to_cn(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now
    return now.astimezone(_CN_TZ)


def _missed_entry_window_reason(trade_date: str, *, now: datetime | None = None) -> str:
    """Return a blocking reason when the signal's next-open entry window has passed."""
    signal_date = str(trade_date or "").strip().replace("-", "")
    if len(signal_date) != 8 or not signal_date.isdigit():
        return ""

    next_trade_date = _resolve_next_trade_date(signal_date)
    if len(next_trade_date) != 8 or not next_trade_date.isdigit():
        return ""

    now_cn = _normalize_now_to_cn(now or _current_cn_datetime())
    now_date = now_cn.strftime("%Y%m%d")
    window_has_passed = now_date > next_trade_date or (now_date == next_trade_date and now_cn.time() >= _ENTRY_WINDOW_CUTOFF)
    if not window_has_passed:
        return ""

    return (
        f"信号日 {signal_date} 对应计划买入日 {next_trade_date} 开盘, "
        f"当前时间 {now_cn.strftime('%Y%m%d %H:%M')} 已过 09:30 买入窗口已错过; "
        "为避免盘中追单或事后补单, 本次不输出新 BUY. "
        f"请在 {next_trade_date} 收盘数据完成后刷新缓存, 再生成下一交易日计划"
    )


@dataclass
class DailyAction:
    """今日单只票的动作。"""

    ticker: str
    setup: str
    action: str  # "BUY" | "SKIP"
    kelly_pct: float
    entry_price: float
    soft_stop: float
    hard_stop: float
    time_exit: str
    invalidation_condition: str
    distribution_summary: str  # "n=5374 winrate=51% cv=1.53 E=+2.6%"
    reasoning: str


def _load_prices_for_ticker(ticker: str, report_date: str) -> pd.DataFrame:
    """加载 ticker 价格 (tushare 优先, 含报告日前的历史)。"""
    cache = Path("data/price_cache") / f"{ticker}.csv"
    if cache.exists():
        df = pd.read_csv(cache, dtype={"date": str})
        df["date"] = pd.to_datetime(df["date"])
        return df
    # 拉取 (tushare)
    import os

    token = ""
    if os.path.exists(".env"):
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("TUSHARE_TOKEN="):
                token = line.split("=", 1)[1].strip().strip("'\"")
    if not token:
        return pd.DataFrame()
    import tushare as ts

    ts.set_token(token)
    pro = ts.pro_api()
    suffix = ".SZ" if ticker.startswith(("0", "3")) else ".SH"
    raw = pro.daily(ts_code=f"{ticker}{suffix}", start_date="20200101", end_date=report_date)
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    df = (
        pd.DataFrame(
            {
                "date": pd.to_datetime(raw["trade_date"], format="%Y%m%d"),
                "close": raw["close"].astype(float),
                "open": raw["open"].astype(float),
                "high": raw["high"].astype(float),
                "low": raw["low"].astype(float),
                "pct_change": raw["pct_chg"].astype(float),
            }
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache, index=False)
    return df


def generate_daily_action(
    report_path: Path | str | None = None,
    tracker: PaperTracker | None = None,
    tickers_to_scan: int = 30,
    *,
    use_data_fetcher: Any = None,
    price_loader: Any = None,
    scan_mode: str = "full_market",
) -> list[DailyAction]:
    """生成今日机械动作。

    流程:
    1. 确定 trade_date + regime (full_market: price_cache 最新日; report: 报告日期)
    2. **先平到期仓位 + 回填 realized P&L** (驱动 drawdown, 保证熔断基于最新 nav)
    3. drawdown 熔断检查 (决定是否允许新仓)
    4. 扫描候选 ticker, 对每个跑所有已验证 setup 的 detect
    5. 命中票查对应 known_distribution → Kelly 仓位
    6. 风险计划 (止损 + 时间退出 + 失效条件)
    7. 写入 paper journal

    Args:
        scan_mode: "full_market" (默认, 扫 price_cache 全市场 302 ticker) 或
            "report" (读 --auto 报告的 top-N 候选, 旧模式, 测试兼容)
        use_data_fetcher: ``(ticker, start, end) -> [{"time", "close"}, ...]`` 注入
            seam, 传给 close_matured 取 T+N 收益 (测试用, 对齐 recommendation_tracker)
        price_loader: ``(ticker, report_date) -> DataFrame`` 注入 seam, 传给
            close_matured 读 low 序列检测止损触发 (测试用)
    """
    if tracker is None:
        tracker = PaperTracker()
    _load_prices = price_loader if price_loader is not None else _load_prices_for_ticker
    tracker.last_action_stale_reason = ""

    # 1. 确定 trade_date + regime + 候选 ticker 列表
    if scan_mode == "report":
        # 旧模式: 读 --auto 报告 (测试兼容)
        if report_path is None:
            from src.screening.consecutive_recommendation import resolve_report_dir
            from src.screening.data_quality_audit import _find_latest_report

            latest = _find_latest_report(resolve_report_dir())
            if latest is None:
                return []
            report_path = latest
        with open(report_path, encoding="utf-8") as f:
            report = json.loads(f.read())
        trade_date = str(report.get("date", ""))
        recs = report.get("recommendations", [])[:tickers_to_scan]
        scan_tickers = [str(rec.get("ticker", "")) for rec in recs if rec.get("ticker")]
        regime = str(report.get("market_state", {}).get("regime_gate_level", "normal"))
    else:
        # full_market: 全市场扫描 (不依赖 --auto 报告的 score_b 候选池)
        trade_date, regime = _resolve_trade_date_and_regime()
        tracker.last_action_trade_date = trade_date
        latest_report_date = _latest_auto_report_date()
        if latest_report_date and trade_date and latest_report_date > trade_date:
            tracker.last_action_stale_reason = (
                f"price_cache 最新交易日 {trade_date} 落后于最新 --auto 报告 {latest_report_date}; "
                "为避免使用过期信号, 本次不输出新 BUY"
            )
            tracker.close_matured(trade_date, use_data_fetcher=use_data_fetcher, price_loader=_load_prices)
            return []
        missed_window_reason = _missed_entry_window_reason(trade_date)
        if missed_window_reason:
            tracker.last_action_stale_reason = missed_window_reason
            tracker.close_matured(trade_date, use_data_fetcher=use_data_fetcher, price_loader=_load_prices)
            return []
        all_cache_tickers = sorted(p.stem for p in Path("data/price_cache").glob("*.csv"))
        # ST 过滤 (安全: --auto 候选池在 Layer A 过滤 ST, full_market 直扫需独立过滤)
        st_tickers = _load_st_tickers()
        if st_tickers:
            excluded = [t for t in all_cache_tickers if t in st_tickers]
            if excluded:
                logger.info("full_market 扫描排除 %d 只 ST 股: %s", len(excluded), excluded[:5])
            scan_tickers = [t for t in all_cache_tickers if t not in st_tickers]
        else:
            scan_tickers = all_cache_tickers
        recs = []  # report 模式专用

    tracker.last_action_trade_date = trade_date

    # 2. 先平到期仓位 + 回填 realized P&L → 驱动 drawdown (闭环核心)
    tracker.close_matured(trade_date, use_data_fetcher=use_data_fetcher, price_loader=_load_prices)

    # 3. drawdown 熔断
    dd_action = tracker.drawdown_action()
    if dd_action == "liquidate":
        return []

    # 4. 资金流 store
    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    store = FundFlowStore(cache_dir="data/fund_flow_cache/")

    # 5. 预加载每个已验证 setup 的 known_distribution
    setup_configs = []
    for name, cls, horizon in _VERIFIED_SETUPS:
        dist = get_known_distribution(name, horizon)
        if dist is None:
            logger.warning("无 %s T+%d 已知分布, 跳过该 setup", name, horizon)
            continue
        setup_configs.append((name, cls(), horizon, dist))
    if not setup_configs:
        logger.warning("无任何已验证 setup 的 known_distribution, --daily-action 无法出信号")
        return []

    needs_industry_day_pct = any(name == "btst_breakout" for name, *_rest in setup_configs)
    industry_day_pct_by_ticker = (
        _load_industry_day_pct_by_ticker(trade_date, scan_tickers) if needs_industry_day_pct else {}
    )

    ranked_candidates: list[tuple[float, float, float, int, DailyAction]] = []
    for ticker in scan_tickers:
        if not ticker:
            continue
        prices = _load_prices(ticker, trade_date)
        if prices is None or len(prices) == 0:
            continue
        flow_records = store.get_range(ticker, "20200101", trade_date)

        last_row = prices.iloc[-1]
        pct = float(last_row.get("pct_change", 0.0) or 0.0)

        # 对每个已验证 setup 跑 detect
        for setup_name, setup_obj, horizon, known_dist in setup_configs:
            # 快速预过滤 (避免对全量 ticker 跑慢 detect)
            if setup_name == "btst_breakout" and pct < 9.5:
                continue  # BTST 只看涨停日
            if setup_name == "oversold_bounce":
                # OversoldBounce: 近30日跌幅需>20% (否则 detect 必 miss)
                if len(prices) < 31:
                    continue
                drop30 = (float(last_row["close"]) / float(prices.iloc[-31]["close"]) - 1) * 100
                if drop30 > -20:
                    continue

            industry_pct = (
                float(industry_day_pct_by_ticker.get(ticker, 0.0) or 0.0)
                if setup_name == "btst_breakout"
                else 0.0
            )
            ctx = {
                "prices": prices,
                "fund_flow_records": flow_records,
                "industry_day_pct": industry_pct,
                "regime": regime,
            }
            result = setup_obj.detect(ticker, trade_date, ctx)
            if not result.hit:
                if scan_mode == "report":
                    tracker.record_skip(trade_date, ticker, setup_name, horizon, reasoning=f"未触发 (pct={pct:.1f}%)")
                continue

            # Kelly 仓位 (组合总上限稍后在排序后统一分配)
            kelly = compute_kelly_size(known_dist, max_pct=_MAX_POSITION_PCT)
            size_factor = 0.5 if dd_action == "decrease" else 1.0
            kelly_pct = kelly.position_pct * size_factor
            if kelly_pct <= 0:
                if scan_mode == "report":
                    tracker.record_skip(trade_date, ticker, setup_name, horizon, reasoning="Kelly 仓位为 0")
                continue

            # 风险计划
            risk = build_risk_plan(
                invalidation_condition=result.invalidation_condition,
                avg_loss=known_dist.avg_loss,
                natural_horizon=horizon,
            )
            entry_price = float(last_row["close"])
            soft_stop_price = entry_price * (1 + risk.stop_loss_pct)
            hard_stop_price = entry_price * (1 + risk.hard_stop_pct)
            dist_summary = (
                f"n={known_dist.n} winrate={known_dist.winrate:.0%} "
                f"cv={known_dist.convexity_ratio:.2f} E=+{known_dist.expected_return:.1%}"
            )

            action = DailyAction(
                ticker=ticker,
                setup=setup_name,
                action="BUY",
                kelly_pct=kelly_pct,
                entry_price=entry_price,
                soft_stop=soft_stop_price,
                hard_stop=hard_stop_price,
                time_exit=risk.time_exit,
                invalidation_condition=result.invalidation_condition,
                distribution_summary=dist_summary,
                reasoning=f"{setup_name} T+{horizon} 命中; half-Kelly {kelly_pct:.1%}; drawdown={dd_action}",
            )
            ranked_candidates.append(
                (
                    float(known_dist.expected_return),
                    float(result.trigger_strength),
                    float(known_dist.convexity_ratio),
                    horizon,
                    action,
                )
            )
            break  # 同票只取第一个命中的 setup (避免重复仓位)

    ranked_candidates.sort(
        key=lambda item: (
            -item[0],
            -item[1],
            -item[2],
            item[4].ticker,
        )
    )

    actions: list[DailyAction] = []
    portfolio_position_used = 0.0
    for _expected_return, _trigger_strength, _convexity, horizon, action in ranked_candidates:
        kelly_pct = action.kelly_pct
        if portfolio_position_used + kelly_pct > _MAX_PORTFOLO_PCT:
            kelly_pct = max(0.0, _MAX_PORTFOLO_PCT - portfolio_position_used)
        if kelly_pct <= 0:
            break

        action.kelly_pct = kelly_pct
        action.reasoning = f"{action.setup} T+{horizon} 命中; half-Kelly {kelly_pct:.1%}; drawdown={dd_action}"
        actions.append(action)
        portfolio_position_used += kelly_pct

        tracker.record_buy(
            trade_date=trade_date,
            ticker=action.ticker,
            setup=action.setup,
            horizon=horizon,
            entry_price=action.entry_price,
            kelly_pct=kelly_pct,
            soft_stop=action.soft_stop,
            hard_stop=action.hard_stop,
            invalidation=action.invalidation_condition,
            reasoning=action.reasoning,
        )

    return actions


def render_daily_action(
    actions: list[DailyAction],
    trade_date: str,
    tracker: PaperTracker,
    *,
    closed_positions: list[dict[str, Any]] | None = None,
) -> str:
    """渲染机械动作 (decision support, 移除情绪)。

    Args:
        closed_positions: close_matured 返回的平仓摘要 (今日到期平仓的仓位).
            若有, 在组合状态后渲染平仓段, 让 operator 看到 realized P&L 演进.
            默认从 tracker.last_closed_positions 读 (generate_daily_action 已缓存).
    """
    from colorama import Fore, Style

    # 默认从 tracker 缓存读 (generate_daily_action 调 close_matured 时已写入)
    if closed_positions is None:
        closed_positions = getattr(tracker, "last_closed_positions", None) or []

    state = tracker.state
    dd = tracker.drawdown_action()
    dd_tag = {  # risk state
        "normal": f"{Fore.GREEN}正常{Style.RESET_ALL}",
        "decrease": f"{Fore.YELLOW}-15%降仓{Style.RESET_ALL}",
        "liquidate": f"{Fore.RED}-20%清仓{Style.RESET_ALL}",
    }[dd]
    next_trade_date = _resolve_next_trade_date(trade_date)
    buy_date_label = next_trade_date or "下一交易日"

    lines = [
        f"\n{Fore.CYAN}{Style.BRIGHT}📋 机械交易计划 — 信号日: {trade_date} (Phase A paper trading){Style.RESET_ALL}",
        f"  计划买入日: {buy_date_label}  执行价口径: {buy_date_label} 开盘; 当前展示价为信号日收盘参考价",
        f"  组合净值: {state.nav:.3f}  回撤: {state.drawdown_pct:+.1%}  风控状态: {dd_tag}",
        f"  持仓数: {state.open_positions}  累计已实现: {state.realized_pnl_pct:+.2%}",
    ]

    # 今日平仓摘要 (闭环核心: operator 看到 realized P&L 演进 + 止损触发披露)
    if closed_positions:
        lines.append(f"\n  {Fore.WHITE}📤 今日到期平仓 ({len(closed_positions)} 只):{Style.RESET_ALL}")
        for c in closed_positions:
            pnl = c.get("realized_pnl", 0.0)
            pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
            stop_flag = ""
            if c.get("stop_would_have_triggered"):
                stop_flag = f"  {Fore.YELLOW}⚠ 期间触硬止损{Style.RESET_ALL}"
            lines.append(
                f"  - {Fore.CYAN}{c.get('ticker', '')}{Style.RESET_ALL}  "
                f"realized {pnl_color}{pnl:+.1%}{Style.RESET_ALL}  "
                f"exit ~{c.get('exit_price', 0.0):.2f}{stop_flag}"
            )

    stale_reason = getattr(tracker, "last_action_stale_reason", "")
    if stale_reason:
        lines.append(f"\n  {Fore.RED}⚠ 数据滞后 — {stale_reason}{Style.RESET_ALL}")
        lines.append(f"  {Fore.YELLOW}本次不输出新 BUY; 请先刷新 data/price_cache / fund_flow_cache 后重跑。{Style.RESET_ALL}")
        return "\n".join(lines)

    if dd == "liquidate":
        lines.append(f"\n  {Fore.RED}⚠ DRAWDOWN 熔断 (-20%) — 不出新仓, 平掉所有持仓{Style.RESET_ALL}")
        return "\n".join(lines)

    if not actions:
        lines.append(f"\n  {Fore.YELLOW}今日无凸性 setup 命中 (空仓等待){Style.RESET_ALL}")
        return "\n".join(lines)

    lines.append(f"\n  {Fore.GREEN}计划 BUY ({len(actions)} 只, {buy_date_label} 开盘执行):{Style.RESET_ALL}\n")
    for i, a in enumerate(actions, 1):
        lines.append(
            f"  {Fore.WHITE}{i}. {Fore.CYAN}{a.ticker}{Style.RESET_ALL}  [{a.setup}]  "
            f"仓位 {a.kelly_pct:.1%}  参考价(信号日收盘) ~{a.entry_price:.2f}"
        )
        lines.append(f"     风险价位: 软止损 {a.soft_stop:.2f} (观察) / 硬止损 {a.hard_stop:.2f} (实际风控)  时间退出: {a.time_exit}")
        lines.append(f"     先验分布: {a.distribution_summary}")
        lines.append(f"     {Fore.YELLOW}失效: {a.invalidation_condition}{Style.RESET_ALL}\n")

    lines.append(f"  {Fore.WHITE}术语说明:{Style.RESET_ALL}")
    lines.append(f"  - 软止损=历史平均亏损x1.5的观察线, 用于风险参考, 不是自动卖出触发")
    lines.append(f"  - 硬止损=固定-8%的实际风控线; 触发硬止损或失效条件后, 当日收盘平")
    lines.append(f"  - 先验分布: n=历史样本数, winrate=历史胜率, cv=凸性比, E=历史平均收益")

    lines.append(f"\n  {Fore.WHITE}执行规则 (按规则执行):{Style.RESET_ALL}")
    lines.append(f"  - {buy_date_label} 开盘买入 (不追涨, 涨停买不到就放弃)")
    lines.append(f"  - 只执行预先写好的买入/止损/到期规则, 不临盘主观加仓/扛单")
    lines.append(f"  - 触硬止损或失效条件 → 当日收盘平")
    lines.append(f"  - 到期 (setup horizon) → 无条件平 (不恋战)")
    lines.append(f"  - 回撤 -15% 自动降仓 / -20% 清仓")
    # 闭环已自动: close_matured 在 generate_daily_action 开头平到期仓并回填 P&L.
    # 此前写 "30 天后用 --paper-pnl 复盘" 是死承诺 (该命令从未实现).
    lines.append(f"\n  {Fore.WHITE}已写入 paper journal (按各 setup horizon 到期自动平仓 + 回填 realized P&L){Style.RESET_ALL}")
    return "\n".join(lines)
