from src.main import _build_analyst_batches, _get_analyst_concurrency_limit, _order_selected_analysts


def test_build_analyst_batches_respects_limit():
    batches = _build_analyst_batches(["a", "b", "c", "d", "e"], 2)

    assert batches == [["a", "b"], ["c", "d"], ["e"]]


def test_get_analyst_concurrency_limit_defaults_to_two(monkeypatch):
    monkeypatch.delenv("ANALYST_CONCURRENCY_LIMIT", raising=False)

    assert _get_analyst_concurrency_limit() == 2


def test_order_selected_analysts_uses_config_order():
    ordered = _order_selected_analysts(["warren_buffett", "ben_graham", "aswath_damodaran"])

    assert ordered == ["aswath_damodaran", "ben_graham", "warren_buffett"]