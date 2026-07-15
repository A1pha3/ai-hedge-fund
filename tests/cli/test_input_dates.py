"""CLI end_date 默认值的 17:00 阈值逻辑测试。

资金流数据 (tushare moneyflow / akshare push2his) 约 17:00 后才完成当日入库。
不传 --end-date 时, 17:00 前自动回退一天, 避免查到不存在的当日数据。
显式传 --end-date 时完全尊重用户指定。
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.cli.input import _resolve_default_end_date, resolve_dates
from src.utils.date_utils import SignalSessionUnavailable


class TestResolveDefaultEndDate:
    """_resolve_default_end_date 的 17:00 阈值逻辑。"""

    @pytest.fixture(autouse=True)
    def _authoritative_calendar(self, monkeypatch):
        """Hermetic forward calendar so these tests exercise the shared
        ``resolve_signal_session`` resolver (spec 8.1) deterministically,
        without depending on the real ``data/reports`` calendar files."""
        from datetime import date

        monkeypatch.setattr(
            "src.screening.offensive.daily_action._load_authoritative_session_dates",
            lambda: (
                date(2026, 7, 8),
                date(2026, 7, 9),
                date(2026, 7, 10),
                date(2026, 7, 13),
            ),
        )

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
            assert _resolve_default_end_date() == "2026-07-10"

    def test_sunday_evening_returns_friday(self):
        """周日 17:00 后也应回退到最近开市日, 不能生成周日报告日期。"""
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 12, 18, 0)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert _resolve_default_end_date() == "2026-07-10"

    def test_signal_session_cutoff_is_fixed_at_1700(self, monkeypatch):
        """Production signal-session policy is fixed at 17:00."""
        monkeypatch.setenv("DATA_READY_HOUR", "20")
        with patch("src.cli.input.datetime") as mock_dt:
            # Environment configuration must not split Auto and Daily Action.
            mock_dt.now.return_value = datetime(2026, 7, 9, 18, 0)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            assert _resolve_default_end_date() == "2026-07-09"

    def test_invalid_env_does_not_change_fixed_cutoff(self, monkeypatch):
        """Invalid legacy configuration cannot change the fixed policy."""
        monkeypatch.setenv("DATA_READY_HOUR", "not_a_number")
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 9, 16, 0)
            mock_dt.strptime.side_effect = lambda *a, **kw: datetime.strptime(*a, **kw)
            assert _resolve_default_end_date() == "2026-07-08"

    def test_delegate_returns_dashed_iso_format(self):
        """_resolve_default_end_date 委托 helper 后仍返回 YYYY-MM-DD (不是 YYYYMMDD)."""
        # 契约回归: 委托 resolve_signal_date_iso 后格式必须保持 YYYY-MM-DD,
        # 下游 resolve_dates / argparse --end-date 依赖带横线格式.
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 9, 10, 30)
            result = _resolve_default_end_date()
        assert result == "2026-07-08"
        assert "-" in result  # 必须带横线, 不能是紧凑 YYYYMMDD

    def test_signal_session_unavailable_propagates_without_authoritative_calendar(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            "src.screening.offensive.daily_action._load_authoritative_session_dates",
            lambda: (),
        )
        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 13, 18, 0)
            with pytest.raises(SignalSessionUnavailable):
                _resolve_default_end_date()

    def test_auto_adapter_uses_aware_shanghai_clock(self, monkeypatch):
        observed = {}

        def capture_clock(**kwargs):
            observed["now_cn"] = kwargs["now_cn"]
            return date(2026, 7, 13)

        monkeypatch.setattr(
            "src.utils.date_utils.resolve_signal_session", capture_clock
        )

        assert _resolve_default_end_date() == "2026-07-13"
        assert observed["now_cn"].tzinfo is not None
        assert observed["now_cn"].tzinfo.key == "Asia/Shanghai"

    def test_auto_and_daily_action_adapters_share_cutoff(self):
        from src.screening.offensive.daily_action import resolve_daily_action_signal

        sessions = (date(2026, 7, 10), date(2026, 7, 13))
        before_cutoff = datetime(
            2026, 7, 13, 16, 59, tzinfo=ZoneInfo("Asia/Shanghai")
        )

        with patch("src.cli.input.datetime") as mock_dt:
            mock_dt.now.return_value = before_cutoff
            auto_date = _resolve_default_end_date()
        daily_date, _ = resolve_daily_action_signal(
            now_cn=before_cutoff,
            open_sessions=sessions,
        )

        assert auto_date == "2026-07-10"
        assert daily_date == date(2026, 7, 10)


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

    def test_auto_strict_override_rejects_non_session(self):
        with patch(
            "src.screening.offensive.daily_action._load_authoritative_session_dates",
            return_value=(date(2026, 7, 10), date(2026, 7, 13)),
        ):
            with pytest.raises(SignalSessionUnavailable):
                resolve_dates(
                    None,
                    "2026-07-12",
                    default_months_back=3,
                    production_strict=True,
                )

    def test_research_override_remains_unrestricted(self):
        _, end = resolve_dates(
            None,
            "2026-07-12",
            default_months_back=3,
            production_strict=False,
        )

        assert end == "2026-07-12"


def test_parse_cli_inputs_routes_auto_to_production_strict(monkeypatch):
    from src.cli.input import parse_cli_inputs

    observed = {}

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--auto", "--end-date", "2026-07-13"],
    )
    monkeypatch.setattr(
        "src.cli.input._resolve_default_end_date", lambda: "2026-07-13"
    )
    monkeypatch.setattr(
        "src.cli.input.resolve_dates",
        lambda start, end, **kwargs: (
            observed.update(kwargs) or "2026-04-13",
            end,
        ),
    )
    monkeypatch.setattr(
        "src.cli.input.get_default_model_config",
        lambda: ("test-model", "test-provider"),
    )

    parse_cli_inputs(
        description="test",
        require_tickers=False,
        default_months_back=3,
    )

    assert observed["production_strict"] is True
