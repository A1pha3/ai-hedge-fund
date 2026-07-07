"""P0-7 盘前 5 分钟「今日 Top 3 决策卡」— CLI 命令 ``--daily-brief``。

设计目标:
- 不重跑 pipeline, 直接读取最新 ``auto_screening_*.json`` + 可选 ``tracking_history.json``
- 盘前 9:25 打开, 30 秒决定今日重点关注标的
- 输出格式稳定 (格式化 ASCII + colorama), 延迟 < 1s

入口:
- ``run_daily_brief() -> int`` — 由 ``src/cli/dispatcher.py`` 早期分发
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from colorama import Fore, Style

# BH-021 family: 降级路径此前无任何日志, 运维无法区分 "用户没配 watchlist" vs
# "watchlist 配置损坏 / import 失败"。debug 级别避免噪音。
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STRATEGY_LABELS_CN: dict[str, str] = {
    "trend": "趋势",
    "mean_reversion": "均值回归",
    "fundamental": "基本面",
    "event_sentiment": "事件情绪",
}

_TRACKING_HISTORY_FILENAME: str = "tracking_history.json"

_RANK_MEDALS: tuple[str, str, str] = ("🥇", "🥈", "🥉")

# Industry rotation 票数阈值 — Top 10 中某行业票数 >= 此数才显示 Top 1, 否则显示 "—"
_INDUSTRY_MIN_COUNT: int = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_report_dir() -> Path:
    """定位 ``data/reports`` 目录 (复用 ``consecutive_recommendation.resolve_report_dir``)。"""
    try:
        from src.screening.consecutive_recommendation import resolve_report_dir

        return resolve_report_dir()
    except Exception:  # pragma: no cover — 兜底, 不让 CLI 崩溃
        return Path("data/reports")


def _find_latest_report(report_dir: Path) -> Path | None:
    """返回 ``report_dir`` 下最新的 ``auto_screening_YYYYMMDD.json`` 路径。

    R86 (R54 同族): 文件名 stem 必须能解析为 ``%Y%m%d``。纯字母排序会把非数字
    开头的 malformed 文件名 (如 ``auto_screening_garbage.json``, 字母在 ASCII
    数字之后) 排到合法日期之前, 误选为"最新"导致 ``--daily-brief`` 渲染错误
    报告或 JSONDecodeError 崩溃。校验日期后再排序, 与 sibling
    ``data_quality_audit._find_latest_report`` (R54) 一致。
    """
    if not report_dir.exists():
        return None
    candidates = [path for path in report_dir.glob("auto_screening_*.json") if _parses_as_report_date(path.stem.replace("auto_screening_", ""))]
    candidates.sort(reverse=True)
    return candidates[0] if candidates else None


def _parses_as_report_date(date_str: str) -> bool:
    """R54 同族: 文件名 stem 必须能解析为 ``%Y%m%d`` 才算合法报告日期。"""
    try:
        datetime.strptime(date_str, "%Y%m%d")
        return True
    except ValueError:
        return False


def _load_report(report_path: Path) -> dict[str, Any]:
    """读取 ``auto_screening_*.json`` 报告, 失败时抛 ``ValueError``。"""
    with open(report_path, encoding="utf-8") as f:
        return json.load(f)


def _load_tracking_history(report_dir: Path) -> list[dict[str, Any]]:
    """读取 ``tracking_history.json``, 不存在时返回空列表 (优雅降级)。

    Delegates to :func:`src.screening.consecutive_recommendation.load_tracking_history`.
    """
    from src.screening.consecutive_recommendation import load_tracking_history

    return load_tracking_history(report_dir)


def _compute_consecutive_days_from_history(records: list[dict[str, Any]]) -> dict[str, int]:
    """从 ``tracking_history.json`` 计算每只 ticker 的连续推荐天数。

    连续推荐定义: ``recommended_date`` 排序去重, 从最新一天向前数连续
    **交易日**数 (跳过周六/周日, 与 R36 主路径 ``consecutive_recommendation``
    语义一致)。用于 fallback (报告中无 ``consecutive_days`` 字段) 或双重校验。

    R36/R45 同族修复: 此前用自然日 ``timedelta(days=1)`` 步进, 导致周五→周一
    (跨周末) 的连续推荐在 ``--daily-brief`` Top 3 排序键与「Top 3 必须含连续
    推荐 ≥2 日」门控中被误清零。复用 ``consecutive_recommendation._prev_trading_day``
    的交易日语义, 与主 streak 计算路径保持一致, 避免逻辑分裂。
    """
    from src.screening.consecutive_recommendation import _prev_trading_day

    by_ticker: dict[str, set[str]] = {}
    for rec in records:
        ticker = str(rec.get("ticker", "") or "").strip()
        date_str = str(rec.get("recommended_date", "") or "").strip()
        if not ticker or not date_str:
            continue
        cleaned = date_str.replace("-", "")
        if len(cleaned) != 8:
            continue
        by_ticker.setdefault(ticker, set()).add(cleaned)

    result: dict[str, int] = {}
    for ticker, dates_set in by_ticker.items():
        sorted_dates = sorted(dates_set, reverse=True)
        if not sorted_dates:
            continue
        try:
            latest = datetime.strptime(sorted_dates[0], "%Y%m%d")
        except ValueError:
            continue
        streak = 1
        cursor = latest
        for d in sorted_dates[1:]:
            try:
                next_dt = datetime.strptime(d, "%Y%m%d")
            except ValueError:
                continue
            # R36 交易日语义: cursor 的前一交易日 == next_dt 才算连续。
            # _prev_trading_day 步进一天后跳过周六/周日, 故 Fri→Mon 计为连续。
            if _prev_trading_day(cursor) == next_dt:
                streak += 1
                cursor = next_dt
            else:
                break
        result[ticker] = streak
    return result


def _format_brief_date(report_path: Path, payload: dict[str, Any]) -> str:
    """从报告 payload 的 ``date`` 字段或文件名提取 ``YYYY-MM-DD``。"""
    raw_date = str(payload.get("date", "") or "").strip()
    cleaned = raw_date.replace("-", "")
    if len(cleaned) == 8 and cleaned.isdigit():
        return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    stem = report_path.stem.replace("auto_screening_", "")
    if len(stem) == 8 and stem.isdigit():
        return f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
    return datetime.now().strftime("%Y-%m-%d")


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全 float 转换, NaN/None → default。"""
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result:  # NaN
        return default
    return result


def _safe_int(value: Any, default: int = 0) -> int:
    """安全 int 转换, None/garbage → default。"""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_consecutive_days(rec: dict[str, Any], history_lookup: dict[str, int]) -> int:
    """从 rec.consecutive_days 优先, 否则从 tracking_history 兜底。"""
    consec = _safe_int(rec.get("consecutive_days"), 0)
    if consec > 0:
        return consec
    ticker = str(rec.get("ticker", "") or "").strip()
    return history_lookup.get(ticker, 0)


def _strategy_arrow(direction: int) -> str:
    """Map a strategy direction to a directional arrow glyph."""
    return "↑" if direction > 0 else "↓" if direction < 0 else "—"


def _summarize_one_liner(rec: dict[str, Any], industry: str) -> str:
    """生成一句话原因: 取 strategy_signals 中 confidence 最高的 1-2 个方向相同的策略。

    规则:
      - 收集所有 strategy_signals, 按 |confidence| 降序
      - 取前 2 个方向相同的策略 (e.g. 都 direction=1): "趋势↑ + 均值回归↑ 共振, ..."
      - 若前 2 个方向不同 (1 个正 1 个负): "趋势↑ 但 均值回归↓ 谨慎, ..."
      - 都没数据: "策略数据缺失"
    """
    signals = rec.get("strategy_signals") or {}
    if not isinstance(signals, dict) or not signals:
        return "策略数据缺失"

    items: list[tuple[str, int, float]] = []
    for strat_name, payload in signals.items():
        if not isinstance(payload, dict):
            continue
        direction = _safe_int(payload.get("direction"), 0)
        confidence = _safe_float(payload.get("confidence"), 0.0)
        items.append((strat_name, direction, confidence))

    if not items:
        return "策略数据缺失"

    items.sort(key=lambda x: abs(x[2]), reverse=True)
    top = items[:2]
    if len(top) == 1:
        name, direction, conf = top[0]
        cn_label = _STRATEGY_LABELS_CN.get(name, name)
        return f"{cn_label}{_strategy_arrow(direction)} (conf {conf:.0f}) 主导, {industry}业 关注"

    a_name, a_dir, _ = top[0]
    b_name, b_dir, _ = top[1]
    a_label = _STRATEGY_LABELS_CN.get(a_name, a_name)
    b_label = _STRATEGY_LABELS_CN.get(b_name, b_name)

    if (a_dir > 0 and b_dir > 0) or (a_dir < 0 and b_dir < 0):
        return f"{a_label}{_strategy_arrow(a_dir)} + {b_label}{_strategy_arrow(b_dir)} 共振, {industry}业 momentum top"
    return f"{a_label}{_strategy_arrow(a_dir)} 但 {b_label}{_strategy_arrow(b_dir)} 谨慎, {industry}业 待观察"


def _select_top3(recs: list[dict[str, Any]], history_lookup: dict[str, int]) -> list[dict[str, Any]]:
    """Top 3 选择算法。

    排序键 (降序):
      - 主排序: score_b (含 +0.05/天 的连续推荐 bonus)
      - 同分时: consecutive_days 降序, 再 ticker 升序 (稳定)

    Top 3 必须包含至少 1 只「连续推荐 ≥2 日」(如有, 替换最末位)。
    """
    if not recs:
        return []

    scored: list[tuple[float, int, str, dict[str, Any]]] = []
    for rec in recs:
        ticker = str(rec.get("ticker", "") or "")
        score_b = _safe_float(rec.get("score_b"), 0.0)
        consec = _extract_consecutive_days(rec, history_lookup)
        adjusted = score_b + 0.05 * consec
        scored.append((adjusted, consec, ticker, rec))

    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))

    top3 = [item[3] for item in scored[:3]]

    # Top 3 必须包含至少 1 只「连续推荐 ≥2 日」
    has_consec = any(_extract_consecutive_days(r, history_lookup) >= 2 for r in top3)
    if not has_consec:
        consec_candidates = [item[3] for item in scored if _extract_consecutive_days(item[3], history_lookup) >= 2]
        if consec_candidates and len(top3) >= 3:
            # 替换最末位 (Top 3 中 score 最低的), 保留前 2 不变
            consec_candidates.sort(key=lambda r: -_safe_float(r.get("score_b"), 0.0))
            replacement = consec_candidates[0]
            # 避免重复
            top3_tickers = {r.get("ticker") for r in top3}
            if replacement.get("ticker") not in top3_tickers:
                top3 = top3[:2] + [replacement]

    return top3


def _compute_industry_rotation_top1(recs: list[dict[str, Any]], top_n: int = 10) -> tuple[str, int] | tuple[str, int]:
    """行业轮动 Top 1: 统计 Top ``top_n`` 中 industry_sw 出现次数最多的行业。

    并列时取 score_b 总和最高的行业。返回 (industry_name, count)。无行业数据返回 ("—", 0)。
    """
    if not recs:
        return ("—", 0)
    universe = recs[:top_n]
    by_industry: dict[str, list[float]] = {}
    for rec in universe:
        industry = str(rec.get("industry_sw", "") or "").strip()
        if not industry:
            continue
        score_b = _safe_float(rec.get("score_b"), 0.0)
        by_industry.setdefault(industry, []).append(score_b)

    if not by_industry:
        return ("—", 0)

    # 排序键: (-票数, -score_b总和)
    best_industry = max(
        by_industry.items(),
        key=lambda kv: (-len(kv[1]), -sum(kv[1])),
    )
    return (best_industry[0], len(best_industry[1]))


def _format_consec_badge(consec: int) -> str:
    """连续推荐天数的彩色徽章。"""
    if consec >= 3:
        return f"{Fore.GREEN}{Style.BRIGHT}{consec} 日 ⭐{Style.RESET_ALL}"
    if consec == 2:
        return f"{Fore.YELLOW}{consec} 日{Style.RESET_ALL}"
    if consec == 1:
        return f"{Fore.WHITE}{consec} 日{Style.RESET_ALL}"
    return f"{Fore.RED}—{Style.RESET_ALL}"


def _format_score_colored(score_b: float) -> str:
    """score_b 着色: >=0.35 绿, >=0 黄, <0 红。"""
    if score_b >= 0.35:
        return f"{Fore.GREEN}{score_b:+.2f}{Style.RESET_ALL}"
    if score_b >= 0.0:
        return f"{Fore.YELLOW}{score_b:+.2f}{Style.RESET_ALL}"
    return f"{Fore.RED}{score_b:+.2f}{Style.RESET_ALL}"


def _format_decision_colored(decision: str) -> str:
    """decision 着色: bullish 绿, bearish 红, 其他黄。"""
    d = (decision or "").lower()
    if d == "bullish":
        return f"{Fore.GREEN}{decision}{Style.RESET_ALL}"
    if d == "bearish":
        return f"{Fore.RED}{decision}{Style.RESET_ALL}"
    return f"{Fore.YELLOW}{decision or 'neutral'}{Style.RESET_ALL}"


def _print_daily_brief(
    *,
    payload: dict[str, Any],
    top3: list[dict[str, Any]],
    industry_top1: tuple[str, int],
    report_path: Path,
    has_tracking_history: bool,
) -> None:
    """打印格式化的决策卡 (单一 stdout 输出函数, 便于测试)。"""
    bar = "=" * 70
    brief_date = _format_brief_date(report_path, payload)
    market_state = payload.get("market_state") or {}

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{bar}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}📅 盘前决策卡 — {brief_date}  (报告: {report_path.name}){Style.RESET_ALL}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{bar}{Style.RESET_ALL}")

    state_type = str(market_state.get("state_type", "—") or "—")
    position_scale = _safe_float(market_state.get("position_scale"), 1.0)
    regime = str(market_state.get("regime_gate_level", "normal") or "normal")
    print(f"{Fore.CYAN}📊 市场状态:{Style.RESET_ALL} {state_type}  |  " f"{Fore.CYAN}仓位系数:{Style.RESET_ALL} {position_scale:.2f}  |  " f"{Fore.CYAN}regime:{Style.RESET_ALL} {regime}")

    if not top3:
        print(f"\n{Fore.YELLOW}⚠️  最新报告中无 Top 3 推荐{Style.RESET_ALL}\n")
        return

    print()
    from src.screening.investability import build_front_door_verdict

    # autodev-23 loop 126: top-level front-door verdict summary. The per-pick
    # `前门: AVOID ⚠` annotation (loop 102) is buried mid-line under the medal
    # + strong_buy + bullish one-liner, so the operator's first impression of
    # an AVOID-rated #1 is still "🥇 buy this". Summarize the front-door
    # verdict UPFRONT so the operator sees which picks the gate actually
    # endorses before reading the per-pick details. Same disease class as
    # C-GREEN-GRADE-AVOID-MISMATCH (visual hierarchy overwhelming the verdict).
    verdict_groups: dict[str, list[str]] = {"BUY": [], "HOLD": [], "AVOID": []}
    for rec in top3:
        v = build_front_door_verdict(rec, market_regime=regime)
        action = str(v.get("action", "AVOID"))
        ticker = str(rec.get("ticker", "—") or "—")
        verdict_groups.setdefault(action, []).append(ticker)
    buy_tickers = verdict_groups.get("BUY", [])
    avoid_tickers = verdict_groups.get("AVOID", [])
    hold_tickers = verdict_groups.get("HOLD", [])
    total = len(top3)
    # Prominent summary line: green BUY count first, red AVOID last so the
    # operator's eye catches the gate-rejected picks even when skimming.
    summary_parts = [f"{Fore.GREEN}前门 BUY {len(buy_tickers)}/{total}{Style.RESET_ALL}"]
    if hold_tickers:
        summary_parts.append(f"{Fore.YELLOW}HOLD {len(hold_tickers)}{Style.RESET_ALL}")
    if avoid_tickers:
        summary_parts.append(f"{Fore.RED}AVOID {len(avoid_tickers)}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}🎯 前门判决:{Style.RESET_ALL} " + "  |  ".join(summary_parts))
    if buy_tickers:
        print(f"  {Fore.GREEN}✓ BUY: {', '.join(buy_tickers)}{Style.RESET_ALL}")
    if avoid_tickers:
        print(f"  {Fore.RED}⚠ AVOID: {', '.join(avoid_tickers)} (前门门控拒绝, 谨慎对待){Style.RESET_ALL}")
    print()

    for idx, rec in enumerate(top3):
        medal = _RANK_MEDALS[idx] if idx < len(_RANK_MEDALS) else f"#{idx + 1}"
        ticker = str(rec.get("ticker", "—") or "—")
        name = str(rec.get("name", "") or "")
        industry = str(rec.get("industry_sw", "—") or "—")
        score_b = _safe_float(rec.get("score_b"), 0.0)
        decision = str(rec.get("decision", "neutral") or "neutral")
        consec = _extract_consecutive_days(rec, _load_history_lookup_cached.get("last") or {})

        # autodev-13 / loop 102: surface the front-door verdict alongside the
        # raw LLM decision. Empirical dogfood of report 20260703 found ALL 3
        # daily-brief top picks CONTRADICTED the --top-picks front-door verdict:
        # 688019/688766 daily-brief "strong_buy" but front-door AVOID (样本不足/
        # 动量转负/量价背离/winrate<50%); 002463 "watch" but front-door BUY. The
        # raw ``decision`` field is the pre-gate qualitative read; the front-door
        # verdict applies the BUY gate (composite ≥ 0.5 AND T+5/T+10 winrate
        # ≥ 0.55 AND mature sample ≥ 20 AND edge > 0). Without this disclosure
        # the operator's morning card says "strong_buy #1" for a pick the gate
        # rejects — directly causing wrong actions on a 赚钱工具. Additive
        # disclosure: raw decision retained; gated verdict + ⚠ appended. Same
        # disease class as C268 (composite-only → BUY-verdict) and the
        # opportunity-index fix.
        verdict = build_front_door_verdict(rec, market_regime=regime)
        action = str(verdict.get("action", "AVOID"))
        _raw_lower = decision.lower()
        _raw_buyish = any(k in _raw_lower for k in ("buy", "bull", "strong"))
        # Dangerous contradiction: raw says buy-ish but the gate did not clear
        # BUY (operator could act on the raw signal and be rejected by the gate).
        _contradiction = _raw_buyish and action != "BUY"
        verdict_marker = f" {Fore.RED}⚠{Style.RESET_ALL}" if _contradiction else ""
        verdict_str = f"{Fore.CYAN}前门:{Style.RESET_ALL} {action}{verdict_marker}"

        ticker_label = f"{ticker} {name}" if name else ticker
        score_str = _format_score_colored(score_b)
        decision_str = _format_decision_colored(decision)
        consec_str = _format_consec_badge(consec) if has_tracking_history or consec > 0 else "—"

        one_liner = _summarize_one_liner(rec, industry)

        print(f"  {medal} #{idx + 1}  {Fore.WHITE}{Style.BRIGHT}{ticker_label}{Style.RESET_ALL} ({industry})")
        print(f"       score_b: {score_str}  |  决策: {decision_str}  |  {verdict_str}  |  连续推荐: {consec_str}")
        print(f"       💡 一句话: {one_liner}")
        print(f"       👉 详情: uv run python src/main.py --explain {ticker}")
        print()

    industry_name, industry_count = industry_top1
    total_topn = min(len(payload.get("recommendations", [])), 10)
    if industry_count > 0 and total_topn > 0:
        industry_count_str = f"{industry_count}/{total_topn}"
    else:
        industry_count_str = "—"

    # autodev-28 loop 143: 跨 surface 选择逻辑差异披露. _select_top3 对 score_b
    # 加 +0.05/日 连续推荐 bonus 并保证 Top 3 含 ≥2 日连续标的, 可能产生与 --top
    # (纯 score_b 排序) 不同的 Top 3. 当差异存在时披露, 避免操作者困惑.
    raw_recs = payload.get("recommendations", []) or []
    raw_top3_tickers = [str(r.get("ticker", "")) for r in raw_recs[:3]]
    brief_top3_tickers = [str(r.get("ticker", "")) for r in top3]
    if raw_top3_tickers != brief_top3_tickers:
        promoted = [t for t in brief_top3_tickers if t not in raw_top3_tickers]
        demoted = [t for t in raw_top3_tickers if t not in brief_top3_tickers]
        parts = ["Top 3 按 score_b + 连续推荐加成 (+0.05/日) 排序"]
        if promoted:
            parts.append(f"连续推荐标的 {','.join(promoted)} 因加成上位" + (f" (替换 {','.join(demoted)})" if demoted else ""))
        print(f"📝 {Fore.CYAN}排序说明:{Style.RESET_ALL} " + "; ".join(parts))
        print(f"  (与 --top 纯 score_b 排序可能不同; 详情见 --explain <ticker>)")

    print(f"🏭 {Fore.CYAN}行业轮动 Top 1:{Style.RESET_ALL} {Fore.GREEN}{Style.BRIGHT}{industry_name}{Style.RESET_ALL} (今日推荐 {industry_count_str}/Top10)")
    print(f"{Fore.WHITE}{Style.BRIGHT}{bar}{Style.RESET_ALL}\n")


# Module-level cache for tracking_history lookup — populated by run_daily_brief,
# read by _print_daily_brief. Avoids re-reading the file inside the print loop.
_load_history_lookup_cached: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# P16-2: Watchlist health summary in daily brief
# ---------------------------------------------------------------------------


def _print_watchlist_health(report_dir: Path, all_recs: list[dict[str, Any]]) -> None:
    """Append a compact health summary for watchlist tickers to the daily brief.

    Uses score_b from the latest report as a quick health indicator.
    """
    try:
        from src.screening.watchlist import load_watchlist

        watchlist = load_watchlist()
    except Exception as exc:
        # BH-021 family: watchlist 健康块此前对任何错误 (配置损坏 / import 失败 /
        # JSON 解析错误) 静默 return, 运维无法知道关注池健康速览为何消失。
        logger.debug("daily_brief: watchlist 加载失败, 跳过关注池健康速览: %s", exc)
        return

    tickers = watchlist.get("tickers", [])
    if not tickers or not isinstance(tickers, list):
        return

    # Build a quick lookup from latest recommendations
    rec_map: dict[str, dict[str, Any]] = {}
    for rec in all_recs:
        t = str(rec.get("ticker", ""))
        if t:
            rec_map[t] = rec

    print(f"\n{Fore.CYAN}📋 关注池健康速览{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}{'─' * 50}{Style.RESET_ALL}")

    for ticker in tickers:
        rec = rec_map.get(ticker)
        if rec is None:
            print(f"  {Fore.YELLOW}{ticker:<8} — 不在最新推荐列表{Style.RESET_ALL}")
            continue
        score_b = float(rec.get("score_b", 0.0) or 0.0)
        name = str(rec.get("name", "") or ticker)[:10]
        if score_b >= 0.4:
            color = Fore.GREEN
            status = "健康"
        elif score_b >= 0.2:
            color = Fore.YELLOW
            status = "关注"
        else:
            color = Fore.RED
            status = "走弱"
        print(f"  {ticker:<8} {name:<10} score_b={color}{score_b:.3f}{Style.RESET_ALL}  {color}{status}{Style.RESET_ALL}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_daily_brief(report_dir: Path | None = None) -> int:
    """``--daily-brief`` 主入口 — 盘前 5 分钟决策卡。

    Args:
        report_dir: 可选覆盖 (测试用)。默认从 ``resolve_report_dir()`` 获取。

    Returns:
        退出码: 0 = 成功, 1 = 无报告 / 加载失败。
    """
    try:
        actual_dir = report_dir if report_dir is not None else _resolve_report_dir()
    except Exception as exc:  # pragma: no cover
        print(f"{Fore.RED}[DailyBrief] 无法定位 reports 目录: {exc}{Style.RESET_ALL}")
        return 1

    latest = _find_latest_report(actual_dir)
    if latest is None:
        print(f"{Fore.RED}[DailyBrief] 未找到 auto_screening_*.json 报告, 请先运行 --auto{Style.RESET_ALL}")
        return 1

    try:
        payload = _load_report(latest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"{Fore.RED}[DailyBrief] 读取报告失败 ({latest.name}): {exc}{Style.RESET_ALL}")
        return 1

    recs = payload.get("recommendations") or []
    if not isinstance(recs, list):
        recs = []

    # tracking_history (优雅降级: 不存在时跳过连续推荐字段)
    history_records = _load_tracking_history(actual_dir)
    history_lookup = _compute_consecutive_days_from_history(history_records)
    _load_history_lookup_cached["last"] = history_lookup
    has_tracking_history = bool(history_records)

    top3 = _select_top3(recs, history_lookup)
    industry_top1 = _compute_industry_rotation_top1(recs, top_n=10)

    _print_daily_brief(
        payload=payload,
        top3=top3,
        industry_top1=industry_top1,
        report_path=latest,
        has_tracking_history=has_tracking_history,
    )

    # P16-2: Show watchlist health summary if available
    _print_watchlist_health(actual_dir, recs)

    # R72 (R71 同族 gamma trust calibration): 盘前决策卡输出具体的 Top 3
    # ticker + score_b + BUY/HOLD/AVOID 决策标签, 与 --top-picks (R71)、PDF
    # exporter、backtest CLI 同属"可能被误读为投资指令的具体决策建议"。footer
    # disclaimer 与其余三个前门入口语义一致, 服务于产品目标 "更高确信"
    # (确信包含诚实的边界告知, 而非只展示确信的数字)。
    _print_brief_disclaimer()

    return 0


def _print_brief_disclaimer() -> None:
    """R72: research-only disclaimer at the end of the pre-market decision card.

    Mirrors the R71 ``--top-picks`` disclaimer (``top_picks._print_disclaimer``)
    so all four user-facing decision surfaces (--top-picks / --daily-brief /
    PDF export / backtest CLI) carry the same boundary disclosure.
    """
    print(f"{Fore.WHITE}⚠ 以上盘前决策卡由 AI 模型自动生成, 仅供研究 / 学习用途, 不构成任何投资建议。" f"实际投资需结合个人风险承受能力与最新市场情况。{Style.RESET_ALL}")


__all__ = ["run_daily_brief"]
