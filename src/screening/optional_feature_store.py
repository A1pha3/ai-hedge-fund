"""Local optional feature snapshots for auto screening.

This module is intentionally read-only from the scorer's point of view.  Provider
network calls belong in refresh code, not in score_batch().
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd

from src.screening.scoring_feature_quality import ObservationStatus


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
class OptionalObservation(Mapping[str, object]):
    """One snapshot observation with read-only mapping compatibility."""

    status: ObservationStatus
    values: Mapping[str, object] = field()
    source_fingerprint: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def __getitem__(self, key: str) -> object:
        return self.values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)


@dataclass(frozen=True)
class OptionalFeatureStore:
    base_dir: Path | str = Path("data/feature_cache")
    max_stale_days: int = 0
    allow_stale: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_dir", Path(self.base_dir))

    def load_intraday_metrics(
        self, trade_date: str, tickers: list[str]
    ) -> OptionalObservation:
        return self._load_metrics(_INTRADAY_PREFIX, trade_date, tickers)

    def load_fund_flow_metrics(
        self, trade_date: str, tickers: list[str]
    ) -> OptionalObservation:
        return self._load_metrics(_FUND_FLOW_PREFIX, trade_date, tickers)

    def load_manifest(self, trade_date: str) -> dict[str, Any]:
        path = self.base_dir / f"{_MANIFEST_PREFIX}_{trade_date}.json"
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
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

    def _load_metrics(
        self, prefix: str, trade_date: str, tickers: list[str]
    ) -> OptionalObservation:
        return self._load_metrics_with_meta(prefix, trade_date, tickers)[0]

    def _load_metrics_with_meta(
        self,
        prefix: str,
        trade_date: str,
        tickers: list[str],
    ) -> tuple[OptionalObservation, str | None, bool]:
        resolved = self._resolve_snapshot_path(prefix, trade_date)
        if resolved is None:
            return (
                OptionalObservation(ObservationStatus.UNAVAILABLE, {}, None),
                None,
                False,
            )
        path, snapshot_date, is_stale = resolved
        source_fingerprint: str | None = None
        try:
            source_bytes = path.read_bytes()
            source_fingerprint = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
            df = pd.read_csv(
                io.BytesIO(source_bytes),
                dtype={"ticker": str, "trade_date": str},
            )
        except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
            return (
                OptionalObservation(
                    ObservationStatus.FAILED,
                    {},
                    source_fingerprint,
                ),
                snapshot_date,
                is_stale,
            )
        if "ticker" not in df.columns:
            return (
                OptionalObservation(
                    ObservationStatus.FAILED,
                    {},
                    source_fingerprint,
                ),
                snapshot_date,
                is_stale,
            )
        df = df.copy()
        df["ticker"] = df["ticker"].astype(str).str.zfill(6)
        if "trade_date" in df.columns:
            df = df[df["trade_date"].astype(str) == str(snapshot_date)]
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
        return (
            OptionalObservation(
                ObservationStatus.SUCCESS,
                result,
                source_fingerprint,
            ),
            snapshot_date,
            is_stale,
        )

    def _resolve_snapshot_path(self, prefix: str, trade_date: str) -> tuple[Path, str, bool] | None:
        exact_path = self.base_dir / f"{prefix}_{trade_date}.csv"
        if exact_path.exists():
            return exact_path, str(trade_date), False
        if not self.allow_stale or self.max_stale_days <= 0:
            return None
        try:
            requested = datetime.strptime(str(trade_date), "%Y%m%d")
        except ValueError:
            return None

        best: tuple[datetime, Path, str] | None = None
        for path in self.base_dir.glob(f"{prefix}_*.csv"):
            snapshot_date = path.stem.removeprefix(f"{prefix}_")
            if len(snapshot_date) != 8 or not snapshot_date.isdigit():
                continue
            try:
                snapshot_dt = datetime.strptime(snapshot_date, "%Y%m%d")
            except ValueError:
                continue
            stale_days = (requested - snapshot_dt).days
            if stale_days < 0 or stale_days > self.max_stale_days:
                continue
            if best is None or snapshot_dt > best[0]:
                best = (snapshot_dt, path, snapshot_date)
        if best is None:
            return None
        return best[1], best[2], True

    def _quality_for_family(
        self,
        *,
        family: str,
        prefix: str,
        trade_date: str,
        tickers: list[str],
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        observation, snapshot_date, is_stale = self._load_metrics_with_meta(
            prefix, trade_date, tickers
        )
        rows = observation.values
        total = len(tickers)
        feature_manifest = (manifest.get("features") or {}).get(family, {})
        provider_failures = int(feature_manifest.get("provider_failures", 0) or 0)
        missing = total - len(rows)
        quality = {
            "coverage": round((len(rows) / total), 4) if total else 0.0,
            "source": (
                "missing"
                if observation.status is ObservationStatus.UNAVAILABLE
                else "snapshot"
            ),
            "trade_date": trade_date,
            "stale": is_stale,
            "provider_failures": provider_failures,
            "missing_tickers": missing,
            "observation_status": observation.status.value,
        }
        if is_stale and snapshot_date is not None:
            quality["snapshot_date"] = snapshot_date
        return quality
