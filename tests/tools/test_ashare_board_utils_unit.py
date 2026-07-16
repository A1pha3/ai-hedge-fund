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
    is_excluded_ticker,
    limit_up_pct_for_ticker,
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


class TestLimitUpPctForTicker:
    """Board-aware limit-up threshold: 主板 9.5%, 科创/创业 19.5%, 北交所 29.0%.

    BTST setup 名为「涨停突破」, 必须按板块判涨停 — 旧固定 9.5% 会把科创/创业
    的大涨日 (+9.5%~+19.5%, 非涨停) 误判为涨停. 这些测试锁定板块自适应口径.
    """

    def test_main_board_shanghai(self) -> None:
        assert limit_up_pct_for_ticker("600519") == 9.5

    def test_main_board_shenzhen(self) -> None:
        assert limit_up_pct_for_ticker("000001") == 9.5

    def test_star_market_688(self) -> None:
        """科创板 ±20% → 19.5%."""
        assert limit_up_pct_for_ticker("688981") == 19.5

    def test_chinext_300(self) -> None:
        """创业板 ±20% → 19.5%."""
        assert limit_up_pct_for_ticker("300118") == 19.5

    def test_chinext_301(self) -> None:
        """创业板 301 前缀 ±20% → 19.5%."""
        assert limit_up_pct_for_ticker("301308") == 19.5

    def test_beijing_exchange(self) -> None:
        """北交所 ±30% → 29.0%."""
        assert limit_up_pct_for_ticker("830879") == 29.0

    def test_suffix_stripped(self) -> None:
        """带后缀的 ts_code 要正确提取 symbol 后判板块."""
        assert limit_up_pct_for_ticker("688981.SH") == 19.5
        assert limit_up_pct_for_ticker("300118.SZ") == 19.5
        assert limit_up_pct_for_ticker("600519.SH") == 9.5

    def test_main_board_big_move_not_limit_up(self) -> None:
        """语义守卫: 主板 +9.5% 是涨停, 但科创/创业 +9.5% 不是涨停 (要 +19.5%)."""
        assert 9.5 >= limit_up_pct_for_ticker("600519")  # 主板 +9.5% 触发
        assert 9.5 < limit_up_pct_for_ticker("688981")  # 科创 +9.5% 不触发
        assert 19.5 >= limit_up_pct_for_ticker("688981")  # 科创 +19.5% 才触发


class TestExcludedTicker:
    """永久排除票 (退市/数据残缺) 判定 — 锁死核心契约, 防回归."""

    def test_delisted_000004_excluded(self) -> None:
        """000004.SZ 2023-12-31 退市, 必须永久排除."""
        assert is_excluded_ticker("000004") is True
        assert is_excluded_ticker("000004.SZ") is True

    def test_normal_ticker_not_excluded(self) -> None:
        """正常票不受影响."""
        assert is_excluded_ticker("600519") is False
        assert is_excluded_ticker("000001") is False
        assert is_excluded_ticker("300750") is False

    def test_empty_or_none_not_excluded(self) -> None:
        """空输入安全降级, 不判排除 (避免误伤)."""
        assert is_excluded_ticker("") is False
        assert is_excluded_ticker(None) is False

    def test_env_extra_appends_not_replaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """EXTRA_EXCLUDED_TICKERS 只追加, 不覆盖内置 denylist."""
        monkeypatch.setenv("EXTRA_EXCLUDED_TICKERS", "000999,  600001")
        assert is_excluded_ticker("000004") is True  # 内置仍在
        assert is_excluded_ticker("000999") is True  # 追加生效
        assert is_excluded_ticker("600001") is True  # 追加生效 (含空格)
        assert is_excluded_ticker("000001") is False  # 正常票仍通过

    def test_env_empty_does_not_clear_builtin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """空 env 值不误清内置 denylist."""
        monkeypatch.setenv("EXTRA_EXCLUDED_TICKERS", "")
        assert is_excluded_ticker("000004") is True
