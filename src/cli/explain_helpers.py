"""Explain 展示辅助函数 — 从 src/main.py 抽取的纯 UI 辅助。

Round 20.14 抽取: 五个 ``run_explain`` 的私有辅助函数, 约 200 行。
所有函数签名和行为与抽取前完全一致 (纯重构, 无行为变更)。
"""
from __future__ import annotations

from src.screening.custom_weights import STRATEGY_KEYS as _STRATEGY_ORDER

# 4 策略的中文展示标签 (长形式) — run_explain Block A 因子明细使用。
# 注意: strategy_report._STRATEGY_NAMES 用短形式 ("趋势" 而非 "趋势策略"), 语义不同, 不可合并。
_STRATEGY_CN_LABELS: dict[str, str] = {
    "trend": "趋势策略",
    "mean_reversion": "均值回归",
    "fundamental": "基本面",
    "event_sentiment": "事件情绪",
}


def _build_factor_bar(confidence: float, max_bar_width: int = 10) -> str:
    """Build a 10-cell ASCII bar chart proportional to confidence (0-100)."""
    import math as _math

    # Guard against NaN — cannot convert NaN to int
    if isinstance(confidence, float) and _math.isnan(confidence):
        confidence = 0.0
    filled = min(max(int(round(confidence / 10.0)), 0), max_bar_width)
    return "█" * filled + "░" * (max_bar_width - filled)


def _print_strategy_breakdown(signals: dict) -> None:
    """Print per-strategy direction/confidence contribution lines for --explain.

    Each of the 4 strategies (trend/mean_reversion/fundamental/event_sentiment)
    shows an arrow (↑/↓/—) + confidence value, color-coded by direction.
    Extracted from ``run_explain`` to keep the per-strategy formatting in one place.
    """
    from colorama import Fore, Style

    print(f"\n{Fore.CYAN}策略贡献:{Style.RESET_ALL}")
    for strat_name in _STRATEGY_ORDER:
        sig = signals.get(strat_name)
        if not sig:
            print(f"  {strat_name:18s}  —  数据缺失")
            continue
        direction = sig.get("direction", 0)
        conf = sig.get("confidence", 0.0)
        arrow = "↑" if direction > 0 else "↓" if direction < 0 else "—"
        color = Fore.GREEN if direction > 0 else Fore.RED if direction < 0 else Fore.YELLOW
        print(f"  {strat_name:18s}  {color}{arrow} {conf:5.1f}{Style.RESET_ALL}")


def _print_factor_detail_block(signals: dict) -> None:
    """Block A: Print top-3 sub-factor detail per strategy, grouped and bar-charted."""
    from colorama import Fore, Style

    print(f"\n{Fore.CYAN}因子明细:{Style.RESET_ALL}")
    has_any_factor = False
    for strat_name in _STRATEGY_ORDER:
        sig = signals.get(strat_name)
        if not sig or not isinstance(sig, dict):
            continue
        sub_factors = sig.get("sub_factors")
        if not sub_factors or not isinstance(sub_factors, dict):
            continue
        # Collect (name, direction, confidence) for each sub-factor
        factor_items: list[tuple[str, int, float]] = []
        for _fname, fpayload in sub_factors.items():
            if not isinstance(fpayload, dict):
                continue
            fname = fpayload.get("name", _fname)
            fdir = fpayload.get("direction", 0)
            fconf = fpayload.get("confidence", 0.0)
            factor_items.append((str(fname), int(fdir), float(fconf)))
        if not factor_items:
            continue
        # Sort by |confidence| descending, take top 3
        factor_items.sort(key=lambda x: abs(x[2]), reverse=True)
        label = _STRATEGY_CN_LABELS.get(strat_name, strat_name)
        print(f"  {label}:")
        for fname, fdir, fconf in factor_items[:3]:
            arrow = "↑" if fdir > 0 else "↓" if fdir < 0 else "—"
            color = Fore.GREEN if fdir > 0 else Fore.RED if fdir < 0 else Fore.YELLOW
            bar = _build_factor_bar(fconf)
            print(f"    {fname:20s} {color}{arrow} {fconf:5.2f}{Style.RESET_ALL}  {bar}")
            has_any_factor = True
    if not has_any_factor:
        print("  暂无因子明细数据")


def _print_recent_events_block(report_data: dict, match: dict) -> None:
    """Block B: Print recent 5-day key events from report or event_sentiment sub-factors."""
    from colorama import Fore, Style

    print(f"\n{Fore.CYAN}近期事件 (5 日):{Style.RESET_ALL}")

    # Priority 1: report-level recent_events field
    events = report_data.get("recent_events")
    if events and isinstance(events, list) and len(events) > 0:
        for evt in events[:5]:
            if isinstance(evt, dict):
                date_str = str(evt.get("date", evt.get("time", "")))
                desc = str(evt.get("description", evt.get("text", str(evt))))
                print(f"  {date_str}  {desc}")
            else:
                print(f"  {evt}")
        return

    # Priority 2: extract from event_sentiment strategy's sub-factors metrics
    signals = match.get("strategy_signals", {})
    event_sig = signals.get("event_sentiment")
    if event_sig and isinstance(event_sig, dict):
        sub_factors = event_sig.get("sub_factors")
        if isinstance(sub_factors, dict):
            articles = _extract_articles_from_event_subfactors(sub_factors)
            if articles:
                printed_any = False
                for art in articles[:5]:
                    date_str = str(art.get("days_old", "?"))
                    title = str(art.get("title", ""))
                    if title:
                        day_label = f"{int(date_str)}天前" if date_str.isdigit() else date_str
                        print(f'  {day_label}  新闻: "{title}"')
                        printed_any = True
                if printed_any:
                    return

    print("  暂无近期事件数据")


def _extract_articles_from_event_subfactors(sub_factors: dict) -> list[dict]:
    """Extract article metrics from news_sentiment sub-factor within event_sentiment."""
    news_sf = sub_factors.get("news_sentiment")
    if not isinstance(news_sf, dict):
        return []
    metrics = news_sf.get("metrics")
    if not isinstance(metrics, dict):
        return []
    articles = metrics.get("articles")
    if not isinstance(articles, list):
        return []
    return [a for a in articles if isinstance(a, dict)]


def _print_industry_ranking_block(recs: list[dict], match: dict) -> None:
    """Block C: Print industry ranking and percentile among same-industry recommendations."""
    from colorama import Fore, Style

    from src.utils.numeric import safe_float as _safe_float

    industry = match.get("industry_sw", "")
    ticker = match.get("ticker", "")

    if not industry:
        print(f"\n{Fore.CYAN}同行业排名:{Style.RESET_ALL} 无行业信息")
        return

    # Filter recommendations in the same industry, sort by score_b descending
    # GAMMA-008: coerce None / NaN score_b to 0.0 — .get() only substitutes
    # when the key is missing, not when the value is explicitly None or NaN.
    peers = [(r.get("ticker", ""), _safe_float(r.get("score_b"), 0.0)) for r in recs if r.get("industry_sw") == industry]
    if not peers:
        print(f"\n{Fore.CYAN}同行业排名:{Style.RESET_ALL} 无同行业数据")
        return

    peers_sorted = sorted(peers, key=lambda x: x[1], reverse=True)
    total = len(peers_sorted)

    # Find current ticker's rank
    rank = 1
    for idx, (t, _s) in enumerate(peers_sorted, 1):
        if t == ticker:
            rank = idx
            break

    percentile = rank / total if total > 0 else 1.0
    pct_label = f"前 {percentile:.0%}" if percentile <= 1.0 else "—"
    print(f"\n{Fore.CYAN}同行业排名:{Style.RESET_ALL} {industry} — 第 {rank}/{total} 名 ({pct_label})")
