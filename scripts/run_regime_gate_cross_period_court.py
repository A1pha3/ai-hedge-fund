"""Cross-period regime-gate court validation (P1b, 2026-08-14).

Runs the honest-court backtest (T+1 open + slippage) for BTST-only across
two out-of-sample periods (2022 bear, 2024) x {ungated, gated} to test whether
"skip crisis/risk_off signal days" is robust cross-period (court decision pack
regime_gate_decision_pack_2026-08-09.md §8 item 2) rather than a 2026H1 fluke.
"""

from __future__ import annotations

import json

from scripts.backtest_paper_loop import backtest_paper_loop as bt

PERIODS = {
    # 2022/2024 曾被 fund_flow 数据阻塞 (缓存仅从 2025-07 起, 条件2 全 miss → 0 交易).
    # 2026-08-15: scripts/backfill_fund_flow_history.py 已补齐 2022-01→2025-07 段
    # (tushare 批量端点实证可得), 两个跨期窗口解锁. 2025H2 不重跑 (8/14 证据不变:
    # 回填与该窗口数据不相交).
    "2022熊市": ("20220104", "20221230"),
    "2024": ("20240102", "20241231"),
}

results: dict[str, dict] = {}
for period, (start, end) in PERIODS.items():
    for gate, block in (("ungated", ()), ("gated", ("crisis", "risk_off"))):
        key = f"{period}_{gate}"
        print(f"===== {key}: {start}→{end} block={block or 'none'} =====", flush=True)
        results[key] = bt(
            start_date=start,
            end_date=end,
            block_regimes=block,
            only_setups=("btst_breakout",),
        )

out = "data/reports/regime_gate_cross_period_court_20260815.json"
with open(out, "w", encoding="utf-8") as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)
print(f"written: {out}")
