"""btst_court_fetch.fetch_daily_panel 列契约与限速纪律 (R51 Op1).

日度运维环第一步 (runbook 2b) 的拉取面: tushare schema 漂移 (返回缺列)
时类型化跳过该日并继续, 不再 ``df[_DAILY_COLS]`` 裸 KeyError 中止整个
运行 (后续会话与 limit_list/SW 阶段全部不执行); 空返回路径保持
rate-limit 纪律。全部测试 fake pro, 无网络无 token, slot 内自足。
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts import btst_court_fetch as fetch_mod


class _FakePro:
    """逐日返回预置 DataFrame; 记录调用序, 无网络。"""

    def __init__(self, frames_by_day: dict[str, pd.DataFrame | None]):
        self._frames = frames_by_day
        self.calls: list[str] = []

    def daily(self, trade_date: str, fields: str) -> pd.DataFrame | None:
        self.calls.append(trade_date)
        return self._frames.get(trade_date)


def _good_frame(rows: int = 2) -> pd.DataFrame:
    data = {col: [f"{col}_{i}" for i in range(rows)] for col in fetch_mod._DAILY_COLS}
    return pd.DataFrame(data)


@pytest.fixture()
def fetch_env(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_mod, "RAW_DIR", tmp_path)
    sleeps: list[float] = []
    monkeypatch.setattr(
        fetch_mod.time, "sleep", lambda seconds: sleeps.append(seconds)
    )
    return tmp_path, sleeps


def test_missing_column_day_skipped_and_loop_continues(fetch_env, capsys):
    """缺列日类型化跳过 (含缺失列名), 后续会话照常拉取 (RED: 裸 KeyError 中止)."""
    tmp_path, _ = fetch_env
    bad = _good_frame().drop(columns=["pre_close"])
    pro = _FakePro({"20260101": bad, "20260102": _good_frame()})

    ok, skipped = fetch_mod.fetch_daily_panel(pro, ["20260101", "20260102"])

    assert (ok, skipped) == (1, 0)
    assert pro.calls == ["20260101", "20260102"]
    assert not (tmp_path / "daily" / "daily_20260101.csv").exists()
    assert (tmp_path / "daily" / "daily_20260102.csv").exists()
    out = capsys.readouterr().out
    assert "[bad-schema]" in out
    assert "pre_close" in out


def test_missing_column_day_lands_in_missing_summary(fetch_env):
    """缺列日不落盘 → 调用方既有 missing 汇总口径 (文件存在性) 暴露该缺口."""
    tmp_path, _ = fetch_env
    bad = _good_frame().drop(columns=["vol", "amount"])
    pro = _FakePro({"20260101": bad, "20260102": _good_frame()})
    fetch_mod.fetch_daily_panel(pro, ["20260101", "20260102"])

    missing_daily = [
        d
        for d in ("20260101", "20260102")
        if not (tmp_path / "daily" / f"daily_{d}.csv").exists()
    ]
    assert missing_daily == ["20260101"]


def test_empty_return_sleeps_before_next_call(fetch_env):
    """空返回路径与下一调用之间保持 rate-limit sleep (RED: 现状零 sleep)."""
    _, sleeps = fetch_env
    pro = _FakePro({"20260101": pd.DataFrame(), "20260102": _good_frame()})

    fetch_mod.fetch_daily_panel(pro, ["20260101", "20260102"])

    # day1 空返回 → day2 调用前至少一次限速 sleep (day2 写盘后的 sleep 不计).
    assert len(sleeps) >= 2


def test_success_path_column_order_and_idempotent_skip(fetch_env):
    """成功路径列序 == _DAILY_COLS; 重跑已存在文件跳过, 字节不变."""
    tmp_path, _ = fetch_env
    pro = _FakePro({"20260101": _good_frame()})

    assert fetch_mod.fetch_daily_panel(pro, ["20260101"]) == (1, 0)
    path = tmp_path / "daily" / "daily_20260101.csv"
    first_bytes = path.read_bytes()
    assert pd.read_csv(path).columns.tolist() == fetch_mod._DAILY_COLS

    assert fetch_mod.fetch_daily_panel(_FakePro({}), ["20260101"]) == (0, 1)
    assert path.read_bytes() == first_bytes
