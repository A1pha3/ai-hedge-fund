"""R-5.A 核心: 把真实 T+30 按 market regime 分组, 算各 regime 的胜率。

用真实报告的 regime_gate_level + tushare 真实 T+30。
这是 R-5.A 动态披露的数据基础, 也是 R-5.F regime-gating 的科学依据。
"""
from dotenv import load_dotenv
load_dotenv()

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

from src.tools.tushare_api import _get_pro, _to_ts_code

pro = _get_pro()

# 收集所有真实报告 (mode=auto_screening)
by_regime = defaultdict(list)  # regime -> [(date, ticker, score, t30)]
for rp in sorted(Path("data/reports").glob("auto_screening_*.json")):
    d = json.load(open(rp))
    if d.get("mode") != "auto_screening":
        continue
    date = str(d.get("date", ""))
    regime = d.get("market_state", {}).get("regime_gate_level", "normal")
    for rec in d.get("recommendations", []):
        t = rec["ticker"]
        sb = rec.get("score_b", 0)
        # tushare 真实 T+30
        end = (datetime.strptime(date, "%Y%m%d") + timedelta(days=45)).strftime("%Y%m%d")
        try:
            df = pro.daily(ts_code=_to_ts_code(t), start_date=date, end_date=end)
            df = df.sort_values("trade_date") if len(df) else df
            if len(df) > 30:
                t30 = (float(df.iloc[30].close) / float(df.iloc[0].close) - 1) * 100
                by_regime[regime].append((date, t, sb, t30))
        except Exception:
            pass

print("=== 各 regime 真实 T+30 表现 (R-5.A 数据基础) ===\n")
print(f"{'regime':<12} {'n':>4} {'胜率':>6} {'avg':>9} {'median':>9} {'高分(≥0.4)胜率':>14} {'低分(<0.4)胜率':>14}")
print("-" * 80)
summary = {}
for regime in ["normal", "cautious", "crisis", "risk_off"]:
    items = by_regime.get(regime, [])
    if not items:
        continue
    rets = [x[3] for x in items]
    wins = sum(1 for r in rets if r > 0)
    wr = wins / len(rets)
    hi = [x[3] for x in items if x[2] >= 0.4]
    lo = [x[3] for x in items if x[2] < 0.4]
    hi_wr = f"{sum(1 for r in hi if r>0)/len(hi):.0%}(n={len(hi)})" if hi else "-"
    lo_wr = f"{sum(1 for r in lo if r>0)/len(lo):.0%}(n={len(lo)})" if lo else "-"
    print(f"{regime:<12} {len(items):>4} {wr:>5.0%} {mean(rets):>+8.2f}% {median(rets):>+8.2f}% {hi_wr:>14} {lo_wr:>14}")
    summary[regime] = {"n": len(items), "winrate": wr, "avg": mean(rets), "median": median(rets)}

# 缓存给 R-5.A 实现用
print("\n=== 缓存各 regime 摘要 (供 R-5.A 实现引用) ===")
print(json.dumps(summary, ensure_ascii=False, indent=2))
