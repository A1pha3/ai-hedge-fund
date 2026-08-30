"""btst_court_build 口径核心纯函数测试 — court 管道 (AGENTS.md 钉死的全候选评估
唯一权威) 的行业映射 / PIT 截断 / ratchet 退出接线 / 公式代际交叉验证首张回归网.

行为基线 = 2026-08-18 探针实测 (生产 evaluate_shadow_exit/compute_atr 逐字复用):
- ATR 因果下界: compute_atr(period=14, at_idx=entry_idx+1) 需要 entry_idx>=13,
  否则 ratchet_replay 立即返回 None (court build 的 entry_idx 是触发日, 天然满足);
- holding_session>=9 (PLAN_EXIT_SESSION) 的 maximum_holding_session 判定先于
  armed/trailing 检查;
- 触发返回 (触发行 idx + 1, reason) — 出场发生在下一行开盘的次日语义。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from btst_court_build import (  # noqa: E402
    FORWARD_SESSIONS,
    _cross_check_vs_panel,
    industry_of,
    ratchet_replay,
    ticker_frame,
)


# ---------- industry_of: SW as-of 时点映射 (条件 3 行业过滤口径基础) ----------


def test_industry_of_active_membership_hit():
    rows = {"600000": [("银行", "20200101", "")]}
    assert industry_of(rows, "600000", "20260814") == "银行"


def test_industry_of_boundary_days():
    # d_in 当天命中 (d_in <= d); d_out 当天失效 (d_out <= d 即出)
    rows = {"600000": [("银行", "20260101", "20260701")]}
    assert industry_of(rows, "600000", "20260101") == "银行"
    assert industry_of(rows, "600000", "20260630") == "银行"
    assert industry_of(rows, "600000", "20260701") is None


def test_industry_of_multiple_records_first_active_wins():
    rows = {"600000": [("旧行业", "20200101", "20250101"), ("新行业", "20250102", "")]}
    assert industry_of(rows, "600000", "20260814") == "新行业"
    assert industry_of(rows, "600000", "20240101") == "旧行业"


def test_industry_of_missing_symbol_and_blank_name():
    assert industry_of({}, "000001", "20260814") is None
    # 空 l1_name 不作为命中返回 (调用方按 industry_missing 记账)
    assert industry_of({"600000": [("", "20200101", "")]}, "600000", "20260814") is None


# ---------- ticker_frame: PIT 截断 + 列契约 (detect 语义输入帧) ----------


def _raw_group() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": ["20260812", "20260813", "20260814"],
            "open": ["10.0", "10.5", "11.0"],
            "high": ["10.8", "11.2", "11.5"],
            "low": ["9.9", "10.3", "10.8"],
            "close": ["10.5", "11.0", "11.2"],
            "vol": ["1000", "1100", "1200"],
            "pct_chg": ["1.0", "4.76", "1.82"],
        }
    )


def test_ticker_frame_pit_truncation_and_columns():
    frame = ticker_frame(_raw_group(), upto="20260813")
    assert list(frame.columns) == ["date", "open", "high", "low", "close", "volume", "pct_change"]
    assert len(frame) == 2  # 只含 <= upto 的行
    assert frame["date"].tolist() == ["2026-08-12", "2026-08-13"]  # YYYYMMDD → YYYY-MM-DD
    assert frame["volume"].tolist() == [1000.0, 1100.0]  # vol → volume, float
    assert frame["pct_change"].tolist() == [1.0, 4.76]
    assert frame.index.tolist() == [0, 1]  # reset_index


def test_ticker_frame_exact_upto_inclusive():
    frame = ticker_frame(_raw_group(), upto="20260814")
    assert len(frame) == 3


# ---------- ratchet_replay: 退出合约接线 (生产 exit policy 逐字复用) ----------


def _make_frame(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
            "open": [float(c) for c in closes],
            "high": [c * 1.02 for c in closes],
            "low": [c * 0.98 for c in closes],
            "close": [float(c) for c in closes],
            "volume": [1e6] * n,
            "pct_change": [0.0] * n,
        }
    )


def test_ratchet_atr_causal_lower_bound_returns_none():
    # entry_idx=12 → compute_atr(at_idx=13) 因果前缀不足 14 行 → None 立即短路
    assert ratchet_replay(_make_frame([10.0] * 30), 12, 10.0) is None


def test_ratchet_maximum_holding_session_next_open_semantics():
    # entry_idx=13 (ATR 恰可得); 无 armed 无崩盘 → holding_session>=9 于
    # index=21 触发, 返回 22 (= 触发行下一行, 次日开盘执行语义)
    result = ratchet_replay(_make_frame([10.0] * 30), 13, 10.0)
    assert result == (22, "maximum_holding_session")


def test_ratchet_close_below_trailing_line():
    # idx16 armed (close 11.5 >= entry*1.10), idx18 close 9.0 跌破
    # highest-2.5*ATR 移动线 → 返回 (19, close_below_trailing_line)
    closes = [10.0] * 16 + [11.5, 11.5, 9.0] + [9.0] * 15
    result = ratchet_replay(_make_frame(closes), 13, 10.0)
    assert result == (19, "close_below_trailing_line")


def test_ratchet_maximum_precedes_trailing_check():
    # armed 后慢跌: idx21 holding_session==9 时 maximum 判定先于 trailing
    closes = [10.0] * 20 + [11.5] * 3 + [9.0] * 10
    result = ratchet_replay(_make_frame(closes), 13, 10.0)
    assert result == (22, "maximum_holding_session")


def test_ratchet_forward_sessions_window_constant():
    # 窗口常量与 BTST T+10 合约族的持有窗口一致 (court build 头部冻结)
    assert FORWARD_SESSIONS == 15


# ---------- _cross_check_vs_panel: 公式代际交叉验证分类 ----------


def test_cross_check_panel_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # 无 data/reports/setup_output_panel.jsonl
    assert _cross_check_vs_panel(pd.DataFrame()) == {"status": "panel_missing"}


def test_cross_check_classification(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    panel_dir = tmp_path / "data" / "reports"
    panel_dir.mkdir(parents=True)
    # panel 契约: signal_date 为 8 位 YYYYMMDD (与生产 setup_output_panel.jsonl 一致)
    records = [
        {"ticker": "600000", "signal_date": "20260810", "trigger_strength": 0.7, "logged_at": "2026-08-10T18:00"},
        {"ticker": "600001", "signal_date": "20260810", "trigger_strength": 0.8, "logged_at": "2026-08-10T18:00"},
        {"ticker": "600002", "signal_date": "20260811", "trigger_strength": 0.9, "logged_at": "2026-08-11T18:00"},
        # 旧代 (2026-08-09 前) 不参与交叉验证
        {"ticker": "600003", "signal_date": "20260801", "trigger_strength": 0.5, "logged_at": "2026-08-01T18:00"},
    ]
    (panel_dir / "setup_output_panel.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8"
    )
    table = pd.DataFrame(
        {
            "symbol": ["600000", "600001"],
            "signal_date": ["20260810", "20260810"],
            "trigger_strength": [0.7, 0.75],  # 600000 matched; 600001 mismatched; 600002 absent
        }
    )
    out = _cross_check_vs_panel(table)
    assert out["new_gen_records"] == 3
    assert out["matched"] == 1
    assert out["mismatched"] == 1
    assert out["absent"] == 1
    assert {"ticker": "600001", "date": "20260810", "replay": 0.75, "panel": 0.8} in out["details"]
    assert {"ticker": "600002", "date": "20260811", "status": "not_in_replay"} in out["details"]


# ---- R73: regime 输入指纹与漂移检测 (单一实现 _btst_court_common) ----

from _btst_court_common import (  # noqa: E402
    regime_drift_status,
    regime_window_fingerprint,
    regime_window_labels,
)


def test_regime_window_fingerprint_deterministic_and_sensitive():
    """同窗同标签恒同指纹 (键序无关); 标签修订或窗口扩张即变。"""
    window = {"20260105": "normal", "20260106": "crisis"}
    flipped = dict(reversed(list(window.items())))
    assert regime_window_fingerprint(window) == regime_window_fingerprint(flipped)
    revised = dict(window, **{"20260106": "normal"})
    assert regime_window_fingerprint(window) != regime_window_fingerprint(revised)
    widened = dict(window, **{"20260107": "normal"})
    assert regime_window_fingerprint(window) != regime_window_fingerprint(widened)


def test_regime_window_labels_skips_missing_sessions():
    """缺标签会话不进窗口 — 与构建器剔除语义一致 (缺失披露走 regime_missing)。"""
    regime = {"20260105": "normal"}
    assert regime_window_labels(regime, ["20260105", "20260106"]) == {"20260105": "normal"}


def test_regime_drift_status_three_states():
    """无漂移 / 标签修订 / 会话缺失 / 旧构建无窗口 — 四形态各自如实。"""
    manifest = {"regime_window": {"20260105": "normal", "20260106": "crisis"}}
    same = regime_drift_status(manifest, {"20260105": "normal", "20260106": "crisis"})
    assert same == {"checked": True, "drift": False, "changed_sessions": []}

    revised = regime_drift_status(manifest, {"20260105": "normal", "20260106": "normal"})
    assert revised["checked"] is True and revised["drift"] is True
    assert revised["changed_sessions"] == [
        {"session": "20260106", "manifest": "crisis", "current": "normal"}]

    missing_now = regime_drift_status(manifest, {"20260105": "normal"})
    assert missing_now["drift"] is True
    assert missing_now["changed_sessions"] == [
        {"session": "20260106", "manifest": "crisis", "current": None}]

    legacy = regime_drift_status({"regime_missing_sessions": []}, {})
    assert legacy == {"checked": False, "drift": False, "changed_sessions": []}
