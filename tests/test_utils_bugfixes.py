"""Tests for progress tracker, LLM helpers, and streaming utilities."""

from src.utils.progress import AgentProgress
from src.utils.llm import (
    _is_rate_limit_error,
    _is_transport_error,
    _compute_retry_delay,
    create_default_response,
    extract_json_from_response,
    _try_json_loads,
)
from src.utils.llm_json_helpers import extract_balanced_json_candidates
from src.utils.numeric import clip, clamp_unit_interval


# ---------------------------------------------------------------------------
# Bug 8: progress handler type hint and invocation
# ---------------------------------------------------------------------------

class TestProgressHandlerSignature:
    def test_handler_receives_five_arguments(self):
        """Handler registered via register_handler must receive
        (agent_name, ticker, status, analysis, timestamp) -- 5 args."""
        progress = AgentProgress()
        received = {}

        def handler(agent_name, ticker, status, analysis, timestamp):
            received.update(
                agent_name=agent_name,
                ticker=ticker,
                status=status,
                analysis=analysis,
                timestamp=timestamp,
            )

        progress.register_handler(handler)
        progress.update_status("test_agent", "AAPL", "Running", analysis="{}")
        assert received["agent_name"] == "test_agent"
        assert received["ticker"] == "AAPL"
        assert received["status"] == "Running"
        assert received["timestamp"] is not None

    def test_unregister_handler_stops_callbacks(self):
        progress = AgentProgress()
        call_count = {"n": 0}

        def handler(*args):
            call_count["n"] += 1

        progress.register_handler(handler)
        progress.update_status("agent1", None, "Step 1")
        assert call_count["n"] == 1

        progress.unregister_handler(handler)
        progress.update_status("agent1", None, "Step 2")
        assert call_count["n"] == 1  # Not called again

    def test_multiple_handlers(self):
        progress = AgentProgress()
        log = []

        def handler_a(*args):
            log.append("a")

        def handler_b(*args):
            log.append("b")

        progress.register_handler(handler_a)
        progress.register_handler(handler_b)
        progress.update_status("agent1", None, "Step")
        assert "a" in log and "b" in log


# ---------------------------------------------------------------------------
# LLM error classification
# ---------------------------------------------------------------------------

class TestLLMErrorClassification:
    def test_rate_limit_429(self):
        assert _is_rate_limit_error(Exception("429 Too Many Requests"))

    def test_rate_limit_text(self):
        assert _is_rate_limit_error(Exception("rate limit exceeded"))

    def test_rate_limit_usage(self):
        assert _is_rate_limit_error(Exception("usage limit exceeded for quota"))

    def test_not_rate_limit(self):
        assert not _is_rate_limit_error(Exception("internal server error"))

    def test_transport_timeout(self):
        assert _is_transport_error(TimeoutError("timed out"))

    def test_transport_connection(self):
        assert _is_transport_error(ConnectionError("connection refused"))

    def test_transport_read_timeout(self):
        assert _is_transport_error(Exception("ReadTimeout error"))

    def test_not_transport(self):
        assert not _is_transport_error(Exception("invalid API key"))


# ---------------------------------------------------------------------------
# Retry delay computation
# ---------------------------------------------------------------------------

class TestRetryDelay:
    def test_rate_limit_backoff_bounded(self):
        error = Exception("429")
        delay = _compute_retry_delay(5, error)
        assert delay <= 10.0

    def test_transport_backoff_bounded(self):
        error = TimeoutError("timed out")
        delay = _compute_retry_delay(5, error)
        assert delay <= 3.0

    def test_first_attempt_rate_limit(self):
        error = Exception("rate limit exceeded")
        delay = _compute_retry_delay(0, error)
        assert delay == 2.0


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

class TestJsonExtraction:
    def test_try_json_loads_valid(self):
        assert _try_json_loads('{"a": 1}') == {"a": 1}

    def test_try_json_loads_invalid(self):
        assert _try_json_loads("not json") is None

    def test_try_json_loads_trailing_comma(self):
        assert _try_json_loads('{"a": 1,}') == {"a": 1}

    def test_try_json_loads_empty(self):
        assert _try_json_loads("") is None

    def test_extract_from_markdown_code_block(self):
        content = '```json\n{"signal": "bullish", "confidence": 80}\n```'
        result = extract_json_from_response(content)
        assert result is not None
        assert result["signal"] == "bullish"

    def test_extract_balanced_candidates(self):
        text = 'prefix {"a": 1} middle {"b": 2} suffix'
        candidates = extract_balanced_json_candidates(text)
        assert len(candidates) == 2


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

class TestNumericHelpers:
    def test_clip_within_range(self):
        assert clip(0.5, 0.0, 1.0) == 0.5

    def test_clip_above(self):
        assert clip(1.5, 0.0, 1.0) == 1.0

    def test_clip_below(self):
        assert clip(-0.5, 0.0, 1.0) == 0.0

    def test_clamp_unit_normal(self):
        assert clamp_unit_interval(0.5) == 0.5

    def test_clamp_unit_above(self):
        assert clamp_unit_interval(2.0) == 1.0

    def test_clamp_unit_negative(self):
        assert clamp_unit_interval(-1.0) == 0.0

    def test_clamp_unit_none(self):
        assert clamp_unit_interval(None) == 0.0

    def test_clamp_unit_nan(self):
        assert clamp_unit_interval(float("nan")) == 0.0


# ---------------------------------------------------------------------------
# Default response creation
# ---------------------------------------------------------------------------

class TestDefaultResponse:
    def test_create_default_response_with_basic_types(self):
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str
            value: float
            count: int

        result = create_default_response(TestModel)
        assert result.name == "Error in analysis, using default"
        assert result.value == 0.0
        assert result.count == 0
