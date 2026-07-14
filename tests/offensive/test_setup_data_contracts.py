"""Tests for versioned setup data contracts and capability evaluation."""

import pytest

from src.screening.offensive.setup_data_contracts import (
    SETUP_REQUIREMENTS_VERSION,
    BTST_CONTRACT,
    OVERSOLD_BOUNCE_CONTRACT,
    SetupCapability,
    SetupDataRequirements,
    evaluate_btst_capability,
    evaluate_oversold_bounce_capability,
    disabled_capability,
)


class TestBTSTCapability:
    def test_full_data_is_scannable_and_eligible(self):
        cap = evaluate_btst_capability(
            price_status="current", price_history_days=120,
            fund_flow_status="current", fund_flow_history_days=25,
            industry_current=True,
        )
        assert cap.scannable is True
        assert cap.plan_eligible is True
        assert cap.degraded is False

    def test_shallow_fund_flow_is_scannable_but_not_eligible(self):
        """4 days fund flow history → degraded, display-only."""
        cap = evaluate_btst_capability(
            price_status="current", price_history_days=120,
            fund_flow_status="current", fund_flow_history_days=4,
            industry_current=True,
        )
        assert cap.scannable is True
        assert cap.degraded is True
        assert cap.plan_eligible is False

    def test_short_window_fund_flow_is_degraded(self):
        """5-19 days → degraded (short window mean)."""
        cap = evaluate_btst_capability(
            price_status="current", price_history_days=120,
            fund_flow_status="current", fund_flow_history_days=15,
            industry_current=True,
        )
        assert cap.scannable is True
        assert cap.degraded is True
        assert cap.plan_eligible is False

    def test_industry_missing_is_degraded(self):
        cap = evaluate_btst_capability(
            price_status="current", price_history_days=120,
            fund_flow_status="current", fund_flow_history_days=25,
            industry_current=False,
        )
        assert cap.scannable is True
        assert cap.degraded is True
        assert cap.plan_eligible is False

    def test_suspended_blocks(self):
        cap = evaluate_btst_capability(
            price_status="suspended", price_history_days=0,
            fund_flow_status="suspended", fund_flow_history_days=0,
            industry_current=False, is_suspended=True,
        )
        assert cap.scannable is False
        assert cap.plan_eligible is False
        assert "suspended" in cap.block_reasons

    def test_price_missing_blocks(self):
        cap = evaluate_btst_capability(
            price_status="missing_unexplained", price_history_days=0,
            fund_flow_status="current", fund_flow_history_days=25,
            industry_current=True,
        )
        assert cap.scannable is False
        assert cap.plan_eligible is False

    def test_fund_flow_unsupported_blocks(self):
        cap = evaluate_btst_capability(
            price_status="current", price_history_days=120,
            fund_flow_status="unsupported", fund_flow_history_days=0,
            industry_current=True,
        )
        assert cap.scannable is False

    def test_price_history_insufficient_blocks(self):
        cap = evaluate_btst_capability(
            price_status="current", price_history_days=3,
            fund_flow_status="current", fund_flow_history_days=25,
            industry_current=True,
        )
        assert cap.scannable is False


class TestOversoldBounceCapability:
    def test_default_disabled(self):
        cap = evaluate_oversold_bounce_capability(
            price_status="current", price_history_days=120,
            fund_flow_status="current", enabled=False,
        )
        assert cap.enabled is False
        assert cap.scannable is False

    def test_enabled_with_full_data(self):
        cap = evaluate_oversold_bounce_capability(
            price_status="current", price_history_days=120,
            fund_flow_status="current", enabled=True,
        )
        assert cap.scannable is True
        assert cap.plan_eligible is True


class TestContracts:
    def test_setup_requirements_version(self):
        assert SETUP_REQUIREMENTS_VERSION == "daily-action-setups-v1"

    def test_btst_contract_fields(self):
        assert BTST_CONTRACT.setup_name == "btst_breakout"
        assert BTST_CONTRACT.requires_price is True
        assert BTST_CONTRACT.requires_fund_flow is True
        assert BTST_CONTRACT.min_price_history_days == 6

    def test_oversold_bounce_contract_fields(self):
        assert OVERSOLD_BOUNCE_CONTRACT.setup_name == "oversold_bounce"
        assert OVERSOLD_BOUNCE_CONTRACT.min_price_history_days == 31


def test_disabled_capability():
    cap = disabled_capability("oversold_bounce")
    assert cap.enabled is False
    assert cap.scannable is False
