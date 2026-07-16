"""Versioned setup data dependencies and capability evaluation.

Shared between readiness manifest, scanner, and service. Ensures all three
use the same definition of what each setup needs and what "degraded" means.

Setup requirements version: daily-action-setups-v1

BTST first-version policy (preserves current behavior, not re-validated strategy):
  - Price capability: target-day price exists AND ≥5 prior sessions
  - Fund flow capability: target-day fund flow required
    - 0-4 days history: skip mean condition, degraded
    - 5-19 days: short-window mean, degraded
    - 20+ days: full execution
  - Industry: target-day industry pct missing → skip condition, degraded
  - Confirmed suspension: prohibits new BTST signal

OversoldBounce: default enabled=false; only evaluates readiness when
explicitly enabled via environment control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


SETUP_REQUIREMENTS_VERSION = "daily-action-setups-v1"

# BTST data contract thresholds (preserved from current btst_breakout.py)
_BTST_MIN_PRICE_HISTORY_DAYS = 6  # trigger day + 5 prior
_BTST_FULL_FLOW_HISTORY_DAYS = 20
_BTST_MIN_FLOW_HISTORY_DAYS = 5


class SetupCapabilityStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class SetupCapability:
    """Per-setup, per-ticker readiness evaluation result.

    scannable: setup can run and produce diagnostic results
    plan_eligible: setup result is authorized for new trade planning
    degraded: setup ran but with incomplete data conditions (display-only)
    """
    enabled: bool
    scannable: bool
    plan_eligible: bool
    degraded: bool
    block_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    consumed_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("enabled", "scannable", "plan_eligible", "degraded"):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"{field_name} must be bool")
        if not isinstance(self.block_reasons, (list, tuple)) or any(
            not isinstance(reason, str) for reason in self.block_reasons
        ):
            raise ValueError("block_reasons must contain only strings")
        if not isinstance(self.warnings, (list, tuple)) or any(
            not isinstance(warning, str) for warning in self.warnings
        ):
            raise ValueError("warnings must contain only strings")
        object.__setattr__(self, "block_reasons", tuple(self.block_reasons))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if self.consumed_fingerprint is not None and not _is_sha256(
            self.consumed_fingerprint
        ):
            raise ValueError("consumed_fingerprint must be a sha256 fingerprint")
        if self.scannable and not self.enabled:
            raise ValueError("scannable capability must be enabled")
        if self.degraded and (not self.enabled or not self.scannable):
            raise ValueError("degraded capability must be enabled and scannable")
        if self.plan_eligible and (
            not self.enabled
            or not self.scannable
            or self.degraded
            or self.consumed_fingerprint is None
        ):
            raise ValueError(
                "plan_eligible requires enabled, scannable, non-degraded, "
                "and consumed_fingerprint"
            )


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


@dataclass(frozen=True)
class SetupDataRequirements:
    """Declares what a setup needs. Versioned for compatibility."""
    setup_name: str
    requires_price: bool
    requires_fund_flow: bool
    requires_industry_pct: bool
    min_price_history_days: int
    full_fund_flow_history_days: int
    min_fund_flow_history_days: int


# --- Contract declarations ---

BTST_CONTRACT = SetupDataRequirements(
    setup_name="btst_breakout",
    requires_price=True,
    requires_fund_flow=True,
    requires_industry_pct=True,
    min_price_history_days=_BTST_MIN_PRICE_HISTORY_DAYS,
    full_fund_flow_history_days=_BTST_FULL_FLOW_HISTORY_DAYS,
    min_fund_flow_history_days=_BTST_MIN_FLOW_HISTORY_DAYS,
)

OVERSOLD_BOUNCE_CONTRACT = SetupDataRequirements(
    setup_name="oversold_bounce",
    requires_price=True,
    requires_fund_flow=True,
    requires_industry_pct=False,
    min_price_history_days=31,  # 30-day drop lookback + trigger day
    full_fund_flow_history_days=3,
    min_fund_flow_history_days=3,
)

SETUP_CONTRACTS: dict[str, SetupDataRequirements] = {
    "btst_breakout": BTST_CONTRACT,
    "oversold_bounce": OVERSOLD_BOUNCE_CONTRACT,
}


# --- Capability evaluation ---

def evaluate_btst_capability(
    *,
    price_status: str,  # "current" | "suspended" | etc
    price_history_days: int,
    fund_flow_status: str,
    fund_flow_history_days: int,
    industry_current: bool,
    is_suspended: bool = False,
    is_st: bool = False,
    consumed_fingerprint: str | None = None,
) -> SetupCapability:
    """Evaluate BTST setup capability for a single ticker.

    Preserves current degradation semantics:
    - Suspended/st ST → not scannable, not eligible
    - Price missing/failed → not scannable
    - Price history < 6 days → not scannable (setup will miss anyway)
    - Fund flow missing/failed/unsupported → not scannable
    - Fund flow history 0-19 days → scannable but degraded, not plan_eligible
    - Industry missing → scannable but degraded, not plan_eligible
    - All complete → scannable AND plan_eligible
    """
    block_reasons: list[str] = []
    warnings: list[str] = []

    if is_suspended:
        return SetupCapability(
            enabled=True, scannable=False, plan_eligible=False, degraded=False,
            block_reasons=("suspended",),
        )
    if is_st:
        return SetupCapability(
            enabled=True, scannable=False, plan_eligible=False, degraded=False,
            block_reasons=("st_stock",),
        )

    # Price capability
    if price_status not in ("current",):
        return SetupCapability(
            enabled=True, scannable=False, plan_eligible=False, degraded=False,
            block_reasons=(f"price_{price_status}",),
        )
    if price_history_days < _BTST_MIN_PRICE_HISTORY_DAYS:
        return SetupCapability(
            enabled=True, scannable=False, plan_eligible=False, degraded=False,
            block_reasons=(f"price_history_insufficient_{price_history_days}",),
        )

    # Fund flow capability
    if fund_flow_status not in ("current",):
        return SetupCapability(
            enabled=True, scannable=False, plan_eligible=False, degraded=False,
            block_reasons=(f"fund_flow_{fund_flow_status}",),
        )

    degraded = False
    degradation_reasons: list[str] = []

    if fund_flow_history_days < _BTST_FULL_FLOW_HISTORY_DAYS:
        degraded = True
        if fund_flow_history_days < _BTST_MIN_FLOW_HISTORY_DAYS:
            degradation_reasons.append(f"fund_flow_history_{fund_flow_history_days}d_lt_min_{_BTST_MIN_FLOW_HISTORY_DAYS}d")
        else:
            degradation_reasons.append(f"fund_flow_history_{fund_flow_history_days}d_lt_full_{_BTST_FULL_FLOW_HISTORY_DAYS}d")

    if not industry_current:
        degraded = True
        degradation_reasons.append("industry_data_missing")

    if not degraded and consumed_fingerprint is None:
        degraded = True
        degradation_reasons.append("consumed_fingerprint_unavailable")

    if consumed_fingerprint is None:
        return SetupCapability(
            enabled=True,
            scannable=True,
            plan_eligible=False,
            degraded=True,
            warnings=tuple(degradation_reasons),
        )
    return SetupCapability(
        enabled=True,
        scannable=True,
        plan_eligible=not degraded,
        degraded=degraded,
        block_reasons=tuple(block_reasons),
        warnings=tuple(degradation_reasons) if degraded else (),
        consumed_fingerprint=consumed_fingerprint if not degraded else None,
    )


def evaluate_oversold_bounce_capability(
    *,
    price_status: str,
    price_history_days: int,
    fund_flow_status: str,
    is_suspended: bool = False,
    is_st: bool = False,
    enabled: bool = False,
    consumed_fingerprint: str | None = None,
) -> SetupCapability:
    """Evaluate OversoldBounce capability. Default disabled unless explicitly enabled."""
    if not enabled:
        return SetupCapability(
            enabled=False, scannable=False, plan_eligible=False, degraded=False,
            block_reasons=("setup_disabled_by_default",),
        )
    if is_suspended:
        return SetupCapability(
            enabled=True, scannable=False, plan_eligible=False, degraded=False,
            block_reasons=("suspended",),
        )
    if is_st:
        return SetupCapability(
            enabled=True, scannable=False, plan_eligible=False, degraded=False,
            block_reasons=("st_stock",),
        )
    if price_status != "current" or price_history_days < 31:
        return SetupCapability(
            enabled=True, scannable=False, plan_eligible=False, degraded=False,
            block_reasons=(f"price_unavailable_or_history_{price_history_days}",),
        )
    if fund_flow_status != "current":
        return SetupCapability(
            enabled=True, scannable=False, plan_eligible=False, degraded=False,
            block_reasons=(f"fund_flow_{fund_flow_status}",),
        )
    if consumed_fingerprint is None:
        return SetupCapability(
            enabled=True,
            scannable=True,
            plan_eligible=False,
            degraded=True,
            warnings=("consumed_fingerprint_unavailable",),
        )
    return SetupCapability(
        enabled=True,
        scannable=True,
        plan_eligible=True,
        degraded=False,
        consumed_fingerprint=consumed_fingerprint,
    )


def disabled_capability(setup_name: str, reason: str = "setup_disabled") -> SetupCapability:
    """Return a disabled capability for a setup that's not enabled."""
    return SetupCapability(
        enabled=False, scannable=False, plan_eligible=False, degraded=False,
        block_reasons=(reason,),
    )
