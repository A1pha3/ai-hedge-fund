"""CLI end_date 默认值的 17:00 阈值逻辑测试。

资金流数据 (tushare moneyflow / akshare push2his) 约 17:00 后才完成当日入库。
不传 --end-date 时, 17:00 前自动回退一天, 避免查到不存在的当日数据。
显式传 --end-date 时完全尊重用户指定。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from src.cli.input import _resolve_default_end_date, resolve_dates


class TestResolveDefaultEndDate:
    """_resolve_default_end_date 的 17:00 阈值逻辑。"""

    def test_before_1700_returns_previous_day(self):
        """17:00 前 → 前一天。"""
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 9, 10, 30)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _resolve_default_end_date() == "2026-07-08"

    def test_midnight_returns_previous_day(self):
        """凌晨 00:01 → 前一天。"""
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 9, 0, 1)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            assert _resolve_default_end_date() == "2026-07-08"

    def test_exactly_1700_returns_today(self):
        """正好 17:00 → 当天 (>= 阈值算就绪)。"""
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 9, 17, 0)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            assert _resolve_default_end_date() == "2026-07-09"

    def test_after_1700_returns_today(self):
        """17:00 后 → 当天。"""
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 9, 23, 59)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            assert _resolve_default_end_date() == "2026-07-09"

    def test_monday_morning_returns_friday(self):
        """周一凌晨 → 上周五 (跨周末回退)。"""
        with patch("src.cli.input.datetime") as mock_dt:
            # 2026-07-13 是周一
            mock_dt.now.return_value = datetime(2026, 7, 13, 8, 0)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _resolve_default_end_date() == "2026-07-12"  # 周日 (自然日回退)

    def test_custom_threshold_via_env(self, monkeypatch):
        """DATA_READY_HOUR 环境变量可覆盖阈值。"""
        monkeypatch.setenv("DATA_READY_HOUR", "20")
        with patch("src.cli.input.datetime") as mock_dt:
            # 18:00 在默认 17:00 之后, 但自定义阈值 20:00 之前 → 前一天
            mock_dt.now.return_value = datetime(2026, 7, 9, 18, 0)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            assert _resolve_default_end_date() == "2026-07-08"

    def test_invalid_env_falls_back_to_17(self, monkeypatch):
        """DATA_READY_HOUR 非法值 → 回退默认 17。"""
        monkeypatch.setenv("DATA_READY_HOUR", "not_a_number")
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 9, 16, 0)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            assert _resolve_default_end_date() == "2026-07-08"


class TestResolveDatesExplicitOverride:
    """显式 --end-date 不受 17:00 阈值影响。"""

    def test_explicit_end_date_respected_before_1700(self):
        """显式指定今天, 即使没过 17:00 也尊重用户意图。"""
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 9, 10, 0)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            _, end = resolve_dates(None, "2026-07-09", default_months_back=3)
            assert end == "2026-07-09"

    def test_explicit_end_date_respected_arbitrary(self):
        """显式指定任意日期不受影响。"""
        _, end = resolve_dates(None, "2026-01-15", default_months_back=3)
        assert end == "2026-01-15"

    def test_no_end_date_uses_threshold(self):
        """不指定 end_date → 走 17:00 阈值。"""
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 9, 10, 0)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            _, end = resolve_dates(None, None, default_months_back=3)
            assert end == "2026-07-08"

    def test_start_date_follows_end_date(self):
        """start_date 随 end_date 回退一致 (保持 3 个月间隔)。"""
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 9, 10, 0)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            start, end = resolve_dates(None, None, default_months_back=3)
            assert end == "2026-07-08"
            assert start == "2026-04-08"

    def test_invalid_explicit_end_date_raises(self):
        """显式指定非法日期格式 → 报错。"""
        with pytest.raises(ValueError, match="End date must be"):
            resolve_dates(None, "2026/07/09", default_months_back=3)
