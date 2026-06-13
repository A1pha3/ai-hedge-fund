"""Tests for src/screening/watchlist.py — P0-5 智能自选池."""

from __future__ import annotations

import json

import pytest

from src.screening.watchlist import (
    MAX_SCORE_HISTORY_DAYS,
    Watchlist,
    WatchlistEntry,
    _dedupe_tags,
    format_watchlist_status,
)


# ---------------------------------------------------------------------------
# _dedupe_tags
# ---------------------------------------------------------------------------


class TestDedupeTags:
    def test_empty(self) -> None:
        assert _dedupe_tags([]) == []

    def test_none(self) -> None:
        assert _dedupe_tags(None) == []

    def test_dedupes(self) -> None:
        assert _dedupe_tags(["银行", "高股息", "银行"]) == ["银行", "高股息"]

    def test_strips_whitespace(self) -> None:
        assert _dedupe_tags([" 银行 ", "  ", "地产"]) == ["银行", "地产"]

    def test_non_string_converted(self) -> None:
        assert _dedupe_tags([123, "银行"]) == ["123", "银行"]


# ---------------------------------------------------------------------------
# WatchlistEntry
# ---------------------------------------------------------------------------


class TestWatchlistEntry:
    def test_to_dict(self) -> None:
        entry = WatchlistEntry(ticker="000001", name="平安银行", added_at="2026-01-01", tags=["银行"])
        d = entry.to_dict()
        assert d["ticker"] == "000001"
        assert d["name"] == "平安银行"
        assert d["tags"] == ["银行"]

    def test_from_dict(self) -> None:
        d = {"ticker": "000001", "name": "平安银行", "added_at": "2026-01-01"}
        entry = WatchlistEntry.from_dict(d)
        assert entry.ticker == "000001"
        assert entry.name == "平安银行"

    def test_from_dict_missing_fields(self) -> None:
        d = {"ticker": "000001"}
        entry = WatchlistEntry.from_dict(d)
        assert entry.ticker == "000001"
        assert entry.name == ""

    def test_from_dict_dedupes_tags(self) -> None:
        d = {"ticker": "A", "name": "N", "tags": ["银行", "银行", "地产"]}
        entry = WatchlistEntry.from_dict(d)
        assert entry.tags == ["银行", "地产"]

    def test_from_dict_bad_tags_type(self) -> None:
        d = {"ticker": "A", "name": "N", "tags": "not a list"}
        entry = WatchlistEntry.from_dict(d)
        assert entry.tags == []

    def test_from_dict_bad_history_type(self) -> None:
        d = {"ticker": "A", "name": "N", "score_history": "bad"}
        entry = WatchlistEntry.from_dict(d)
        assert entry.score_history == []


# ---------------------------------------------------------------------------
# Watchlist (file-backed)
# ---------------------------------------------------------------------------


class TestWatchlist:
    def test_new_watchlist_creates_file(self, tmp_path) -> None:
        path = tmp_path / "wl.json"
        wl = Watchlist(path)
        wl.add("000001", "平安银行")
        assert path.exists()

    def test_add_and_list(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "平安银行", tags=["银行"])
        wl.add("000002", "万科", tags=["地产"])
        entries = wl.list()
        assert len(entries) == 2

    def test_add_empty_ticker_raises(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        with pytest.raises(ValueError, match="ticker 不能为空"):
            wl.add("", "test")

    def test_remove(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "平安")
        assert wl.remove("000001") is True
        assert len(wl.list()) == 0

    def test_remove_nonexistent(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        assert wl.remove("999999") is False

    def test_update_score(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "平安")
        wl.update_score("000001", score=0.5, signal="buy", date="2026-01-01")
        history = wl.get_score_history("000001")
        assert len(history) == 1
        assert history[0]["score"] == 0.5
        assert history[0]["signal"] == "buy"

    def test_update_score_same_day_overwrites(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "平安")
        wl.update_score("000001", score=0.5, signal="buy", date="2026-01-01")
        wl.update_score("000001", score=0.7, signal="strong_buy", date="2026-01-01")
        history = wl.get_score_history("000001")
        assert len(history) == 1
        assert history[0]["score"] == 0.7

    def test_update_score_nonexistent_ticker_silent(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.update_score("999999", score=0.5, signal="buy")  # Should not raise

    def test_history_truncation(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "平安")
        for i in range(40):
            wl.update_score("000001", score=float(i) / 100, signal="test", date=f"2026-01-{(i % 28) + 1:02d}")
        history = wl.get_score_history("000001")
        assert len(history) <= MAX_SCORE_HISTORY_DAYS

    def test_get_score_history_nonexistent(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        assert wl.get_score_history("999999") == []

    def test_filter_valid_tickers(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "A")
        wl.add("000002", "B")
        result = wl.filter_valid_tickers(["000001", "000003", "000002"])
        assert result == ["000001", "000002"]

    def test_filter_valid_tickers_empty(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        assert wl.filter_valid_tickers([]) == []

    def test_list_with_tag_filter(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "A", tags=["银行"])
        wl.add("000002", "B", tags=["地产"])
        wl.add("000003", "C", tags=["银行"])
        entries = wl.list(tag="银行")
        assert len(entries) == 2

    def test_contains(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "A")
        assert "000001" in wl
        assert "000002" not in wl

    def test_len(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "A")
        wl.add("000002", "B")
        assert len(wl) == 2

    def test_all_tickers(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000002", "B")
        wl.add("000001", "A")
        assert wl.all_tickers() == ["000001", "000002"]

    def test_add_existing_updates_name(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "OldName")
        wl.add("000001", "NewName")
        entry = wl.get("000001")
        assert entry is not None
        assert entry.name == "NewName"

    def test_persistence(self, tmp_path) -> None:
        path = tmp_path / "wl.json"
        wl = Watchlist(path)
        wl.add("000001", "平安", tags=["银行"])
        wl.update_score("000001", score=0.5, signal="buy", date="2026-01-01")
        # Reload
        wl2 = Watchlist(path)
        assert len(wl2) == 1
        assert wl2.get("000001") is not None
        history = wl2.get_score_history("000001")
        assert len(history) == 1

    def test_load_corrupt_file(self, tmp_path) -> None:
        path = tmp_path / "wl.json"
        path.write_text("NOT JSON", encoding="utf-8")
        wl = Watchlist(path)
        assert len(wl) == 0

    def test_load_missing_structure(self, tmp_path) -> None:
        path = tmp_path / "wl.json"
        path.write_text(json.dumps({"not_watchlist": {}}), encoding="utf-8")
        wl = Watchlist(path)
        assert len(wl) == 0

    def test_get_nonexistent(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        assert wl.get("999999") is None


# ---------------------------------------------------------------------------
# format_watchlist_status
# ---------------------------------------------------------------------------


class TestFormatWatchlistStatus:
    def test_empty_watchlist(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        result = format_watchlist_status(wl)
        assert "自选池为空" in result

    def test_with_entries(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "平安银行")
        wl.update_score("000001", score=0.5, signal="buy", date="2026-01-01")
        result = format_watchlist_status(wl)
        assert "000001" in result
        assert "平安银行" in result

    def test_with_consecutive_lookup(self, tmp_path) -> None:
        wl = Watchlist(tmp_path / "wl.json")
        wl.add("000001", "平安银行")
        wl.update_score("000001", score=0.5, signal="buy", date="2026-01-01")
        lookup = {"000001": {"consecutive_days": 5, "status": "3plus"}}
        result = format_watchlist_status(wl, consecutive_lookup=lookup)
        assert "持续 5 天推荐" in result
