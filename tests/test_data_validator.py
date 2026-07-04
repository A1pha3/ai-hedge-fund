from __future__ import annotations

from src.data.validator import DataPipeline, DataValidator


def test_validate_prices_preserves_only_valid_rows_and_warning_messages(caplog):
    prices = [
        {"time": "2024-01-01", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000},
        {"time": "2024-01-02", "open": 10, "high": 9, "low": 8, "close": 11, "volume": 1000},
        {"time": "bad-date", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000},
    ]

    with caplog.at_level("WARNING"):
        result = DataValidator.validate_prices(prices)

    assert result == [{"time": "2024-01-01", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}]
    assert caplog.messages == ["Price validation errors: ['Price[1]: high < max(open, close)', 'Price[2]: invalid date format']"]


def test_validate_prices_preserves_empty_input():
    assert DataValidator.validate_prices([]) == []


def test_validate_financial_metrics_preserves_warning_only_fields_and_filters_missing_required(caplog):
    metrics = [
        {
            "ticker": "AAPL",
            "report_period": "2024-Q4",
            "price_to_earnings_ratio": -1.0,
            "price_to_book_ratio": -2.0,
            "return_on_equity": 1.5,
            "debt_to_equity": -0.2,
        },
        {"ticker": "", "report_period": "2024-Q4"},
        {"ticker": "MSFT", "report_period": None},
    ]

    with caplog.at_level("WARNING"):
        result = DataValidator.validate_financial_metrics(metrics)

    assert result == [metrics[0]]
    assert caplog.messages == [
        "Metric[0]: negative P/E ratio",
        "Metric[0]: negative P/B ratio",
        "Metric[0]: ROE outside [-1, 1]",
        "Metric[0]: negative debt_to_equity",
        "Financial metrics validation errors: ['Metric[1]: missing ticker', 'Metric[2]: missing report_period']",
    ]


# ---------------------------------------------------------------------------
# DataPipeline.process — dispatch + unknown-type passthrough (was 0 coverage)
# ---------------------------------------------------------------------------

_VALID_PRICE = {"time": "2024-01-01", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}


def test_pipeline_process_prices_routes_through_validate_and_clean():
    """process(valid_prices, 'prices') preserves the valid row."""
    pipeline = DataPipeline()
    result = pipeline.process([_VALID_PRICE], "prices")
    assert result == [_VALID_PRICE]


def test_pipeline_process_prices_filters_invalid_rows():
    """An invalid price row (high < open) is filtered out by the pipeline."""
    bad_price = {"time": "2024-01-01", "open": 10, "high": 9, "low": 8, "close": 11, "volume": 1000}
    pipeline = DataPipeline()
    result = pipeline.process([_VALID_PRICE, bad_price], "prices")
    assert result == [_VALID_PRICE]


def test_pipeline_process_empty_prices_returns_empty():
    pipeline = DataPipeline()
    assert pipeline.process([], "prices") == []


def test_pipeline_process_unknown_type_passthrough():
    """Unknown data_type has no matching branch → data returned unchanged."""
    data = [{"arbitrary": "data"}]
    pipeline = DataPipeline()
    assert pipeline.process(data, "unknown_type") == data


def test_pipeline_process_metrics_routes_through_validate_and_clean():
    valid_metric = {
        "ticker": "AAPL",
        "report_period": "2024-Q4",
        "price_to_earnings_ratio": 25.0,
    }
    pipeline = DataPipeline()
    result = pipeline.process([valid_metric], "metrics")
    assert result == [valid_metric]


def test_default_pipeline_singleton_is_usable():
    """The module-level default_pipeline instance works the same as a fresh one."""
    from src.data.validator import default_pipeline

    assert default_pipeline.process([], "prices") == []
