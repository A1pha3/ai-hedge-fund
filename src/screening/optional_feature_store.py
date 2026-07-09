"""Local optional feature snapshots for auto screening.

This module is intentionally read-only from the scorer's point of view.  Provider
network calls belong in refresh code, not in score_batch().
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


_INTRADAY_PREFIX = "intraday_short_trade_metrics"
_FUND_FLOW_PREFIX = "daily_fund_flow_metrics"
_MANIFEST_PREFIX = "feature_manifest"
_METRIC_COLUMNS = {
    "flow_60",
    "flow_60_source",
    "close_support_30",
    "close_support_30_source",
    "persist_120",
    "persist_120_source",
    "main_flow_ratio",
    "main_flow_ratio_source",
}


@dataclass(frozen=True)
class OptionalFeatureStore:
    base_dir: Path | str = Path("data/feature_cache")
    max_stale_days: int = 0
    allow_stale: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_dir", Path(self.base_dir))

    def load_intraday_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
        return self._load_metrics(_INTRADAY_PREFIX, trade_date, tickers)

    def load_fund_flow_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
        return self._load_metrics(_FUND_FLOW_PREFIX, trade_date, tickers)

    def load_manifest(self, trade_date: str) -> dict[str, Any]:
        path = self.base_dir / f"{_MANIFEST_PREFIX}_{trade_date}.json"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        return payload if isinstance(payload, dict) else {}

    def build_quality_summary(self, trade_date: str, tickers: list[str]) -> dict[str, Any]:
        unique_tickers = sorted({str(ticker).zfill(6) for ticker in tickers})
        manifest = self.load_manifest(trade_date)
        return {
            "optional_features": {
                "intraday_short_trade_metrics": self._quality_for_family(
                    family="intraday_short_trade_metrics",
                    prefix=_INTRADAY_PREFIX,
                    trade_date=trade_date,
                    tickers=unique_tickers,
                    manifest=manifest,
                ),
                "daily_fund_flow_metrics": self._quality_for_family(
                    family="daily_fund_flow_metrics",
                    prefix=_FUND_FLOW_PREFIX,
                    trade_date=trade_date,
                    tickers=unique_tickers,
                    manifest=manifest,
                ),
            }
        }

    def _load_metrics(self, prefix: str, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
        path = self.base_dir / f"{prefix}_{trade_date}.csv"
        if not path.exists():
            return {}
        df = pd.read_csv(path, dtype={"ticker": str, "trade_date": str})
        if df.empty or "ticker" not in df.columns:
            return {}
        df = df.copy()
        df["ticker"] = df["ticker"].astype(str).str.zfill(6)
        if "trade_date" in df.columns:
            df = df[df["trade_date"].astype(str) == str(trade_date)]
        wanted = {str(ticker).zfill(6) for ticker in tickers}
        df = df[df["ticker"].isin(wanted)]
        result: dict[str, dict[str, Any]] = {}
        for _, row in df.iterrows():
            metrics: dict[str, Any] = {}
            for column in _METRIC_COLUMNS:
                if column not in row.index:
                    continue
                value = row[column]
                if pd.isna(value):
                    continue
                metrics[column] = value.item() if hasattr(value, "item") else value
            if metrics:
                result[str(row["ticker"]).zfill(6)] = metrics
        return result

    def _quality_for_family(
        self,
        *,
        family: str,
        prefix: str,
        trade_date: str,
        tickers: list[str],
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        rows = self._load_metrics(prefix, trade_date, tickers)
        total = len(tickers)
        feature_manifest = (manifest.get("features") or {}).get(family, {})
        provider_failures = int(feature_manifest.get("provider_failures", 0) or 0)
        missing = total - len(rows)
        return {
            "coverage": round((len(rows) / total), 4) if total else 0.0,
            "source": "snapshot" if rows else "missing",
            "trade_date": trade_date,
            "stale": False,
            "provider_failures": provider_failures,
            "missing_tickers": missing,
        }
