"""TDD guards for ``resolve_zhipu_route_inputs`` truthiness parsing.

BH-036: the env-var path parsed ``ZHIPU_USE_CODING_PLAN`` as a truthy string
(``"1"``/``"true"``/``"yes"``), but the ``api_keys`` dict path used naive
``bool(...)`` — so a string ``"false"`` (or any non-empty string) was coerced
to ``True``, silently enabling the Coding Plan route when a caller intended to
disable it. The web request path (``request.api_keys``) is user-controlled and
can carry string values, so this is reachable, not purely latent. These guards
lock the shared truthy-parser fix (both paths now agree).
"""

from __future__ import annotations

import os

from src.llm.zhipu_model_helpers import resolve_zhipu_route_inputs

# --- api_keys dict path ---


def test_api_keys_string_false_disables_coding_plan() -> None:
    """A string 'false' must NOT enable coding plan (bool('false') is True bug)."""
    _, _, prefer = resolve_zhipu_route_inputs({"ZHIPU_USE_CODING_PLAN": "false"})
    assert prefer is False


def test_api_keys_string_true_enables_coding_plan() -> None:
    _, _, prefer = resolve_zhipu_route_inputs({"ZHIPU_USE_CODING_PLAN": "true"})
    assert prefer is True


def test_api_keys_string_yes_enables_coding_plan() -> None:
    _, _, prefer = resolve_zhipu_route_inputs({"ZHIPU_USE_CODING_PLAN": "yes"})
    assert prefer is True


def test_api_keys_string_one_enables_coding_plan() -> None:
    _, _, prefer = resolve_zhipu_route_inputs({"ZHIPU_USE_CODING_PLAN": "1"})
    assert prefer is True


def test_api_keys_string_zero_disables_coding_plan() -> None:
    _, _, prefer = resolve_zhipu_route_inputs({"ZHIPU_USE_CODING_PLAN": "0"})
    assert prefer is False


def test_api_keys_bool_true_enables() -> None:
    """A Python bool True (registry default) continues to enable."""
    _, _, prefer = resolve_zhipu_route_inputs({"ZHIPU_USE_CODING_PLAN": True})
    assert prefer is True


def test_api_keys_bool_false_disables() -> None:
    _, _, prefer = resolve_zhipu_route_inputs({"ZHIPU_USE_CODING_PLAN": False})
    assert prefer is False


def test_api_keys_missing_disables() -> None:
    _, _, prefer = resolve_zhipu_route_inputs({"ZHIPU_API_KEY": "k"})
    assert prefer is False


# --- env-var path (behavior preserved) ---


def test_env_string_false_disables(monkeypatch) -> None:
    monkeypatch.setenv("ZHIPU_USE_CODING_PLAN", "false")
    _, _, prefer = resolve_zhipu_route_inputs(None)
    assert prefer is False


def test_env_string_true_enables(monkeypatch) -> None:
    monkeypatch.setenv("ZHIPU_USE_CODING_PLAN", "true")
    _, _, prefer = resolve_zhipu_route_inputs(None)
    assert prefer is True


def test_env_unset_disables(monkeypatch) -> None:
    monkeypatch.delenv("ZHIPU_USE_CODING_PLAN", raising=False)
    _, _, prefer = resolve_zhipu_route_inputs(None)
    assert prefer is False
