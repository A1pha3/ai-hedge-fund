from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class JsonBraceScanState:
    brace_count: int = 0
    start_idx: int = -1
    in_string: bool = False
    escape_next: bool = False


def extract_balanced_json_candidates(content: str) -> list[str]:
    """Finds balanced JSON object candidates while ignoring braces inside strings."""
    candidates: list[str] = []
    state = JsonBraceScanState()
    for index, char in enumerate(content):
        if _consume_string_character(state, char):
            continue
        if char == "{":
            _open_json_candidate(state, index)
            continue
        if char == "}":
            _close_json_candidate(content=content, candidates=candidates, state=state, index=index)
    return candidates


def _consume_string_character(state: JsonBraceScanState, char: str) -> bool:
    if state.in_string:
        if state.escape_next:
            state.escape_next = False
            return True
        if char == "\\":
            state.escape_next = True
            return True
        if char == '"':
            state.in_string = False
        return True
    if char == '"':
        state.in_string = True
        return True
    return False


def _open_json_candidate(state: JsonBraceScanState, index: int) -> None:
    if state.brace_count == 0:
        state.start_idx = index
    state.brace_count += 1


def _close_json_candidate(*, content: str, candidates: list[str], state: JsonBraceScanState, index: int) -> None:
    if state.brace_count <= 0:
        return
    state.brace_count -= 1
    if state.brace_count == 0 and state.start_idx != -1:
        candidates.append(content[state.start_idx : index + 1])
        state.start_idx = -1


def extract_json_payload_from_content(
    *,
    content: str,
    try_json_loads: Callable[[str], dict | None],
    extract_common_signal_payload: Callable[[str], dict | None],
) -> dict | None:
    if content.startswith("{") or content.startswith("["):
        parsed = try_json_loads(content)
        if parsed is not None:
            return parsed

    for code_block in _extract_markdown_json_blocks(content):
        parsed = try_json_loads(code_block)
        if parsed is not None:
            return parsed

    for json_str in extract_balanced_json_candidates(content):
        parsed = try_json_loads(json_str)
        if parsed is not None:
            return parsed

    return extract_common_signal_payload(content)


def _extract_markdown_json_blocks(content: str) -> list[str]:
    blocks: list[str] = []
    tagged_block = _extract_code_block(content, "```json", 7)
    if tagged_block is not None:
        blocks.append(tagged_block)
    untagged_block = _extract_code_block(content, "```", 3)
    if untagged_block is not None and (untagged_block.startswith("{") or untagged_block.startswith("[")):
        blocks.append(untagged_block)
    return blocks


def _extract_code_block(content: str, marker: str, marker_length: int) -> str | None:
    block_start = content.find(marker)
    if block_start == -1:
        return None
    block_text = content[block_start + marker_length :]
    block_end = block_text.find("```")
    if block_end == -1:
        return None
    return block_text[:block_end].strip()
