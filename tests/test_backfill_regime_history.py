"""backfill_regime_history — 端点解析与幂等回填的零网络测试.

R10 slot 自足纪律: _classify_one_day / _fetch_trading_days / _save_history
全部 stub, 只测端点守卫与 pending 语义。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import scripts.backfill_regime_history as bfrh


TODAY = date(2026, 9, 2)


class TestResolveEndDate:
    def test_default_is_yesterday(self):
        assert bfrh._resolve_end_date(None, today=TODAY) == "20260901"

    def test_explicit_end_respected(self):
        assert bfrh._resolve_end_date("20260831", today=TODAY) == "20260831"

    def test_today_rejected(self):
        with pytest.raises(SystemExit):
            bfrh._resolve_end_date("20260902", today=TODAY)

    def test_future_rejected(self):
        with pytest.raises(SystemExit):
            bfrh._resolve_end_date("20260910", today=TODAY)

    def test_garbage_rejected(self):
        with pytest.raises(SystemExit):
            bfrh._resolve_end_date("2026-08-31", today=TODAY)

    def test_empty_falls_back_to_default(self):
        # 显式空串与 None 同语义 → 默认昨日 (无害: argparse 层不会产生歧义值)
        assert bfrh._resolve_end_date("", today=TODAY) == "20260901"


class TestBackfillIdempotency:
    def test_pending_only_missing_days_and_no_overwrite(self, tmp_path, monkeypatch):
        history_path = tmp_path / "regime_history.json"
        history_path.write_text(
            json.dumps({"20260706": "crisis", "20260707": "crisis", "20260717": "crisis"}), encoding="utf-8"
        )
        monkeypatch.setattr(bfrh, "_REGIME_HISTORY_PATH", history_path)
        monkeypatch.setattr(bfrh, "_REPORTS_DIR", tmp_path)
        monkeypatch.setattr(
            bfrh, "_fetch_trading_days", lambda end=None: [
                "20260706", "20260707", "20260708", "20260709",
                "20260710", "20260713", "20260717",
            ]
        )
        seen: list[str] = []

        def fake_classify(day: str) -> str:
            seen.append(day)
            return "normal"

        monkeypatch.setattr(bfrh, "_classify_one_day", fake_classify)

        result = bfrh.backfill(end="20260901", sleep=0.0)

        # 只补缺: 0708/0709/0710/0713 四日被计算, 0707/0717 未重算
        assert sorted(seen) == ["20260708", "20260709", "20260710", "20260713"]
        # 既有标签不被覆盖, 新标签落盘
        assert result["20260707"] == "crisis"
        assert result["20260717"] == "crisis"
        for day in ("20260708", "20260709", "20260710", "20260713"):
            assert result[day] == "normal"
        on_disk = json.loads(history_path.read_text(encoding="utf-8"))
        assert on_disk == result

    def test_rerun_converges_zero_new(self, tmp_path, monkeypatch):
        history_path = tmp_path / "regime_history.json"
        history_path.write_text(json.dumps({"20260710": "normal"}), encoding="utf-8")
        monkeypatch.setattr(bfrh, "_REGIME_HISTORY_PATH", history_path)
        monkeypatch.setattr(bfrh, "_REPORTS_DIR", tmp_path)
        monkeypatch.setattr(
            bfrh, "_fetch_trading_days", lambda end=None: ["20260710"]
        )
        called: list[str] = []
        monkeypatch.setattr(
            bfrh, "_classify_one_day", lambda d: called.append(d) or "crisis"
        )
        result = bfrh.backfill(end="20260901", sleep=0.0)
        assert called == []  # 幂等: 已有标签不再计算
        assert result == {"20260710": "normal"}
