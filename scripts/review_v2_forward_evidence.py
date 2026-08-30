#!/usr/bin/env python
"""v2 台账新档 (2026-08-14 regime gate 接线后重置) 前向证据复查.

回答四个问题 (全部 read-only, 可随时重跑):

1. 前向成交 vs 冻结先验 — 新档已平仓交易的净收益 vs ``known_distributions``
   冻结分布: 按信号日聚类 bootstrap CI90 (n≥30 才出判定语, R10 纪律), 保守
   单侧衰减判定 (前向 CI 上界低于先验期望才立案, R77 Op1).
2. 被挡候选对照组 — panel (setup_output_panel.jsonl) 里被拦截候选的事后
   T+10 收益: gate/门禁到底挡掉了钱还是挡掉了亏损 (反事实).
3. ⭐双信号子集 — 同日也在 --auto Top-N 的成交/被挡票 vs 其余 (当前 CI 跨 0,
   样本累积后重估).
4. 台账健康 — NAV/回撤/持仓/待结算计划一览.

用法:
    .venv/bin/python scripts/review_v2_forward_evidence.py
    .venv/bin/python scripts/review_v2_forward_evidence.py --since 2026-08-14

样本不足 (平仓 < LOW_CONFIDENCE_N) 时各节显式声明, 不输出伪精确结论.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.screening.offensive.known_distributions import KNOWN_DISTRIBUTIONS  # noqa: E402
from scripts.winrate_payoff_decomposition import cluster_boot_ci_low  # noqa: E402

LOW_CONFIDENCE_N = 10  # 与 setup_performance.LOW_CONFIDENCE_N 同例: 小样本不驱动决策
DEFAULT_SINCE = "2026-08-14"  # 台账重置开新档日 (regime gate 语义起点)
# house 纪律 (R10/R15): n<30 只披露不判定 — 衰减判定语只在此样本量之上输出。
DECISION_MIN_N = 30


@dataclass(frozen=True)
class SliceStats:
    n: int
    winrate: float
    expected_return: float
    avg_gain: float
    avg_loss: float
    payoff: float | None

    @property
    def low_confidence(self) -> bool:
        return self.n < LOW_CONFIDENCE_N


def _slice_stats(returns: list[float]) -> SliceStats | None:
    """一组净收益 → 统计; 空返回 None (调用方显式声明样本缺失, 不编造)."""
    if not returns:
        return None
    gains = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    avg_gain = sum(gains) / len(gains) if gains else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    payoff = avg_gain / abs(avg_loss) if avg_loss else None
    return SliceStats(
        n=len(returns),
        winrate=len(gains) / len(returns),
        expected_return=sum(returns) / len(returns),
        avg_gain=avg_gain,
        avg_loss=avg_loss,
        payoff=payoff,
    )


def _fmt_slice(stats: SliceStats | None, *, indent: str = "  ") -> list[str]:
    if stats is None:
        return [f"{indent}（无样本）"]
    low = "  ⚠️ 样本不足（n<10，仅供参考，不驱动决策）" if stats.low_confidence else ""
    payoff_text = f"{stats.payoff:.2f}" if stats.payoff is not None else "—"
    return [
        f"{indent}n={stats.n} · 胜率 {stats.winrate:.1%} · 期望 {stats.expected_return:+.2%} · "
        f"盈亏比 {payoff_text}（盈 {stats.avg_gain:+.2%} / 亏 {stats.avg_loss:+.2%}）{low}"
    ]


def closed_trade_net_return(trade: sqlite3.Row) -> float:
    """单笔净收益口径: (卖出净回收 - 买入总成本) / 买入总成本 (含全部费用)."""
    entry_total = (
        trade["raw_entry_price"] * trade["quantity"]
        + trade["entry_commission"] + trade["entry_tax"] + trade["entry_slippage"]
    )
    exit_net = (
        trade["raw_exit_price"] * trade["quantity"]
        - trade["exit_commission"] - trade["exit_tax"] - trade["exit_slippage"]
    )
    return (exit_net - entry_total) / entry_total


def load_closed_trades(ledger_path: Path, since: str) -> list[sqlite3.Row]:
    """只读连接 (mode=ro) 取 since 起已平仓交易; 绝不写生产台账."""
    uri = f"file:{ledger_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM trades WHERE state='closed' AND signal_date >= ? "
            "ORDER BY signal_date, trade_id",
            (since,),
        ).fetchall()
    return rows


def load_ledger_health(ledger_path: Path) -> dict:
    uri = f"file:{ledger_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        latest = conn.execute(
            "SELECT * FROM daily_valuations ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        counts = conn.execute(
            "SELECT state, COUNT(*) AS n FROM trades GROUP BY state"
        ).fetchall()
    return {
        "latest_valuation": dict(latest) if latest else None,
        "state_counts": {row["state"]: row["n"] for row in counts},
    }


def load_panel_rows(panel_path: Path, since: str) -> list[dict]:
    if not panel_path.exists():
        return []
    since_compact = since.replace("-", "")
    rows: list[dict] = []
    for line in panel_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # 半截行不致命 — 报告标注覆盖数即可
        if str(row.get("signal_date") or "") >= since_compact:
            rows.append(row)
    return rows


def load_auto_topn_by_date(reports_dir: Path) -> dict[str, set[str]]:
    """信号日 → --auto Top-N ticker 集合 (与渲染层 ⭐双信号标记同口径)."""
    result: dict[str, set[str]] = {}
    for path in sorted(reports_dir.glob("auto_screening_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        tickers = {
            str(rec.get("ticker", "")).split(".")[0]
            for rec in payload.get("recommendations") or []
            if rec.get("ticker")
        }
        result[path.stem.replace("auto_screening_", "")] = tickers
    return result


def cluster_ci90(returns: list[float], days: list[str]) -> tuple[float, float] | None:
    """按信号日聚类 bootstrap CI90 (单一实现复用, per-call seeded — R13 纪律).

    下界来自 ``cluster_boot_ci_low``; 上界 = 对负值取下界再取负 (不复制
    bootstrap 实现)。信号日 <2 或样本 <2 时 None (调用方只披露不出 CI)。
    """
    if len(returns) < 2 or len(set(days)) < 2:
        return None
    low = cluster_boot_ci_low(returns, days)
    high = -cluster_boot_ci_low([-r for r in returns], days)
    return low, high


def _decay_verdict_lines(
    stats: SliceStats,
    returns: list[float],
    days: list[str],
    prior,
    *,
    indent: str = "    ",
) -> list[str]:
    """前向 vs 先验的判定面: 聚类 CI 披露 + 门槛化判定语。

    语义 (R77 Op1 对抗审查修复): 旧逻辑「点估计落在先验 CI 内」把紧先验 CI
    (n≈1464, ±1.8pp) 当作前向判据 — 前向样本增长全程中真实无衰减的 edge 因
    采样噪声频繁越出 → 假衰减告警, 真衰减也可长期容含 → 假安心。现改为保守
    单侧: 仅 n≥DECISION_MIN_N 且前向 CI90 上界 < 先验期望才立案; 点估计与
    先验 CI 的关系降级为纯披露。
    """
    lines = [
        f"{indent}先验（n={prior.n}）：胜率 {prior.winrate:.1%} · 期望 {prior.expected_return:+.2%}"
        f"（CI {prior.ci_low:+.2%}~{prior.ci_high:+.2%}）"
    ]
    ci = cluster_ci90(returns, days)
    if ci is None:
        lines.append(f"{indent}前向 CI90: 信号日/样本不足, 不出 CI（不判定）")
        return lines
    lo, hi = ci
    lines.append(f"{indent}前向 CI90（按信号日聚类）: {lo:+.2%}~{hi:+.2%}")
    if stats.n < DECISION_MIN_N:
        lines.append(
            f"{indent}→ n={stats.n} < {DECISION_MIN_N}: 按纪律只披露不判定"
            f"（衰减结论须 n≥{DECISION_MIN_N}）"
        )
    elif hi < prior.expected_return:
        lines.append(f"{indent}→ ⚠️ 前向 CI90 上界低于先验期望 — 立案复查 edge 衰减")
    elif lo > prior.expected_return:
        lines.append(f"{indent}→ 前向 CI90 下界高于先验期望 — 前向强于先验（信息行, 非判定）")
    else:
        lines.append(f"{indent}→ 前向 CI90 覆盖先验期望 — edge 未衰减")
    in_prior_ci = prior.ci_low <= stats.expected_return <= prior.ci_high
    lines.append(
        f"{indent}参考: 前向点估计{'在' if in_prior_ci else '越出'}先验 95% CI"
        f"（仅披露, 非判定）"
    )
    return lines


def build_report(
    closed_trades: list[sqlite3.Row],
    panel_rows: list[dict],
    auto_topn_by_date: dict[str, set[str]],
    ledger_health: dict,
    *,
    since: str,
) -> str:
    lines: list[str] = []
    lines.append(f"━━━ v2 台账新档前向证据复查（{since} 起）━━━")
    lines.append("")

    # ---- 1. 前向成交 vs 冻结先验 ----
    lines.append("一、前向成交 vs 冻结先验（edge 衰减监测）")
    if not closed_trades:
        lines.append("  （新档尚无已平仓交易 — T+10 退出合约下首批平仓约在 10 个交易日后出现）")
    by_setup: dict[str, tuple[list[float], list[str]]] = {}
    for trade in closed_trades:
        rets, days = by_setup.setdefault(trade["setup"], ([], []))
        rets.append(closed_trade_net_return(trade))
        days.append(str(trade["signal_date"]))
    for setup, (returns, days) in sorted(by_setup.items()):
        stats = _slice_stats(returns)
        lines.append(f"  {setup}（T+10 时间退出，含费用净口径）:")
        lines.extend(_fmt_slice(stats, indent="    "))
        prior = KNOWN_DISTRIBUTIONS.get((setup, 10))
        if prior is not None and stats is not None:
            lines.extend(_decay_verdict_lines(stats, returns, days, prior))
    lines.append("")

    # ---- 2. 被挡候选对照组 (反事实) ----
    lines.append("二、被挡候选对照组（panel, T+10 事后收益）")
    blocked = [
        row for row in panel_rows
        if row.get("block_reason") and row.get("realized") and row.get("return_t10") is not None
    ]
    taken = [
        row for row in panel_rows
        if not row.get("block_reason") and row.get("realized") and row.get("return_t10") is not None
    ]
    if not blocked and not taken:
        lines.append("  （panel 在复查窗口内无已实现样本）")
    else:
        lines.append("  被挡组（gate/门禁拦截，若放行会买这些）:")
        lines.extend(_fmt_slice(_slice_stats([float(r["return_t10"]) / 100.0 for r in blocked]), indent="    "))
        lines.append("  通过组（实际放行动量票）:")
        lines.extend(_fmt_slice(_slice_stats([float(r["return_t10"]) / 100.0 for r in taken]), indent="    "))
        regime_blocked = [r for r in blocked if "regime" in str(r["block_reason"])]
        if regime_blocked:
            lines.append("  其中 regime 闸拦截子集（危机/避险日反事实）:")
            lines.extend(_fmt_slice(_slice_stats([float(r["return_t10"]) / 100.0 for r in regime_blocked]), indent="    "))
    lines.append("")

    # ---- 3. ⭐双信号子集 ----
    lines.append("三、⭐双信号子集（同日也在 --auto Top-N）")

    def _is_converge(ticker: str, signal_date: str) -> bool:
        return ticker.split(".")[0] in auto_topn_by_date.get(str(signal_date).replace("-", ""), set())

    converge_returns = [
        closed_trade_net_return(t) for t in closed_trades if _is_converge(t["ticker"], t["signal_date"])
    ]
    plain_returns = [
        closed_trade_net_return(t) for t in closed_trades if not _is_converge(t["ticker"], t["signal_date"])
    ]
    if not closed_trades:
        lines.append("  （无已平仓交易）")
    else:
        lines.append("  双信号子集:")
        lines.extend(_fmt_slice(_slice_stats(converge_returns), indent="    "))
        lines.append("  其余成交:")
        lines.extend(_fmt_slice(_slice_stats(plain_returns), indent="    "))
        lines.append("  （注意：当前子集历史 CI[-7%,+28%] 跨 0 未达显著，本对比仅作累积监测）")
    lines.append("")

    # ---- 4. 台账健康 ----
    lines.append("四、台账健康")
    latest = ledger_health.get("latest_valuation")
    if latest:
        lines.append(
            f"  最新估值 {latest['trade_date']}：净值 {latest['nav']:,.0f} · "
            f"峰值 {latest['peak']:,.0f} · 回撤 {latest['drawdown']:+.1%}"
        )
    else:
        lines.append("  （无估值记录）")
    counts = ledger_health.get("state_counts") or {}
    if counts:
        lines.append("  交易状态分布：" + " · ".join(f"{state} {n}" for state, n in sorted(counts.items())))
    lines.append("")
    lines.append("复查判据：n≥30 且前向聚类 CI90 上界低于先验期望才立案复查 edge 衰减（R77 语义，"
                 "点估计 vs 先验 CI 仅披露）；被挡组期望显著为负 = 闸在赚钱；"
                 "双信号子集达到 n≥10 且方向一致后再考虑调整展示措辞。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="v2 台账新档前向证据复查 (read-only)")
    parser.add_argument("--ledger", default=str(REPO_ROOT / "data/paper_trading_v2/ledger.sqlite3"))
    parser.add_argument("--panel", default=str(REPO_ROOT / "data/reports/setup_output_panel.jsonl"))
    parser.add_argument("--reports-dir", default=str(REPO_ROOT / "data/reports"))
    parser.add_argument("--since", default=DEFAULT_SINCE, help="复查起点 (YYYY-MM-DD), 默认新档重置日")
    args = parser.parse_args()

    ledger_path = Path(args.ledger)
    if not ledger_path.exists():
        print(f"台账不存在: {ledger_path}")
        return 1

    report = build_report(
        load_closed_trades(ledger_path, args.since),
        load_panel_rows(Path(args.panel), args.since),
        load_auto_topn_by_date(Path(args.reports_dir)),
        load_ledger_health(ledger_path),
        since=args.since,
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
