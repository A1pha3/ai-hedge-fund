"""P2 (2026-06-05) tests for profile routing contract.

Key invariants:
  1. Conservative must be at least as restrictive as aggressive across all gates.
  2. Default contract is valid and balanced.
  3. Override mechanism preserves invariants.
"""

from __future__ import annotations

import pytest

from src.paper_trading.btst_profile_routing import (
    DEFAULT_PROFILE_ROUTING_CONTRACT,
    Gate,
    ProfileName,
    ProfileRoutingContract,
    ProfileRoutingHook,
    ProfileRoutingRule,
    resolve_profile_routing_contract,
)


class TestDefaultContract:
    def test_default_contract_is_valid(self) -> None:
        # Default contract must validate.
        assert DEFAULT_PROFILE_ROUTING_CONTRACT.schema_version == 1
        assert DEFAULT_PROFILE_ROUTING_CONTRACT.name == "default_btst_v1"

    def test_conservative_select_threshold_higher_than_aggressive(self) -> None:
        cons_normal = DEFAULT_PROFILE_ROUTING_CONTRACT.conservative.hook_for("normal_trade")
        agg_normal = DEFAULT_PROFILE_ROUTING_CONTRACT.aggressive.hook_for("normal_trade")
        assert cons_normal.select_threshold >= agg_normal.select_threshold

    def test_conservative_rank_cap_lower_or_equal(self) -> None:
        cons_normal = DEFAULT_PROFILE_ROUTING_CONTRACT.conservative.hook_for("normal_trade")
        agg_normal = DEFAULT_PROFILE_ROUTING_CONTRACT.aggressive.hook_for("normal_trade")
        assert cons_normal.rank_cap <= agg_normal.rank_cap

    def test_halt_blocks_both_profiles(self) -> None:
        cons_halt = DEFAULT_PROFILE_ROUTING_CONTRACT.conservative.hook_for("halt")
        agg_halt = DEFAULT_PROFILE_ROUTING_CONTRACT.aggressive.hook_for("halt")
        assert cons_halt.gate_action == "block"
        assert agg_halt.gate_action == "block"


class TestRestrictiveInvariants:
    def test_conservative_lower_select_threshold_rejected(self) -> None:
        with pytest.raises(Exception, match="select_threshold"):
            ProfileRoutingContract(
                schema_version=1,
                name="bad",
                conservative=ProfileRoutingRule(
                    profile=ProfileName.CONSERVATIVE,
                    rules={"normal_trade": ProfileRoutingHook(select_threshold=0.3, rank_cap=10)},
                ),
                aggressive=ProfileRoutingRule(
                    profile=ProfileName.AGGRESSIVE,
                    rules={"normal_trade": ProfileRoutingHook(select_threshold=0.5, rank_cap=10)},
                ),
            )

    def test_conservative_higher_rank_cap_rejected(self) -> None:
        with pytest.raises(Exception, match="rank_cap"):
            ProfileRoutingContract(
                schema_version=1,
                name="bad",
                conservative=ProfileRoutingRule(
                    profile=ProfileName.CONSERVATIVE,
                    rules={"normal_trade": ProfileRoutingHook(rank_cap=20)},
                ),
                aggressive=ProfileRoutingRule(
                    profile=ProfileName.AGGRESSIVE,
                    rules={"normal_trade": ProfileRoutingHook(rank_cap=10)},
                ),
            )

    def test_conservative_admits_when_aggressive_blocks_rejected(self) -> None:
        with pytest.raises(Exception, match="admit"):
            ProfileRoutingContract(
                schema_version=1,
                name="bad",
                conservative=ProfileRoutingRule(
                    profile=ProfileName.CONSERVATIVE,
                    rules={"shadow_only": ProfileRoutingHook(gate_action="admit")},
                ),
                aggressive=ProfileRoutingRule(
                    profile=ProfileName.AGGRESSIVE,
                    rules={"shadow_only": ProfileRoutingHook(gate_action="block")},
                ),
            )

    def test_conservative_skips_confirmation_required_by_aggressive_rejected(self) -> None:
        with pytest.raises(Exception, match="confirmation"):
            ProfileRoutingContract(
                schema_version=1,
                name="bad",
                conservative=ProfileRoutingRule(
                    profile=ProfileName.CONSERVATIVE,
                    rules={"normal_trade": ProfileRoutingHook(confirmation_required=False)},
                ),
                aggressive=ProfileRoutingRule(
                    profile=ProfileName.AGGRESSIVE,
                    rules={"normal_trade": ProfileRoutingHook(confirmation_required=True)},
                ),
            )

    def test_conservative_position_size_higher_than_aggressive_rejected(self) -> None:
        with pytest.raises(Exception, match="position_size_scale"):
            ProfileRoutingContract(
                schema_version=1,
                name="bad",
                conservative=ProfileRoutingRule(
                    profile=ProfileName.CONSERVATIVE,
                    rules={"normal_trade": ProfileRoutingHook(position_size_scale=1.2)},
                ),
                aggressive=ProfileRoutingRule(
                    profile=ProfileName.AGGRESSIVE,
                    rules={"normal_trade": ProfileRoutingHook(position_size_scale=0.8)},
                ),
            )


class TestOverrideMechanism:
    def test_override_preserves_invariants(self) -> None:
        # Tighten conservative and aggressive together — should succeed.
        contract = resolve_profile_routing_contract(
            conservative={"rules": {"normal_trade": ProfileRoutingHook(select_threshold=0.65, rank_cap=4)}},
            aggressive={"rules": {"normal_trade": ProfileRoutingHook(select_threshold=0.55, rank_cap=8)}},
        )
        cons = contract.conservative.hook_for("normal_trade")
        agg = contract.aggressive.hook_for("normal_trade")
        assert cons.select_threshold == 0.65
        assert agg.select_threshold == 0.55
        assert cons.rank_cap == 4
        assert agg.rank_cap == 8


class TestHookForGate:
    def test_known_gate(self) -> None:
        cons = DEFAULT_PROFILE_ROUTING_CONTRACT.conservative
        hook = cons.hook_for("normal_trade")
        assert hook.select_threshold == 0.55

    def test_unknown_gate_returns_empty_hook(self) -> None:
        cons = DEFAULT_PROFILE_ROUTING_CONTRACT.conservative
        hook = cons.hook_for("nonexistent_gate")
        # Should return an empty hook, not raise.
        assert hook.select_threshold is None
        assert hook.rank_cap is None

    def test_gate_enum_works(self) -> None:
        cons = DEFAULT_PROFILE_ROUTING_CONTRACT.conservative
        hook = cons.hook_for(Gate.HALT)
        assert hook.gate_action == "block"
