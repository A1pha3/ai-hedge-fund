"""回测校验: 移除 Auto-300 门控对 BTST 涨停突破胜率/赔率的影响。

背景
----
`--daily-action` v2 此前用 Auto 的 score_b 候选池 (top-300 按 20 日均量流动性)
对 BTST 候选逐票门控, 导致「池外的合格涨停突破票」被 `manifest_ticker_absent`
拦掉。提交 51e467af 改为消费已验证快照, 移除了 Auto-300 耦合。

本脚本用历史数据回答: **池外 (outside) 的涨停突破 BTST 候选, 其 T+1..T+10 胜率/
赔率是否与池内 (inside) 相当?** 据此判断移除门控是净正/中性/有害。

数据约束 (已交叉验证, 见 AGENTS.md 陷阱)
--------------------------------------
- price_cache 仅 6 个月 (2026-01-12 → 2026-07-13) → 前向收益只能在此段算。
- 90 份 auto_screening 报告里 **仅 20260714 一份含 candidate_pool_run.tickers(300)**;
  48 个窗口内日期全部无当日 Auto-300 名单 → 无法按「当日名单」切分。
- 解决: Auto-300 = 按 avg_volume_20d 流动性 top-300 (rank 严格按均量降序, 已核实),
  流动性慢变/持久 → 用 20260714 名单作**静态成员标签**代理整个 2026H1。
  因标签是 per-stock 属性 (是否属流动性 top-300), 可扫窗口内**所有交易日**, 样本大增。
  脚本内置持久性验证 (inside/outside 的 price_cache 均量分布对比)。

方法 (可复现)
-----------
1. 成员标签: ticker 是否在 20260714 candidate_pool_run.tickers 内 (inside/outside)。
2. 对窗口内每个交易日 D、每只 price_cache ticker, 忠实复用 BtstBreakoutSetup.detect()
   (prices + fund_flow + industry 全套, 对两组同等处理), 检出涨停突破命中。
3. 前向收益: T+1 开盘入场, close@T+1/3/5/8/10 相对 T+1 开盘价。
4. 按标签分组, 报 n/胜率/E[r]/中位/盈亏比/尾部(<-10%,-15%)/均值差 bootstrap CI + Welch。
5. 执行性检查: T+1 开盘涨停锁死 (无法成交) 比例, 两组对比。

用法
----
    uv run python scripts/backtest_auto300_gate_removal.py            # 全量
    uv run python scripts/backtest_auto300_gate_removal.py --max-days 5   # 探针
    uv run python scripts/backtest_auto300_gate_removal.py --out data/reports/auto300_gate_removal_20260715.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# 仓库脚本惯例: 入口先 load_dotenv (TUSHARE_TOKEN 等), 再 import 依赖 env 的模块。
load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.screening.offensive.data.fund_flow_store import FundFlowStore  # noqa: E402
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup  # noqa: E402
from src.tools.ashare_board_utils import limit_up_pct_for_ticker  # noqa: E402

PRICE_CACHE_DIR = _PROJECT_ROOT / "data" / "price_cache"
FUND_FLOW_DIR = _PROJECT_ROOT / "data" / "fund_flow_cache"
AUTO300_REPORT = _PROJECT_ROOT / "data" / "reports" / "auto_screening_20260714.json"
HORIZONS = (1, 3, 5, 8, 10)
PREFILTER_PCT = 9.5  # 与真实 scan 一致的宽松涨停下限 (板块自适应阈值在 detect 内精确判定)


# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #
def load_auto300_membership() -> tuple[set[str], dict[str, float]]:
    """20260714 candidate_pool_run.tickers → inside 集合 + {ticker: avg_volume_20d}。"""
    rep = json.loads(AUTO300_REPORT.read_text(encoding="utf-8"))
    cpr = rep["candidate_pool_run"]
    inside = {str(t) for t in cpr["tickers"]}
    amt20 = {}
    for c in cpr.get("candidates", []):
        if isinstance(c, dict) and c.get("ticker"):
            v = c.get("avg_volume_20d")
            if v is not None:
                amt20[str(c["ticker"])] = float(v)
    return inside, amt20


def load_price_frames() -> dict[str, pd.DataFrame]:
    """每只 ticker 的完整 price_cache DataFrame (date 为 datetime, 升序)。"""
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(PRICE_CACHE_DIR.glob("*.csv")):
        ticker = path.stem
        try:
            df = pd.read_csv(path, dtype={"date": str})
            if "date" not in df.columns or len(df) == 0:
                continue
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            df["date_str"] = df["date"].dt.strftime("%Y%m%d")
            frames[ticker] = df
        except Exception:  # noqa: BLE001
            continue
    return frames


def build_industry_context(
    tickers: list[str],
) -> tuple[dict[str, str], dict[tuple[str, str], float]]:
    """全市场 ticker→SW 行业映射 + {(行业名, YYYYMMDD): 当日涨幅}。

    对 inside/outside 同等使用 build_ticker_to_industry (全市场 tushare 映射), 避免
    「inside 有行业数据、outside 降级」的系统性偏差。任一失败则返回空 (detect 降级,
    跳过行业过滤但对两组一致)。
    """
    ticker_to_industry: dict[str, str] = {}
    industry_day_pct: dict[tuple[str, str], float] = {}
    try:
        from scripts.setup_research import build_ticker_to_industry, load_industry_day_pct

        ticker_to_industry = build_ticker_to_industry(tickers)
        industry_day_pct = load_industry_day_pct()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 行业上下文加载失败, BTST 行业条件将对两组一致降级: {exc}")
    return ticker_to_industry, industry_day_pct


# --------------------------------------------------------------------------- #
# 命中检测 + 前向收益
# --------------------------------------------------------------------------- #
@dataclass
class Hit:
    ticker: str
    signal_date: str  # YYYYMMDD
    inside: bool
    pct_change: float
    trigger_strength: float
    degraded: bool
    t1_open_gap_pct: float  # (T+1 open / D close - 1)*100
    t1_locked_unbuyable: bool
    returns: dict[int, float] = field(default_factory=dict)  # horizon → 收益(小数)


def compute_forward_returns(
    df: pd.DataFrame, trigger_pos: int, ticker: str, d_close: float
) -> tuple[dict[int, float], float, bool] | None:
    """T+1 开盘入场, 各 horizon close 收益。

    Returns (returns_by_horizon, t1_open_gap_pct, t1_locked_unbuyable) 或 None (无 T+1)。
    """
    t1_pos = trigger_pos + 1
    if t1_pos >= len(df):
        return None
    t1 = df.iloc[t1_pos]
    entry_open = float(t1["open"])
    if not math.isfinite(entry_open) or entry_open <= 0:
        return None
    t1_gap = (entry_open / d_close - 1) * 100 if d_close > 0 else 0.0
    # T+1 开盘锁死 (无法成交) 代理: 开盘即涨停锁 (open==high==low 且高开到板)。
    limit_thr = limit_up_pct_for_ticker(ticker)
    t1_hi, t1_lo = float(t1["high"]), float(t1["low"])
    t1_locked = (t1_hi == t1_lo) and (t1_gap >= limit_thr * 0.95)
    returns: dict[int, float] = {}
    for h in HORIZONS:
        pos = trigger_pos + h
        if pos >= len(df):
            continue
        exit_close = float(df.iloc[pos]["close"])
        if math.isfinite(exit_close) and exit_close > 0:
            returns[h] = exit_close / entry_open - 1
    return returns, t1_gap, t1_locked


def scan(
    frames: dict[str, pd.DataFrame],
    inside_set: set[str],
    ticker_to_industry: dict[str, str],
    industry_day_pct: dict[tuple[str, str], float],
    store: FundFlowStore,
    max_days: int | None,
    min_signal_date: str | None = None,
) -> list[Hit]:
    """对每只 ticker 的每个涨停日运行真实 BTST detect, 收集命中 + 前向收益。"""
    setup = BtstBreakoutSetup()
    # 主交易日历 (price_cache 全体日期并集, 升序), 用于确定可用信号窗口。
    all_dates = sorted({d for df in frames.values() for d in df["date_str"].tolist()})
    if not all_dates:
        return []
    last_date = all_dates[-1]
    # 可用信号日: 至少要有 T+1。为让 T+10 样本非空, 不强制 D+10, 各 horizon 各自报 n。
    usable_dates = all_dates[:-1]  # 去掉最后一天 (无 T+1)
    if min_signal_date is not None:
        # 干净窗口稳健性检查: 只保留全 723 宇宙齐备后的信号日 (排除仅 99 只深史票的 2025 信号)。
        usable_dates = [d for d in usable_dates if d >= min_signal_date]
    if max_days is not None:
        usable_dates = usable_dates[-max_days:]
    usable_set = set(usable_dates)

    hits: list[Hit] = []
    for ticker, df in frames.items():
        industry = ticker_to_industry.get(ticker)
        # 该 ticker 的涨停日 (宽松预过滤 pct>=9.5, 与真实 scan 一致)
        cand_mask = df["pct_change"].astype(float) >= PREFILTER_PCT
        for pos in df.index[cand_mask]:
            d_str = df.iloc[pos]["date_str"]
            if d_str not in usable_set:
                continue
            prices_upto = df.iloc[: pos + 1].copy()
            flow_records = store.get_range(ticker, "20200101", d_str)
            ind_pct = None
            if industry is not None:
                ind_pct = industry_day_pct.get((industry, d_str))
            ctx = {
                "prices": prices_upto,
                "fund_flow_records": flow_records,
                "industry_day_pct": ind_pct,
                "regime": "normal",
            }
            result = setup.detect(ticker, d_str, ctx)
            if not result.hit:
                continue
            d_close = float(df.iloc[pos]["close"])
            fwd = compute_forward_returns(df, pos, ticker, d_close)
            if fwd is None:
                continue
            returns, t1_gap, t1_locked = fwd
            hits.append(
                Hit(
                    ticker=ticker,
                    signal_date=d_str,
                    inside=ticker in inside_set,
                    pct_change=float(df.iloc[pos]["pct_change"]),
                    trigger_strength=float(result.trigger_strength),
                    degraded=bool(result.degraded),
                    t1_open_gap_pct=t1_gap,
                    t1_locked_unbuyable=t1_locked,
                    returns=returns,
                )
            )
    return hits


# --------------------------------------------------------------------------- #
# 统计
# --------------------------------------------------------------------------- #
def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def _median(xs: list[float]) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return float("nan")
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def payoff_ratio(xs: list[float]) -> float:
    wins = [x for x in xs if x > 0]
    losses = [-x for x in xs if x < 0]
    if not wins or not losses:
        return float("nan")
    return _mean(wins) / _mean(losses)


def group_stats(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    wins = sum(1 for x in xs if x > 0)
    return {
        "n": len(xs),
        "winrate": wins / len(xs),
        "mean": _mean(xs),
        "median": _median(xs),
        "std": _std(xs),
        "payoff_ratio": payoff_ratio(xs),
        "tail_lt_-10pct": sum(1 for x in xs if x < -0.10) / len(xs),
        "tail_lt_-15pct": sum(1 for x in xs if x < -0.15) / len(xs),
        "best": max(xs),
        "worst": min(xs),
    }


def welch_t(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch t 统计量 + 双侧 p (正态近似)。样本小时以 bootstrap CI 为准。"""
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    ma, mb = _mean(a), _mean(b)
    va, vb = _std(a) ** 2, _std(b) ** 2
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return float("nan"), float("nan")
    t = (ma - mb) / se
    # 双侧 p, 正态近似 (df 较大时准确; 小样本偏乐观, 故并列 bootstrap)
    p = math.erfc(abs(t) / math.sqrt(2))
    return t, p


def bootstrap_diff_ci(
    a: list[float], b: list[float], n_boot: int = 10000, seed: int = 20260715
) -> tuple[float, float, float]:
    """a-b 均值差的 95% bootstrap CI (percentile)。返回 (点估计, lo, hi)。"""
    if not a or not b:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    point = _mean(a) - _mean(b)
    diffs = []
    na, nb = len(a), len(b)
    for _ in range(n_boot):
        ra = _mean([a[rng.randrange(na)] for _ in range(na)])
        rb = _mean([b[rng.randrange(nb)] for _ in range(nb)])
        diffs.append(ra - rb)
    diffs.sort()
    lo = diffs[int(0.025 * n_boot)]
    hi = diffs[int(0.975 * n_boot)]
    return point, lo, hi


def bootstrap_winrate_diff_ci(
    a: list[float], b: list[float], n_boot: int = 10000, seed: int = 20260716
) -> tuple[float, float, float]:
    """a-b 胜率差的 95% bootstrap CI。"""
    if not a or not b:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    wa = [1.0 if x > 0 else 0.0 for x in a]
    wb = [1.0 if x > 0 else 0.0 for x in b]
    point = _mean(wa) - _mean(wb)
    diffs = []
    na, nb = len(wa), len(wb)
    for _ in range(n_boot):
        ra = _mean([wa[rng.randrange(na)] for _ in range(na)])
        rb = _mean([wb[rng.randrange(nb)] for _ in range(nb)])
        diffs.append(ra - rb)
    diffs.sort()
    return point, diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot)]


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def build_report(hits: list[Hit], inside_amt20: dict[str, float], frames: dict[str, pd.DataFrame]) -> dict:
    inside_hits = [h for h in hits if h.inside]
    outside_hits = [h for h in hits if not h.inside]

    report: dict = {
        "meta": {
            "n_hits_total": len(hits),
            "n_inside": len(inside_hits),
            "n_outside": len(outside_hits),
            "n_unique_tickers_inside": len({h.ticker for h in inside_hits}),
            "n_unique_tickers_outside": len({h.ticker for h in outside_hits}),
            "signal_date_min": min((h.signal_date for h in hits), default=None),
            "signal_date_max": max((h.signal_date for h in hits), default=None),
            "horizons": list(HORIZONS),
        },
        "executability": {
            "inside_t1_locked_share": _mean([1.0 if h.t1_locked_unbuyable else 0.0 for h in inside_hits]) if inside_hits else None,
            "outside_t1_locked_share": _mean([1.0 if h.t1_locked_unbuyable else 0.0 for h in outside_hits]) if outside_hits else None,
            "inside_mean_t1_gap_pct": _mean([h.t1_open_gap_pct for h in inside_hits]) if inside_hits else None,
            "outside_mean_t1_gap_pct": _mean([h.t1_open_gap_pct for h in outside_hits]) if outside_hits else None,
        },
        "by_horizon": {},
        "by_horizon_buyable_only": {},
    }

    for h in HORIZONS:
        ins = [hit.returns[h] for hit in inside_hits if h in hit.returns]
        out = [hit.returns[h] for hit in outside_hits if h in hit.returns]
        dpoint, dlo, dhi = bootstrap_diff_ci(ins, out)
        wpoint, wlo, whi = bootstrap_winrate_diff_ci(ins, out)
        t, p = welch_t(ins, out)
        report["by_horizon"][f"T+{h}"] = {
            "inside": group_stats(ins),
            "outside": group_stats(out),
            "mean_diff_inside_minus_outside": dpoint,
            "mean_diff_ci95": [dlo, dhi],
            "mean_diff_ci_crosses_zero": (dlo <= 0 <= dhi) if not math.isnan(dlo) else None,
            "winrate_diff_inside_minus_outside": wpoint,
            "winrate_diff_ci95": [wlo, whi],
            "welch_t": t,
            "welch_p_twosided_normal_approx": p,
        }
        # 仅可成交子集 (剔除 T+1 开盘锁死)
        ins_b = [hit.returns[h] for hit in inside_hits if h in hit.returns and not hit.t1_locked_unbuyable]
        out_b = [hit.returns[h] for hit in outside_hits if h in hit.returns and not hit.t1_locked_unbuyable]
        dpb, dlob, dhib = bootstrap_diff_ci(ins_b, out_b)
        report["by_horizon_buyable_only"][f"T+{h}"] = {
            "inside": group_stats(ins_b),
            "outside": group_stats(out_b),
            "mean_diff_inside_minus_outside": dpb,
            "mean_diff_ci95": [dlob, dhib],
            "mean_diff_ci_crosses_zero": (dlob <= 0 <= dhib) if not math.isnan(dlob) else None,
        }

    # 持久性验证: inside/outside 的 price_cache 末端 20 日均量分布
    def trailing_vol(ticker: str) -> float | None:
        df = frames.get(ticker)
        if df is None or "volume" not in df.columns or len(df) < 20:
            return None
        v = df["volume"].astype(float).tail(20).mean()
        return float(v) if math.isfinite(v) else None

    ins_vol = [v for t in {h.ticker for h in inside_hits} if (v := trailing_vol(t)) is not None]
    out_vol = [v for t in {h.ticker for h in outside_hits} if (v := trailing_vol(t)) is not None]
    report["liquidity_persistence_check"] = {
        "note": "inside 应显著高于 outside (Auto-300=流动性 top-300); 验证静态标签合理性",
        "inside_trailing20d_vol_median": _median(ins_vol) if ins_vol else None,
        "outside_trailing20d_vol_median": _median(out_vol) if out_vol else None,
        "inside_n": len(ins_vol),
        "outside_n": len(out_vol),
    }
    return report


def print_summary(report: dict) -> None:
    m = report["meta"]
    print("=" * 78)
    print("BTST Auto-300 门控移除校验 — inside(池内) vs outside(池外) 涨停突破前向收益")
    print("=" * 78)
    print(
        f"命中总数 {m['n_hits_total']} (inside {m['n_inside']} / outside {m['n_outside']}), "
        f"唯一票 inside {m['n_unique_tickers_inside']} / outside {m['n_unique_tickers_outside']}"
    )
    print(f"信号日范围: {m['signal_date_min']} → {m['signal_date_max']}")
    ex = report["executability"]
    print(
        f"T+1 开盘锁死(不可成交)占比: inside {ex['inside_t1_locked_share']}, outside {ex['outside_t1_locked_share']}"
    )
    lp = report["liquidity_persistence_check"]
    print(
        f"流动性持久性: inside 20d均量中位 {lp['inside_trailing20d_vol_median']:.0f} "
        f"vs outside {lp['outside_trailing20d_vol_median']:.0f}"
        if lp["inside_trailing20d_vol_median"] and lp["outside_trailing20d_vol_median"]
        else "流动性持久性: 数据不足"
    )
    print("-" * 78)
    hdr = f"{'H':>4} {'组':>7} {'n':>5} {'胜率':>7} {'E[r]':>8} {'中位':>8} {'盈亏比':>7} {'<-10%':>7} {'<-15%':>7}"
    print(hdr)
    for h in HORIZONS:
        blk = report["by_horizon"][f"T+{h}"]
        for label, key in (("inside", "inside"), ("outside", "outside")):
            g = blk[key]
            if not g.get("n"):
                print(f"T+{h:<2} {label:>7} {0:>5}   (无样本)")
                continue
            print(
                f"T+{h:<2} {label:>7} {g['n']:>5} {g['winrate']*100:>6.1f}% "
                f"{g['mean']*100:>+7.2f}% {g['median']*100:>+7.2f}% "
                f"{g['payoff_ratio']:>6.2f} {g['tail_lt_-10pct']*100:>6.1f}% {g['tail_lt_-15pct']*100:>6.1f}%"
            )
        d = blk["mean_diff_inside_minus_outside"]
        lo, hi = blk["mean_diff_ci95"]
        cross = blk["mean_diff_ci_crosses_zero"]
        wl, wh = blk["winrate_diff_ci95"]
        wd = blk["winrate_diff_inside_minus_outside"]
        sig = "CI跨0(不显著)" if cross else "CI不跨0(显著)"
        print(
            f"     Δ均值(in-out)={d*100:+.2f}% CI95[{lo*100:+.2f}%,{hi*100:+.2f}%] {sig}; "
            f"Δ胜率={wd*100:+.1f}pp CI95[{wl*100:+.1f},{wh*100:+.1f}]pp"
        )
        print("-" * 78)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-days", type=int, default=None, help="仅扫最近 N 个交易日 (探针用)")
    ap.add_argument(
        "--min-signal-date",
        type=str,
        default=None,
        help="仅保留 >= 该日 (YYYYMMDD) 的信号日; 用于干净窗口稳健性检查 (排除仅深史票的 2025 信号)",
    )
    ap.add_argument(
        "--out",
        type=str,
        default="data/reports/auto300_gate_removal_validation_20260715.json",
        help="输出 JSON 路径",
    )
    args = ap.parse_args()

    print("[1/5] 加载 20260714 Auto-300 成员标签 ...")
    inside_set, inside_amt20 = load_auto300_membership()
    print(f"      inside (流动性 top-300): {len(inside_set)} 只")

    print("[2/5] 加载 price_cache ...")
    frames = load_price_frames()
    n_inside_universe = sum(1 for t in frames if t in inside_set)
    print(
        f"      price_cache 宇宙: {len(frames)} 只 (其中 inside {n_inside_universe}, "
        f"outside {len(frames) - n_inside_universe})"
    )

    print("[3/5] 构建全市场行业上下文 (对两组同等) ...")
    ticker_to_industry, industry_day_pct = build_industry_context(sorted(frames.keys()))
    covered = sum(1 for t in frames if t in ticker_to_industry)
    print(f"      行业映射覆盖: {covered}/{len(frames)}; industry_day_pct 条目: {len(industry_day_pct)}")

    print("[4/5] 扫描涨停突破命中 (忠实复用 BtstBreakoutSetup.detect) ...")
    store = FundFlowStore(cache_dir=str(FUND_FLOW_DIR))
    hits = scan(frames, inside_set, ticker_to_industry, industry_day_pct, store, args.max_days, args.min_signal_date)
    print(f"      命中 {len(hits)} 条")

    print("[5/5] 统计 + 报告 ...")
    report = build_report(hits, inside_amt20, frames)
    out_path = _PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      写出 {out_path}")
    print()
    print_summary(report)


if __name__ == "__main__":
    main()
