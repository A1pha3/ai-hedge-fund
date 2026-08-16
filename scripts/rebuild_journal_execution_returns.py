"""T+1/T+N 执行合约重放 — 2026 journal 的第三列数字 (executable)。

背景 (AGENTS.md 2026 实测表现): journal recorded P&L 受锚定 bug 污染
(2026-07-18 三方复现), 修正后只有 T0 收盘/零成本口径; **目标执行口径
(T0 决策 → T+1 开盘买 → T+N 开盘卖, 真实成本) 的准确结果始终缺失** —
"双边成本必然拖累收益, 但 T+1 开盘相对 T0 收盘的 gap 可正可负, 不能
断言只会更低"。本脚本补上这一列。

重建口径 (2026-08-16 冻结):
- E = 信号日 + 1 个交易日 (T+1 开盘买); X = 信号日 + horizon 个交易日
  (T+10/T+5 开盘卖)。journal 的 EXIT.date 与 BUY.date 相同 (回测两端都
  记在信号日), 到期日只能从交易日历机械推导。
- 交易日历 = regime_history.json 的键 (2020–2026 全覆盖, --auto 逐日追加)。
- 价格 = price_cache + `_back_adjust_ohlcv` 回溯复权 (trap 15 除权免疫);
  open-to-open 收益在复权帧上计算, 一字判定也在复权帧上做 — 复权后的
  trigger_close 恰为交易所除权锚定的前收, 与 v2 ledger limit 推导同思路。
- 成本 = 30bps/边滑点 + 5bps 卖出印花税 (v2.1 执行成本口径), 乘法:
  net = (1+gross) × (1−0.0030) × (1−0.0035) − 1 ≈ gross − 0.65%。
- 排除项确定性命名并计数 (一字买不进/停牌/缺 bar/日历缺失), 绝不
  stale-close; 同一 pass 顺带复算 corrected-T0 (own-anchor 收盘对收盘)
  并与 2026-07-18 修正产物交叉验证 (plumbing 自检)。

证据边界: 这是 RESEARCH_RECONSTRUCTION 研究重建 — 不构成 edge 授权、
regime 加仓证据或任何交易权限; journal 原文件未改动 (2026 原版已从
git 0be66383 恢复至 outputs/journal_20260115_20260706_recovered.jsonl)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.screening.offensive.execution_adjuster import is_limit_up_unbuyable_next_day  # noqa: E402
from src.screening.scoring_feature_store import _back_adjust_ohlcv  # noqa: E402

# 展示/统计单位: 百分比 (与 tracking_history 一致)
_REALIZED_RE = re.compile(r"realized=([+-]?[\d.]+)%")


@dataclass(frozen=True)
class ReplayConfig:
    slippage_bps_entry: int = 30
    slippage_bps_exit: int = 30
    stamp_duty_bps_sell: int = 5


@dataclass(frozen=True)
class Position:
    ticker: str
    setup: str
    horizon: int
    signal_date: str
    regime: str
    recorded_pct: float | None = None  # journal reasoning 里的 recorded realized (锚定 bug 污染, 仅对照)


@dataclass(frozen=True)
class ReplayOutcome:
    position: Position
    status: str  # 'filled' | 'excluded'
    reason: str | None
    entry_date: str | None
    exit_date: str | None
    gross_return_pct: float | None  # open-to-open, 除权免疫, 无成本
    net_return_pct: float | None  # 扣 30bps/边 + 5bps 卖出印花税
    corrected_t0_pct: float | None  # own-anchor T0 收盘→T+N 收盘, 零成本 (对照列)
    note: str | None = None


def _normalize_date(value: Any) -> str:
    return str(value or "").replace("-", "")[:8]


def pair_positions(
    records: Sequence[Mapping[str, Any]],
    regime_by_date: Mapping[str, str],
) -> tuple[list[Position], list[Mapping[str, Any]]]:
    """BUY/EXIT 按 (ticker, setup) FIFO 配对 (回测逐票顺序开平)。

    EXIT.date == BUY.date (两端都记在信号日), 配对只看顺序; regime 取信号日
    的 regime_history 值, 缺失映射 'unknown' (不编造)。
    """
    pending: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    exits: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for rec in records:
        key = (str(rec.get("ticker", "")), str(rec.get("setup", "")))
        if rec.get("action") == "BUY":
            pending[key].append(rec)
        elif rec.get("action") == "EXIT":
            exits[key].append(rec)

    positions: list[Position] = []
    unpaired: list[Mapping[str, Any]] = []
    for key in set(pending) | set(exits):
        buys = pending[key]
        exs = exits[key]
        for i in range(max(len(buys), len(exs))):
            if i < len(buys) and i < len(exs):
                buy = buys[i]
                signal_date = _normalize_date(buy.get("date"))
                recorded = None
                if (m := _REALIZED_RE.search(str(exs[i].get("reasoning", "")))) :
                    try:
                        recorded = float(m.group(1))
                    except ValueError:
                        recorded = None
                positions.append(
                    Position(
                        ticker=str(buy.get("ticker", "")),
                        setup=str(buy.get("setup", "")),
                        horizon=int(buy.get("horizon") or 0),
                        signal_date=signal_date,
                        regime=str(regime_by_date.get(signal_date) or "unknown"),
                        recorded_pct=recorded,
                    )
                )
            elif i < len(buys):
                unpaired.append(buys[i])
            else:
                unpaired.append(exs[i])
    positions.sort(key=lambda p: (p.signal_date, p.ticker))
    return positions, unpaired


def load_adjusted_frame(cache_dir: Path, ticker: str) -> pd.DataFrame | None:
    """读 price_cache 单票帧 → 规范化 → `_back_adjust_ohlcv` 回溯复权。

    返回 date 列为 YYYYMMDD 字符串、按日期升序的帧; 缺文件/缺列/空帧 → None。
    """
    path = Path(cache_dir) / f"{str(ticker)[:6]}.csv"
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path, dtype={"date": str})
    except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return None
    required = {"date", "open", "close", "high", "low", "pct_change"}
    if frame.empty or not required.issubset(frame.columns):
        return None
    frame = frame.copy()
    frame["date"] = frame["date"].map(_normalize_date)
    frame = frame.sort_values("date").drop_duplicates(subset="date").reset_index(drop=True)
    for column in ("open", "close", "high", "low", "pct_change"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "close"])
    if frame.empty:
        return None
    return _back_adjust_ohlcv(frame).reset_index(drop=True)


def replay_position(
    frame: pd.DataFrame | None,
    calendar: Sequence[str],
    position: Position,
    config: ReplayConfig,
) -> ReplayOutcome:
    """单仓位执行合约重放 — 全部排除路径确定性命名, 绝不 stale-close。"""

    def _excluded(reason: str) -> ReplayOutcome:
        return ReplayOutcome(position, "excluded", reason, None, None, None, None, None)

    if frame is None:
        return _excluded("missing_cache")
    cal_idx = {d: i for i, d in enumerate(calendar)}
    sig_i = cal_idx.get(position.signal_date)
    if sig_i is None:
        return _excluded("no_signal_calendar_day")
    e_i = sig_i + 1  # T+1 开盘买
    x_i = sig_i + int(position.horizon)  # T+N 开盘卖 (从 T0 起数)
    if e_i >= len(calendar):
        return _excluded("no_entry_day")
    if x_i >= len(calendar):
        return _excluded("no_exit_day")
    entry_date = calendar[e_i]
    exit_date = calendar[x_i]

    date_idx = {str(d): i for i, d in enumerate(frame["date"])}
    sig_row = date_idx.get(position.signal_date)
    if sig_row is None:
        return _excluded("no_signal_day_bar")  # 无法验证触发日/可买性, 保守排除
    e_row = date_idx.get(entry_date)
    if e_row is None:
        return _excluded("suspended_or_missing_entry_bar")
    x_row = date_idx.get(exit_date)
    if x_row is None:
        return _excluded("suspended_or_missing_exit_bar")

    # 一字买不进: 触发日涨停 + 次日开盘续涨停 (板块自适应阈值; 复权帧上
    # trigger_close 即交易所除权锚定前收)。复权帧行序 == 日历序 (缺 bar 已排除)。
    if is_limit_up_unbuyable_next_day(frame, sig_row, position.ticker):
        return _excluded("entry_unbuyable_limit_up")

    entry_open = float(frame.iloc[e_row]["open"])
    exit_open = float(frame.iloc[x_row]["open"])
    if entry_open <= 0 or exit_open <= 0:
        return _excluded("nonpositive_price")
    gross = (exit_open / entry_open - 1.0) * 100.0
    entry_factor = 1.0 - config.slippage_bps_entry / 10_000.0
    exit_factor = 1.0 - (config.slippage_bps_exit + config.stamp_duty_bps_sell) / 10_000.0
    net = ((1.0 + gross / 100.0) * entry_factor * exit_factor - 1.0) * 100.0

    # 对照列: own-anchor T0 收盘 → T+N 收盘, 零成本 (2026-07-18 修正口径)
    corrected_t0: float | None = None
    sig_close = float(frame.iloc[sig_row]["close"])
    if x_row is not None and sig_close > 0:
        corrected_t0 = (float(frame.iloc[x_row]["close"]) / sig_close - 1.0) * 100.0

    return ReplayOutcome(
        position=position,
        status="filled",
        reason=None,
        entry_date=entry_date,
        exit_date=exit_date,
        gross_return_pct=gross,
        net_return_pct=net,
        corrected_t0_pct=corrected_t0,
    )


def aggregate(outcomes: Sequence[ReplayOutcome]) -> dict[str, dict[str, Any]]:
    """按 setup/regime + setup/ALL 聚合: 三列均值/胜率 + 排除计数。"""
    groups: dict[str, list[ReplayOutcome]] = defaultdict(list)
    for out in outcomes:
        setup = out.position.setup
        groups[f"{setup}/{out.position.regime}"].append(out)
        groups[f"{setup}/ALL"].append(out)

    stats: dict[str, dict[str, Any]] = {}
    for key in sorted(groups):
        filled = [o for o in groups[key] if o.status == "filled" and o.net_return_pct is not None]
        nets = [o.net_return_pct for o in filled]
        entry: dict[str, Any] = {
            "n_filled": len(filled),
            "excluded": dict(
                sorted(
                    {
                        r: sum(1 for o in groups[key] if o.reason == r)
                        for r in {o.reason for o in groups[key] if o.reason}
                    }.items()
                )
            ),
        }
        if nets:
            entry["net_mean"] = statistics.fmean(nets)
            entry["net_median"] = statistics.median(nets)
            entry["net_win_rate"] = sum(1 for v in nets if v > 0) / len(nets)
            grosses = [o.gross_return_pct for o in filled if o.gross_return_pct is not None]
            if grosses:
                entry["gross_mean"] = statistics.fmean(grosses)
            t0s = [o.corrected_t0_pct for o in filled if o.corrected_t0_pct is not None]
            if t0s:
                entry["corrected_t0_mean"] = statistics.fmean(t0s)
                entry["corrected_t0_win_rate"] = sum(1 for v in t0s if v > 0) / len(t0s)
            recs = [o.position.recorded_pct for o in filled if o.position.recorded_pct is not None]
            if recs:
                entry["recorded_mean"] = statistics.fmean(recs)
                entry["recorded_win_rate"] = sum(1 for v in recs if v > 0) / len(recs)
        stats[key] = entry
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fmt_pct(value: Any) -> str:
    return f"{value:+.2f}%" if isinstance(value, (int, float)) else "—"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--journal",
        default="outputs/journal_20260115_20260706_recovered.jsonl",
        help="journal jsonl (2026 原版已从 git 0be66383 恢复至 outputs/)",
    )
    parser.add_argument("--regime-history", default="data/reports/regime_history.json")
    parser.add_argument("--price-cache", default="data/price_cache")
    parser.add_argument(
        "--corrected-artifact",
        default="outputs/journal_corrected_stats_20260718.json",
        help="2026-07-18 修正产物, 用于 corrected-T0 列交叉验证",
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    journal_path = Path(args.journal)
    regime_path = Path(args.regime_history)
    cache_dir = Path(args.price_cache)
    if not journal_path.is_absolute():
        journal_path = root / journal_path
    if not regime_path.is_absolute():
        regime_path = root / regime_path
    if not cache_dir.is_absolute():
        cache_dir = root / cache_dir

    records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    regime_by_date = json.loads(regime_path.read_text(encoding="utf-8"))
    calendar = sorted(str(k) for k in regime_by_date)

    positions, unpaired = pair_positions(records, regime_by_date)
    config = ReplayConfig()

    frame_cache: dict[str, pd.DataFrame | None] = {}
    outcomes: list[ReplayOutcome] = []
    for pos in positions:
        if pos.ticker not in frame_cache:
            frame_cache[pos.ticker] = load_adjusted_frame(cache_dir, pos.ticker)
        outcomes.append(replay_position(frame_cache[pos.ticker], calendar, pos, config))

    stats = aggregate(outcomes)

    # corrected-T0 交叉验证 (plumbing 自检): 与 2026-07-18 产物逐组对比
    cross_check: dict[str, dict[str, float]] = {}
    corrected_path = Path(args.corrected_artifact)
    if not corrected_path.is_absolute():
        corrected_path = root / corrected_path
    if corrected_path.exists():
        artifact = json.loads(corrected_path.read_text(encoding="utf-8"))
        # artifact 键前缀是 btst/ob, 本脚本 setup 是 btst_breakout/oversold_bounce
        setup_prefix = {"btst_breakout": "btst", "oversold_bounce": "ob"}
        for art_key, art_vals in (artifact.get("by_group") or {}).items():
            prefix, regime = art_key.split("/", 1)
            setup = next((s for s, p in setup_prefix.items() if p == prefix), None)
            if setup is None:
                continue
            mine = stats.get(f"{setup}/{regime}", {})
            my_t0 = mine.get("corrected_t0_mean")
            if my_t0 is not None:
                cross_check[art_key] = {
                    "mine_corrected_t0_mean": round(my_t0, 2),
                    "artifact_corrected_mean": float(art_vals.get("corrected_mean")),
                    "delta": round(my_t0 - float(art_vals.get("corrected_mean")), 2),
                }

    n_filled = sum(1 for o in outcomes if o.status == "filled")
    excluded_total = sum(1 for o in outcomes if o.status == "excluded")
    out_path = (
        Path(args.out)
        if args.out
        else root / f"outputs/journal_execution_stats_{date.today():%Y%m%d}.json"
    )
    payload = {
        "generated_at": f"{date.today():%Y-%m-%d}",
        "methodology": {
            "contract": "T0 决策 → T+1 开盘买 → 信号日+horizon 个交易日开盘卖 (T+10/T+5, 从 T0 起数)",
            "costs": "30bps/边滑点 + 5bps 卖出印花税, 乘法口径 ≈ -0.65% 往返",
            "adjustment": "price_cache + _back_adjust_ohlcv pct_change 链回溯复权 (trap 15 除权免疫); 一字判定同帧",
            "calendar": f"regime_history.json 键 ({calendar[0]}→{calendar[-1]}, n={len(calendar)})",
            "exclusion_policy": "一字买不进/停牌/缺 bar/日历缺失逐项计数, 绝不 stale-close",
            "evidence_boundary": "RESEARCH_RECONSTRUCTION 研究重建, 不构成 edge/regime 授权或交易权限",
        },
        "inputs": {
            "journal": str(journal_path) + f" (sha256={_sha256(journal_path)[:16]}…)",
            "records": len(records),
            "positions_paired": len(positions),
            "unpaired": len(unpaired),
        },
        "by_group": stats,
        "totals": {"filled": n_filled, "excluded": excluded_total},
        "corrected_t0_cross_check": cross_check,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 摘要表 ----
    print(f"执行合约重放: {n_filled} filled / {excluded_total} excluded / {len(unpaired)} unpaired")
    print(
        f"{'组':<24}{'n':>4}  {'recorded':>9}  {'corr-T0':>9}  {'exec净':>9}  {'净胜率':>7}"
    )
    order = ["btst_breakout", "oversold_bounce"]
    sorted_keys = sorted(
        stats.keys(),
        key=lambda k: (order.index(k.split("/")[0]) if k.split("/")[0] in order else 99, k),
    )
    for key in sorted_keys:
        entry = stats[key]
        wr = f"{entry['net_win_rate']:.0%}" if "net_win_rate" in entry else "—"
        print(
            f"{key:<26}{entry.get('n_filled', 0):>4}  "
            f"{_fmt_pct(entry.get('recorded_mean')):>9}  "
            f"{_fmt_pct(entry.get('corrected_t0_mean')):>9}  "
            f"{_fmt_pct(entry.get('net_mean')):>9}  "
            f"{wr:>7}"
        )
    if cross_check:
        worst = max(cross_check.items(), key=lambda kv: abs(kv[1]["delta"]))
        print(f"\ncorrected-T0 交叉验证: {len(cross_check)} 组, 最大 |delta| = {abs(worst[1]['delta']):.2f}pp ({worst[0]})")
    print(f"\n产物: {out_path}")
    print("边界: RESEARCH_RECONSTRUCTION — 不构成 edge/regime 授权或交易权限")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
