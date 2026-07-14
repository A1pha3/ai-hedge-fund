from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Literal

import pandas as pd

from src.tools.tushare_api import _cached_tushare_dataframe_call, _get_pro

CalendarSource = Literal["tushare_trade_cal", "akshare_sina"]


@dataclass(frozen=True)
class TradingSessionCalendar:
    open_sessions: tuple[date, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "open_sessions", tuple(sorted(set(self.open_sessions)))
        )

    @classmethod
    def from_dates(cls, open_dates: Iterable[date]) -> TradingSessionCalendar:
        return cls(tuple(open_dates))

    def _require_data(self) -> None:
        if not self.open_sessions:
            raise ValueError("open-session data unavailable")

    def _exact_index(self, session: date) -> int:
        self._require_data()
        index = bisect_left(self.open_sessions, session)
        if index >= len(self.open_sessions) or self.open_sessions[index] != session:
            raise ValueError(
                f"date={session.isoformat()} is absent from open-session data"
            )
        return index

    def next_session(self, current: date) -> date:
        self._require_data()
        index = bisect_right(self.open_sessions, current)
        if index >= len(self.open_sessions):
            raise ValueError(
                f"open-session data unavailable after {current.isoformat()}"
            )
        return self.open_sessions[index]

    def contains_session(self, value: date) -> bool:
        index = bisect_left(self.open_sessions, value)
        return index < len(self.open_sessions) and self.open_sessions[index] == value

    def nth_holding_session(self, entry_date: date, n: int) -> date:
        if n < 1:
            raise ValueError("holding-session number must be at least 1")
        entry_index = self._exact_index(entry_date)
        target_index = entry_index + n - 1
        if target_index >= len(self.open_sessions):
            raise ValueError(
                f"open-session data unavailable for holding session {n} "
                f"from {entry_date.isoformat()}"
            )
        return self.open_sessions[target_index]

    def session_distance(self, start: date, end: date) -> int:
        start_index = self._exact_index(start)
        end_index = self._exact_index(end)
        return end_index - start_index


@dataclass(frozen=True)
class NextTradeDateResolution:
    signal_date_iso: str
    signal_date_compact: str
    next_trade_date_iso: str
    next_trade_date_compact: str
    calendar_source: CalendarSource


def _normalize_iso_date(value: str) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    raise ValueError(f"unsupported date: {value!r}")


def _extract_open_dates_from_frame(
    df: pd.DataFrame | None, start_compact: str, end_compact: str
) -> list[str]:
    if df is None or df.empty:
        return []

    if "cal_date" in df.columns:
        values: list[str] = []
        for v in df["cal_date"].tolist():
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            text = str(v).replace("-", "")
            if len(text) >= 8 and text[:8].isdigit():
                values.append(text[:8])
    elif "trade_date" in df.columns:
        values = []
        for v in df["trade_date"].tolist():
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            try:
                values.append(pd.to_datetime(v).strftime("%Y%m%d"))
            except (ValueError, TypeError):
                continue
    else:
        return []

    return sorted({v for v in values if start_compact <= v <= end_compact})


def _load_open_trade_dates_cn_sse(
    start_compact: str, end_compact: str
) -> tuple[list[str], CalendarSource]:
    # Primary: tushare trade_cal (SSE open days)
    pro = _get_pro()
    if pro is not None:
        try:
            df = _cached_tushare_dataframe_call(
                pro,
                "trade_cal",
                exchange="SSE",
                start_date=start_compact,
                end_date=end_compact,
                is_open=1,
                fields="cal_date,is_open",
            )
            dates = _extract_open_dates_from_frame(df, start_compact, end_compact)
            if dates:
                return dates, "tushare_trade_cal"
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "tushare trade_cal failed for %s-%s: %s",
                start_compact,
                end_compact,
                exc,
            )

    # Fallback: akshare sina trade-date history
    try:
        import akshare as ak

        df = ak.tool_trade_date_hist_sina()
    except Exception as e:
        raise ValueError(
            "Unable to load SSE open trade dates: tushare unavailable and akshare fallback failed"
        ) from e

    dates = _extract_open_dates_from_frame(df, start_compact, end_compact)
    if not dates:
        raise ValueError(
            f"Unable to load SSE open trade dates between {start_compact} and {end_compact}"
        )
    return dates, "akshare_sina"


def resolve_next_trade_date_cn_sse_strict(
    signal_date: str, lookahead_days: int = 20
) -> NextTradeDateResolution:
    signal_date_iso = _normalize_iso_date(signal_date)
    signal_compact = signal_date_iso.replace("-", "")
    start_compact = signal_compact

    end_compact = (
        datetime.strptime(signal_date_iso, "%Y-%m-%d") + timedelta(days=lookahead_days)
    ).strftime("%Y%m%d")
    open_dates, source = _load_open_trade_dates_cn_sse(start_compact, end_compact)

    if signal_compact not in open_dates:
        raise ValueError(
            f"signal_date={signal_date_iso} is not an SSE open trading day"
        )

    calendar = TradingSessionCalendar.from_dates(
        datetime.strptime(value, "%Y%m%d").date() for value in open_dates
    )
    try:
        next_date = calendar.next_session(
            datetime.strptime(signal_compact, "%Y%m%d").date()
        )
    except ValueError as exc:
        raise ValueError(
            f"Unable to resolve next trade date after {signal_date_iso}"
        ) from exc
    next_compact = next_date.strftime("%Y%m%d")
    next_iso = f"{next_compact[:4]}-{next_compact[4:6]}-{next_compact[6:8]}"
    return NextTradeDateResolution(
        signal_date_iso=signal_date_iso,
        signal_date_compact=signal_compact,
        next_trade_date_iso=next_iso,
        next_trade_date_compact=next_compact,
        calendar_source=source,
    )
