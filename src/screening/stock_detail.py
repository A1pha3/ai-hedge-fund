"""P2-6 标的深度分析 — 单只股票的完整分析报告。

聚合所有已有报告数据 (auto_screening + tracking_history + consecutive_recommendation +
signal_decay_detector)，生成单只标的的深度分析概览。不调用任何外部 API。

主入口:
  - ``StockDetail``: 标的详情 dataclass
  - ``compute_stock_detail``: 聚合所有可用数据
  - ``render_stock_detail``: ASCII 详情报告 (CLI 输出)
  - ``run_stock_detail_cli``: CLI 入口 (供 main.py --stock-detail 复用)
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import (
    compute_consecutive_recommendations,
    DEFAULT_LOOKBACK_DAYS,
    resolve_report_dir,
)
from src.screening.recommendation_tracker import HISTORY_FILENAME
from src.screening.signal_decay_detector import detect_signal_decay
from src.utils.numeric import safe_int as _safe_int

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class StockDetail:
    """单只标的的完整深度分析报告。

    所有字段均为 Optional-safe — 缺失数据时填充 None / 0 / False,
    不抛异常, 不阻塞渲染。
    """

    ticker: str
    name: str
    industry_sw: str

    # 基本面
    pe_ratio: float | None
    pb_ratio: float | None
    roe: float | None
    revenue_growth: float | None
    profit_growth: float | None
    dividend_yield: float | None

    # 技术面
    price: float
    change_pct: float
    ma5: float | None
    ma20: float | None
    ma60: float | None
    rsi_14: float | None
    macd_signal: str  # "bullish" / "bearish" / "neutral"
    atr_pct: float | None

    # 资金流
    money_flow_net: float | None  # 万元
    north_money_net: float | None
    dragon_tiger: bool  # 近 5 日是否上龙虎榜

    # 系统历史
    recommendation_count_30d: int  # 近 30 天被推荐次数
    latest_score_b: float | None
    latest_decision: str | None
    consecutive_days: int
    decay_level: str

    # 同行业排名
    industry_rank: int | None
    industry_total: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float | None = None) -> float | None:
    """安全转为有限 float; None / NaN / Inf / 非数值 -> ``default``."""
    if value is None:
        return default
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(fv) or math.isinf(fv):
        return default
    return fv


def _determine_macd_signal(metrics: dict[str, Any]) -> str:
    """根据 strategy_signals 中趋势因子的 MACD 子因子判定信号方向。

    Returns: "bullish" / "bearish" / "neutral"
    """
    trend_signal = metrics.get("trend")
    if not isinstance(trend_signal, dict):
        return "neutral"

    sub_factors = trend_signal.get("sub_factors")
    if not isinstance(sub_factors, dict):
        # fallback: 用 direction 判定
        direction = _safe_int(trend_signal.get("direction"), 0)
        if direction > 0:
            return "bullish"
        if direction < 0:
            return "bearish"
        return "neutral"

    # 优先看 macd 子因子
    macd_sf = sub_factors.get("macd")
    if isinstance(macd_sf, dict):
        d = _safe_int(macd_sf.get("direction"), 0)
        if d > 0:
            return "bullish"
        if d < 0:
            return "bearish"

    # 其次看 trend_signal 的 direction
    direction = _safe_int(trend_signal.get("direction"), 0)
    if direction > 0:
        return "bullish"
    if direction < 0:
        return "bearish"
    return "neutral"


def _count_recommendations_30d(
    ticker: str,
    report_dir: Path,
    end_date: str,
) -> int:
    """统计近 30 天被推荐次数 (出现在 recommendations 中的天数)。"""
    from src.screening.consecutive_recommendation import load_auto_screening_history

    history = load_auto_screening_history(
        lookback_days=30,
        report_dir=report_dir,
        end_date=end_date,
    )
    count = 0
    for entry in history:
        recs = entry.get("payload", {}).get("recommendations", []) or []
        for rec in recs:
            if isinstance(rec, dict) and rec.get("ticker") == ticker:
                count += 1
                break
    return count


def _compute_industry_rank(
    recommendations: list[dict],
    match: dict,
) -> tuple[int | None, int | None]:
    """在同行业推荐列表中计算排名。"""
    industry = match.get("industry_sw", "")
    ticker = match.get("ticker", "")
    if not industry:
        return None, None

    peers = [(r.get("ticker", ""), _safe_float(r.get("score_b"), 0.0) or 0.0) for r in recommendations if isinstance(r, dict) and r.get("industry_sw") == industry]
    if not peers:
        return None, None

    peers_sorted = sorted(peers, key=lambda x: x[1], reverse=True)
    total = len(peers_sorted)
    rank: int | None = None
    for idx, (t, _s) in enumerate(peers_sorted, 1):
        if t == ticker:
            rank = idx
            break
    if rank is None:
        return None, total
    return rank, total


def _load_tracking_history(report_dir: Path) -> list[dict]:
    """加载 tracking_history.json，失败时返回空列表。"""
    history_path = report_dir / HISTORY_FILENAME
    if not history_path.exists():
        return []
    try:
        with open(history_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        records = data.get("records", [])
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
    return []


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def compute_stock_detail(
    ticker: str,
    recommendations: list[dict] | None = None,
    tracking_history: list[dict] | None = None,
    consecutive_map: dict | None = None,
    decay_map: dict | None = None,
    report_dir: Path | None = None,
    trade_date: str | None = None,
) -> StockDetail:
    """聚合所有可用数据生成单只标的的深度分析。

    不调用外部 API — 完全基于已有报告数据。

    Args:
        ticker: 6 位 A 股代码 (e.g. "300750")
        recommendations: 最新 auto_screening 报告的 recommendations 列表;
            None 时从最新报告自动加载
        tracking_history: tracking_history.json 内容; None 时自动加载
        consecutive_map: consecutive_recommendation 数据; None 时自动计算
        decay_map: signal_decay_detector 数据; None 时自动计算
        report_dir: 报告目录; None 时自动解析
        trade_date: 当前日期 YYYYMMDD; None 时从最新报告推断

    Returns:
        StockDetail 实例
    """
    if report_dir is None:
        report_dir = resolve_report_dir()

    # 加载 recommendations (若未传入)
    if recommendations is None:
        from src.screening.compare_tool import load_latest_recommendations

        recommendations = load_latest_recommendations(
            report_dir=report_dir,
            trade_date=trade_date,
        )

    # 找到匹配的推荐条目
    match: dict | None = None
    for rec in recommendations:
        if isinstance(rec, dict) and rec.get("ticker") == ticker:
            match = rec
            break

    # 无法找到匹配 — 用默认值构造
    if match is None:
        return StockDetail(
            ticker=ticker,
            name="",
            industry_sw="",
            pe_ratio=None,
            pb_ratio=None,
            roe=None,
            revenue_growth=None,
            profit_growth=None,
            dividend_yield=None,
            price=0.0,
            change_pct=0.0,
            ma5=None,
            ma20=None,
            ma60=None,
            rsi_14=None,
            macd_signal="neutral",
            atr_pct=None,
            money_flow_net=None,
            north_money_net=None,
            dragon_tiger=False,
            recommendation_count_30d=0,
            latest_score_b=None,
            latest_decision=None,
            consecutive_days=0,
            decay_level="none",
            industry_rank=None,
            industry_total=None,
        )

    # 提取基本信息
    name = str(match.get("name", "") or "")
    industry_sw = str(match.get("industry_sw", "") or "")

    # 提取 metrics
    metrics = match.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}

    strategy_signals = match.get("strategy_signals")
    if not isinstance(strategy_signals, dict):
        strategy_signals = {}

    # 基本面 — 从 fundamental strategy signals 的 sub_factors 中提取
    pe_ratio = _safe_float(metrics.get("pe_ratio"))
    pb_ratio = _safe_float(metrics.get("pb_ratio"))
    roe = _safe_float(metrics.get("roe"))
    revenue_growth = _safe_float(metrics.get("revenue_growth"))
    profit_growth = _safe_float(metrics.get("profit_growth"))
    dividend_yield = _safe_float(metrics.get("dividend_yield"))

    # 尝试从 fundamental sub_factors 提取基本面
    fund_sig = strategy_signals.get("fundamental")
    if isinstance(fund_sig, dict):
        sub_factors = fund_sig.get("sub_factors")
        if isinstance(sub_factors, dict):
            for sf_name, sf_data in sub_factors.items():
                if not isinstance(sf_data, dict):
                    continue
                sf_metrics = sf_data.get("metrics", {})
                if not isinstance(sf_metrics, dict):
                    continue
                if pe_ratio is None:
                    pe_ratio = _safe_float(sf_metrics.get("pe_ratio"))
                if pb_ratio is None:
                    pb_ratio = _safe_float(sf_metrics.get("pb_ratio"))
                if roe is None:
                    roe = _safe_float(sf_metrics.get("roe"))
                if revenue_growth is None:
                    revenue_growth = _safe_float(sf_metrics.get("revenue_growth"))
                if profit_growth is None:
                    profit_growth = _safe_float(sf_metrics.get("profit_growth"))
                if dividend_yield is None:
                    dividend_yield = _safe_float(sf_metrics.get("dividend_yield"))

    # 技术面
    price = _safe_float(metrics.get("price"), 0.0) or 0.0
    change_pct = _safe_float(metrics.get("change_pct"), 0.0) or 0.0
    ma5 = _safe_float(metrics.get("ma5"))
    ma20 = _safe_float(metrics.get("ma20"))
    ma60 = _safe_float(metrics.get("ma60"))
    rsi_14 = _safe_float(metrics.get("rsi_14"))

    # 从 trend sub_factors 中提取技术指标
    trend_sig = strategy_signals.get("trend")
    if isinstance(trend_sig, dict):
        t_sub = trend_sig.get("sub_factors")
        if isinstance(t_sub, dict):
            for sf_name, sf_data in t_sub.items():
                if not isinstance(sf_data, dict):
                    continue
                sf_metrics = sf_data.get("metrics", {})
                if not isinstance(sf_metrics, dict):
                    continue
                if price == 0.0:
                    price = _safe_float(sf_metrics.get("price"), 0.0) or 0.0
                if change_pct == 0.0:
                    change_pct = _safe_float(sf_metrics.get("change_pct"), 0.0) or 0.0
                if ma5 is None:
                    ma5 = _safe_float(sf_metrics.get("ma5"))
                if ma20 is None:
                    ma20 = _safe_float(sf_metrics.get("ma20"))
                if ma60 is None:
                    ma60 = _safe_float(sf_metrics.get("ma60"))
                if rsi_14 is None:
                    rsi_14 = _safe_float(sf_metrics.get("rsi_14"))

    macd_signal = _determine_macd_signal(strategy_signals)
    atr_pct = _safe_float(metrics.get("atr_pct"))

    # 资金流
    money_flow_net = _safe_float(metrics.get("money_flow_net"))
    north_money_net = _safe_float(metrics.get("north_money_net"))
    dragon_tiger = bool(metrics.get("dragon_tiger", False))

    # 推断 trade_date (若未传入)
    if trade_date is None:
        # 尝试从 tracking_history 或最新报告推断
        from src.screening.consecutive_recommendation import (
            _latest_report_date as _get_latest,
        )

        latest_dt = _get_latest(report_dir)
        if latest_dt is not None:
            trade_date = latest_dt.strftime("%Y%m%d")
        else:
            trade_date = datetime.now().strftime("%Y%m%d")

    # 系统历史
    recommendation_count_30d = _count_recommendations_30d(ticker, report_dir, trade_date)
    latest_score_b = _safe_float(match.get("score_b"))
    latest_decision = str(match.get("decision", "neutral") or "neutral")

    # 连续推荐
    if consecutive_map is None:
        try:
            all_stats = compute_consecutive_recommendations(
                lookback_days=DEFAULT_LOOKBACK_DAYS,
                report_dir=report_dir,
                end_date=trade_date,
            )
            consecutive_days = all_stats.get(ticker).consecutive_days if ticker in all_stats else 0
        except Exception:
            consecutive_days = 0
    else:
        stats = consecutive_map.get(ticker)
        if stats and hasattr(stats, "consecutive_days"):
            consecutive_days = stats.consecutive_days
        elif isinstance(stats, dict):
            consecutive_days = _safe_int(stats.get("consecutive_days"), 0)
        else:
            consecutive_days = 0

    # 信号衰减
    if decay_map is None:
        try:
            all_decay = detect_signal_decay(
                current_recommendations=[match],
                report_dir=report_dir,
                end_date=trade_date,
            )
            decay_info = all_decay.get(ticker)
            decay_level = decay_info.level.value if decay_info else "none"
        except Exception:
            decay_level = "none"
    else:
        decay_info = decay_map.get(ticker)
        if decay_info and hasattr(decay_info, "level"):
            decay_level = decay_info.level.value
        elif isinstance(decay_info, dict):
            decay_level = str(decay_info.get("level", "none"))
        else:
            decay_level = "none"

    # 同行业排名
    industry_rank, industry_total = _compute_industry_rank(recommendations, match)

    return StockDetail(
        ticker=ticker,
        name=name,
        industry_sw=industry_sw,
        pe_ratio=pe_ratio,
        pb_ratio=pb_ratio,
        roe=roe,
        revenue_growth=revenue_growth,
        profit_growth=profit_growth,
        dividend_yield=dividend_yield,
        price=price,
        change_pct=change_pct,
        ma5=ma5,
        ma20=ma20,
        ma60=ma60,
        rsi_14=rsi_14,
        macd_signal=macd_signal,
        atr_pct=atr_pct,
        money_flow_net=money_flow_net,
        north_money_net=north_money_net,
        dragon_tiger=dragon_tiger,
        recommendation_count_30d=recommendation_count_30d,
        latest_score_b=latest_score_b,
        latest_decision=latest_decision,
        consecutive_days=consecutive_days,
        decay_level=decay_level,
        industry_rank=industry_rank,
        industry_total=industry_total,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_stock_detail(detail: StockDetail) -> str:
    """ASCII 详情报告 — 无颜色 (纯文本, 供 CLI / 日志 / Web 端消费)。

    输出格式:
        ━━━ 标的详情 · 300750 宁德时代 (电力设备) ━━━
        ...
    """
    lines: list[str] = []

    # 标题
    header = f"标的详情 · {detail.ticker}"
    if detail.name:
        header += f" {detail.name}"
    if detail.industry_sw:
        header += f" ({detail.industry_sw})"
    lines.append("━" * 3 + f" {header} " + "━" * 3)

    # 基本面
    lines.append("")
    lines.append("── 基本面 " + "─" * 33)
    pe_str = f"{detail.pe_ratio:.1f}" if detail.pe_ratio is not None else "—"
    pb_str = f"{detail.pb_ratio:.1f}" if detail.pb_ratio is not None else "—"
    roe_str = f"{detail.roe:.1f}%" if detail.roe is not None else "—"
    lines.append(f"PE: {pe_str}  PB: {pb_str}  ROE: {roe_str}")
    rev_str = f"+{detail.revenue_growth:.1f}%" if detail.revenue_growth is not None else "—"
    profit_str = f"+{detail.profit_growth:.1f}%" if detail.profit_growth is not None else "—"
    div_str = f"{detail.dividend_yield:.1f}%" if detail.dividend_yield is not None else "—"
    lines.append(f"营收增长: {rev_str}  利润增长: {profit_str}  股息率: {div_str}")

    # 技术面
    lines.append("")
    lines.append("── 技术面 " + "─" * 33)
    change_str = f"({detail.change_pct:+.1f}%)" if detail.change_pct != 0.0 else ""
    price_str = f"{detail.price:.2f}" if detail.price != 0.0 else "—"
    ma5_str = f"{detail.ma5:.1f}" if detail.ma5 is not None else "—"
    ma20_str = f"{detail.ma20:.1f}" if detail.ma20 is not None else "—"
    lines.append(f"现价: {price_str} {change_str}  MA5: {ma5_str}  MA20: {ma20_str}")
    rsi_str = f"{detail.rsi_14:.1f}" if detail.rsi_14 is not None else "—"
    atr_str = f"{detail.atr_pct:.1f}%" if detail.atr_pct is not None else "—"
    lines.append(f"RSI: {rsi_str}  MACD: {detail.macd_signal}  ATR: {atr_str}")

    # 资金流
    lines.append("")
    lines.append("── 资金流 " + "─" * 33)
    if detail.money_flow_net is not None:
        flow_str = f"+{detail.money_flow_net / 10000:.1f}亿" if abs(detail.money_flow_net) >= 10000 else f"{detail.money_flow_net:.0f}万"
    else:
        flow_str = "—"
    north_str = f"+{detail.north_money_net / 10000:.1f}亿" if detail.north_money_net is not None else "—"
    dt_str = "近5日有" if detail.dragon_tiger else "无"
    lines.append(f"主力净流入: {flow_str}  北向: {north_str}  龙虎榜: {dt_str}")

    # 系统历史
    lines.append("")
    lines.append("── 系统历史 " + "─" * 33)
    score_str = f"{detail.latest_score_b:+.2f}" if detail.latest_score_b is not None else "—"
    decision_str = detail.latest_decision or "—"
    lines.append(f"近30天推荐: {detail.recommendation_count_30d}次  最新score_b: {score_str}  决策: {decision_str}")
    lines.append(f"连续推荐: {detail.consecutive_days}天  信号衰减: {detail.decay_level}")

    # 同行业排名
    if detail.industry_rank is not None and detail.industry_total is not None:
        lines.append(f"同行业排名: 第 {detail.industry_rank}/{detail.industry_total} 名")
    else:
        lines.append("同行业排名: 无数据")

    # 综合评价
    lines.append("")
    summary_parts: list[str] = []
    if detail.pe_ratio is not None and detail.pe_ratio < 50 and detail.roe is not None and detail.roe > 10:
        summary_parts.append("基本面优秀")
    if detail.macd_signal == "bullish":
        summary_parts.append("技术强势")
    elif detail.macd_signal == "bearish":
        summary_parts.append("技术弱势")
    if detail.money_flow_net is not None and detail.money_flow_net > 0:
        summary_parts.append("资金持续流入")
    if detail.consecutive_days >= 3:
        summary_parts.append(f"系统连续{detail.consecutive_days}天推荐")
    if not summary_parts:
        summary_parts.append("数据不足，建议人工判断")

    lines.append("综合评价: " + "+".join(summary_parts))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_stock_detail_cli(ticker: str, trade_date: str | None = None) -> int:
    """CLI 入口 — ``--stock-detail 300750`` 调用。

    Args:
        ticker: 6 位 A 股代码
        trade_date: 可选日期 YYYYMMDD; None 时取最新报告

    Returns:
        退出码 (0 = 成功, 1 = 未找到标的)
    """
    from colorama import Fore, Style

    detail = compute_stock_detail(ticker=ticker, trade_date=trade_date)

    if detail.name == "" and detail.latest_score_b is None:
        print(f"{Fore.YELLOW}[StockDetail] 标的 {ticker} 未在任何推荐报告中出现, 请先运行 --auto{Style.RESET_ALL}")
        return 1

    # 带颜色的 CLI 输出
    print()
    print(f"{Fore.CYAN}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[StockDetail] 标的深度分析 (P2-6){Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print()

    # 逐段加颜色
    plain = render_stock_detail(detail)
    # 加粗分隔线和标题
    for line in plain.splitlines():
        if line.startswith("━"):
            print(f"{Fore.CYAN}{Style.BRIGHT}{line}{Style.RESET_ALL}")
        elif line.startswith("─"):
            print(f"{Fore.CYAN}{line}{Style.RESET_ALL}")
        elif line.startswith("综合评价"):
            print(f"{Fore.GREEN}{Style.BRIGHT}{line}{Style.RESET_ALL}")
        else:
            print(line)

    print()
    return 0


__all__ = [
    "StockDetail",
    "compute_stock_detail",
    "render_stock_detail",
    "run_stock_detail_cli",
]
