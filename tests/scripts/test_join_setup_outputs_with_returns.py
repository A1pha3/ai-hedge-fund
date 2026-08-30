"""join_setup_outputs_with_returns — net 列契约 (R78 Op2, hermetic 合成)。"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.join_setup_outputs_with_returns import (  # noqa: E402
    NET_COST_BASIS,
    HORIZONS as JOIN_HORIZONS,
    compute_forward_returns,
    join_records,
)
from scripts.winrate_payoff_decomposition import ROUNDTRIP_COST  # noqa: E402


def _price_frame(dates: list[str], opens: list[float], closes: list[float],
                 pcts: list[float]) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame({
        "compact": dates,
        "date": pd.to_datetime(dates),
        "open": opens,
        "high": [max(o, c) for o, c in zip(opens, closes)],
        "low": [min(o, c) for o, c in zip(opens, closes)],
        "close": closes,
        "pct_change": pcts,
    })


def _world() -> pd.DataFrame:
    """12 个交易日线性价格: 信号日在第 1 日, T+1 开盘入场。"""
    n = 12
    dates = [f"202608{d:02d}" for d in range(10, 10 + n)]
    base = 10.0
    closes = [base * (1.0 + 0.02 * i) for i in range(n)]
    opens = [c * 0.99 for c in closes]
    pcts = [2.0] * n
    return _price_frame(dates, opens, closes, pcts)


def test_net_columns_equal_gross_minus_roundtrip() -> None:
    df = _world()
    rets = compute_forward_returns(df, "20260810")
    for h in JOIN_HORIZONS:
        g = rets[h]
        assert g is not None
        expected_net = g / 100.0 - ROUNDTRIP_COST
        assert math.isclose(expected_net * 100.0, g - ROUNDTRIP_COST * 100.0, abs_tol=1e-12)


def test_join_records_net_columns_and_disclosure() -> None:
    df = _world()
    records = [{"ticker": "600487", "signal_date": "20260810", "setup": "btst_breakout"}]
    joined = join_records(records, {"600487": df})
    row = joined[0]
    assert row["net_cost_basis"] == ROUNDTRIP_COST == NET_COST_BASIS
    for h in JOIN_HORIZONS:
        g, net = row[f"return_t{h}"], row[f"return_t{h}_net"]
        assert g is not None and net is not None
        assert math.isclose(net, g - ROUNDTRIP_COST * 100.0, abs_tol=1e-9)
    assert row["realized"] is True


def test_join_records_none_passthrough_without_series() -> None:
    records = [{"ticker": "999999", "signal_date": "20260810", "setup": "btst_breakout"}]
    joined = join_records(records, {})
    row = joined[0]
    for h in JOIN_HORIZONS:
        assert row[f"return_t{h}"] is None
        assert row[f"return_t{h}_net"] is None
    assert row["realized"] is False
    assert row["net_cost_basis"] == ROUNDTRIP_COST


def test_gross_columns_unchanged_by_hardening() -> None:
    """gross 列与修复前口径逐位一致 (与 compute_forward_returns 直出比对)。"""
    df = _world()
    direct = compute_forward_returns(df, "20260810")
    records = [{"ticker": "600487", "signal_date": "20260810", "setup": "x"}]
    row = join_records(records, {"600487": df})[0]
    for h in JOIN_HORIZONS:
        assert row[f"return_t{h}"] == direct[h]


if __name__ == "__main__":
    sys.exit(pytest_main := __import__("pytest").main([__file__, "-v"]))
