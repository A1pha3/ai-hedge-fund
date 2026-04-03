from src.graph.state import merge_dicts


def test_merge_dicts_prefers_newer_values():
    original = {"a": 1, "shared": "old"}
    incoming = {"b": 2, "shared": "new"}

    merged = merge_dicts(original, incoming)

    assert merged == {"a": 1, "b": 2, "shared": "new"}
