"""Direct unit tests for src/tools/ashare_board_utils.py helper functions.

The existing tests/test_ashare_board_detection.py covers the Beijing-92 prefix
edge case end-to-end, but split_ashare_exchange_prefix, get_ashare_symbol, and
to_prefixed_ashare_code had zero direct unit coverage. These tests lock down
their per-exchange behavior.
"""

from __future__ import annotations

import pytest

from src.tools.ashare_board_utils import (
    get_ashare_symbol,
    split_ashare_exchange_prefix,
    to_prefixed_ashare_code,
)


class TestSplitAshareExchangePrefix:
    def test_no_prefix_returns_none_and_symbol(self) -> None:
        assert split_ashare_exchange_prefix("600519") == (None, "600519")

    def test_sh_prefix_extracted(self) -> None:
        assert split_ashare_exchange_prefix("sh600519") == ("sh", "600519")

    def test_sz_prefix_extracted(self) -> None:
        assert split_ashare_exchange_prefix("sz000001") == ("sz", "000001")

    def test_bj_prefix_extracted(self) -> None:
        assert split_ashare_exchange_prefix("bj830879") == ("bj", "830879")

    def test_uppercase_prefix_lowered(self) -> None:
        """Prefixes are case-insensitive (normalized to lower)."""
        assert split_ashare_exchange_prefix("SH600519") == ("sh", "600519")

    def test_non_exchange_prefix_not_split(self) -> None:
        """A 6-digit code starting with a digit is not an exchange prefix."""
        assert split_ashare_exchange_prefix("000001") == (None, "000001")

    def test_none_input_returns_empty(self) -> None:
        assert split_ashare_exchange_prefix(None) == (None, "")

    def test_whitespace_stripped(self) -> None:
        assert split_ashare_exchange_prefix("  sh600519  ") == ("sh", "600519")


class TestGetAshareSymbol:
    @pytest.mark.parametrize(
        "ticker,expected",
        [
            ("600519", "600519"),
            ("sh600519", "600519"),
            ("SZ000001", "000001"),
            ("bj830879", "830879"),
        ],
    )
    def test_symbol_extracted(self, ticker: str, expected: str) -> None:
        assert get_ashare_symbol(ticker) == expected


class TestToPrefixedAshareCode:
    def test_shanghai_symbol_gets_sh_prefix(self) -> None:
        assert to_prefixed_ashare_code("600519") == "sh600519"

    def test_shenzhen_symbol_gets_sz_prefix(self) -> None:
        assert to_prefixed_ashare_code("000001") == "sz000001"

    def test_chinext_symbol_gets_sz_prefix(self) -> None:
        """300xxx is ChiNext (Shenzhen)."""
        assert to_prefixed_ashare_code("300118") == "sz300118"

    def test_beijing_symbol_gets_bj_prefix(self) -> None:
        """8xx is Beijing exchange."""
        assert to_prefixed_ashare_code("830879") == "bj830879"

    def test_already_prefixed_passthrough(self) -> None:
        assert to_prefixed_ashare_code("sh600519") == "sh600519"

    def test_star_market_gets_sh_prefix(self) -> None:
        """68x is STAR market (Shanghai)."""
        assert to_prefixed_ashare_code("688981") == "sh688981"
