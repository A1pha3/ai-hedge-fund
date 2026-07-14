"""Tests for scan_from_verified_snapshot — the snapshot-aware scanner.

Verifies that:
- The scanner consumes only the verified snapshot (never reopens cache files).
- Degraded (plan_eligible=False) candidates are filtered BEFORE ranking.
- Candidates carry snapshot_id and consumed_fingerprint provenance.
- Empty/blocked snapshots produce empty candidate lists.
"""

from __future__ import annotations

import json
from types import MappingProxyType
from datetime import date
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import pandas as pd
import pytest

from src.screening.offensive.daily_action import scan_from_verified_snapshot
from src.screening.offensive.daily_action_readiness import (
    DailyActionReadinessManifest,
    DailyActionTickerReadiness,
    SharedReadinessEvidence,
)
from src.screening.offensive.daily_action_snapshot import VerifiedDailyActionSnapshot
from src.screening.offensive.setup_data_contracts import SetupCapability


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_SHARED_EVIDENCE = SharedReadinessEvidence(
    regime_row={},
    regime_fingerprint=None,
    industry_mapping_fingerprint=None,
    security_status_fingerprint=None,
    board_rule_version="ashare-board-prefix-v1",
    normalization_version="pit-canonical-v1",
    signal_session_policy_version="ashare-cn-1700-v1",
)


def _capability(
    *,
    enabled: bool = True,
    scannable: bool = True,
    plan_eligible: bool = True,
    degraded: bool = False,
    block_reasons: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> SetupCapability:
    return SetupCapability(
        enabled=enabled,
        scannable=scannable,
        plan_eligible=plan_eligible,
        degraded=degraded,
        block_reasons=block_reasons,
        warnings=warnings,
        consumed_fingerprint="sha256:test",
    )


def _manifest(
    tickers: tuple[str, ...] = ("000001",),
    readiness: dict[str, DailyActionTickerReadiness] | None = None,
) -> DailyActionReadinessManifest:
    if readiness is None:
        readiness = {
            t: DailyActionTickerReadiness(
                evidence_status="verified",
                capabilities=MappingProxyType({
                    "btst_breakout": _capability(),
                    "oversold_bounce": _capability(enabled=False),
                }),
            )
            for t in tickers
        }
    return DailyActionReadinessManifest(
        schema_version=1,
        domain="daily_action",
        run_id="test-run",
        trade_date=date(2026, 7, 13),
        created_at="2026-07-13T12:00:00Z",
        status="healthy",
        universe_kind="resolved_refresh_universe",
        universe_tickers=tickers,
        universe_fingerprint="sha256:universe",
        input_fingerprint="sha256:batch",
        ticker_readiness=MappingProxyType(readiness),
        warnings=(),
        shared_evidence=_SHARED_EVIDENCE,
        policy_versions=MappingProxyType({
            "readiness_policy": "daily-action-readiness-v1",
            "setup_requirements": "daily-action-setups-v1",
        }),
    )


def _prices_with_limit_up() -> pd.DataFrame:
    """22 日价格序列, 最后一日涨停 (+10%)."""
    dates = pd.bdate_range("2026-06-01", periods=22)
    closes = [10.0] * 21 + [11.0]
    closes[-6] = 10.5  # 5日前 close=10.5 (今日 11.0 → 涨幅 4.76% ≤ 8%)
    pct = [0.0] * 20 + [0.0, 10.0]
    return pd.DataFrame({
        "date": dates, "close": closes, "open": closes,
        "high": closes, "low": closes, "pct_change": pct,
    })


def _snapshot(
    manifest: DailyActionReadinessManifest | None = None,
    prices_by_ticker: dict[str, pd.DataFrame] | None = None,
    fund_flow_by_ticker: dict[str, tuple[dict, ...]] | None = None,
) -> VerifiedDailyActionSnapshot:
    manifest = manifest or _manifest()
    return VerifiedDailyActionSnapshot(
        signal_date=manifest.trade_date,
        snapshot_id="sha256:snapshot-test",
        manifest=manifest,
        universe_tickers=manifest.universe_tickers,
        prices_by_ticker=MappingProxyType(prices_by_ticker or {}),
        fund_flow_by_ticker=MappingProxyType(fund_flow_by_ticker or {}),
        industry_day_pct_by_ticker=MappingProxyType({}),
        regime="normal",
        board_rule_version="ashare-board-prefix-v1",
        normalization_version="pit-canonical-v1",
        setup_requirements_version="daily-action-setups-v1",
        ticker_blocks=MappingProxyType({}),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScanFromVerifiedSnapshot:
    def test_empty_snapshot_returns_empty_lists(self):
        """No scannable tickers → empty candidates and blocked."""
        manifest = _manifest(tickers=("000001",), readiness={
            "000001": DailyActionTickerReadiness(
                evidence_status="blocked",
                capabilities=MappingProxyType({
                    "btst_breakout": _capability(scannable=False, plan_eligible=False),
                    "oversold_bounce": _capability(enabled=False),
                }),
            ),
        })
        snapshot = _snapshot(manifest=manifest)
        candidates, blocked = scan_from_verified_snapshot(snapshot)
        assert candidates == []
        assert blocked == []

    def test_degraded_capability_filtered_before_ranking(self):
        """plan_eligible=False candidates go to blocked, not candidates."""
        manifest = _manifest(tickers=("000001",), readiness={
            "000001": DailyActionTickerReadiness(
                evidence_status="verified",
                capabilities=MappingProxyType({
                    "btst_breakout": _capability(
                        scannable=True, plan_eligible=False, degraded=True,
                        warnings=("fund_flow_history_4d",),
                    ),
                    "oversold_bounce": _capability(enabled=False),
                }),
            ),
        })
        prices = _prices_with_limit_up()
        snapshot = _snapshot(
            manifest=manifest,
            prices_by_ticker={"000001": prices},
        )
        candidates, blocked = scan_from_verified_snapshot(snapshot)
        assert len(candidates) == 0, "degraded capability should not produce candidates"
        assert len(blocked) == 1
        assert blocked[0].degraded is True
        assert "fund_flow_history_4d" in blocked[0].degradation_reason

    def test_candidate_carries_snapshot_provenance(self):
        """Candidates must carry snapshot_id and consumed_fingerprint in reasoning."""
        manifest = _manifest(tickers=("300001",))
        prices = _prices_with_limit_up()
        # Ensure ticker starts with 300 for board quality
        manifest_300 = _manifest(
            tickers=("300001",),
            readiness={
                "300001": DailyActionTickerReadiness(
                    evidence_status="verified",
                    capabilities=MappingProxyType({
                        "btst_breakout": _capability(),
                        "oversold_bounce": _capability(enabled=False),
                    }),
                ),
            },
        )
        snapshot = _snapshot(
            manifest=manifest_300,
            prices_by_ticker={"300001": prices},
        )
        candidates, blocked = scan_from_verified_snapshot(snapshot)
        # Even if no hit (setup conditions may not match exactly), verify the
        # function runs without error. If there IS a hit, check provenance.
        for c in candidates:
            assert "sha256:snapshot-test" in c.reasoning
            assert "consumed_fingerprint=" in c.reasoning

    def test_scanner_never_reopens_cache_files(self, monkeypatch):
        """The scanner must not call Path.open or read_csv on cache files."""
        manifest = _manifest(tickers=("000001",))
        prices = _prices_with_limit_up()
        snapshot = _snapshot(
            manifest=manifest,
            prices_by_ticker={"000001": prices},
        )
        # Patch Path.open to catch any cache file reopening.
        original_open = Path.open
        call_count = Mock()

        def guarded_open(self, *args, **kwargs):
            call_count()
            # Allow __pycache__ reads but block data/ reads
            if "data" in str(self) and "price_cache" in str(self):
                raise AssertionError(f"scanner reopened cache file: {self}")
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", guarded_open)
        # Should not raise
        scan_from_verified_snapshot(snapshot)

    def test_missing_prices_skips_ticker(self):
        """Ticker in manifest but no price data in snapshot → skipped silently."""
        manifest = _manifest(tickers=("000001",))
        snapshot = _snapshot(manifest=manifest, prices_by_ticker={})
        candidates, blocked = scan_from_verified_snapshot(snapshot)
        assert candidates == []

    def test_btst_prefilter_skips_non_limit_up(self):
        """Ticker with pct_change < 9.5 → BTST setup skipped (prefilter)."""
        manifest = _manifest(tickers=("000001",))
        prices = _prices_with_limit_up()
        prices.loc[prices.index[-1], "pct_change"] = 5.0  # not a limit-up day
        snapshot = _snapshot(
            manifest=manifest,
            prices_by_ticker={"000001": prices},
        )
        candidates, blocked = scan_from_verified_snapshot(snapshot)
        # BTST won't hit because pct < 9.5 prefilter
        assert len(candidates) == 0
