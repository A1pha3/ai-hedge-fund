"""Stop-loss × regime-gate joint court validation (P0+P1b, 2026-08-14).

Question: are stop-loss and regime-gate substitutes or complements for BTST?
Grid: {2025H2, 2026H1} × {ungated, gated} × {stop=none, stop=fixed8}.

Context:
- paper_tracker._execution_stop_mode: DAILY_ACTION_EXECUTION_STOP=fixed8 makes
  close_matured actually exit at stop price (default none = disclose only).
- 2026-07-10 81-trade bull-sample test showed stops REDUCE E[r] (肥尾被砍).
- But 600879 -35.47% shows tail risk is real; court shows crisis/risk_off is
  where the disasters live. This grid measures the tradeoff on honest
  execution-adjusted P&L (T+1 open + slippage), BTST-only.

fund_flow cache only covers 2025-07+, so these are the only two windows
where the strategy can actually trade.
"""

from __future__ import annotations

import json
import os

from scripts.backtest_paper_loop import backtest_paper_loop as bt

PERIODS = {
    "2025H2": ("20250701", "20251231"),
    "2026H1": ("20260101", "20260706"),
}

def main() -> None:
    results: dict[str, dict] = {}
    for period, (start, end) in PERIODS.items():
        for gate, block in (("ungated", ()), ("gated", ("crisis", "risk_off"))):
            for stop in ("none", "fixed8"):
                key = f"{period}_{gate}_stop-{stop}"
                print(f"===== {key} =====", flush=True)
                if stop == "none":
                    os.environ.pop("DAILY_ACTION_EXECUTION_STOP", None)
                else:
                    os.environ["DAILY_ACTION_EXECUTION_STOP"] = stop
                results[key] = bt(
                    start_date=start,
                    end_date=end,
                    block_regimes=block,
                    only_setups=("btst_breakout",),
                )

    os.environ.pop("DAILY_ACTION_EXECUTION_STOP", None)
    out = "data/reports/stop_loss_x_regime_gate_court_20260814.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    print(f"written: {out}")


if __name__ == "__main__":
    main()
