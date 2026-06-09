"""Tests for _call_tushare_dataframe_api exponential backoff retry (可靠性 #2)."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.tools.tushare_api import _call_tushare_dataframe_api


class TestTushareRetryBackoff:
    """可靠性 #2: tushare API 调用 exponential backoff 重试。"""

    def test_success_first_attempt(self) -> None:
        """首次调用成功直接返回，不重试。"""
        pro = MagicMock()
        expected_df = pd.DataFrame({"close": [10.0]})
        pro.daily.return_value = expected_df

        result = _call_tushare_dataframe_api(pro, "daily", ts_code="000001.SZ")
        assert result is not None
        assert len(result) == 1
        assert pro.daily.call_count == 1

    def test_retry_on_transient_error(self) -> None:
        """瞬时错误触发重试，重试成功返回数据。"""
        pro = MagicMock()
        expected_df = pd.DataFrame({"close": [10.0]})
        # First call fails, second succeeds
        pro.daily.side_effect = [ConnectionError("timeout"), expected_df]

        with patch("src.tools.tushare_api.time.sleep") as mock_sleep:
            result = _call_tushare_dataframe_api(pro, "daily", ts_code="000001.SZ")

        assert result is not None
        assert len(result) == 1
        assert pro.daily.call_count == 2
        # Should have slept once between retries
        mock_sleep.assert_called_once()

    def test_exponential_backoff_delay(self) -> None:
        """重试间隔按指数递增 (base_delay * 2^attempt)，加 ±30% jitter。"""
        pro = MagicMock()
        pro.daily.side_effect = [ConnectionError("err1"), ConnectionError("err2"), pd.DataFrame({"close": [10.0]})]

        with patch.dict("os.environ", {"TUSHARE_MAX_RETRIES": "2", "TUSHARE_RETRY_BASE_DELAY": "1.0"}):
            with patch("src.tools.tushare_api.time.sleep") as mock_sleep:
                # Pin jitter (random.random()) to 0 so factor = 1 + 0*0.3 = 1.0,
                # yielding the exact exponential base without the ±30% spread.
                with patch("random.random", return_value=0.0):
                    result = _call_tushare_dataframe_api(pro, "daily", ts_code="000001.SZ")

        assert result is not None
        assert pro.daily.call_count == 3
        # Sleep calls: 1.0 * 2^0 = 1.0s, 1.0 * 2^1 = 2.0s (jitter pinned to 0)
        calls = mock_sleep.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0] == pytest.approx(1.0)
        assert calls[1][0][0] == pytest.approx(2.0)

    def test_all_retries_exhausted(self) -> None:
        """所有重试用尽后返回 None。"""
        pro = MagicMock()
        pro.daily.side_effect = ConnectionError("always fails")

        with patch.dict("os.environ", {"TUSHARE_MAX_RETRIES": "2"}):
            with patch("src.tools.tushare_api.time.sleep"):
                result = _call_tushare_dataframe_api(pro, "daily", ts_code="000001.SZ")

        assert result is None
        assert pro.daily.call_count == 3  # 1 initial + 2 retries

    def test_non_retryable_error_no_retry(self) -> None:
        """非瞬时错误（TypeError/ValueError）不重试，直接返回 None。"""
        pro = MagicMock()
        pro.daily.side_effect = TypeError("bad argument")

        with patch("src.tools.tushare_api.time.sleep") as mock_sleep:
            result = _call_tushare_dataframe_api(pro, "daily", ts_code="000001.SZ")

        assert result is None
        assert pro.daily.call_count == 1
        mock_sleep.assert_not_called()

    def test_value_error_no_retry(self) -> None:
        """ValueError 不重试。"""
        pro = MagicMock()
        pro.daily.side_effect = ValueError("invalid value")

        result = _call_tushare_dataframe_api(pro, "daily", ts_code="000001.SZ")
        assert result is None
        assert pro.daily.call_count == 1

    def test_attribute_error_no_retry(self) -> None:
        """AttributeError 不重试。"""
        pro = MagicMock()
        pro.daily.side_effect = AttributeError("no such method")

        result = _call_tushare_dataframe_api(pro, "daily", ts_code="000001.SZ")
        assert result is None
        assert pro.daily.call_count == 1

    def test_missing_api_function(self) -> None:
        """API 函数不存在时返回 None。"""
        pro = MagicMock(spec=[])  # no attributes
        result = _call_tushare_dataframe_api(pro, "nonexistent_api")
        assert result is None

    def test_zero_max_retries(self) -> None:
        """TUSHARE_MAX_RETRIES=0 时不重试。"""
        pro = MagicMock()
        pro.daily.side_effect = ConnectionError("fail")

        with patch.dict("os.environ", {"TUSHARE_MAX_RETRIES": "0"}):
            result = _call_tushare_dataframe_api(pro, "daily", ts_code="000001.SZ")

        assert result is None
        assert pro.daily.call_count == 1

    def test_runtime_error_is_retryable(self) -> None:
        """RuntimeError 是瞬时错误，应该重试。"""
        pro = MagicMock()
        pro.daily.side_effect = [RuntimeError("rate limit"), pd.DataFrame({"close": [10.0]})]

        with patch("src.tools.tushare_api.time.sleep"):
            result = _call_tushare_dataframe_api(pro, "daily", ts_code="000001.SZ")

        assert result is not None
        assert pro.daily.call_count == 2
