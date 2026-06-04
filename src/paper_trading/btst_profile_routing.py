"""BTST profile routing contract — defines how profile enters upstream decisions.

P2 (2026-06-05): Phase 1 — schema and experimental harness only.

**Design goals:**
- Profile (conservative / aggressive) currently only changes doc rendering thresholds.
- P2 makes profile enter upstream candidate selection / execution rules at well-defined hooks.
- This module defines the contract; actual upstream wiring is added incrementally.

**Routing hooks (where profile can affect decisions):**

1. ``select_threshold`` — score threshold for selecting vs rejecting a candidate.
2. ``rank_cap`` — max number of selected tickers per day.
3. ``gate_action`` — whether to admit a ticker under a given market_gate.
4. ``confirmation_required`` — whether to require intraday confirmation before execution.
5. ``position_size_scale`` — scale factor for position sizing.

**Phase 1 (this module):**
- Pydantic schema for profile routing rules.
- Validator: conservative must be at least as restrictive as aggressive.
- Builder helpers to merge / override.

**Phase 2+ (future work):**
- Actually apply these rules in upstream code paths.
- Walk-forward experiments comparing profiles against closed outcomes.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProfileName(str, Enum):
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"


class Gate(str, Enum):
    NORMAL_TRADE = "normal_trade"
    AGGRESSIVE_TRADE = "aggressive_trade"
    SHADOW_ONLY = "shadow_only"
    HALT = "halt"


class ProfileRoutingHook(BaseModel):
    """One routing hook for a profile under a specific gate."""

    model_config = ConfigDict(extra="forbid")

    select_threshold: float | None = None
    rank_cap: int | None = None
    gate_action: str | None = None  # "admit" / "shadow" / "block"
    confirmation_required: bool | None = None
    position_size_scale: float | None = None
    notes: str | None = None


class ProfileRoutingRule(BaseModel):
    """Routing rules for one profile across all gates."""

    model_config = ConfigDict(extra="forbid")

    profile: ProfileName
    rules: dict[str, ProfileRoutingHook] = Field(default_factory=dict)
    description: str | None = None

    def hook_for(self, gate: str | Gate) -> ProfileRoutingHook:
        """Return the routing hook for the given gate; defaults to an empty hook."""
        gate_key = gate.value if isinstance(gate, Gate) else str(gate)
        return self.rules.get(gate_key, ProfileRoutingHook())


class ProfileRoutingContract(BaseModel):
    """A complete routing contract — conservative + aggressive across all gates."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    name: str
    conservative: ProfileRoutingRule
    aggressive: ProfileRoutingRule
    notes: str | None = None

    @model_validator(mode="after")
    def _conservative_must_be_at_least_as_restrictive(self) -> "ProfileRoutingContract":
        """Conservative must NOT have looser thresholds than aggressive.

        Specifically:
          - ``select_threshold``: conservative >= aggressive (higher bar).
          - ``rank_cap``: conservative <= aggressive (fewer slots).
          - ``gate_action``: conservative must not admit if aggressive blocks.
          - ``confirmation_required``: conservative cannot be False if aggressive is True.
          - ``position_size_scale``: conservative <= aggressive.
        """
        cons = self.conservative
        agg = self.aggressive
        all_gates = set(cons.rules.keys()) | set(agg.rules.keys())
        for gate_key in all_gates:
            c = cons.hook_for(gate_key)
            a = agg.hook_for(gate_key)
            # Skip comparison if either side is None (unconstrained).
            if c.select_threshold is not None and a.select_threshold is not None:
                if c.select_threshold < a.select_threshold:
                    raise ValueError(
                        f"Conservative select_threshold ({c.select_threshold}) must be "
                        f">= aggressive ({a.select_threshold}) for gate={gate_key}"
                    )
            if c.rank_cap is not None and a.rank_cap is not None:
                if c.rank_cap > a.rank_cap:
                    raise ValueError(
                        f"Conservative rank_cap ({c.rank_cap}) must be <= "
                        f"aggressive ({a.rank_cap}) for gate={gate_key}"
                    )
            if c.gate_action is not None and a.gate_action is not None:
                if c.gate_action == "admit" and a.gate_action == "block":
                    raise ValueError(
                        f"Conservative cannot admit if aggressive blocks for gate={gate_key}"
                    )
            if c.confirmation_required is False and a.confirmation_required is True:
                raise ValueError(
                    f"Conservative cannot skip confirmation if aggressive requires it "
                    f"for gate={gate_key}"
                )
            if (
                c.position_size_scale is not None
                and a.position_size_scale is not None
                and c.position_size_scale > a.position_size_scale
            ):
                raise ValueError(
                    f"Conservative position_size_scale ({c.position_size_scale}) must be <= "
                    f"aggressive ({a.position_size_scale}) for gate={gate_key}"
                )
        return self


# ---------------------------------------------------------------------------
# Default contracts
# ---------------------------------------------------------------------------

DEFAULT_PROFILE_ROUTING_CONTRACT = ProfileRoutingContract(
    schema_version=1,
    name="default_btst_v1",
    conservative=ProfileRoutingRule(
        profile=ProfileName.CONSERVATIVE,
        description="默认 conservative 风控基线",
        rules={
            "normal_trade": ProfileRoutingHook(
                select_threshold=0.55,
                rank_cap=5,
                gate_action="admit",
                confirmation_required=True,
                position_size_scale=0.8,
                notes="默认 normal_trade 风控基线",
            ),
            "aggressive_trade": ProfileRoutingHook(
                select_threshold=0.55,
                rank_cap=5,
                gate_action="shadow",
                confirmation_required=True,
                position_size_scale=0.8,
            ),
            "shadow_only": ProfileRoutingHook(
                gate_action="shadow",
                confirmation_required=True,
                notes="shadow_only 不下单",
            ),
            "halt": ProfileRoutingHook(
                gate_action="block",
                notes="halt 阶段不下单",
            ),
        },
    ),
    aggressive=ProfileRoutingRule(
        profile=ProfileName.AGGRESSIVE,
        description="更激进的 profile，仅在实验有效证据后启用",
        rules={
            "normal_trade": ProfileRoutingHook(
                select_threshold=0.45,
                rank_cap=10,
                gate_action="admit",
                confirmation_required=False,
                position_size_scale=1.0,
            ),
            "aggressive_trade": ProfileRoutingHook(
                select_threshold=0.45,
                rank_cap=10,
                gate_action="admit",
                confirmation_required=False,
                position_size_scale=1.0,
            ),
            "shadow_only": ProfileRoutingHook(
                gate_action="shadow",
                confirmation_required=False,
            ),
            "halt": ProfileRoutingHook(
                gate_action="block",
            ),
        },
    ),
    notes="P2 phase 1 default contract — conservative vs aggressive on 4 gates",
)


def resolve_profile_routing_contract(
    *,
    conservative: dict[str, Any] | None = None,
    aggressive: dict[str, Any] | None = None,
    base: ProfileRoutingContract | None = None,
) -> ProfileRoutingContract:
    """Build a contract with optional overrides on top of a base."""
    base = base or DEFAULT_PROFILE_ROUTING_CONTRACT
    cons_data = base.conservative.model_dump()
    cons_data.update(conservative or {})
    agg_data = base.aggressive.model_dump()
    agg_data.update(aggressive or {})
    return ProfileRoutingContract(
        schema_version=1,
        name=base.name,
        conservative=ProfileRoutingRule(**cons_data),
        aggressive=ProfileRoutingRule(**agg_data),
        notes=base.notes,
    )
