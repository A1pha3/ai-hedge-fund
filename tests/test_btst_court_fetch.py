"""btst_court_fetch main() 缺日 fail-loud 语义 (R95 Op8) — fixture 零网络.

钉死: 缺 daily → exit 1 (nightly 历史如实记录); 仅缺 limit_list → rc=0
(floor 语义 + build 兜底, report-only 防误收紧); 全覆盖 → rc=0。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import btst_court_fetch as fetch_mod  # noqa: E402


SESSIONS = ["20260105", "20260106", "20260107"]


@pytest.fixture
def stubbed(monkeypatch):
    """零网络 stub: _pro + 三个 fetch 函数; 日线按写入集落盘。"""
    calls = {}

    def configure(tmp_path, present_daily, present_lu=()):
        raw_dir = tmp_path / "raw"
        (raw_dir / "daily").mkdir(parents=True)
        (raw_dir / "limit_up").mkdir(parents=True)
        for s in present_daily:
            (raw_dir / "daily" / f"daily_{s}.csv").write_text("ts_code\n", encoding="utf-8")
        for s in present_lu:
            (raw_dir / "limit_up" / f"lu_{s}.csv").write_text("ts_code\n", encoding="utf-8")

        def fake_daily(pro, sessions, raw_dir=None):
            calls["daily"] = list(sessions)
            return 0, 0

        def fake_lu(pro, sessions, raw_dir=None):
            calls["lu"] = list(sessions)
            return 0, 0

        def fake_sw(pro, raw_dir=None):
            calls["sw"] = True
            return raw_dir

        monkeypatch.setattr(fetch_mod, "load_sessions", lambda start, end: list(SESSIONS))
        monkeypatch.setattr(fetch_mod, "_pro", lambda: object())
        monkeypatch.setattr(fetch_mod, "fetch_daily_panel", fake_daily)
        monkeypatch.setattr(fetch_mod, "fetch_limit_lists", fake_lu)
        monkeypatch.setattr(fetch_mod, "fetch_sw_membership", fake_sw)
        return raw_dir

    return configure


def _run_main(monkeypatch, raw_dir):
    monkeypatch.setattr(
        "sys.argv",
        ["btst_court_fetch.py", "--raw-dir", str(raw_dir), "--limit-list-start", SESSIONS[0]],
    )
    fetch_mod.main()


class TestFailLoud:
    def test_all_present_rc0(self, tmp_path, monkeypatch, stubbed):
        raw_dir = stubbed(tmp_path, present_daily=SESSIONS, present_lu=SESSIONS)
        _run_main(monkeypatch, raw_dir)  # 不抛 = rc 0

    def test_missing_daily_exits_1(self, tmp_path, monkeypatch, stubbed, capsys):
        raw_dir = stubbed(tmp_path, present_daily=SESSIONS[:2], present_lu=SESSIONS)
        with pytest.raises(SystemExit) as exc:
            _run_main(monkeypatch, raw_dir)
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "20260107" in out  # 缺失清单披露

    def test_missing_lu_only_still_rc0(self, tmp_path, monkeypatch, stubbed):
        """仅缺 limit_list → rc=0 (report-only 语义钉死, 防误收紧)。"""
        raw_dir = stubbed(tmp_path, present_daily=SESSIONS, present_lu=[])
        _run_main(monkeypatch, raw_dir)  # 不抛 = rc 0

    def test_missing_list_named_first_days(self, tmp_path, monkeypatch, stubbed, capsys):
        raw_dir = stubbed(tmp_path, present_daily=[], present_lu=[])
        with pytest.raises(SystemExit):
            _run_main(monkeypatch, raw_dir)
        out = capsys.readouterr().out
        assert SESSIONS[0] in out and "daily 缺 3 天" in out
