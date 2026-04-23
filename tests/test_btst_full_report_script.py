from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import sys

import pandas as pd

import scripts.btst_full_report as btst_full_report


class _FakePro:
    def __init__(self) -> None:
        self._market_dates = ["20260413", "20260414", "20260415", "20260416", "20260417", "20260420"]
        self._requested_trade_date = "20260417"
        self._trade_frames = {trade_date: self._build_market_frame(trade_date) for trade_date in self._market_dates}
        self._history_frame = self._build_history_frame()

    def trade_cal(self, exchange: str, start_date: str, end_date: str, is_open: str) -> pd.DataFrame:
        return pd.DataFrame({"cal_date": self._market_dates})

    def daily(self, trade_date: str | None = None, ts_code: str | None = None, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        if ts_code:
            return self._history_frame.copy()
        return self._trade_frames[trade_date].copy()

    def stock_basic(self, exchange: str, list_status: str, fields: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "list_date": "19910403"},
                {"ts_code": "688001.SH", "name": "科创样本", "industry": "半导体", "list_date": "20200101"},
                {"ts_code": "920001.BJ", "name": "北交样本", "industry": "机械", "list_date": "20200101"},
                {"ts_code": "000002.SZ", "name": "万科A", "industry": "全国地产", "list_date": "19910129"},
            ]
        )

    def limit_list(self, trade_date: str, limit_type: str) -> pd.DataFrame:
        return pd.DataFrame(columns=["ts_code"])

    def _build_market_frame(self, trade_date: str) -> pd.DataFrame:
        day_offset = self._market_dates.index(trade_date)
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "open": 10.0 + day_offset * 0.2,
                    "high": 10.4 + day_offset * 0.2,
                    "low": 9.9 + day_offset * 0.2,
                    "close": 10.3 + day_offset * 0.2,
                    "amount": 250000.0 + day_offset * 10000.0,
                    "vol": 1500000 + day_offset * 1000,
                    "pct_chg": 3.2 + day_offset * 0.1,
                },
                {
                    "ts_code": "688001.SH",
                    "open": 15.0 + day_offset * 0.15,
                    "high": 15.5 + day_offset * 0.15,
                    "low": 14.9 + day_offset * 0.15,
                    "close": 15.4 + day_offset * 0.15,
                    "amount": 320000.0 + day_offset * 12000.0,
                    "vol": 1800000 + day_offset * 1200,
                    "pct_chg": 4.6 + day_offset * 0.1,
                },
                {
                    "ts_code": "920001.BJ",
                    "open": 8.0 + day_offset * 0.1,
                    "high": 8.3 + day_offset * 0.1,
                    "low": 7.9 + day_offset * 0.1,
                    "close": 8.2 + day_offset * 0.1,
                    "amount": 260000.0 + day_offset * 9000.0,
                    "vol": 900000 + day_offset * 800,
                    "pct_chg": 5.1 + day_offset * 0.1,
                },
                {
                    "ts_code": "000002.SZ",
                    "open": 20.0 + day_offset * 0.1,
                    "high": 20.3 + day_offset * 0.1,
                    "low": 19.8 + day_offset * 0.1,
                    "close": 20.1 + day_offset * 0.1,
                    "amount": 210000.0 + day_offset * 8000.0,
                    "vol": 1200000 + day_offset * 1000,
                    "pct_chg": 1.4 + day_offset * 0.1,
                },
            ]
        )

    def _build_history_frame(self) -> pd.DataFrame:
        start = datetime(2026, 3, 10)
        rows: list[dict[str, object]] = []
        for index in range(30):
            trade_date = (start + timedelta(days=index)).strftime("%Y%m%d")
            rows.extend(
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": trade_date,
                        "open": 8.0 + index * 0.1,
                        "high": 8.3 + index * 0.1,
                        "low": 7.9 + index * 0.1,
                        "close": 8.2 + index * 0.1,
                        "amount": 200000.0 + index * 5000.0,
                        "vol": 1000000 + index * 1000,
                    },
                    {
                        "ts_code": "688001.SH",
                        "trade_date": trade_date,
                        "open": 12.0 + index * 0.12,
                        "high": 12.4 + index * 0.12,
                        "low": 11.9 + index * 0.12,
                        "close": 12.3 + index * 0.12,
                        "amount": 240000.0 + index * 4500.0,
                        "vol": 1200000 + index * 1100,
                    },
                    {
                        "ts_code": "920001.BJ",
                        "trade_date": trade_date,
                        "open": 6.0 + index * 0.08,
                        "high": 6.2 + index * 0.08,
                        "low": 5.9 + index * 0.08,
                        "close": 6.1 + index * 0.08,
                        "amount": 210000.0 + index * 3500.0,
                        "vol": 700000 + index * 900,
                    },
                    {
                        "ts_code": "000002.SZ",
                        "trade_date": trade_date,
                        "open": 18.0 + index * 0.05,
                        "high": 18.2 + index * 0.05,
                        "low": 17.9 + index * 0.05,
                        "close": 18.1 + index * 0.05,
                        "amount": 180000.0 + index * 4000.0,
                        "vol": 900000 + index * 1000,
                    },
                ]
            )
        return pd.DataFrame(rows)


def test_btst_full_report_main_writes_requested_trade_date_outputs(monkeypatch, tmp_path: Path) -> None:
    fake_pro = _FakePro()
    fake_tushare = SimpleNamespace(set_token=lambda _token: None, pro_api=lambda: fake_pro)

    monkeypatch.setitem(sys.modules, "tushare", fake_tushare)
    monkeypatch.setattr(btst_full_report, "parse_args", lambda: SimpleNamespace(trade_date="20260417"))
    monkeypatch.setattr(btst_full_report, "__file__", str(tmp_path / "scripts" / "btst_full_report.py"))

    btst_full_report.main()

    reports_dir = tmp_path / "data" / "reports"
    report_path = reports_dir / "btst_full_report_20260417.md"
    assert report_path.exists()
    assert (reports_dir / "btst_full_report_20260417.json").exists()

    report_text = report_path.read_text(encoding="utf-8")
    assert "688001" in report_text
    assert "920001" not in report_text
    assert "排除北交:" in report_text
    assert "排除科创/北交" not in report_text
