import pytest

from src.targets.short_trade_forward_label_helpers import build_short_trade_forward_labels


def test_build_short_trade_forward_labels_surfaces_fast_confirm_retention_and_tail() -> None:
    labels = build_short_trade_forward_labels(
        entry_price=10.0,
        forward_days=[
            {"high": 10.45, "close": 10.02},
            {"high": 10.70, "close": 10.18},
            {"high": 10.92, "close": 10.12},
            {"high": 11.05, "close": 10.20},
            {"high": 11.40, "close": 10.28},
            {"high": 11.85, "close": 10.44},
            {"high": 12.05, "close": 10.62},
            {"high": 12.25, "close": 10.80},
            {"high": 12.10, "close": 10.68},
        ],
    )

    assert labels["label_fast_confirm"] is True
    assert labels["label_retention"] is True
    assert labels["label_tail_20"] is True
    assert labels["max_high_return_t1_t2"] == pytest.approx(0.07)
    assert labels["positive_close_count_t2_t4"] == 3
    assert labels["mean_close_return_t2_t4"] == pytest.approx((0.018 + 0.012 + 0.02) / 3)
    assert labels["max_high_return_t2_t9"] == pytest.approx(0.225)


def test_build_short_trade_forward_labels_returns_false_when_follow_through_is_missing() -> None:
    labels = build_short_trade_forward_labels(
        entry_price=10.0,
        forward_days=[
            {"high": 10.10, "close": 9.96},
            {"high": 10.15, "close": 9.98},
            {"high": 10.18, "close": 9.95},
            {"high": 10.22, "close": 9.92},
        ],
    )

    assert labels["label_fast_confirm"] is False
    assert labels["label_retention"] is False
    assert labels["label_tail_20"] is False
    assert labels["positive_close_count_t2_t4"] == 0
    assert labels["max_high_return_t2_t9"] == pytest.approx(0.022)


def test_build_short_trade_forward_labels_rejects_non_positive_entry_price() -> None:
    with pytest.raises(ValueError, match="entry_price must be positive"):
        build_short_trade_forward_labels(entry_price=0.0, forward_days=[{"high": 1.0, "close": 1.0}])


def test_build_short_trade_forward_labels_rejects_nan_forward_prices() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        build_short_trade_forward_labels(
            entry_price=10.0,
            forward_days=[
                {"high": float("nan"), "close": 10.1},
            ],
        )


def test_data_sufficient_true_when_at_least_3_forward_days() -> None:
    labels = build_short_trade_forward_labels(
        entry_price=10.0,
        forward_days=[
            {"high": 10.10, "close": 10.00},
            {"high": 10.05, "close": 9.98},
            {"high": 10.02, "close": 9.95},
        ],
    )
    assert labels["data_sufficient"] is True
    # With 3 days, labels are computed (booleans), not None
    assert labels["label_fast_confirm"] is False
    assert labels["label_retention"] is False
    assert labels["label_tail_20"] is False


def test_data_sufficient_false_when_fewer_than_3_forward_days() -> None:
    labels = build_short_trade_forward_labels(
        entry_price=10.0,
        forward_days=[
            {"high": 10.50, "close": 10.30},
            {"high": 10.80, "close": 10.60},
        ],
    )
    assert labels["data_sufficient"] is False
    assert labels["observed_forward_days"] == 2
    # Labels should be None when data is insufficient
    assert labels["label_fast_confirm"] is None
    assert labels["label_retention"] is None
    assert labels["label_tail_20"] is None


def test_data_sufficient_false_when_zero_forward_days() -> None:
    labels = build_short_trade_forward_labels(
        entry_price=10.0,
        forward_days=[],
    )
    assert labels["data_sufficient"] is False
    assert labels["observed_forward_days"] == 0
    assert labels["label_fast_confirm"] is None
    assert labels["label_retention"] is None
    assert labels["label_tail_20"] is None
