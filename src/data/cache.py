import logging
from typing import Any

logger = logging.getLogger(__name__)


class Cache:
    """In-memory cache for API responses."""

    def __init__(self):
        self._prices_cache: dict[str, list[dict[str, Any]]] = {}
        self._financial_metrics_cache: dict[str, list[dict[str, Any]]] = {}
        self._line_items_cache: dict[str, list[dict[str, Any]]] = {}
        self._insider_trades_cache: dict[str, list[dict[str, Any]]] = {}
        self._company_news_cache: dict[str, list[dict[str, Any]]] = {}

    def _merge_data(self, existing: list[dict] | None, new_data: list[dict], key_field: str) -> list[dict]:
        """Merge existing and new data, avoiding duplicates based on a key field."""
        if not existing:
            return new_data

        # Create a set of existing keys for O(1) lookup
        existing_keys = {item.get(key_field) for item in existing if key_field in item}

        # Only add items that don't exist yet; track dropped entries
        kept: list[dict] = []
        dropped_missing_key = 0
        dropped_duplicate = 0
        for item in new_data:
            if key_field not in item:
                dropped_missing_key += 1
            elif item[key_field] in existing_keys:
                dropped_duplicate += 1
            else:
                kept.append(item)

        if dropped_missing_key > 0:
            logger.warning(
                "Cache._merge_data: dropped %d item(s) missing key_field '%s' out of %d new items",
                dropped_missing_key,
                key_field,
                len(new_data),
            )

        merged = existing.copy()
        merged.extend(kept)
        return merged

    def get_prices(self, ticker: str) -> list[dict[str, Any]] | None:
        """Get cached price data if available."""
        return self._prices_cache.get(ticker)

    def set_prices(self, ticker: str, data: list[dict[str, Any]]):
        """Append new price data to cache."""
        self._prices_cache[ticker] = self._merge_data(self._prices_cache.get(ticker), data, key_field="time")

    def get_financial_metrics(self, ticker: str) -> list[dict[str, Any]] | None:
        """Get cached financial metrics if available."""
        return self._financial_metrics_cache.get(ticker)

    def set_financial_metrics(self, ticker: str, data: list[dict[str, Any]]):
        """Append new financial metrics to cache."""
        self._financial_metrics_cache[ticker] = self._merge_data(self._financial_metrics_cache.get(ticker), data, key_field="report_period")

    def get_line_items(self, ticker: str) -> list[dict[str, Any]] | None:
        """Get cached line items if available."""
        return self._line_items_cache.get(ticker)

    def set_line_items(self, ticker: str, data: list[dict[str, Any]]):
        """Append new line items to cache."""
        self._line_items_cache[ticker] = self._merge_data(self._line_items_cache.get(ticker), data, key_field="report_period")

    def get_insider_trades(self, ticker: str) -> list[dict[str, Any]] | None:
        """Get cached insider trades if available."""
        return self._insider_trades_cache.get(ticker)

    def set_insider_trades(self, ticker: str, data: list[dict[str, Any]]):
        """Append new insider trades to cache."""
        self._insider_trades_cache[ticker] = self._merge_data(self._insider_trades_cache.get(ticker), data, key_field="filing_date")  # Could also use transaction_date if preferred

    def get_company_news(self, ticker: str) -> list[dict[str, Any]] | None:
        """Get cached company news if available."""
        return self._company_news_cache.get(ticker)

    def set_company_news(self, ticker: str, data: list[dict[str, Any]]):
        """Append new company news to cache."""
        self._company_news_cache[ticker] = self._merge_data(self._company_news_cache.get(ticker), data, key_field="date")


# Global cache instance
_cache = Cache()


def get_cache() -> Cache:
    """Get the global cache instance."""
    return _cache
