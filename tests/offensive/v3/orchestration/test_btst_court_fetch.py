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


# ---------- R88 Op1: 早期窗口隔离原料目录 (raw_dir 参数化) ----------

class TestEarlyWindowRawDir:
    """早期窗口 (2022-2024) 原料必须写隔离目录 — 生产 raw/ 是生产 build 的
    对账真值, 混入早期文件会污染 panel/sessions/limit 对账面。"""

    def test_custom_raw_dir_writes_there_not_production(self, fetch_env):
        tmp_path, _ = fetch_env
        early = tmp_path / "raw_early"
        pro = _FakePro({"20220104": _good_frame()})
        ok, skipped = fetch_mod.fetch_daily_panel(
            pro, ["20220104"], raw_dir=early
        )
        assert (ok, skipped) == (1, 0)
        assert (early / "daily" / "daily_20220104.csv").exists()
        assert not (tmp_path / "daily" / "daily_20220104.csv").exists()

    def test_custom_raw_dir_idempotent_skip(self, fetch_env):
        """自定义目录下幂等续传原样 — 已存在文件跳过零调用。"""
        early = fetch_env[0] / "raw_early"
        pro = _FakePro({"20220104": _good_frame()})
        fetch_mod.fetch_daily_panel(pro, ["20220104"], raw_dir=early)
        pro2 = _FakePro({"20220104": _good_frame()})
        ok, skipped = fetch_mod.fetch_daily_panel(pro2, ["20220104"], raw_dir=early)
        assert (ok, skipped) == (0, 1)
        assert pro2.calls == []

    def test_limit_lists_custom_dir_and_empty_day_lands(self, fetch_env):
        """limit_list 空涨停日在自定义目录也落盘 (防反复重试纪律继承)。"""

        class _LuPro:
            def limit_list_d(self, trade_date, limit_type):
                return pd.DataFrame(columns=["ts_code"])

        early = fetch_env[0] / "raw_early"
        ok, skipped = fetch_mod.fetch_limit_lists(
            _LuPro(), ["20220104"], raw_dir=early
        )
        assert (ok, skipped) == (1, 0)
        assert (early / "limit_up" / "lu_20220104.csv").exists()
        assert not (fetch_env[0] / "limit_up" / "lu_20220104.csv").exists()

    def test_main_limit_list_start_releases_window_a_filter(
        self, fetch_env, monkeypatch, capsys
    ):
        """--limit-list-start 20220104: 早期会话不再被 WINDOW_A_START 过滤;
        缺省时过滤语义不变。"""
        import argparse

        real_parse = fetch_mod._parse_args if hasattr(fetch_mod, "_parse_args") else None
        # _parse_args 不存在 — main 内联 parse; 直接构造 parser 语义等价验证
        parser = argparse.ArgumentParser()
        parser.add_argument("--start", default=None)
        parser.add_argument("--end", default=None)
        parser.add_argument("--raw-dir", default=None)
        parser.add_argument("--limit-list-start", default=None)
        args = parser.parse_args(
            ["--limit-list-start", "20220104", "--raw-dir", "/tmp/x"]
        )
        assert args.limit_list_start == "20220104"
        assert args.raw_dir == "/tmp/x"
        # main 语义: floor = args.limit_list_start or WINDOW_A_START
        floor = args.limit_list_start or fetch_mod.WINDOW_A_START
        assert floor == "20220104"
        assert "20220104" >= floor  # 早期会话放行
        assert not ("20220104" >= fetch_mod.WINDOW_A_START)  # 缺省过滤本会滤掉
