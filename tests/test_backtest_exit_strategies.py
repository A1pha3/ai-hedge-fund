"""backtest_exit_strategies 正确性回归网 (autodev batch3 Round 1, RED→GREEN).

固化三个已知缺陷的修复 (2026-08-18):
1. trap 15: 不复权价跨除权缺口的止损幻影 — 10送10 型缺口的 raw low 不得触发
   止损, 模拟必须在 `_back_adjust_ohlcv` 复权帧上进行; 复权链不可证明的票
   显式排除计数 (`adjusted_fallback_raw`), 不静默用 raw。
2. journal 源守卫: 2024 跨周期重放覆盖版 journal → SystemExit(2) fail-closed;
   journal 缺失 → SystemExit(2) 带恢复指引。
3. 缺口穿越止损的诚实成交: 触发日 open ≤ stop 按 open 成交 (跳空不可按止损
   价成交); 日内触及才按止损价成交。

口径契约 (与 2026-07-10 结论可比的相对比较): 锚=个股帧+N (各策略共用)、滑点
10bps/边、ATR 只用 entry 前窗口、排除项逐项计数 (样本侵蚀可观测)。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

from scripts.backtest_exit_strategies import (  # noqa: E402
    _load_btst_trades,
    _load_raw_frame,
    simulate_strategy,
    simulate_trade,
)

_SCRIPT = _PROJECT_ROOT / "scripts" / "backtest_exit_strategies.py"


def _frame(rows: list[tuple[str, float, float, float, float, float]]) -> pd.DataFrame:
    """合成帧列: (date, open, close, high, low, pct_change)。"""
    return pd.DataFrame(
        rows, columns=["date", "open", "close", "high", "low", "pct_change"]
    )


# ---------------------------------------------------------------------------
# 纯函数: simulate_trade (输入帧视作已复权)
# ---------------------------------------------------------------------------


def _flat_gap_free() -> pd.DataFrame:
    """无缺口帧: 连续日期, raw 比值 == 1+pct (复权因子恒 1)。"""
    return _frame(
        [
            ("20260101", 10.0, 10.0, 10.10, 9.90, 0.0),   # 信号日
            ("20260102", 10.0, 9.80, 10.05, 9.90, -2.0),  # T+1 entry
            ("20260103", 9.60, 9.50, 9.70, 9.40, -3.1),
            ("20260104", 9.40, 9.45, 9.60, 9.30, 0.5),
            ("20260105", 9.50, 9.60, 9.70, 9.45, 1.1),    # T+4
        ]
    )


def test_no_stop_time_exit_return():
    r = simulate_trade(_flat_gap_free(), "20260101", stop_mode="none", time_exit=4)
    assert r["status"] == "ok" and r["stopped"] is False
    entry = 10.0 * 1.001
    expected = 9.60 * 0.999 / entry - 1.0
    assert r["ret"] == pytest.approx(expected, abs=1e-12)


def test_intraday_touch_fills_at_stop():
    frame = _frame(
        [
            ("20260101", 10.0, 10.0, 10.10, 9.90, 0.0),
            ("20260102", 10.0, 9.80, 10.05, 9.90, -2.0),   # entry
            ("20260103", 9.60, 9.50, 9.70, 9.00, -8.2),    # open>stop, low 触及
            ("20260104", 9.40, 9.45, 9.60, 9.30, 0.5),
            ("20260105", 9.50, 9.60, 9.70, 9.45, 1.1),
        ]
    )
    r = simulate_trade(frame, "20260101", stop_mode="fixed_pct", stop_param=-0.08, time_exit=4)
    assert r["status"] == "ok" and r["stopped"] is True
    entry = 10.0 * 1.001
    stop = entry * 0.92
    expected = stop * 0.999 / entry - 1.0  # ≈ -8.1% (双边滑点)
    assert r["ret"] == pytest.approx(expected, abs=1e-12)


def test_gap_through_stop_fills_at_open():
    """open 跳空跌破止损价 → 必须按 open 诚实成交, 不是按止损价 (旧缺陷)。"""
    frame = _frame(
        [
            ("20260101", 10.0, 10.0, 10.10, 9.90, 0.0),
            ("20260102", 10.0, 9.80, 10.05, 9.90, -2.0),   # entry
            ("20260103", 8.50, 8.40, 8.60, 8.30, -14.3),   # open 8.5 < stop 9.21
            ("20260104", 8.40, 8.60, 8.70, 8.35, 2.4),
            ("20260105", 8.60, 8.70, 8.80, 8.55, 1.2),
        ]
    )
    r = simulate_trade(frame, "20260101", stop_mode="fixed_pct", stop_param=-0.08, time_exit=4)
    assert r["status"] == "ok" and r["stopped"] is True
    entry = 10.0 * 1.001
    expected = 8.50 * 0.999 / entry - 1.0  # ≈ -15.1%, 而非 -8.1%
    assert r["ret"] == pytest.approx(expected, abs=1e-12)
    assert r["ret"] < -0.10


def test_exclusion_reasons_are_named():
    frame = _flat_gap_free()
    assert simulate_trade(frame, "20251231", stop_mode="none")["reason"] == "no_sigdate_bar"
    assert simulate_trade(frame, "20260103", time_exit=10)["reason"] == "window_truncated"
    zero_open = frame.copy()
    zero_open.iloc[1, 1] = 0.0  # entry open = 0
    assert simulate_trade(zero_open, "20260101", stop_mode="none", time_exit=3)["reason"] == "entry_invalid"


def test_atr_stop_uses_pre_entry_window():
    """ATR 只用 entry 前窗口; 窗口不足 → 无止损降级时间退出 (不崩)。"""
    rows = [("20250101", 10.0, 10.0, 10.3, 9.7, 0.0)]
    d = 1
    for _ in range(24):  # 24 个 pre-entry 会话, TR ≈ 0.6
        d += 1
        rows.append((f"202501{d:02d}" if d <= 9 else f"202501{d}", 10.0, 10.0, 10.3, 9.7, 0.0))
    rows.append(("20260101", 10.0, 10.0, 10.3, 9.7, 0.0))     # 信号日
    rows.append(("20260102", 10.0, 10.0, 10.1, 9.9, 0.0))     # entry, open 10
    rows.append(("20260103", 9.9, 9.5, 9.95, 8.4, -5.0))      # low 8.4 触发
    rows.append(("20260104", 9.5, 9.6, 9.7, 9.45, 1.1))
    frame = _frame(rows)
    r = simulate_trade(frame, "20260101", stop_mode="atr", stop_param=2.0, time_exit=3)
    assert r["status"] == "ok" and r["stopped"] is True
    entry = 10.0 * 1.001
    # TR 恒 0.6 (high-low=0.6, 对 close 无跳空) → Wilder ATR 收敛到 0.6
    stop = entry - 2.0 * 0.6
    assert r["ret"] == pytest.approx(stop * 0.999 / entry - 1.0, abs=1e-6)


def test_atr_insufficient_pre_window_degrades_to_time_exit():
    rows = [
        ("20260101", 10.0, 10.0, 10.3, 9.7, 0.0),
        ("20260102", 10.0, 9.9, 10.1, 9.9, -1.0),
        ("20260103", 9.9, 9.5, 9.95, 8.4, -4.0),
        ("20260104", 9.5, 9.6, 9.7, 9.45, 1.1),
    ]
    r = simulate_trade(_frame(rows), "20260101", stop_mode="atr", stop_param=2.0, time_exit=3)
    assert r["status"] == "ok" and r["stopped"] is False  # ATR 不可算 → 时间退出


# ---------------------------------------------------------------------------
# journal 加载与源守卫
# ---------------------------------------------------------------------------


def _journal_line(action: str, d: str, ticker: str, setup: str = "btst_breakout", reasoning: str = "") -> str:
    return json.dumps(
        {"action": action, "date": d, "ticker": ticker, "setup": setup, "horizon": 10, "reasoning": reasoning}
    )


def test_loader_pairs_buy_exit_and_ignores_other_setups(tmp_path):
    journal = tmp_path / "j.jsonl"
    journal.write_text(
        "\n".join(
            [
                _journal_line("BUY", "20260301", "600000"),
                _journal_line("EXIT", "20260301", "600000", reasoning="... realized=+8.15% ..."),
                _journal_line("BUY", "20260302", "000001", setup="oversold_bounce"),
                _journal_line("EXIT", "20260302", "000001", setup="oversold_bounce", reasoning="realized=+1.0%"),
                _journal_line("BUY", "20260303", "300033"),  # 无 EXIT 配对 → 丢弃
            ]
        ),
        encoding="utf-8",
    )
    trades = _load_btst_trades(journal)
    assert len(trades) == 1
    assert trades[0] == {"sigdate": "20260301", "ticker": "600000", "horizon": 10, "orig_ret": pytest.approx(0.0815)}


def test_2024_replay_journal_refused(tmp_path):
    journal = tmp_path / "replay2024.jsonl"
    lines = []
    for i in range(4):
        d = f"2024031{i + 1}"
        lines.append(_journal_line("BUY", d, f"60000{i}"))
        lines.append(_journal_line("EXIT", d, f"60000{i}", reasoning="realized=+5.0%"))
    journal.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _load_btst_trades(journal)
    assert exc.value.code == 2


def test_journal_missing_fails_closed_with_guidance(tmp_path):
    with pytest.raises(SystemExit) as exc:
        _load_btst_trades(tmp_path / "nope.jsonl")
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# 聚合器: 复权链 + 排除计数 + 统计
# ---------------------------------------------------------------------------


def _write_cache(tmp_path: Path, ticker: str, frame: pd.DataFrame) -> None:
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    frame.to_csv(cache / f"{ticker}.csv", index=False)


def _trades(*items: tuple[str, str]) -> list[dict]:
    return [{"sigdate": d, "ticker": t, "horizon": 10, "orig_ret": 0.0} for d, t in items]


def test_ex_div_gap_does_not_trigger_stop(tmp_path):
    """trap 15 核心: 10送10 型除权缺口 (raw low 腰斩但 pct 为正) 不得触发止损。

    raw 口径 (旧缺陷) 会在 4.95 的幻影 low 上按 stop≈9.21 成交, 记 ≈-8%;
    复权口径 entry≈4.66、止损线≈4.30, 幻影消失, 时间退出为正收益。
    """
    frame = _frame(
        [
            ("20260101", 10.0, 10.00, 10.10, 9.90, 0.0),    # 信号日
            ("20260102", 10.0, 10.20, 10.25, 9.95, 2.0),    # T+1 entry (raw)
            ("20260103", 10.2, 10.40, 10.45, 10.15, 1.96),
            ("20260104", 5.10, 5.00, 5.15, 4.95, 3.0),      # 除权: raw 腰斩, 真实 +3%
            ("20260105", 5.05, 5.10, 5.15, 5.00, 2.0),      # T+4 exit
        ]
    )
    _write_cache(tmp_path, "600000", frame)
    r = simulate_strategy(
        _trades(("20260101", "600000")),
        cache_dir=tmp_path / "cache",
        stop_mode="fixed_pct",
        stop_param=-0.08,
        time_exit=4,
    )
    assert r["n"] == 1 and r["stop_trig"] == 0
    assert r["E"] > 0.05  # 复权后真实路径为正; 幻影口径会给出 ≈-8%


def test_adjusted_fallback_raw_excluded_and_counted(tmp_path):
    frame = _frame(
        [
            ("20260101", 10.0, 10.0, 10.1, 9.9, float("nan")),  # pct 缺失 → 链不可证明
            ("20260102", 10.0, 10.2, 10.3, 9.9, 2.0),
            ("20260103", 10.2, 10.4, 10.5, 10.1, 2.0),
            ("20260104", 10.4, 10.5, 10.6, 10.3, 1.0),
            ("20260105", 10.5, 10.6, 10.7, 10.4, 1.0),
        ]
    )
    _write_cache(tmp_path, "600001", frame)
    r = simulate_strategy(_trades(("20260101", "600001")), cache_dir=tmp_path / "cache", time_exit=4)
    assert r["n"] == 0
    assert r["excluded"]["adjusted_fallback_raw"] == 1


def test_missing_cache_counted(tmp_path):
    r = simulate_strategy(_trades(("20260101", "999999")), cache_dir=tmp_path / "cache")
    assert r["n"] == 0
    assert r["excluded"]["missing_price_cache"] == 1


def test_strategy_stats_fields(tmp_path):
    # 三个票: +10% / -2% / +4% (no_stop, T+3, 无缺口帧)
    for ticker, close_exit in (("600100", 11.0), ("600200", 9.8), ("600300", 10.4)):
        frame = _frame(
            [
                ("20260101", 10.0, 10.0, 10.1, 9.9, 0.0),
                ("20260102", 10.0, 10.0, 10.1, 9.9, 0.0),
                ("20260103", 10.0, 10.0, 10.1, 9.9, 0.0),
                ("20260104", close_exit, close_exit, close_exit, close_exit, (close_exit / 10.0 - 1) * 100),
            ]
        )
        _write_cache(tmp_path, ticker, frame)
    trades = _trades(("20260101", "600100"), ("20260101", "600200"), ("20260101", "600300"))
    r = simulate_strategy(trades, cache_dir=tmp_path / "cache", time_exit=3)
    assert r["n"] == 3 and r["trades_loaded"] == 3
    rets = sorted([9.8 * 0.999 / 10.01 - 1.0, 11.0 * 0.999 / 10.01 - 1.0, 10.4 * 0.999 / 10.01 - 1.0])
    assert r["E"] == pytest.approx(sum(rets) / 3, abs=1e-12)
    assert r["winrate"] == pytest.approx(2 / 3)
    assert r["median"] == pytest.approx(10.4 * 0.999 / 10.01 - 1.0, abs=1e-12)
    assert r["max_loss"] == pytest.approx(rets[0], abs=1e-12)
    assert r["stop_trig"] == 0
    assert sum(r["excluded"].values()) == 0


# ---------------------------------------------------------------------------
# CLI 端到端 (subprocess)
# ---------------------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(_PROJECT_ROOT)}
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )


def test_cli_2024_journal_exit_2(tmp_path):
    journal = tmp_path / "replay.jsonl"
    journal.write_text(
        "\n".join(
            [
                _journal_line("BUY", "20240501", "600000"),
                _journal_line("EXIT", "20240501", "600000", reasoning="realized=+5.0%"),
            ]
        ),
        encoding="utf-8",
    )
    proc = _run_cli("--journal", str(journal))
    assert proc.returncode == 2
    assert "2024" in proc.stderr


def test_cli_happy_path_prints_table(tmp_path):
    journal = tmp_path / "ok.jsonl"
    journal.write_text(
        "\n".join(
            [
                _journal_line("BUY", "20260101", "600000"),
                _journal_line("EXIT", "20260101", "600000", reasoning="realized=+5.0%"),
            ]
        ),
        encoding="utf-8",
    )
    frame = _frame(
        [
            ("20260101", 10.0, 10.0, 10.1, 9.9, 0.0),
            ("20260102", 10.0, 10.0, 10.1, 9.9, 0.0),
            ("20260103", 10.0, 10.0, 10.1, 9.9, 0.0),
            ("20260104", 10.5, 10.5, 10.6, 10.4, 5.0),
        ]
    )
    _write_cache(tmp_path, "600000", frame)
    proc = _run_cli(
        "--journal", str(journal), "--cache-dir", str(tmp_path / "cache"), "--time-exit", "3"
    )
    assert proc.returncode == 0, proc.stderr
    assert "Exit-Strategy Backtest" in proc.stdout
    assert "no_stop" in proc.stdout


def test_raw_frame_loader_normalizes_dates(tmp_path):
    frame = _frame(
        [
            ("2026-01-02", 10.0, 10.0, 10.1, 9.9, 0.0),
            ("2026-01-01", 9.9, 10.0, 10.1, 9.8, 1.0),
        ]
    )
    _write_cache(tmp_path, "600400", frame)
    loaded = _load_raw_frame(tmp_path / "cache", "600400")
    assert loaded is not None
    assert loaded["date"].tolist() == ["20260101", "20260102"]
