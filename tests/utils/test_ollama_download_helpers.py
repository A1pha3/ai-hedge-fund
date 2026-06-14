"""Characterization tests for src/utils/ollama_download_helpers.py.

extract_download_progress and render_download_progress had zero direct test
coverage. stream_download_progress (TextIO streaming) is deferred.
"""
from __future__ import annotations

from src.utils.ollama_download_helpers import (
    extract_download_progress,
    render_download_progress,
)


class TestExtractDownloadProgress:
    def test_percentage_and_phase(self) -> None:
        assert extract_download_progress("pulling manifest: 50%") == (50.0, "pulling manifest")

    def test_decimal_percentage(self) -> None:
        assert extract_download_progress("downloading: 75.5%") == (75.5, "downloading")

    def test_no_percentage_no_phase(self) -> None:
        assert extract_download_progress("success") == (None, None)

    def test_phase_without_percentage(self) -> None:
        assert extract_download_progress("Error: failed") == (None, "Error")

    def test_percentage_without_phase(self) -> None:
        """'50%' has no letter-prefix phase → (50.0, None)."""
        assert extract_download_progress("50%") == (50.0, None)

    def test_multi_word_phase(self) -> None:
        result = extract_download_progress("writing manifest: 10%")
        assert result == (10.0, "writing manifest")

    def test_empty_string(self) -> None:
        assert extract_download_progress("") == (None, None)


class TestRenderDownloadProgress:
    def test_renders_bar_on_percentage_change(self) -> None:
        rendered, pct, phase = render_download_progress("downloading: 50%", 0.0, "")
        assert rendered is not None
        assert "50.0%" in rendered
        assert pct == 50.0
        assert phase == "downloading"

    def test_no_update_when_less_than_one_percent(self) -> None:
        """<1% change from last → no re-render."""
        rendered, pct, phase = render_download_progress("downloading: 50.5%", 50.0, "downloading")
        assert rendered is None
        assert pct == 50.0
        assert phase == "downloading"

    def test_phase_change_triggers_render(self) -> None:
        """Different phase → re-render even at same percentage."""
        rendered, pct, phase = render_download_progress("extracting: 50%", 50.0, "downloading")
        assert rendered is not None
        assert phase == "extracting"

    def test_download_keyword_without_percentage(self) -> None:
        """'downloading' keyword without % → renders raw output."""
        rendered, pct, phase = render_download_progress("downloading layers", 0.0, "")
        assert rendered is not None
        assert "downloading layers" in rendered
        assert pct == 0.0

    def test_no_keyword_no_percentage_returns_none(self) -> None:
        rendered, pct, phase = render_download_progress("unrelated text", 0.0, "")
        assert rendered is None

    def test_custom_bar_length(self) -> None:
        rendered, _, _ = render_download_progress("downloading: 50%", 0.0, "", bar_length=10)
        # 50% of 10 = 5 filled, 5 empty
        assert rendered is not None
        assert rendered.count("█") == 5
        assert rendered.count("░") == 5
