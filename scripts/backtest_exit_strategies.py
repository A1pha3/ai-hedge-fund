"""Exit-strategy backtester — 用真实回测数据对比不同止损/退出策略的表现.

第一性原理验证: 在改 paper_tracker 的止损逻辑前, 必须先用 data/paper_trading_backtest
的历史成交 + data/price_cache 的 OHLCV 数据, 回测各种退出策略的 E[r]/winrate/
最大亏损/Sharpe, 确认优化方向有数据支持 (而不是拍脑袋).

本脚本是 `DAILY_ACTION_EXECUTION_STOP` 启用真实止损执行 (改变 P&L 口径) 的指定
前置证据工具 (AGENTS.md), 口径要求 (2026-08-18 autodev batch3 Round 1 重造):

1. **除权免疫 (trap 15)**: 价格帧先经 `_back_adjust_ohlcv` 回溯复权再模拟。
   price_cache 是不复权价 — 持有窗跨除权缺口时, raw low 的机械跳变会在幻影
   崩盘上触发止损 (10送10 → raw low -50%)。复权链不可证明 (pct_change 缺失/
   非有限) 的票**显式排除并计数** (`adjusted_fallback_raw`), 绝不静默用 raw。
2. **journal 源守卫**: 磁盘运行时 `data/paper_trading_backtest/journal.jsonl`
   自 2026-08-15 晚起是 2024 跨周期重放覆盖版 (trap, AGENTS.md 数据完整性节)。
   默认输入指向 2026 原版恢复副本; 检测到 2024 跨周期 journal 一律 exit 2
   fail-closed, 不产出被污染样本期的证据。
3. **缺口穿越止损的诚实成交**: 触发日 open 已低于止损价时按 open 成交 (跳空
   无法按止损价成交), 日内触及才按止损价成交 — 旧实现一律按止损价成交, 系统
   性高估止损策略的止损点收益。

相对比较口径保持不变 (与 2026-07-10 结论可比): 锚 = 个股帧 +N (frame+N, 停牌
顺延 — 所有策略共用同一锚, 不影响横向比较); 滑点 10bps/边 (legacy 相对比较
口径, 非 v2.1 执行成本口径); ATR 只用 entry 前窗口 (无未来函数)。

用法:
    uv run python scripts/backtest_exit_strategies.py [--journal PATH]

输出: 各策略的对比表 + 排除项计数 (stdout)。exit 2 = 输入证据不可信。
"""

from __future__ import annotations

import argparse
import json
import re
import statistics as st
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_REALIZED_RE = re.compile(r"realized=([+-]?\d+(?:\.\d+)?)%")
_SLIPPAGE = 0.001  # 10 bps (legacy 相对比较口径, 见模块 docstring)
_DEFAULT_JOURNAL = "outputs/journal_20260115_20260706_recovered.jsonl"
_DEFAULT_CACHE = "data/price_cache"
_REQUIRED_FRAME_COLUMNS = ("date", "open", "close", "high", "low")


def _fail_closed(message: str) -> "SystemExit":
    print(f"backtest_exit_strategies: {message}", file=sys.stderr)
    return SystemExit(2)


def _load_btst_trades(journal_path: Path) -> list[dict[str, Any]]:
    """从 backtest journal 加载 BTST BUY+EXIT 配对, 返回 (sigdate, ticker, horizon, orig_ret).

    fail-closed 守卫 (2026-08-18):
    - journal 缺失 → exit 2 (2026 原版恢复副本的恢复指引见报错);
    - ≥80% BTST 信号日落 2024 → 判定为 2024 跨周期重放覆盖版, exit 2。
    """
    if not journal_path.exists():
        if journal_path == (_PROJECT_ROOT / _DEFAULT_JOURNAL):
            raise _fail_closed(
                f"默认 journal 不存在: {journal_path}\n"
                "  2026 原版 (403 条) 已从 git 0be66383 恢复至 outputs/ — 检查文件是否被移动;\n"
                "  或显式 --journal 指向其它 jsonl。禁止默认回落到运行时 journal\n"
                "  (data/paper_trading_backtest/journal.jsonl 自 2026-08-15 起为 2024 重放覆盖版)。"
            )
        raise _fail_closed(f"journal 不存在: {journal_path}")
    records = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    realized_by_key: dict[tuple[str, str], float] = {}
    for rec in records:
        if rec.get("action") == "EXIT" and rec.get("setup") == "btst_breakout":
            m = _REALIZED_RE.search(str(rec.get("reasoning", "")))
            if m:
                realized_by_key[(str(rec["date"]), str(rec["ticker"]))] = float(m.group(1)) / 100.0
    trades: list[dict[str, Any]] = []
    for rec in records:
        if rec.get("action") != "BUY" or rec.get("setup") != "btst_breakout":
            continue
        key = (str(rec["date"]), str(rec["ticker"]))
        if key not in realized_by_key:
            continue
        trades.append(
            {
                "sigdate": str(rec["date"]),
                "ticker": str(rec["ticker"]),
                "horizon": int(rec.get("horizon", 10)),
                "orig_ret": realized_by_key[key],
            }
        )
    if trades:
        replay_2024 = sum(1 for t in trades if t["sigdate"].startswith("2024"))
        if replay_2024 / len(trades) >= 0.8:
            raise _fail_closed(
                f"拒绝 2024 跨周期重放覆盖版 journal: {replay_2024}/{len(trades)} BTST 信号日落 2024\n"
                "  ({journal_path})。2026-07-10 止损结论的样本是 2026 原版 journal;\n"
                "  运行时 journal 自 2026-08-15 起被 2024 重放覆盖 (AGENTS.md 数据完整性节)。\n"
                "  用 --journal outputs/journal_20260115_20260706_recovered.jsonl 指向 2026 原版恢复副本。".format(
                    journal_path=journal_path
                )
            )
    return trades


def _load_raw_frame(cache_dir: Path, ticker: str) -> pd.DataFrame | None:
    """读 price_cache 单票原始帧: date 归一 YYYYMMDD、升序、数值化、剔除坏行。

    不做复权 — 由调用方先 `is_pct_chain_valid` 证明复权链可用, 再交给
    `_back_adjust_ohlcv`; 链不可证明时显式排除, 不静默回退 raw。
    """
    path = cache_dir / f"{ticker}.csv"
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path, dtype={"date": str})
    except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return None
    if frame.empty or not set(_REQUIRED_FRAME_COLUMNS).issubset(frame.columns):
        return None
    frame = frame.copy()
    frame["date"] = frame["date"].str.replace("-", "", regex=False)
    frame = frame.sort_values("date").drop_duplicates(subset="date").reset_index(drop=True)
    for column in ("open", "close", "high", "low", "pct_change"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "close"])
    if frame.empty:
        return None
    return frame


def simulate_trade(
    frame: pd.DataFrame,
    sigdate: str,
    *,
    stop_mode: str = "none",  # "none" | "fixed_pct" | "atr"
    stop_param: float = 0.08,  # fixed: -0.08; atr: k=2.0
    time_exit: int = 10,
    slippage: float = _SLIPPAGE,
) -> dict[str, Any]:
    """单仓位退出模拟 (纯函数, 输入已复权帧)。

    返回 {"status": "ok", "ret", "stopped"} 或 {"status": "excluded", "reason"}:
    reason ∈ {no_sigdate_bar, window_truncated, entry_invalid}。
    排除项由聚合器计数, 绝不静默缩样本。
    """
    matches = frame.index[frame["date"] == sigdate]
    if len(matches) == 0:
        return {"status": "excluded", "reason": "no_sigdate_bar"}
    sig_idx = int(matches[0])
    entry_idx = sig_idx + 1
    exit_idx = sig_idx + time_exit
    if entry_idx >= len(frame) or exit_idx >= len(frame):
        return {"status": "excluded", "reason": "window_truncated"}
    entry_open = float(frame.iloc[entry_idx]["open"])
    if not entry_open > 0:
        return {"status": "excluded", "reason": "entry_invalid"}
    entry_price = entry_open * (1 + slippage)

    # 确定止损价 (ATR 只用 entry 前窗口, 无未来函数)
    stop_price: float | None = None
    if stop_mode == "fixed_pct":
        stop_price = entry_price * (1 + stop_param)  # stop_param 为负, 如 -0.08
    elif stop_mode == "atr":
        from src.screening.offensive.atr_utils import compute_atr

        pre_entry = frame.iloc[:entry_idx]
        atr = compute_atr(pre_entry, period=20)
        if atr is not None and atr > 0:
            stop_price = entry_price - stop_param * atr  # stop_param=k, 如 2.0

    realized_ret: float | None = None
    stopped = False
    if stop_price is not None:
        for i in range(entry_idx, exit_idx + 1):
            row = frame.iloc[i]
            low = float(row["low"]) if pd.notna(row["low"]) else 0.0
            if not low > 0 or low > stop_price:
                continue
            open_px = float(row["open"]) if pd.notna(row["open"]) else stop_price
            # 缺口穿越: open ≤ stop 时跳空无法按止损价成交, 诚实按 open 成交
            fill = open_px if open_px <= stop_price else stop_price
            realized_ret = (fill * (1 - slippage) / entry_price) - 1.0
            stopped = True
            break
    if realized_ret is None:
        exit_close = float(frame.iloc[exit_idx]["close"])
        realized_ret = (exit_close * (1 - slippage) / entry_price) - 1.0
    return {"status": "ok", "ret": realized_ret, "stopped": stopped}


_EXCLUDED_REASONS = ("no_sigdate_bar", "window_truncated", "entry_invalid")


def simulate_strategy(
    trades: list[dict[str, Any]],
    *,
    cache_dir: Path | str,
    stop_mode: str = "none",
    stop_param: float = 0.08,
    time_exit: int = 10,
) -> dict[str, Any]:
    """回测一种退出策略, 返回统计摘要 + 逐项排除计数 (样本侵蚀可观测)。"""
    from scripts.rebuild_journal_execution_returns import is_pct_chain_valid
    from src.screening.scoring_feature_store import _back_adjust_ohlcv

    cache_dir = Path(cache_dir)
    returns: list[float] = []
    stop_trig = 0
    excluded = {reason: 0 for reason in _EXCLUDED_REASONS}
    excluded["missing_price_cache"] = 0
    excluded["adjusted_fallback_raw"] = 0

    for trade in trades:
        raw = _load_raw_frame(cache_dir, trade["ticker"])
        if raw is None:
            excluded["missing_price_cache"] += 1
            continue
        if not is_pct_chain_valid(raw):
            excluded["adjusted_fallback_raw"] += 1
            continue
        frame = _back_adjust_ohlcv(raw)
        outcome = simulate_trade(
            frame,
            trade["sigdate"],
            stop_mode=stop_mode,
            stop_param=stop_param,
            time_exit=time_exit,
        )
        if outcome["status"] == "excluded":
            excluded[outcome["reason"]] += 1
            continue
        returns.append(outcome["ret"])
        if outcome["stopped"]:
            stop_trig += 1

    summary: dict[str, Any] = {
        "n": len(returns),
        "stop_trig": stop_trig,
        "excluded": excluded,
        "trades_loaded": len(trades),
    }
    if not returns:
        summary.update(
            {"E": 0.0, "winrate": 0.0, "median": 0.0, "max_loss": 0.0, "big_loss_pct": 0.0, "sharpe": 0.0}
        )
        return summary
    wins = [r for r in returns if r > 0]
    big_losses = [r for r in returns if r < -0.10]
    # Sharpe-like: mean / std (年化系数忽略, 仅比较相对)
    sharpe = st.mean(returns) / st.stdev(returns) if len(returns) > 1 and st.stdev(returns) > 0 else 0.0
    summary.update(
        {
            "E": st.mean(returns),
            "winrate": len(wins) / len(returns),
            "median": st.median(returns),
            "max_loss": min(returns),
            "big_loss_pct": len(big_losses) / len(returns),
            "sharpe": sharpe,
        }
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--journal",
        default=_DEFAULT_JOURNAL,
        help=f"journal jsonl (默认 2026 原版恢复副本; 运行时 journal 为 2024 重放覆盖版, 被守卫拒绝)",
    )
    parser.add_argument("--cache-dir", default=_DEFAULT_CACHE, help="price_cache 目录")
    parser.add_argument("--time-exit", type=int, default=10, help="时间退出 horizon (交易日)")
    args = parser.parse_args()

    journal_path = Path(args.journal)
    if not journal_path.is_absolute():
        journal_path = _PROJECT_ROOT / journal_path
    trades = _load_btst_trades(journal_path)
    print(
        f"=== Exit-Strategy Backtest (BTST, {len(trades)} trades) ===\n"
        f"journal: {journal_path}\n"
        "口径: _back_adjust_ohlcv 回溯复权 (trap 15 除权免疫) · 缺口穿越止损按 open 成交\n"
        "     · 锚=个股帧+N (各策略共用) · 滑点 10bps/边 (legacy 相对比较口径)\n"
    )

    strategies = [
        ("no_stop (T+10 收盘)", {"stop_mode": "none"}),
        ("fixed -5%", {"stop_mode": "fixed_pct", "stop_param": -0.05}),
        ("fixed -8% (当前硬止损)", {"stop_mode": "fixed_pct", "stop_param": -0.08}),
        ("fixed -12%", {"stop_mode": "fixed_pct", "stop_param": -0.12}),
        ("fixed -15%", {"stop_mode": "fixed_pct", "stop_param": -0.15}),
        ("ATR 1.5x", {"stop_mode": "atr", "stop_param": 1.5}),
        ("ATR 2.0x", {"stop_mode": "atr", "stop_param": 2.0}),
        ("ATR 2.5x", {"stop_mode": "atr", "stop_param": 2.5}),
        ("ATR 3.0x", {"stop_mode": "atr", "stop_param": 3.0}),
    ]

    header = f"{'strategy':<28} {'n':>3} {'E[r]':>8} {'win':>5} {'median':>8} {'maxloss':>8} {'big>10%':>7} {'sharpe':>7} {'stops':>5}"
    print(header)
    print("-" * len(header))
    baseline_excluded: dict[str, int] | None = None
    for label, kwargs in strategies:
        r = simulate_strategy(trades, cache_dir=args.cache_dir, time_exit=args.time_exit, **kwargs)
        if baseline_excluded is None:
            baseline_excluded = r["excluded"]
        if r["n"] == 0:
            print(f"{label:<28} n=0 (no data)")
            continue
        print(
            f"{label:<28} {r['n']:>3} {r['E']*100:>+7.2f}% {r['winrate']*100:>4.0f}% "
            f"{r['median']*100:>+7.2f}% {r['max_loss']*100:>+7.2f}% "
            f"{r['big_loss_pct']*100:>6.0f}% {r['sharpe']:>7.2f} {r['stop_trig']:>5}"
        )

    if baseline_excluded is not None and sum(baseline_excluded.values()) > 0:
        print(f"\n排除项 (no_stop 基准): {json.dumps(baseline_excluded, ensure_ascii=False)}")

    print("\n=== 关键对比 (决策依据) ===")
    no_stop = simulate_strategy(trades, cache_dir=args.cache_dir, time_exit=args.time_exit, stop_mode="none")
    fixed_8 = simulate_strategy(trades, cache_dir=args.cache_dir, time_exit=args.time_exit, stop_mode="fixed_pct", stop_param=-0.08)
    atr_2 = simulate_strategy(trades, cache_dir=args.cache_dir, time_exit=args.time_exit, stop_mode="atr", stop_param=2.0)
    atr_3 = simulate_strategy(trades, cache_dir=args.cache_dir, time_exit=args.time_exit, stop_mode="atr", stop_param=3.0)
    for label, r in (
        ("no_stop", no_stop),
        ("fixed -8%", fixed_8),
        ("ATR 2.0x", atr_2),
        ("ATR 3.0x", atr_3),
    ):
        print(
            f"  {label:<10} E={r['E']*100:+.2f}%  max_loss={r['max_loss']*100:+.2f}%  "
            f"big>10%={r['big_loss_pct']*100:.0f}%  sharpe={r['sharpe']:.2f}  n={r['n']}"
        )
    print()
    best_e = max(no_stop["E"], fixed_8["E"], atr_2["E"], atr_3["E"])
    best_sharpe = max(no_stop["sharpe"], fixed_8["sharpe"], atr_2["sharpe"], atr_3["sharpe"])
    print(f"  最高 E[r]: {best_e*100:+.2f}%  |  最高 Sharpe: {best_sharpe:.2f}")
    print("  (若 ATR 止损的 E[r] 或 Sharpe 优于 no_stop, 则值得集成到 paper_tracker)")
    print("  ⚠️ 相对比较工具: 启用真实止损执行 (DAILY_ACTION_EXECUTION_STOP) 前先看排除项计数,")
    print("     排除占比过高时本表证据不可用。")


if __name__ == "__main__":
    main()
