"""无偏对照实验 — 剩余三个 Layer-B 策略的全 universe IC 审计 (trend 降权后的权重主力).

背景: trend 降权到 0 (trend_gate_unbiased_experiment 证无 IC) 后, score_b 的权重
100% 落在 mean_reversion / fundamental / event_sentiment 上, 但这三个策略从未做过
全 universe 无偏审计 — 此前的所有结论 (MR family 反向 / fundamental quality-first)
都来自推荐池样本, 而推荐池是选择偏差污染的候选宇宙 (已三次踩坑: +3.55% vs -1.19%,
MR family 全universe IC 为正, 2022 数据缺失伪象).

本脚本复用 factor_audit 口径 (全 universe 涨停候选日 + 截止涨停日切片 + exec 测度),
对每个策略回答同一个问题: 其 confidence 在全 universe 上是否区分 T+10 收益?
(与 trend 审计完全同构, 保证可比.)

数据覆盖 (已验证):
  - price: data/price_cache/*.csv (1510 票, 全期) — MR 纯价格, 无缺口
  - fundamental: 缓存 fina_indicator (1040 票, 2024+ 为主) + daily_basic (全市场逐日,
    2020-2026, pe_ttm/pb/ps_ttm/total_mv 真实) — 2025+ 候选日 45% 覆盖
  - event: news 缓存仅 2026-02-26 ~ 2026-08-11 (965 票) — 只测该窗口

判据: 与 trend 实验完全一致 — Spearman(conf, T+10) + 五分位 + 跨窗同向 + Wilson 分离.
特征契约: 策略用生产评分函数 (score_mean_reversion_strategy 纯价格; fundamental 用
生产子因子逻辑重建; event 用 score_event_sentiment_strategy_from_inputs).

只读缓存; 结果落 data/reports/strategy_unbiased_audit.json.
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backtest_paper_loop import _load_all_prices  # noqa: E402
from scripts.factor_audit import _agg_returns, _time_block_split  # noqa: E402
from src.screening.offensive.execution_adjuster import is_limit_up_unbuyable_next_day  # noqa: E402
from src.screening.strategy_scorer_mean_reversion import score_mean_reversion_strategy  # noqa: E402
from src.tools.ashare_board_utils import (  # noqa: E402
    limit_up_cap_pct_for_ticker,
    limit_up_pct_for_ticker,
)

REPORT_DIR = Path("data/reports")
T_HORIZON = 10
MIN_HISTORY = 200  # trend 实验同口径


def _bucket_stats(values_returns: dict) -> dict:
    out = {}
    for k in sorted(values_returns, key=lambda x: (len(x), x)):
        rets = values_returns[k]
        out[k] = _agg_returns(rets, len(rets))
    return out


def _spearman_rho(confs: list[float], rets: list[float]) -> float:
    if len(confs) < 30:
        return float("nan")
    return float(pd.Series(confs).rank().corr(pd.Series(rets).rank()))


def _cross_window(signals: list[dict]) -> dict:
    """跨窗同向检验 (前半 vs 后半)."""
    first, second, _ = _time_block_split(signals)
    rho1 = _spearman_rho([s["conf"] for s in first], [s["ret"] for s in first]) if len(first) > 30 else float("nan")
    rho2 = _spearman_rho([s["conf"] for s in second], [s["ret"] for s in second]) if len(second) > 30 else float("nan")
    same = (not math.isnan(rho1)) and (not math.isnan(rho2)) and ((rho1 > 0) == (rho2 > 0))
    return {"half1_rho": rho1, "half2_rho": rho2, "same_direction": same}


def _ic_audit(signals: list[dict], label: str, *, extra_split_key: str | None = None) -> dict:
    """对一组 (conf, ret) 信号做标准 IC 审计."""
    exe = [s for s in signals if s["ret"] is not None]
    print(f"\n[{label}] 全 universe IC (exec 测度, n={len(exe)})")
    if len(exe) < 100:
        return {"note": f"样本不足 n={len(exe)}"}
    exe_sorted = sorted(exe, key=lambda s: s["conf"])
    n = len(exe_sorted)
    buckets = defaultdict(list)
    for j, s in enumerate(exe_sorted):
        q = min(4, j * 5 // n)
        buckets[f"Q{q+1}"].append(s["ret"])
    stats = _bucket_stats(buckets)
    rho = _spearman_rho([s["conf"] for s in exe_sorted], [s["ret"] for s in exe_sorted])
    cross = _cross_window(exe_sorted)
    print(f"  Spearman(conf, T+10) = {rho:+.4f}  跨窗: H1={cross['half1_rho']:+.4f} H2={cross['half2_rho']:+.4f} {'同向' if cross['same_direction'] else '不一致'}")
    for k, st in stats.items():
        print(f"  {k}: n={st['n_with_t10_return']} WR={st['winrate']*100:.1f}% median={st['median_t10_return']:+.2f}%")
    verdict = (
        "正IC(conf高→收益高)" if rho > 0.02 else
        "反IC(conf高→收益低)" if rho < -0.02 else
        "无IC(conf不区分T+10)"
    )
    return {
        "n": n,
        "spearman_rho": round(rho, 4),
        "cross_window": {k: (round(v, 4) if isinstance(v, float) and not math.isnan(v) else v) for k, v in cross.items()},
        "quintile_buckets": stats,
        "verdict": verdict,
    }


def scan_mr() -> list[dict]:
    """MR 审计: 全 universe 涨停候选日, conf = 生产 score_mean_reversion_strategy."""
    prices_by = _load_all_prices()
    signals: list[dict] = []
    n_tickers = len(prices_by)
    for ti, (ticker, df) in enumerate(prices_by.items()):
        if ti % 300 == 0:
            print(f"  MR scan 进度 {ti}/{n_tickers}, signals={len(signals)}", flush=True)
        df = df.sort_values("date").reset_index(drop=True)
        if "pct_change" not in df.columns or "close" not in df.columns:
            continue
        pct = pd.to_numeric(df["pct_change"], errors="coerce").values
        close = pd.to_numeric(df["close"], errors="coerce").values
        open_ = pd.to_numeric(df["open"], errors="coerce").values if "open" in df.columns else close
        date_str = df["date_str"].values
        limit_up_pct = limit_up_pct_for_ticker(ticker)
        limit_up_cap = limit_up_cap_pct_for_ticker(ticker)
        n = len(df)
        # MR 信号只依赖价格 → 全部候选日预计算 (不重复切窗)
        for i in range(n):
            p = pct[i]
            if math.isnan(p) or p < limit_up_pct or p > limit_up_cap + 0.5:
                continue
            entry_idx, exit_idx = i + 1, i + T_HORIZON
            ret = None
            if entry_idx < n and exit_idx < n:
                ep = open_[entry_idx]
                if math.isnan(ep) or ep <= 0:
                    ep = close[entry_idx]
                xp = close[exit_idx]
                if not (math.isnan(ep) or math.isnan(xp) or ep <= 0):
                    ret = xp / ep - 1.0
            unbuyable = is_limit_up_unbuyable_next_day(df, i, ticker)
            conf, direction = None, None
            if i + 1 >= 80:
                try:
                    sig = score_mean_reversion_strategy(df.iloc[:i + 1])
                    conf = float(sig.confidence)
                    direction = float(sig.direction)
                except Exception:
                    conf, direction = None, None
            # T+1 收益 (exec: 次日开盘买入, 收盘卖出) — NS-4 翻转是 T+1 验证的,
            # T+10 倒挂可能是 horizon 冲突而非方向错误
            ret1 = None
            if entry_idx < n:
                ep = open_[entry_idx]
                if math.isnan(ep) or ep <= 0:
                    ep = close[entry_idx]
                c1 = close[entry_idx]
                if not (math.isnan(ep) or math.isnan(c1) or ep <= 0):
                    ret1 = c1 / ep - 1.0
            signals.append({
                "ticker": ticker,
                "date": str(date_str[i]),
                "conf": conf,
                "direction": direction,
                "unbuyable_next_day": bool(unbuyable),
                "ret": ret,
                "ret1": ret1,
            })
    return signals


def scan_fundamental() -> list[dict]:
    """Fundamental 审计: 生产链全离线重建 (mock pro + 缓存帧).

    生产 score_fundamental_strategy_from_metrics 链 (profitability/growth/
    financial_health/growth_valuation/industry_pe/quality_cap) 全部从缓存
    fina/daily_basic 帧离线重建 — 已验证 600519/600909/000001 在 2025 候选日
    产出完整 metrics (无 API 请求). 简化重建在 2025 候选日方向分布完全颠倒
    (−1 为主 26/33), 不可用; 必须用生产链.
    """
    import pickle
    import sqlite3

    from unittest import mock

    from src.screening.strategy_scorer_fundamental import score_fundamental_strategy_from_metrics
    from src.tools.tushare_api import get_ashare_financial_metrics_with_tushare

    con = sqlite3.connect("data/cache/cache.sqlite")
    # fina_indicator: 每票全季帧 (需有 ann_date 做披露锚定)
    fkeys = [r[0] for r in con.execute("SELECT key FROM cache WHERE key LIKE 'tushare_df:fina_indicator:%'").fetchall()]
    fina_frames: dict[str, pd.DataFrame] = {}
    for k in fkeys:
        df = pickle.loads(con.execute("SELECT value FROM cache WHERE key=?", (k,)).fetchone()[0])
        if df.empty or "end_date" not in df.columns or "ann_date" not in df.columns:
            continue
        ts = str(df["ts_code"].iloc[0])
        if ts not in fina_frames or len(df) > len(fina_frames[ts]):
            fina_frames[ts] = df
    # 预计算每票 ann_date 降序的披露时点序列, 加速锚定
    fina_anchor: dict[str, list[tuple[str, str]]] = {}
    for ts, frame in fina_frames.items():
        anns = sorted(zip(frame["ann_date"].astype(str), frame["end_date"].astype(str)), reverse=True)
        fina_anchor[ts] = anns
    con.close()

    pro = mock.MagicMock()
    prices_by = _load_all_prices()
    signals: list[dict] = []
    n_tickers = len(prices_by)
    for ti, (ticker, df) in enumerate(prices_by.items()):
        if ti % 300 == 0:
            print(f"  fundamental scan 进度 {ti}/{n_tickers}, signals={len(signals)}", flush=True)
        df = df.sort_values("date").reset_index(drop=True)
        if "pct_change" not in df.columns or "close" not in df.columns:
            continue
        ts_code = ticker + (".SH" if ticker[0] in "69" else ".SZ")
        anchors = fina_anchor.get(ts_code, [])
        pct = pd.to_numeric(df["pct_change"], errors="coerce").values
        close = pd.to_numeric(df["close"], errors="coerce").values
        open_ = pd.to_numeric(df["open"], errors="coerce").values if "open" in df.columns else close
        date_str = df["date_str"].values
        limit_up_pct = limit_up_pct_for_ticker(ticker)
        limit_up_cap = limit_up_cap_pct_for_ticker(ticker)
        n = len(df)
        # 按候选日 pre-compute 该日可用的生产 metrics (一次, 避免重复调用)
        cached_sigs: dict[str, dict | None] = {}
        for i in range(n):
            p = pct[i]
            if math.isnan(p) or p < limit_up_pct or p > limit_up_cap + 0.5:
                continue
            entry_idx, exit_idx = i + 1, i + T_HORIZON
            ret = None
            if entry_idx < n and exit_idx < n:
                ep = open_[entry_idx]
                if math.isnan(ep) or ep <= 0:
                    ep = close[entry_idx]
                xp = close[exit_idx]
                if not (math.isnan(ep) or math.isnan(xp) or ep <= 0):
                    ret = xp / ep - 1.0
            unbuyable = is_limit_up_unbuyable_next_day(df, i, ticker)
            date_i = str(date_str[i])
            conf, direction = None, None
            # 披露锚定: 仅当 fina 有 ann_date <= 候选日的帧才尝试生产链
            has_disclosure = any(ann <= date_i for ann, _ in anchors)
            if has_disclosure:
                sig = cached_sigs.get(date_i)
                if sig is None:
                    try:
                        metrics_list = get_ashare_financial_metrics_with_tushare(ticker, date_i, limit=8)
                        if metrics_list:
                            sig = score_fundamental_strategy_from_metrics(metrics_list)
                        else:
                            sig = None
                    except Exception:
                        sig = None
                    cached_sigs[date_i] = sig
                if sig is not None and sig.completeness > 0:
                    conf = float(sig.confidence)
                    direction = float(sig.direction)
            signals.append({
                "ticker": ticker,
                "date": date_i,
                "conf": conf,
                "direction": direction,
                "unbuyable_next_day": bool(unbuyable),
                "ret": ret,
            })
    return signals


def scan_event() -> list[dict]:
    """Event 审计: news 缓存窗口 (2026-02-26 ~ 2026-08-11) 内的涨停候选日."""
    import pickle
    import sqlite3

    con = sqlite3.connect("data/cache/cache.sqlite")
    nkeys = [r[0] for r in con.execute("SELECT key FROM cache WHERE key LIKE 'akshare_df:stock_news_em:%'").fetchall()]
    news_by_ticker: dict[str, list[dict]] = {}
    for k in nkeys:
        df = pickle.loads(con.execute("SELECT value FROM cache WHERE key=?", (k,)).fetchone()[0])
        if df.empty or "关键词" not in df.columns:
            continue
        kw = str(df["关键词"].iloc[0])
        news_by_ticker.setdefault(kw, []).extend(df.to_dict("records"))
    con.close()
    from src.screening.strategy_scorer_event_sentiment_helpers import score_event_sentiment_strategy_from_inputs
    from src.data.models import CompanyNews

    prices_by = _load_all_prices()
    signals: list[dict] = []
    for ti, (ticker, df) in enumerate(prices_by.items()):
        if ti % 300 == 0:
            print(f"  event scan 进度 {ti}/{len(prices_by)}, signals={len(signals)}", flush=True)
        df = df.sort_values("date").reset_index(drop=True)
        if "pct_change" not in df.columns or "close" not in df.columns:
            continue
        kw = ticker
        news = news_by_ticker.get(kw, [])
        pct = pd.to_numeric(df["pct_change"], errors="coerce").values
        close = pd.to_numeric(df["close"], errors="coerce").values
        open_ = pd.to_numeric(df["open"], errors="coerce").values if "open" in df.columns else close
        date_str = df["date_str"].values
        limit_up_pct = limit_up_pct_for_ticker(ticker)
        limit_up_cap = limit_up_cap_pct_for_ticker(ticker)
        n = len(df)
        for i in range(n):
            p = pct[i]
            if math.isnan(p) or p < limit_up_pct or p > limit_up_cap + 0.5:
                continue
            date_i = str(date_str[i])
            if not ("20260226" <= date_i <= "20260811"):
                continue
            entry_idx, exit_idx = i + 1, i + T_HORIZON
            ret = None
            if entry_idx < n and exit_idx < n:
                ep = open_[entry_idx]
                if math.isnan(ep) or ep <= 0:
                    ep = close[entry_idx]
                xp = close[exit_idx]
                if not (math.isnan(ep) or math.isnan(xp) or ep <= 0):
                    ret = xp / ep - 1.0
            unbuyable = is_limit_up_unbuyable_next_day(df, i, ticker)
            conf, direction = None, None
            try:
                news_items = [
                    CompanyNews(
                        ticker=ticker,
                        title=str(r.get("新闻标题", "")),
                        content=str(r.get("新闻内容", "")),
                        date=str(r.get("发布时间", "")),
                        author=str(r.get("文章来源", "")),
                        source=str(r.get("文章来源", "")),
                        url=str(r.get("新闻链接", "")),
                    )
                    for r in news
                ]
                sig = score_event_sentiment_strategy_from_inputs(news_items, [], date_i)
                if sig.completeness > 0:
                    conf = float(sig.confidence)
                    direction = float(sig.direction)
            except Exception:
                conf, direction = None, None
            signals.append({
                "ticker": ticker,
                "date": date_i,
                "conf": conf,
                "direction": direction,
                "unbuyable_next_day": bool(unbuyable),
                "ret": ret,
            })
    return signals


def _direction_audit(signals: list[dict], label: str) -> dict:
    """direction 维度审计: score_b 的贡献元 = direction × confidence.

    纯 conf IC 会被候选日纠缠污染 (涨停后超买 → conf 高 → T+10 均值回归为负).
    score_b 真正关心的: 按 direction 分桶的 WR 分离 + 符号化贡献的 IC.
    """
    exe = [s for s in signals if s["ret"] is not None and s["direction"] is not None]
    by_dir: dict[int, list[float]] = {1: [], -1: [], 0: []}
    for s in exe:
        d = int(s["direction"])
        by_dir.setdefault(d, []).append(s["ret"])
    dir_stats = {}
    for d in (1, -1, 0):
        rets = by_dir.get(d, [])
        if len(rets) < 30:
            continue
        st = _agg_returns(rets, len(rets))
        dir_stats[f"dir{d:+d}"] = st
        print(f"  direction {d:+d}: n={st['n_with_t10_return']} WR={st['winrate']*100:.1f}% median={st['median_t10_return']:+.2f}%")
    # 符号化贡献 = direction × conf (score_b 权重前的贡献元)
    signed = [s for s in exe if int(s["direction"]) in (1, -1)]
    signed_contrib = [(s["conf"] * float(s["direction"]), s["ret"]) for s in signed]
    rho = _spearman_rho([c for c, _ in signed_contrib], [r for _, r in signed_contrib])
    signed_signals = [{"date": s["date"], "conf": s["conf"] * float(s["direction"]), "ret": s["ret"]} for s in signed]
    first, second, _ = _time_block_split(signed_signals)
    rho1 = _spearman_rho([s["conf"] for s in first], [s["ret"] for s in first]) if len(first) > 30 else float("nan")
    rho2 = _spearman_rho([s["conf"] for s in second], [s["ret"] for s in second]) if len(second) > 30 else float("nan")
    same = (not math.isnan(rho1)) and (not math.isnan(rho2)) and ((rho1 > 0) == (rho2 > 0))
    print(f"  signed(direction×conf) Spearman(contrib, T+10) = {rho:+.4f}  跨窗: H1={rho1:+.4f} H2={rho2:+.4f} {'同向' if same else '不一致'}")
    # 符号化贡献五分位
    sc = sorted(signed_contrib, key=lambda x: x[0])
    n = len(sc)
    if n >= 100:
        buckets = defaultdict(list)
        for j, (c, r) in enumerate(sc):
            q = min(4, j * 5 // n)
            buckets[f"Q{q+1}"].append(r)
        for k, st in _bucket_stats(buckets).items():
            print(f"    {k}: n={st['n_with_t10_return']} WR={st['winrate']*100:.1f}% median={st['median_t10_return']:+.2f}%")
    verdict = (
        "signed正IC(direction×conf 贡献有效)" if rho > 0.02 else
        "signed反IC(direction×conf 贡献反向)" if rho < -0.02 else
        "signed无IC(贡献不区分T+10)"
    )
    return {
        "by_direction": {k: v for k, v in dir_stats.items()},
        "signed_spearman_rho": round(rho, 4),
        "signed_cross_window": {"half1_rho": (round(rho1, 4) if not math.isnan(rho1) else None), "half2_rho": (round(rho2, 4) if not math.isnan(rho2) else None), "same_direction": same},
        "verdict": verdict,
    }


def _t1_direction_check(signals: list[dict]) -> dict:
    """T+1 horizon 的 direction 分离 (NS-4 翻转是 T+1 验证的, 检验 horizon 冲突)."""
    exe = [s for s in signals if s["ret1"] is not None and s["direction"] is not None]
    by_dir: dict[int, list[float]] = {1: [], -1: [], 0: []}
    for s in exe:
        by_dir.setdefault(int(s["direction"]), []).append(s["ret1"])
    stats = {}
    print(f"\n  [MR T+1 horizon] n={len(exe)}")
    for d in (1, -1, 0):
        rets = by_dir.get(d, [])
        if len(rets) < 30:
            continue
        st = _agg_returns(rets, len(rets))
        stats[f"dir{d:+d}"] = st
        print(f"    direction {d:+d}: n={st['n_with_t10_return']} WR={st['winrate']*100:.1f}% median={st['median_t10_return']:+.2f}%")
    # T+1 的符号化贡献 IC
    signed = [s for s in exe if int(s["direction"]) in (1, -1)]
    rho = _spearman_rho([s["conf"] * float(s["direction"]) for s in signed], [s["ret1"] for s in signed])
    print(f"    signed Spearman(contrib, T+1) = {rho:+.4f}")
    return {"n": len(exe), "by_direction": stats, "signed_spearman_rho": round(rho, 4)}


def main() -> None:
    t0 = time.time()
    print("=== 策略无偏审计: MR / fundamental / event (全 universe, 无选择偏差) ===")

    report: dict = {}
    for name, scan_fn in [("mean_reversion", scan_mr), ("fundamental", scan_fundamental), ("event_sentiment", scan_event)]:
        signals = scan_fn()
        exe = [s for s in signals if not s["unbuyable_next_day"] and s["ret"] is not None and s["conf"] is not None]
        print(f"\nscan 完成: {name} {len(signals)} 候选日, exec+有T+10+有conf: {len(exe)}, 耗时 {time.time()-t0:.0f}s")
        report[name] = _ic_audit(exe, name)
        report[name]["direction_audit"] = _direction_audit(exe, name)
        if name == "mean_reversion":
            report[name]["t1_direction_check"] = _t1_direction_check(exe)
    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / "strategy_unbiased_audit.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n报告: {out} (耗时 {time.time()-t0:.0f}s)")
    out = REPORT_DIR / "strategy_unbiased_audit.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n报告: {out} (耗时 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
