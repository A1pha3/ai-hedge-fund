"""T+1/T+N 执行合约重放核心 — 契约测试 (RED→GREEN).

重建口径 (2026-08-16, 冻结):
- E = 信号日 + 1 个交易日 (T+1 开盘买), X = 信号日 + horizon 个交易日 (T+10/T+5 开盘卖);
  journal 的 EXIT.date 与 BUY.date 相同 (回测两端都记在信号日), 到期日必须机械推导。
- 价格帧用 `_back_adjust_ohlcv` 回溯复权 (除权免疫 open-to-open);
  一字判定也在复权帧上做 — 复权后的 trigger_close 恰为交易所除权锚定前收。
- 成本: 30bps/边滑点 + 5bps 卖出印花税, 乘法口径 ≈ -0.65% 往返。
- 排除项全部确定性命名并计数 (missing_cache / no_signal_calendar_day /
  no_entry_day / no_exit_day / no_signal_day_bar / suspended_or_missing_entry_bar /
  suspended_or_missing_exit_bar / entry_unbuyable_limit_up) — 未知不编造,
  绝不 stale-close。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.rebuild_journal_execution_returns import (  # noqa: E402
    ReplayConfig,
    aggregate,
    load_adjusted_frame,
    pair_positions,
    replay_position,
)


def _frame(rows: list[dict]) -> pd.DataFrame:
    """合成 price_cache 帧列: date/open/close/high/low/volume/pct_change。"""
    return pd.DataFrame(rows)


def _day_rows(dates: list[str], open_px: list[float], close_px: list[float], pcts: list[float]) -> pd.DataFrame:
    return _frame(
        [
            {
                "date": d,
                "open": o,
                "close": c,
                "high": max(o, c) * 1.01,
                "low": min(o, c) * 0.99,
                "volume": 1000.0,
                "pct_change": p,
            }
            for d, o, c, p in zip(dates, open_px, close_px, pcts)
        ]
    )


CAL = ["20260701", "20260702", "20260703", "20260706", "20260707",
       "20260708", "20260709", "20260710", "20260713", "20260714", "20260715", "20260716"]
# index:      0         1         2         3         4      ...  10        11


# ---------------------------------------------------------------------------
# pair_positions — FIFO 配对 + regime 归因
# ---------------------------------------------------------------------------


class TestPairPositions:
    def test_fifo_pairing_and_regime(self):
        records = [
            {"action": "BUY", "date": "20260701", "ticker": "000001", "setup": "btst_breakout", "horizon": 10},
            {"action": "EXIT", "date": "20260701", "ticker": "000001", "setup": "btst_breakout", "horizon": 10},
            {"action": "BUY", "date": "20260701", "ticker": "000001", "setup": "btst_breakout", "horizon": 10},
            {"action": "EXIT", "date": "20260701", "ticker": "000001", "setup": "btst_breakout", "horizon": 10},
        ]
        positions, unpaired = pair_positions(records, {"20260701": "crisis"})
        assert len(positions) == 2
        assert positions[0].regime == "crisis"
        assert unpaired == []

    def test_unpaired_exit_counted(self):
        records = [{"action": "EXIT", "date": "20260701", "ticker": "000001", "setup": "btst_breakout", "horizon": 10}]
        positions, unpaired = pair_positions(records, {})
        assert positions == []
        assert len(unpaired) == 1

    def test_unpaired_buy_counted(self):
        records = [{"action": "BUY", "date": "20260701", "ticker": "000001", "setup": "btst_breakout", "horizon": 10}]
        positions, unpaired = pair_positions(records, {})
        assert positions == []
        assert len(unpaired) == 1

    def test_regime_missing_maps_unknown(self):
        records = [
            {"action": "BUY", "date": "20260701", "ticker": "000001", "setup": "btst_breakout", "horizon": 10},
            {"action": "EXIT", "date": "20260701", "ticker": "000001", "setup": "btst_breakout", "horizon": 10},
        ]
        positions, _ = pair_positions(records, {})
        assert positions[0].regime == "unknown"


# ---------------------------------------------------------------------------
# replay_position — 合约日期、成本、除权、一字、排除
# ---------------------------------------------------------------------------


class TestReplayPosition:
    def _position(self, signal_date: str = "20260701", horizon: int = 10, setup: str = "btst_breakout"):
        from scripts.rebuild_journal_execution_returns import Position

        return Position(ticker="600001", setup=setup, horizon=horizon, signal_date=signal_date, regime="normal")

    def test_happy_path_dates_and_returns(self):
        # 12 天日历: 信号 0701, E=0702 (T+1), horizon=10 → X=0715 (index 10)
        opens = [10.0] * 12
        closes = [10.0] * 12
        pcts = [0.0] * 12
        opens[1] = 10.0   # entry open
        opens[10] = 11.0  # exit open → gross +10%
        frame = _day_rows(CAL, opens, closes, pcts)
        out = replay_position(frame, CAL, self._position(), ReplayConfig())
        assert out.status == "filled"
        assert out.entry_date == "20260702"
        assert out.exit_date == "20260715"
        assert out.gross_return_pct == pytest.approx(10.0)
        # net = 1.10 × 0.997 × 0.9965 − 1
        expected_net = (1.10 * (1 - 0.0030) * (1 - 0.0030 - 0.0005) - 1) * 100
        assert out.net_return_pct == pytest.approx(expected_net)

    def test_ex_div_immunity_open_to_open(self, tmp_path: Path):
        # 0714 (index 9) 10送10 除权: raw close 10→5.05 (腰斩), 但 provider
        # pct_change=+1% (真实涨幅) — 走完整路径 (CSV → load_adjusted_frame),
        # 复权因子 0.5 作用于 entry 侧: adj entry open = 5.0, exit open = 5.15。
        opens = [10.0] * 12
        closes = [10.0] * 12
        pcts = [0.0] * 12
        closes[9] = 5.05
        pcts[9] = 1.0
        opens[9] = 5.00   # 除权后开盘 (交易所除权口径)
        opens[10] = 5.15  # 次日真实 +1%
        opens[11] = 5.15
        closes[10] = 5.05  # pct=0 自洽 (close 环比持平; 开盘另算)
        closes[11] = 5.05
        cache = tmp_path / "price_cache"
        cache.mkdir()
        _day_rows(CAL, opens, closes, pcts).to_csv(cache / "600001.csv", index=False)
        frame = load_adjusted_frame(cache, "600001")
        out = replay_position(frame, CAL, self._position(), ReplayConfig())
        assert out.status == "filled"
        # 复权免疫: 持有人拿到送股, open-to-open ≈ +3.0% (两日真实涨幅);
        # raw 比值会给 −48.5% (除权幻影)。
        assert out.gross_return_pct == pytest.approx(3.0, abs=0.2)
        assert out.gross_return_pct > -10.0

    def test_limit_up_unbuyable_excluded(self):
        # 触发日涨停 (pct 10% ≥ 主板 9.5) 且次日开盘继续涨停 → 买不到
        opens = [10.0] * 12
        closes = [10.0] * 12
        pcts = [0.0] * 12
        closes[0] = 11.0    # 信号日收盘 +10% 涨停
        pcts[0] = 10.0
        opens[1] = 12.1     # 次日开盘 = 11 × 1.10 → 一字, 买不到
        closes[1] = 12.1
        pcts[1] = 10.0
        frame = _day_rows(CAL, opens, closes, pcts)
        out = replay_position(frame, CAL, self._position(), ReplayConfig())
        assert out.status == "excluded"
        assert out.reason == "entry_unbuyable_limit_up"

    def test_limit_up_but_open_not_locked_is_buyable(self):
        # 触发日涨停但次日开盘未及续涨停 → 可买 (普通高开)
        opens = [10.0] * 12
        closes = [10.0] * 12
        pcts = [0.0] * 12
        closes[0] = 11.0
        pcts[0] = 10.0
        opens[1] = 11.5  # +4.5% 开盘, 未及 +9.5%
        opens[10] = 12.0
        frame = _day_rows(CAL, opens, closes, pcts)
        out = replay_position(frame, CAL, self._position(), ReplayConfig())
        assert out.status == "filled"

    def test_board_adaptive_threshold_gem(self):
        # 创业板 300xxx 阈值 19.5%: 次日开盘 +10% 不是涨停, 可买
        opens = [10.0] * 12
        closes = [10.0] * 12
        pcts = [0.0] * 12
        closes[0] = 12.0    # +20% 涨停 (创业板)
        pcts[0] = 20.0
        opens[1] = 13.2     # +10% 开盘 — 主板口径会误判一字, 创业板可买
        opens[10] = 14.0
        from scripts.rebuild_journal_execution_returns import Position

        pos = Position(ticker="300001", setup="btst_breakout", horizon=10, signal_date="20260701", regime="normal")
        frame = _day_rows(CAL, opens, closes, pcts)
        out = replay_position(frame, CAL, pos, ReplayConfig())
        assert out.status == "filled"

    def test_exit_day_beyond_calendar_excluded(self):
        # 信号日在日历末尾附近, X 超出 → no_exit_day (绝不 stale-close)
        frame = _day_rows(CAL, [10.0] * 12, [10.0] * 12, [0.0] * 12)
        out = replay_position(frame, CAL, self._position(signal_date="20260714"), ReplayConfig())
        assert out.status == "excluded"
        assert out.reason == "no_exit_day"

    def test_suspended_entry_bar_excluded(self):
        # 日历有 E 但帧缺 E 的 bar (停牌) → suspended_or_missing_entry_bar
        rows = _day_rows(CAL, [10.0] * 12, [10.0] * 12, [0.0] * 12).to_dict("records")
        rows = [r for r in rows if r["date"] != "20260702"]  # 停牌日无 bar
        frame = pd.DataFrame(rows)
        out = replay_position(frame, CAL, self._position(), ReplayConfig())
        assert out.status == "excluded"
        assert out.reason == "suspended_or_missing_entry_bar"

    def test_suspended_exit_bar_excluded(self):
        rows = _day_rows(CAL, [10.0] * 12, [10.0] * 12, [0.0] * 12).to_dict("records")
        rows = [r for r in rows if r["date"] != "20260715"]  # 到期日停牌
        frame = pd.DataFrame(rows)
        out = replay_position(frame, CAL, self._position(), ReplayConfig())
        assert out.status == "excluded"
        assert out.reason == "suspended_or_missing_exit_bar"

    def test_signal_date_not_in_calendar(self):
        frame = _day_rows(CAL, [10.0] * 12, [10.0] * 12, [0.0] * 12)
        out = replay_position(frame, CAL, self._position(signal_date="20250101"), ReplayConfig())
        assert out.status == "excluded"
        assert out.reason == "no_signal_calendar_day"

    def test_missing_signal_bar_excluded(self):
        # 帧里没有信号日 bar → 无法验证可买性, 保守排除
        rows = _day_rows(CAL, [10.0] * 12, [10.0] * 12, [0.0] * 12).to_dict("records")
        rows = [r for r in rows if r["date"] != "20260701"]
        frame = pd.DataFrame(rows)
        out = replay_position(frame, CAL, self._position(), ReplayConfig())
        assert out.status == "excluded"
        assert out.reason == "no_signal_day_bar"


# ---------------------------------------------------------------------------
# load_adjusted_frame — price_cache 读取 + 回溯复权
# ---------------------------------------------------------------------------


class TestLoadAdjustedFrame:
    def test_reads_and_back_adjusts(self, tmp_path: Path):
        cache = tmp_path / "price_cache"
        cache.mkdir()
        _day_rows(CAL, [10.0, 10.0, 20.0], [10.0, 10.0, 10.0], [0.0, 0.0, 0.0]).to_csv(
            cache / "600001.csv", index=False
        )
        frame = load_adjusted_frame(cache, "600001")
        assert frame is not None and len(frame) == 3
        assert list(frame["date"]) == CAL[:3]

    def test_missing_cache_returns_none(self, tmp_path: Path):
        assert load_adjusted_frame(tmp_path, "999999") is None


# ---------------------------------------------------------------------------
# aggregate — 分组统计 + 排除计数
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_group_stats_and_exclusions(self):
        from scripts.rebuild_journal_execution_returns import Position, ReplayOutcome

        def _mk(ticker: str, net: float, setup: str = "btst_breakout", regime: str = "normal"):
            pos = Position(ticker=ticker, setup=setup, horizon=10, signal_date="20260701", regime=regime)
            return ReplayOutcome(
                position=pos,
                status="filled",
                reason=None,
                entry_date="20260702",
                exit_date="20260715",
                gross_return_pct=net + 0.65,
                net_return_pct=net,
                corrected_t0_pct=net,
                note=None,
            )

        outcomes = [
            _mk("600001", 5.0),
            _mk("600002", -2.0),
            _mk("600003", -1.0, regime="crisis"),
            ReplayOutcome(
                position=Position("600004", "btst_breakout", 10, "20260701", "normal"),
                status="excluded",
                reason="entry_unbuyable_limit_up",
                entry_date=None,
                exit_date=None,
                gross_return_pct=None,
                net_return_pct=None,
                corrected_t0_pct=None,
                note=None,
            ),
        ]
        stats = aggregate(outcomes)
        all_group = stats["btst_breakout/ALL"]
        assert all_group["n_filled"] == 3
        assert all_group["net_mean"] == pytest.approx((5.0 - 2.0 - 1.0) / 3)
        assert all_group["net_win_rate"] == pytest.approx(1 / 3)
        assert all_group["excluded"]["entry_unbuyable_limit_up"] == 1
        crisis = stats["btst_breakout/crisis"]
        assert crisis["n_filled"] == 1
        assert crisis["net_mean"] == pytest.approx(-1.0)


class TestDualAnchorAndFallback:
    """对抗审查 F1/F2 修复 (2026-08-16): 双锚口径 + 复权回落可观测。"""

    def _position(self, signal_date: str = "20260701", horizon: int = 10):
        from scripts.rebuild_journal_execution_returns import Position

        return Position(ticker="600001", setup="btst_breakout", horizon=horizon, signal_date=signal_date, regime="normal")

    def test_corrected_anchor_rolls_forward_on_suspension(self):
        """F1: corrected 用 frame+N (顺延), executable 用日历 cal+N — 中途停牌
        (非 E/X 日缺 bar) 时两锚指向不同日期, corrected 取顺延后的行。"""
        rows = _day_rows(CAL, [10.0] * 12, [10.0] * 12, [0.0] * 12).to_dict("records")
        # 挖掉 cal index 5 (中途停牌日, 非 E=1 非 X=10)
        rows = [r for r in rows if r["date"] != CAL[5]]
        # 信号 close=10; frame 第 10 行 (= cal index 11) close=12 → corrected +20%
        rows[-1]["close"] = 12.0
        frame = pd.DataFrame(rows)
        out = replay_position(frame, CAL, self._position(), ReplayConfig())
        assert out.status == "filled"  # E/X bar 都在, 可执行不受中途停牌影响
        assert out.corrected_t0_pct == pytest.approx(20.0)

    def test_excluded_position_still_carries_corrected(self):
        """F1: 被排除仓位 (入场日停牌) 仍产出 corrected 对照值 — artifact
        分母含全部配对仓位, 对照列分母与其对齐。"""
        rows = _day_rows(CAL, [10.0] * 12, [10.0] * 12, [0.0] * 12).to_dict("records")
        rows = [r for r in rows if r["date"] != CAL[1]]  # E 停牌
        rows[-1]["close"] = 11.0  # frame 第 10 行 close 11 → corrected +10%
        frame = pd.DataFrame(rows)
        out = replay_position(frame, CAL, self._position(), ReplayConfig())
        assert out.status == "excluded"
        assert out.reason == "suspended_or_missing_entry_bar"
        assert out.corrected_t0_pct == pytest.approx(10.0)

    def test_adjustment_fallback_excluded(self):
        """F2: pct_change 含 NaN → _back_adjust_ohlcv 静默回落原始价, replay
        必须排除 (adjusted_fallback_raw) 而不是把幻影价当真。"""
        rows = _day_rows(CAL, [10.0] * 12, [10.0] * 12, [0.0] * 12)
        rows.loc[3, "pct_change"] = float("nan")
        out = replay_position(rows, CAL, self._position(), ReplayConfig())
        assert out.status == "excluded"
        assert out.reason == "adjusted_fallback_raw"
        assert out.corrected_t0_pct is None  # 该帧上任何数字都不可信

    def test_missing_pct_column_excluded(self):
        rows = _day_rows(CAL, [10.0] * 12, [10.0] * 12, [0.0] * 12).drop(columns=["pct_change"])
        out = replay_position(rows, CAL, self._position(), ReplayConfig())
        assert out.status == "excluded"
        assert out.reason == "adjusted_fallback_raw"

    def test_aggregate_dual_denominators(self):
        """F1: exec 列只用 filled; corrected/recorded 用全配对 (含被排除)。"""
        from scripts.rebuild_journal_execution_returns import Position, ReplayOutcome

        pos = lambda: Position("600001", "btst_breakout", 10, "20260701", "normal")
        outcomes = [
            ReplayOutcome(pos(), "filled", None, "20260702", "20260715", 10.65, 10.0, 5.0, None),
            ReplayOutcome(pos(), "excluded", "suspended_or_missing_entry_bar", None, None, None, None, 3.0, None),
        ]
        stats = aggregate(outcomes)
        g = stats["btst_breakout/ALL"]
        assert g["n_filled"] == 1
        assert g["n_paired"] == 2
        assert g["net_mean"] == pytest.approx(10.0)
        # corrected 分母=2: (5.0+3.0)/2 — 与 artifact 口径对齐
        assert g["corrected_t0_n"] == 2
        assert g["corrected_t0_mean"] == pytest.approx(4.0)
