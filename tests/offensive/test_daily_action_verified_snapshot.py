"""Tests for the verified immutable Daily Action PIT snapshot (schema v2).

The fixture builds a self-consistent evidence chain through the production
manifest builder: it writes price/fund-flow caches, fingerprints them with the
same canonical PIT functions the refresh uses, feeds those fingerprints into
``build_daily_action_readiness``, and publishes the canonical manifest. The
loader then re-reads the caches, recomputes the fingerprints, and verifies them
against the manifest — so a historical mutation blocks the ticker while a
future-dated append leaves the verified snapshot identical.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pandas as pd
import pytest

from src.screening.offensive.cache_readiness import (
    DailyActionRefreshResult,
    FundFlowStatus,
    PriceStatus,
    SuspensionEvidence,
    TickerRefreshOutcome,
    derive_stats_from_outcomes,
    universe_fingerprint,
)
from src.screening.offensive.daily_action_readiness import (
    SharedReadinessEvidence,
    _fingerprint as _manifest_fingerprint,
    build_daily_action_readiness,
    publish_daily_action_readiness,
)
from src.screening.offensive.daily_action_snapshot import (
    FrozenFlowRow,
    FrozenPriceRow,
    load_verified_daily_action_snapshot,
)
from src.screening.offensive.pit_evidence import (
    canonical_fingerprint,
    canonical_flow_fingerprint,
    canonical_price_fingerprint,
)
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION

SIGNAL_DATE = date(2026, 7, 13)
_MANIFEST_NAME = "daily_action_readiness_20260713.json"


# ---------------------------------------------------------------------------
# Deterministic evidence helpers
# ---------------------------------------------------------------------------


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-07-09",
                "open": "9.80",
                "high": "10.10",
                "low": "9.70",
                "close": "10.00",
                "pct_change": "1.00",
                "volume": "900",
            },
            {
                "date": "2026-07-10",
                "open": "10.00",
                "high": "10.50",
                "low": "9.90",
                "close": "10.20",
                "pct_change": "2.00",
                "volume": "1000",
            },
            {
                "date": "2026-07-13",
                "open": "10.20",
                "high": "11.00",
                "low": "10.10",
                "close": "10.90",
                "pct_change": "6.86",
                "volume": "1500",
            },
        ]
    )


def _flow_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-07-10",
                "close": "10.20",
                "pct_change": "2.00",
                "main_net_inflow": "120000",
                "main_net_pct": "3.10",
            },
            {
                "date": "2026-07-13",
                "close": "10.90",
                "pct_change": "6.86",
                "main_net_inflow": "185000",
                "main_net_pct": "4.20",
            },
        ]
    )


def _shared_evidence(universe: tuple[str, ...]) -> SharedReadinessEvidence:
    regime_row = {"trade_date": SIGNAL_DATE.isoformat(), "regime": "normal"}
    industry_by_ticker = {ticker: "银行" for ticker in universe}
    industry_day_pct = {ticker: 1.5 for ticker in universe}
    security_status_by_ticker = {ticker: "listed" for ticker in universe}
    return SharedReadinessEvidence(
        as_of_date=SIGNAL_DATE,
        regime_row=regime_row,
        industry_by_ticker=industry_by_ticker,
        industry_day_pct=industry_day_pct,
        security_status_by_ticker=security_status_by_ticker,
        regime_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "regime_row": regime_row}),
        industry_fingerprint=_fingerprint(
            {
                "as_of_date": SIGNAL_DATE.isoformat(),
                "industry_by_ticker": industry_by_ticker,
                "industry_day_pct": industry_day_pct,
            }
        ),
        security_fingerprint=_fingerprint(
            {"as_of_date": SIGNAL_DATE.isoformat(), "security_status_by_ticker": security_status_by_ticker}
        ),
        board_rule_version="ashare-board-prefix-v1",
        normalization_version="pit-canonical-v1",
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )


def _write_cache(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _build_and_publish(
    root: Path,
    *,
    tickers: tuple[str, ...] = ("000001",),
    price_frames: dict[str, pd.DataFrame] | None = None,
    flow_frames: dict[str, pd.DataFrame] | None = None,
) -> SimpleNamespace:
    data_dir = root / "data"
    reports_dir = data_dir / "reports"
    price_dir = data_dir / "price_cache"
    flow_dir = data_dir / "fund_flow_cache"
    price_frames = price_frames or {t: _price_frame() for t in tickers}
    flow_frames = flow_frames or {t: _flow_frame() for t in tickers}

    outcomes: dict[str, TickerRefreshOutcome] = {}
    for ticker in tickers:
        pframe = price_frames[ticker]
        fframe = flow_frames[ticker]
        _write_cache(price_dir / f"{ticker}.csv", pframe)
        _write_cache(flow_dir / f"{ticker}.csv", fframe)
        outcomes[ticker] = TickerRefreshOutcome(
            ticker=ticker,
            price_status=PriceStatus.CURRENT,
            price_history_rows=100,
            fund_flow_status=FundFlowStatus.CURRENT,
            fund_flow_history_rows=25,
            evidence_fingerprints={
                "price": canonical_price_fingerprint(pframe, ticker, SIGNAL_DATE),
                "fund_flow": canonical_flow_fingerprint(fframe, ticker, SIGNAL_DATE),
            },
        )

    universe = tuple(sorted(outcomes))
    refresh = DailyActionRefreshResult(
        trade_date=SIGNAL_DATE,
        universe_tickers=universe,
        universe_fingerprint=universe_fingerprint(universe),
        daily_batch_fingerprint=_fingerprint({"batch": SIGNAL_DATE.isoformat()}),
        suspension_evidence=SuspensionEvidence.available(
            SIGNAL_DATE,
            set(),
            source_fingerprint=canonical_fingerprint("suspension", "*", []),
        ),
        outcomes=outcomes,
        stats=derive_stats_from_outcomes(outcomes),
    )
    manifest = build_daily_action_readiness(
        refresh,
        _shared_evidence(universe),
        run_id="fixture-snapshot-v2",
        oversold_bounce_enabled=False,
    )
    publish_daily_action_readiness(manifest, reports_dir)

    return SimpleNamespace(
        data_dir=data_dir,
        reports_dir=reports_dir,
        price_path=price_dir / f"{tickers[0]}.csv",
        flow_path=flow_dir / f"{tickers[0]}.csv",
        manifest_path=reports_dir / _MANIFEST_NAME,
        loader_args={
            "signal_date": SIGNAL_DATE,
            "reports_dir": reports_dir,
            "data_dir": data_dir,
        },
    )


def mutate_price_close(price_path: Path, target_date: date, new_close: float) -> None:
    frame = pd.read_csv(price_path, dtype=str)
    stamp = target_date.strftime("%Y%m%d")
    mask = frame["date"].str.replace("-", "", regex=False).str[:8] == stamp
    frame.loc[mask, "close"] = str(new_close)
    frame.to_csv(price_path, index=False)


def append_future_price(price_path: Path, future_date: date, close: float) -> None:
    frame = pd.read_csv(price_path, dtype=str)
    row = {
        "date": future_date.isoformat(),
        "open": str(close),
        "high": str(close),
        "low": str(close),
        "close": str(close),
        "pct_change": "0.00",
        "volume": "2000",
    }
    frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
    frame.to_csv(price_path, index=False)


@pytest.fixture
def v2_snapshot_fixture(tmp_path: Path) -> SimpleNamespace:
    return _build_and_publish(tmp_path)


# ---------------------------------------------------------------------------
# Manifest state handling
# ---------------------------------------------------------------------------


class TestManifestStates:
    def test_missing_manifest_is_fail_closed(self, tmp_path):
        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=tmp_path, data_dir=tmp_path
        )
        assert result.snapshot is None
        assert result.global_reason == "daily_action_readiness_missing"

    def test_invalid_utf8_manifest_is_rejected(self, tmp_path):
        (tmp_path / _MANIFEST_NAME).write_bytes(b"\xff\xfe")
        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=tmp_path, data_dir=tmp_path
        )
        assert result.snapshot is None
        assert result.global_reason == "readiness_manifest_invalid"

    def test_invalid_json_manifest_is_rejected(self, tmp_path):
        (tmp_path / _MANIFEST_NAME).write_text("{not json", encoding="utf-8")
        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=tmp_path, data_dir=tmp_path
        )
        assert result.snapshot is None
        assert result.global_reason == "readiness_manifest_invalid"

    def test_schema_v1_has_no_new_entry_authority(self, v2_snapshot_fixture):
        raw = json.loads(v2_snapshot_fixture.manifest_path.read_text(encoding="utf-8"))
        raw["schema_version"] = 1
        v2_snapshot_fixture.manifest_path.write_text(
            json.dumps(raw), encoding="utf-8"
        )
        result = load_verified_daily_action_snapshot(
            **v2_snapshot_fixture.loader_args
        )
        assert result.snapshot is None
        assert result.global_reason == "readiness_schema_unsupported"

    def test_date_mismatch_is_rejected(self, v2_snapshot_fixture):
        other_name = "daily_action_readiness_20260714.json"
        (v2_snapshot_fixture.reports_dir / other_name).write_bytes(
            v2_snapshot_fixture.manifest_path.read_bytes()
        )
        result = load_verified_daily_action_snapshot(
            date(2026, 7, 14),
            reports_dir=v2_snapshot_fixture.reports_dir,
            data_dir=v2_snapshot_fixture.data_dir,
        )
        assert result.snapshot is None
        assert result.global_reason == "readiness_date_mismatch"

    def test_not_healthy_manifest_is_rejected(self, v2_snapshot_fixture):
        raw = json.loads(v2_snapshot_fixture.manifest_path.read_text(encoding="utf-8"))
        raw["status"] = "degraded"
        body = {k: v for k, v in raw.items() if k != "content_fingerprint"}
        raw["content_fingerprint"] = _manifest_fingerprint(body)
        v2_snapshot_fixture.manifest_path.write_text(
            json.dumps(raw), encoding="utf-8"
        )
        result = load_verified_daily_action_snapshot(
            **v2_snapshot_fixture.loader_args
        )
        assert result.snapshot is None
        assert result.global_reason == "readiness_manifest_not_healthy"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_valid_manifest_loads_snapshot(self, v2_snapshot_fixture):
        result = load_verified_daily_action_snapshot(**v2_snapshot_fixture.loader_args)
        assert result.snapshot is not None
        assert result.snapshot.universe_tickers == ("000001",)
        assert result.snapshot.ticker_blocks == {}

    def test_prices_and_flows_are_frozen_records(self, v2_snapshot_fixture):
        snapshot = load_verified_daily_action_snapshot(
            **v2_snapshot_fixture.loader_args
        ).snapshot
        assert snapshot is not None
        prices = snapshot.prices_by_ticker["000001"]
        flows = snapshot.fund_flow_by_ticker["000001"]
        assert isinstance(prices, tuple)
        assert all(isinstance(row, FrozenPriceRow) for row in prices)
        assert isinstance(flows, tuple)
        assert all(isinstance(row, FrozenFlowRow) for row in flows)

    def test_reference_price_returns_final_close(self, v2_snapshot_fixture):
        snapshot = load_verified_daily_action_snapshot(
            **v2_snapshot_fixture.loader_args
        ).snapshot
        assert snapshot is not None
        assert snapshot.reference_price("000001") == pytest.approx(10.90)

    def test_reference_price_raises_for_unknown_ticker(self, v2_snapshot_fixture):
        snapshot = load_verified_daily_action_snapshot(
            **v2_snapshot_fixture.loader_args
        ).snapshot
        assert snapshot is not None
        with pytest.raises(KeyError):
            snapshot.reference_price("999999")

    def test_setup_context_carries_consumed_fingerprint(self, v2_snapshot_fixture):
        snapshot = load_verified_daily_action_snapshot(
            **v2_snapshot_fixture.loader_args
        ).snapshot
        assert snapshot is not None
        context = snapshot.setup_context("000001", "btst_breakout")
        assert context is not None
        assert context.setup_name == "btst_breakout"
        assert context.consumed_fingerprint == (
            snapshot.manifest.ticker_readiness["000001"]
            .capabilities["btst_breakout"]
            .consumed_fingerprint
        )
        assert context.regime == "normal"
        assert context.industry_day_pct == pytest.approx(1.5)

    def test_pit_projection_excludes_future_rows(self, v2_snapshot_fixture):
        append_future_price(v2_snapshot_fixture.price_path, date(2026, 7, 14), 20.0)
        snapshot = load_verified_daily_action_snapshot(
            **v2_snapshot_fixture.loader_args
        ).snapshot
        assert snapshot is not None
        latest = snapshot.prices_by_ticker["000001"][-1]
        assert latest.trade_date == date(2026, 7, 13)

    def test_scannable_tickers_reflect_plan_eligibility(self, v2_snapshot_fixture):
        snapshot = load_verified_daily_action_snapshot(
            **v2_snapshot_fixture.loader_args
        ).snapshot
        assert snapshot is not None
        assert snapshot.scannable_tickers == ("000001",)


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_snapshot_is_frozen(self, v2_snapshot_fixture):
        snapshot = load_verified_daily_action_snapshot(
            **v2_snapshot_fixture.loader_args
        ).snapshot
        assert snapshot is not None
        with pytest.raises(FrozenInstanceError):
            snapshot.regime = "crisis"  # type: ignore[misc]

    def test_prices_mapping_is_immutable(self, v2_snapshot_fixture):
        snapshot = load_verified_daily_action_snapshot(
            **v2_snapshot_fixture.loader_args
        ).snapshot
        assert snapshot is not None
        assert isinstance(snapshot.prices_by_ticker, MappingProxyType)
        with pytest.raises(TypeError):
            snapshot.prices_by_ticker["000001"] = ()  # type: ignore[index]

    def test_frozen_price_row_is_immutable(self, v2_snapshot_fixture):
        snapshot = load_verified_daily_action_snapshot(
            **v2_snapshot_fixture.loader_args
        ).snapshot
        assert snapshot is not None
        row = snapshot.prices_by_ticker["000001"][0]
        assert isinstance(row.close, Decimal)
        with pytest.raises(FrozenInstanceError):
            row.close = Decimal("1")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PIT verification (mutation detection)
# ---------------------------------------------------------------------------


class TestPitVerification:
    def test_historical_price_mutation_blocks_ticker(self, v2_snapshot_fixture):
        first = load_verified_daily_action_snapshot(**v2_snapshot_fixture.loader_args)
        assert first.snapshot is not None
        mutate_price_close(v2_snapshot_fixture.price_path, date(2026, 7, 10), 999.0)
        second = load_verified_daily_action_snapshot(**v2_snapshot_fixture.loader_args)
        assert second.ticker_blocks["000001"] == ("pit_fingerprint_mismatch",)
        assert "000001" not in second.snapshot.scannable_tickers

    def test_future_append_does_not_change_verified_snapshot(
        self, v2_snapshot_fixture
    ):
        first = load_verified_daily_action_snapshot(**v2_snapshot_fixture.loader_args)
        append_future_price(v2_snapshot_fixture.price_path, date(2026, 7, 14), 20.0)
        second = load_verified_daily_action_snapshot(**v2_snapshot_fixture.loader_args)
        assert first.snapshot is not None
        assert second.snapshot is not None
        assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
        assert second.ticker_blocks == {}

    def test_deleting_historical_row_blocks_ticker(self, v2_snapshot_fixture):
        frame = pd.read_csv(v2_snapshot_fixture.price_path, dtype=str)
        frame = frame[frame["date"].str.replace("-", "", regex=False) != "20260710"]
        frame.to_csv(v2_snapshot_fixture.price_path, index=False)
        result = load_verified_daily_action_snapshot(**v2_snapshot_fixture.loader_args)
        assert result.ticker_blocks["000001"] == ("pit_fingerprint_mismatch",)

    def test_missing_price_cache_blocks_scannable_ticker(self, v2_snapshot_fixture):
        v2_snapshot_fixture.price_path.unlink()
        result = load_verified_daily_action_snapshot(**v2_snapshot_fixture.loader_args)
        assert "price_data_missing" in result.ticker_blocks["000001"]
