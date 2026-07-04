"""Characterization tests for src/utils/llm_json_helpers.py.

extract_json_payload_from_content is a DI orchestrator that tries multiple
JSON-extraction strategies (raw, markdown block, balanced-scan, fallback).
It had zero direct test coverage (extract_balanced_json_candidates has some
coverage in test_utils_bugfixes.py).
"""

from __future__ import annotations

import json
from typing import Any

from src.utils.llm_json_helpers import extract_json_payload_from_content


def _json_loads(s: str) -> dict | None:
    """Real json.loads-based try function (returns None on failure)."""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def _no_fallback(_content: str) -> dict | None:
    return None


class TestExtractJsonPayloadFromContent:
    def test_raw_json_object_at_start(self) -> None:
        result = extract_json_payload_from_content(
            content='{"key": "val"}',
            try_json_loads=_json_loads,
            extract_common_signal_payload=_no_fallback,
        )
        assert result == {"key": "val"}

    def test_raw_json_array_at_start(self) -> None:
        result = extract_json_payload_from_content(
            content="[1, 2, 3]",
            try_json_loads=_json_loads,
            extract_common_signal_payload=_no_fallback,
        )
        assert result == [1, 2, 3]

    def test_tagged_json_code_block(self) -> None:
        content = 'Some text\n```json\n{"k": 1}\n```\nmore text'
        result = extract_json_payload_from_content(
            content=content,
            try_json_loads=_json_loads,
            extract_common_signal_payload=_no_fallback,
        )
        assert result == {"k": 1}

    def test_untagged_code_block_with_json(self) -> None:
        content = '```\n{"k": 2}\n```'
        result = extract_json_payload_from_content(
            content=content,
            try_json_loads=_json_loads,
            extract_common_signal_payload=_no_fallback,
        )
        assert result == {"k": 2}

    def test_balanced_candidate_in_prose(self) -> None:
        """JSON embedded in prose text → balanced-scan extracts it."""
        content = 'The result is {"signal": "bullish", "confidence": 80} as shown.'
        result = extract_json_payload_from_content(
            content=content,
            try_json_loads=_json_loads,
            extract_common_signal_payload=_no_fallback,
        )
        assert result == {"signal": "bullish", "confidence": 80}

    def test_fallback_when_no_json_found(self) -> None:
        """No extractable JSON → extract_common_signal_payload fallback."""
        fallback_result = {"recovered": True}

        def fallback(_content: str) -> dict | None:
            return fallback_result

        result = extract_json_payload_from_content(
            content="no json here at all",
            try_json_loads=_json_loads,
            extract_common_signal_payload=fallback,
        )
        assert result == fallback_result

    def test_returns_none_when_all_strategies_fail(self) -> None:
        result = extract_json_payload_from_content(
            content="plain text with no json",
            try_json_loads=_json_loads,
            extract_common_signal_payload=_no_fallback,
        )
        assert result is None

    def test_braces_inside_string_not_mistaken_for_json(self) -> None:
        """A brace inside a JSON string value shouldn't break balanced scan."""
        content = '{"msg": "use { and } freely"}'
        result = extract_json_payload_from_content(
            content=content,
            try_json_loads=_json_loads,
            extract_common_signal_payload=_no_fallback,
        )
        assert result == {"msg": "use { and } freely"}

    def test_raw_json_takes_priority_over_code_block(self) -> None:
        """If content starts with {, raw strategy is tried first."""
        calls: list[str] = []

        def tracking_loads(s: str) -> dict | None:
            calls.append(s)
            return json.loads(s)

        extract_json_payload_from_content(
            content='{"first": true}',
            try_json_loads=tracking_loads,
            extract_common_signal_payload=_no_fallback,
        )
        # raw strategy should be the first call
        assert calls[0] == '{"first": true}'
