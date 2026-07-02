"""NS-17/BH-017 R2 final drain — non-decision-chain silent except observability.

AutoDev C5/Loop 9 (c278): drains the 8 remaining low-severity silent except
patterns in non-decision-chain modules (pdf_exporter, enhanced_cache, ollama,
akshare_news_helpers). Verifies best-effort return values are preserved AND
warning/debug logs are emitted so failures become observable.

Severity / level mapping:
- akshare_news_helpers.sort_news_dataframe → WARNING (MEDIUM, 触及新闻时序数据质量)
- akshare_news_helpers.resolve_stock_name → DEBUG (LOW, 纯展示)
- pdf_exporter._register_cjk_font (2 处) → DEBUG (LOW, 纯展示)
- ollama.is_ollama_installed (2 处) → DEBUG (LOW, CLI 检测)
- enhanced_cache.DiskCache.__init__ cleanup close → DEBUG (LOW, defensive dead code, 不测试)
- enhanced_cache.DiskCache._ensure_conn dead conn close → DEBUG (LOW, 清理已坏连接, 主错误已 log)
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pandas as pd


# ---------------------------------------------------------------------------
# akshare_news_helpers — sort_news_dataframe (WARNING, MEDIUM)
# ---------------------------------------------------------------------------


class TestSortNewsDataframeObservability:
    """sort_news_dataframe 失败必须发 warning (触及新闻时序数据质量)."""

    def test_sort_failure_emits_warning_and_returns_original_df(
        self, caplog
    ) -> None:
        from src.tools.akshare_news_helpers import sort_news_dataframe

        df = pd.DataFrame({"发布时间": ["2026-07-01", "2026-06-30"]})

        with patch("pandas.to_datetime", side_effect=RuntimeError("boom")):
            with caplog.at_level(logging.WARNING, logger="src.tools.akshare_news_helpers"):
                result = sort_news_dataframe(df)

        # Best-effort preserved: returns original df
        assert result is df
        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warn_records) == 1, f"expected 1 WARNING, got {warn_records}"
        msg = warn_records[0].getMessage()
        assert "sort_news_dataframe failed" in msg
        assert "rows=2" in msg

    def test_sort_success_no_warning(self, caplog) -> None:
        from src.tools.akshare_news_helpers import sort_news_dataframe

        df = pd.DataFrame({"发布时间": ["2026-07-01", "2026-06-30"]})
        with caplog.at_level(logging.WARNING, logger="src.tools.akshare_news_helpers"):
            result = sort_news_dataframe(df)
        # Sorted descending by _pub_dt
        assert result.iloc[0]["发布时间"] == "2026-07-01"
        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warn_records) == 0


# ---------------------------------------------------------------------------
# akshare_news_helpers — resolve_stock_name (DEBUG, LOW)
# ---------------------------------------------------------------------------


class TestResolveStockNameObservability:
    def test_resolve_failure_emits_debug_and_returns_empty(self, caplog) -> None:
        from src.tools.akshare_news_helpers import resolve_stock_name

        def boom(ticker: str) -> str:
            raise RuntimeError("api down")

        with caplog.at_level(logging.DEBUG, logger="src.tools.akshare_news_helpers"):
            result = resolve_stock_name(boom, "600519")

        assert result == ""
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 1
        msg = debug_records[0].getMessage()
        assert "resolve_stock_name failed" in msg
        assert "ticker=600519" in msg

    def test_resolve_success_no_debug(self, caplog) -> None:
        from src.tools.akshare_news_helpers import resolve_stock_name

        def fake_lookup(ticker: str) -> str:
            return "贵州茅台"

        with caplog.at_level(logging.DEBUG, logger="src.tools.akshare_news_helpers"):
            result = resolve_stock_name(fake_lookup, "600519")

        assert result == "贵州茅台"
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 0

    def test_resolve_ticker_equals_stock_name_returns_empty_no_debug(
        self, caplog
    ) -> None:
        """当 stock_name == ticker (合法的"无中文名"情况) 不应发 debug."""
        from src.tools.akshare_news_helpers import resolve_stock_name

        def fake_lookup(ticker: str) -> str:
            return ticker  # 合法: 无中文名

        with caplog.at_level(logging.DEBUG, logger="src.tools.akshare_news_helpers"):
            result = resolve_stock_name(fake_lookup, "600519")

        assert result == ""
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 0


# ---------------------------------------------------------------------------
# ollama — is_ollama_installed (DEBUG, LOW)
# ---------------------------------------------------------------------------


class TestIsOllamaInstalledObservability:
    def test_which_failure_emits_debug_and_returns_false(
        self, caplog
    ) -> None:
        from src.utils.ollama import is_ollama_installed

        with patch("platform.system", return_value="Darwin"):
            with patch(
                "subprocess.run",
                side_effect=FileNotFoundError("[Errno 2] No such file or directory: 'which'"),
            ):
                with caplog.at_level(logging.DEBUG, logger="src.utils.ollama"):
                    result = is_ollama_installed()

        assert result is False
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 1
        msg = debug_records[0].getMessage()
        assert "is_ollama_installed" in msg
        assert "which ollama" in msg

    def test_which_success_no_debug(self, caplog) -> None:
        from src.utils.ollama import is_ollama_installed

        class _FakeResult:
            returncode = 0

        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.run", return_value=_FakeResult()):
                with caplog.at_level(logging.DEBUG, logger="src.utils.ollama"):
                    result = is_ollama_installed()

        assert result is True
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 0


# ---------------------------------------------------------------------------
# enhanced_cache — DiskCache _ensure_conn close (DEBUG, LOW)
# ---------------------------------------------------------------------------
# Note: __init__ 的 cleanup close failure debug 路径是 defensive dead code —
# `self._conn = self._open_connection()` 原子赋值, 若 _open_connection 抛异常
# 则 self._conn 保持 None, `if self._conn is not None` 永远为 False. drain 保留
# 作为未来重构防御, 但不测试 (路径不可达).


class TestEnhancedCacheCloseObservability:
    """DiskCache _ensure_conn 重连时旧连接关闭失败必须发 debug."""

    def test_ensure_conn_close_failure_emits_debug(
        self, tmp_path: Path, caplog
    ) -> None:
        """When _ensure_conn reconnects AND old connection close fails, debug log emitted."""
        from src.data.enhanced_cache import DiskCache

        # Build a cache with a fake dead connection
        cache = DiskCache(path=str(tmp_path / "test.db"))

        # Inject a fake dead connection whose close() raises
        fake_dead_conn = type(
            "FakeConn",
            (),
            {
                "close": lambda self: (_ for _ in ()).throw(
                    RuntimeError("close dead boom")
                ),
                "row_factory": None,
            },
        )()
        cache._conn = fake_dead_conn
        cache._available = True

        # Force _is_alive to return False so _ensure_conn tries reconnect
        with patch.object(cache, "_is_alive", return_value=False):
            with patch.object(
                cache, "_open_connection", return_value=type("NewConn", (), {"row_factory": None})()
            ):
                with caplog.at_level(logging.DEBUG, logger="src.data.enhanced_cache"):
                    result = cache._ensure_conn()

        # Reconnect succeeded (new connection returned)
        assert result is not None
        debug_records = [
            r for r in caplog.records
            if r.levelno == logging.DEBUG and "dead connection close" in r.getMessage()
        ]
        assert len(debug_records) == 1, (
            f"expected 1 DEBUG for dead conn close, got {debug_records}"
        )


# ---------------------------------------------------------------------------
# pdf_exporter — _register_cjk_font (DEBUG, LOW)
# ---------------------------------------------------------------------------


class TestPdfExporterFontRegisterObservability:
    """pdf_exporter CJK 字体注册失败必须发 debug (纯展示层)."""

    def test_bold_variant_failure_emits_debug(self, caplog) -> None:
        """When bold variant add_font fails, debug log emitted (not silent pass)."""
        from src.reporting.pdf_exporter import _register_cjk_font

        class FakePdf:
            def add_font(self, name, style, path, uni=True):
                if style == "B":
                    raise RuntimeError("bold register failed")

        with patch("pathlib.Path.exists", return_value=True):
            with caplog.at_level(logging.DEBUG, logger="src.reporting.pdf_exporter"):
                result = _register_cjk_font(FakePdf())  # type: ignore[arg-type]

        # Regular variant succeeded → returns name
        assert result is not None
        debug_records = [
            r for r in caplog.records
            if r.levelno == logging.DEBUG and "bold variant" in r.getMessage()
        ]
        assert len(debug_records) == 1, (
            f"expected 1 DEBUG for bold variant failure, got {debug_records}"
        )

    def test_candidate_failure_emits_debug(self, caplog) -> None:
        """When entire candidate font add_font fails, debug log emitted (not silent continue)."""
        from src.reporting.pdf_exporter import _register_cjk_font

        class FakePdf:
            def add_font(self, name, style, path, uni=True):
                raise RuntimeError("candidate register failed")

        with patch("pathlib.Path.exists", return_value=True):
            with caplog.at_level(logging.DEBUG, logger="src.reporting.pdf_exporter"):
                result = _register_cjk_font(FakePdf())  # type: ignore[arg-type]

        # All candidates failed → returns None
        assert result is None
        debug_records = [
            r for r in caplog.records
            if r.levelno == logging.DEBUG and "candidate register failed" in r.getMessage()
        ]
        # Multiple candidates may fail, each emits a debug log
        assert len(debug_records) >= 1, (
            f"expected >=1 DEBUG for candidate failures, got {debug_records}"
        )

    def test_success_no_debug(self, caplog) -> None:
        from src.reporting.pdf_exporter import _register_cjk_font

        class FakePdf:
            def add_font(self, name, style, path, uni=True):
                pass  # success

        with patch("pathlib.Path.exists", return_value=True):
            with caplog.at_level(logging.DEBUG, logger="src.reporting.pdf_exporter"):
                result = _register_cjk_font(FakePdf())  # type: ignore[arg-type]

        assert result is not None
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) == 0
