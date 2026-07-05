"""P0-8 反事实解释: 为什么某只票**不在** Top 推荐中。

与 ``run_explain`` (--explain) 对称 — 后者解释「为什么被推荐」, 本模块解释
「为什么没被推荐」。四个区块:

1. 策略方向冲突 — Top N 中各策略的方向分布 vs 该票的预期方向
2. confidence 不足 — Top N 的 score_b 分布, 给出「需达到多少才能进 Top」
3. 排除规则 — 5 大排除规则 (ST/北交所/次新/涨停/低流动性) 的命中情况
4. 反事实模拟 — 至少覆盖 3 个策略 (trend / mean_reversion / fundamental /
   event_sentiment), 输出方向性提示 (例如 "再涨 5% trend 预估 +0.08 但
   mean_reversion 预估 -0.05, 净 +0.03 仍不足")

设计上**只读** ``data/reports/auto_screening_*.json``, 不重跑 pipeline,
不修改 strategy_scorer 的核心逻辑。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from colorama import Fore, Style

from src.screening.custom_weights import STRATEGY_KEYS as _STRATEGY_ORDER
from src.utils.numeric import safe_float

DEFAULT_REPORT_DIR = Path("data/reports")

_STRATEGY_CN_LABELS: dict[str, str] = {
    "trend": "趋势策略",
    "mean_reversion": "均值回归",
    "fundamental": "基本面",
    "event_sentiment": "事件情绪",
}

# ── A 股板块识别 ────────────────────────────────────────────────────────────
# 上交所主板: 600/601/603/605; 深交所主板: 000/001/002/003; 创业板: 300/301;
# 科创板: 688/689; 北交所: 8xxxxx, 4xxxxx (历史), 92xxxx
_BJ_PREFIX_RE = re.compile(r"^(8|4|92|43|83|87)\d{4}$")
_ST_NAME_KEYWORDS = ("ST", "*ST", "st", "*st")


def _is_bj_ticker(ticker: str) -> bool:
    """Heuristic: 判断 ticker 是否属于北交所。

    A 股 6 位数字代码; 北交所集中在 8xxxxx / 92xxxx, 历史上 4xxxxx 也有。
    该判断是「粗筛」 — 真实归属以 market = 'BJ' 为准, 但 auto_screening
    报告不包含 candidate_pool 字段, 只能用 ticker 前缀。
    """
    if not ticker or not ticker.isdigit() or len(ticker) != 6:
        return False
    return bool(_BJ_PREFIX_RE.match(ticker))


def _load_latest_report(reports_dir: Path) -> tuple[Path, dict[str, Any]] | None:
    """读取 reports_dir 下最新的 auto_screening_*.json; 不存在返回 None。"""
    if not reports_dir.exists():
        return None
    report_files = sorted(reports_dir.glob("auto_screening_*.json"), reverse=True)
    if not report_files:
        return None
    latest = report_files[0]
    try:
        with open(latest, encoding="utf-8") as f:
            return latest, json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _compute_top_score_stats(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """计算 Top N score_b 的统计指标。

    Return type is dict[str, Any] because ``min_rec`` is a rec dict (or None
    when recs is empty), not a float — the previous dict[str, float] annotation
    caused mypy attr-defined errors on the .get() calls in the caller.
    """
    if not recs:
        return {"min": 0.0, "median": 0.0, "max": 0.0, "min_rec": None}
    # R76 (R73 同族): score_b 在生产里通常是 float, 但部分推荐 (例如只进了
    # candidate_pool 但未完成 composite scoring 的标的) 在 JSON 里可能是 null。
    # 裸 float(r.get("score_b", 0.0)) 在 key 存在且为 null 时返回 None 抛 TypeError,
    # 一条残缺 rec 让整个 --why-not 4-区块解释器崩溃。改用 safe_float 与 --top /
    # --top-picks / --daily-brief 三条 sibling renderer 一致。
    scored = [(safe_float(r.get("score_b")), r) for r in recs]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    scores = [s for s, _ in scored]
    n = len(scores)
    median = scores[n // 2] if n % 2 == 1 else (scores[n // 2 - 1] + scores[n // 2]) / 2
    # R76: 末位 rec 必须按 score_b 升序定位, 而非 recs[-1] —— auto_screening_*.json
    # 里的 recs 顺序由 ranking 逻辑决定, 不保证按 score_b 升序, 直接取 recs[-1] 会
    # 把非末位票标成「末位票」, 与上一行「末位: <min> 门槛」自相矛盾。
    return {"min": scores[-1], "median": median, "max": scores[0], "min_rec": scored[-1][1]}


def _aggregate_strategy_directions(recs: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """统计 Top N 各策略的方向分布 (bullish / bearish / neutral 计数)。"""
    agg: dict[str, dict[str, int]] = {s: {"bullish": 0, "bearish": 0, "neutral": 0, "missing": 0} for s in _STRATEGY_ORDER}
    for rec in recs:
        signals = rec.get("strategy_signals") or {}
        for strat in _STRATEGY_ORDER:
            sig = signals.get(strat)
            if not sig or not isinstance(sig, dict):
                agg[strat]["missing"] += 1
                continue
            direction = sig.get("direction", 0)
            if direction > 0:
                agg[strat]["bullish"] += 1
            elif direction < 0:
                agg[strat]["bearish"] += 1
            else:
                agg[strat]["neutral"] += 1
    return agg


def _format_direction_block(strategy_agg: dict[str, dict[str, int]]) -> str:
    """格式化「策略方向冲突」区块。"""
    lines: list[str] = []
    lines.append(f"{Fore.CYAN}区块 1: 策略方向冲突{Style.RESET_ALL}")
    lines.append(f"  Top {sum(next(iter(strategy_agg.values())).values())} 中各策略方向分布 (↑ 看多 / ↓ 看空 / — 中性):")
    for strat in _STRATEGY_ORDER:
        label = _STRATEGY_CN_LABELS.get(strat, strat)
        counts = strategy_agg.get(strat, {})
        bullish = counts.get("bullish", 0)
        bearish = counts.get("bearish", 0)
        neutral = counts.get("neutral", 0)
        missing = counts.get("missing", 0)
        if missing == (bullish + bearish + neutral + missing) and missing > 0:
            lines.append(f"    {label:8s}  数据缺失 ({missing}/{missing})")
            continue
        lines.append(f"    {label:8s}  ↑ {bullish} 只  |  ↓ {bearish} 只  |  — {neutral} 只" + (f"  |  缺失 {missing}" if missing else ""))
    lines.append("")
    lines.append("  简化版判断: 该票不在 Top N 中, 可能:")
    lines.append("    a) 该票至少 1 个策略方向与上述主流方向相反 (冲突扣分)")
    lines.append("    b) 该票多策略综合 confidence 偏低, 未达阈值 (见区块 2)")
    lines.append("    c) 该票被排除规则过滤 (ST/北交所/次新/涨停/低流动性, 见区块 3)")
    lines.append("  注: 完整版需要对该票重跑 score_batch, 本版本仅给方向性提示")
    return "\n".join(lines)


def _format_confidence_block(recs: list[dict[str, Any]], top_n: int) -> str:
    """格式化「confidence 不足」区块。"""
    stats = _compute_top_score_stats(recs)
    cutoff = stats["min"]  # Top N 末位的 score_b
    lines: list[str] = []
    lines.append(f"{Fore.CYAN}区块 2: confidence 不足 (Score B 阈值){Style.RESET_ALL}")
    lines.append(f"  Top {len(recs)} score_b 分布:")
    lines.append(f"    Top 1:  {stats['max']:+.4f}")
    lines.append(f"    中位数: {stats['median']:+.4f}")
    lines.append(f"    末位:  {stats['min']:+.4f}  ← 进 Top {top_n} 的最低门槛")
    # R76: 末位票必须从 stats['min_rec'] 取 (按 score_b 升序定位), 而非 recs[-1]。
    min_rec = stats.get("min_rec")
    if min_rec:
        last_name = min_rec.get("name", min_rec.get("ticker", "末位"))
        last_ticker = min_rec.get("ticker", "")
        lines.append(f"    末位票: {last_ticker} {last_name}")
    lines.append("")
    lines.append(f"  要进入 Top {top_n}, 该票需 score_b ≥ {cutoff:+.4f}")
    lines.append(f"  假设该票 score_b = 0 (无信号), 距门槛差 {-cutoff:+.4f}")
    return "\n".join(lines)


def _format_exclusion_block(ticker: str) -> str:
    """格式化「排除规则」区块 (5 大规则)。"""
    lines: list[str] = []
    lines.append(f"{Fore.CYAN}区块 3: 排除规则检查{Style.RESET_ALL}")
    lines.append("  P0-8 简化版: 仅基于 ticker / 名称 粗筛, 不重跑数据。")
    lines.append("")

    # Rule 1: ST / *ST
    lines.append("  [1] ST / *ST 排除")
    lines.append("      仅能根据名称判断 (auto_screening_*.json 不含 name 字段时无法判定)")
    lines.append("      → 实际排除需在 --auto pipeline 中由 build_candidate_pool 完成")
    lines.append("")

    # Rule 2: 北交所
    lines.append("  [2] 北交所排除 (代码 8xxxxx / 92xxxx / 4xxxxx)")
    if _is_bj_ticker(ticker):
        lines.append(f"      {Fore.RED}命中:{Style.RESET_ALL} {ticker} 属于北交所代码前缀")
        lines.append("      → 该票在 build_candidate_pool() 阶段已被排除, 不会进入策略评分")
    else:
        lines.append(f"      {Fore.GREEN}未命中:{Style.RESET_ALL} {ticker} 不属于北交所代码前缀")
    lines.append("")

    # Rule 3: 次新 (60 交易日)
    lines.append("  [3] 次新股排除 (上市 < 60 交易日)")
    lines.append("      需要 IPO 日期 + 当前交易日数据, 纯 ticker 无法判断")
    lines.append("      → 实际排除由 build_candidate_pool() 阶段完成")
    lines.append("")

    # Rule 4: 涨停
    lines.append("  [4] 涨停排除 (当日涨停, 买入排队失败风险)")
    lines.append("      需要当日行情 (close ≥ 涨停价), 纯 ticker 无法判断")
    lines.append("      → 实际排除由 build_candidate_pool() 阶段完成")
    lines.append("")

    # Rule 5: 低流动性 (成交额 < 5000 万)
    lines.append("  [5] 低流动性排除 (近 N 日均成交额 < 5000 万)")
    lines.append("      需要历史成交额数据, 纯 ticker 无法判断")
    lines.append("      → 实际排除由 build_candidate_pool() 阶段完成")
    return "\n".join(lines)


def _format_counterfactual_block(ticker: str, recs: list[dict[str, Any]]) -> str:
    """格式化「反事实模拟」区块。

    必须覆盖至少 3 个策略 (验收标准)。由于无 per-ticker 重跑数据, 采用
    方向性提示: 对每个策略给出 "如果 X 变化, Y 评分方向" 的定性估计。

    Loop 92 (autodev): drained stale-hardcoded-numbers-in-display (loop 55-56
    _REGIME_ADVICE 同类疾病). 原 cf_lines hardcoded "+0.06 ~ +0.10" /
    "+0.04 ~ +0.07" / "+0.05 ~ +0.09" / "+0.07 ~ +0.12" 作为 per-ticker 估值呈现,
    原 disclaimer "本版本仅给趋势" 不准确 (实际覆盖 4 个策略).
    Fix: 移除具体 ±数字, 保留定性场景描述与方向提示, disclaimer 明确披露
    所有预估均为定性、未基于该票实际数据计算.
    """
    lines: list[str] = []
    lines.append(f"{Fore.CYAN}区块 4: 反事实模拟 (Counterfactual){Style.RESET_ALL}")
    lines.append(f"  假设 {ticker} 当前未达 Top {len(recs)} 门槛, 以下为方向性提示")
    lines.append("  (本区块为定性提示, 未基于该票实际数据计算; 完整反事实需重跑 score_batch)")
    lines.append("")

    # 对每个策略给出 1 行定性提示 (loop 92: 移除 hardcoded ±数字)
    cf_lines: list[tuple[str, str, str, str]] = [
        (
            "trend",
            "再涨 5% (close × 1.05)",
            "trend 评分方向 ↑ (具体幅度需重跑 score_batch)",
            "若 score_b 提升, 名次可前进 (具体名次变动需重跑)",
        ),
        (
            "mean_reversion",
            "再跌 3% (close × 0.97)",
            "mean_reversion 评分方向 ↑ (具体幅度需重跑)",
            "RSI 越接近超卖, 均值回归信号越强",
        ),
        (
            "fundamental",
            "财报超预期 (ROE +2pct)",
            "fundamental 评分方向 ↑ (具体幅度需重跑)",
            "需等到下个财报披露窗口, 短期难以触发",
        ),
        (
            "event_sentiment",
            "出现重大利好 (公告/重组/中标)",
            "event_sentiment 评分方向 ↑ (具体幅度需重跑)",
            "事件驱动评分波动较大, 单事件可决定是否进 Top",
        ),
    ]

    for strat, scenario, delta, hint in cf_lines:
        label = _STRATEGY_CN_LABELS.get(strat, strat)
        lines.append(f"  [{label}]")
        lines.append(f"    场景: {scenario}")
        lines.append(f"    预估: {delta}")
        lines.append(f"    提示: {hint}")
        lines.append("")

    lines.append("  综合提示: ")
    lines.append("    • 趋势/事件类信号短期可触发; 基本面/均值回归需更长窗口")
    lines.append("    • 若 4 策略同向 (全 ↑) 但仍被排除, 多为区块 3 的硬规则命中")
    lines.append("    • 完整反事实: 对该票单独跑 score_batch 即可, 详见 src/screening/strategy_scorer_*.py")
    return "\n".join(lines)


def _print_header(ticker: str, report_path: Path, top_n: int) -> None:
    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Why-Not] {ticker} 反事实解释 (P0-8){Style.RESET_ALL}")
    print(f"  报告: {report_path.name}  |  Top N: {top_n}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")


def _print_already_recommended(ticker: str, match: dict[str, Any]) -> None:
    name = match.get("name", "")
    # R76 (R73 同族): 见 _compute_top_score_stats 同款 null-score_b 守卫, 避免
    # ``{score_b:+.4f}`` 在 None 上抛 TypeError。
    score_b = safe_float(match.get("score_b"))
    decision = match.get("decision", "neutral")
    print(f"{Fore.GREEN}该票已被推荐, 请用 --explain {ticker} 查看推荐理由 (而非 --why-not){Style.RESET_ALL}")
    print(f"  当前状态: {decision}  |  Score B: {score_b:+.4f}  |  名称: {name}")


def _print_not_in_market(ticker: str, report_path: Path) -> None:
    print(f"{Fore.YELLOW}该票 {ticker} 不在扫描范围{Style.RESET_ALL}")
    print("  可能原因:")
    print("    • 港股 / 美股 (本系统仅扫描 A 股)")
    print("    • 已退市 / 停牌")
    print("    • ticker 拼写错误")
    print(f"  报告: {report_path.name}")


def run_why_not(
    ticker: str,
    *,
    reports_dir: Path | str | None = None,
) -> int:
    """反事实解释: 为什么 ticker 不在 Top 推荐中。

    Args:
        ticker: 6 位 A 股代码 (e.g. "000001")。
        reports_dir: 报告目录, 默认 ``data/reports``。测试时可注入 tmp_path。

    Returns:
        退出码, 0 = 成功, 1 = 失败 (无报告)。
    """
    if not ticker:
        print(f"{Fore.RED}--why-not 需要 ticker 参数{Style.RESET_ALL}")
        return 1

    target_dir = Path(reports_dir) if reports_dir is not None else DEFAULT_REPORT_DIR
    result = _load_latest_report(target_dir)
    if result is None:
        print(f"{Fore.RED}未找到 auto_screening_*.json 报告 in {target_dir}, 请先运行 --auto{Style.RESET_ALL}")
        return 1

    report_path, data = result
    recs = data.get("recommendations", []) or []
    top_n = int(data.get("top_n", len(recs) or 10))

    # State 1: 已在推荐中
    match = next((r for r in recs if r.get("ticker") == ticker), None)
    if match is not None:
        _print_header(ticker, report_path, top_n)
        _print_already_recommended(ticker, match)
        # R76: State 1 也带 decision label (当前状态: bullish/bearish), 同主路径补 disclaimer。
        _print_why_not_disclaimer()
        print()
        return 0

    # State 4 (简化): 全市场扫描未覆盖
    # 报告不含 candidate_pool 字段时, 退化为「该票不在 Top N, 直接进入 4 区块分析」
    # 仍走主路径 — 区块 3 的北交所/ST 粗筛可给出方向性提示
    has_pool_data = "candidate_pool" in data or "excluded_tickers" in data
    if has_pool_data:
        pool = set(data.get("candidate_pool") or [])
        excluded = data.get("excluded_tickers") or {}
        if ticker not in pool and ticker not in excluded:
            _print_header(ticker, report_path, top_n)
            _print_not_in_market(ticker, report_path)
            return 0
        if ticker in excluded:
            _print_header(ticker, report_path, top_n)
            print(f"{Fore.YELLOW}该票 {ticker} 被候选池排除规则过滤{Style.RESET_ALL}")
            reasons = excluded.get(ticker) if isinstance(excluded, dict) else None
            if reasons:
                print(f"  排除原因: {reasons}")
            else:
                print("  (具体排除原因需要数据回溯, 详见 --auto pipeline)")
            return 0
    # else: 走主路径 (4 区块)

    # State 2: 在候选池但被分数过滤 (主战场) — 输出 4 个区块
    _print_header(ticker, report_path, top_n)

    # 市场状态
    ms = data.get("market_state") or {}
    if ms:
        print(f"{Fore.CYAN}市场状态:{Style.RESET_ALL} {ms.get('state_type', '?')}  |  " f"仓位系数: {ms.get('position_scale', 1.0):.2f}  |  " f"regime: {ms.get('regime_gate_level', 'normal')}")
        print()

    # 区块 1: 策略方向冲突 (简化版 — 用 Top N 分布对比)
    strategy_agg = _aggregate_strategy_directions(recs)
    print(_format_direction_block(strategy_agg))
    print()

    # 区块 2: confidence 不足
    print(_format_confidence_block(recs, top_n))
    print()

    # 区块 3: 排除规则
    print(_format_exclusion_block(ticker))
    print()

    # 区块 4: 反事实模拟
    print(_format_counterfactual_block(ticker, recs))
    print()

    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}小结:{Style.RESET_ALL} {ticker} 未进 Top {top_n} 的最可能原因:")
    print(f"  1. Score B < {_compute_top_score_stats(recs)['min']:+.4f} (末位门槛)")
    print(f"  2. 至少 1 个策略方向与 Top {top_n} 主流方向冲突")
    print("  3. 详细反事实: 对该票单独跑 score_batch (src/screening/strategy_scorer_*.py)")
    print()
    # R76 (R71/R72/R73/R75 trust-calibration family): this surface emits a
    # per-ticker decision direction (主流方向冲突 / confidence 阈值 / 反事实 ±score)
    # plus the live "当前状态: bullish/bearish" label. Carry the same non-advice
    # disclaimer as --top-picks / --daily-brief / --position-check / --explain /
    # PDF / backtest so users do not read "末位门槛" / "反事实 +0.08" as a
    # deterministic instruction (serves product goal "更高确信" = confidence
    # includes honest boundary disclosure). 6th user-facing decision surface.
    _print_why_not_disclaimer()
    return 0


def _print_why_not_disclaimer() -> None:
    """R76: research-only disclaimer at the end of the why-not explanation.

    Mirrors the R71 ``--top-picks`` disclaimer (``top_picks._print_disclaimer``)
    wording so all six user-facing decision surfaces stay consistent.
    """
    print(f"  {Fore.WHITE}⚠ 以上反事实解释由 AI 模型自动生成, 仅供研究 / 学习用途, 不构成任何投资建议。" f"实际投资需结合个人风险承受能力与最新市场情况。{Style.RESET_ALL}")
