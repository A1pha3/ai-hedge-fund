"""BTST outcome ledger — immutable, per-decision outcome records.

P1 (2026-06-05): establishes the outcome ledger that closes the feedback loop
between pre-trade decisions (``operator_summary.json``) and realized results.

**Design principles:**
- Linked to ``operator_summary`` via stable ``decision_id``.
- Never written back into the original ``operator_summary.json``.
- Supports profile / no-trade / only-early-runner / second-entry category tagging.
- Records sample count, coverage, confidence intervals, and regime coverage.
- Idempotent: same ``(decision_id, ticker)`` pair is unique; re-writes replace,
  not append.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OutcomeCategory(str, Enum):
    FORMAL_SELECTED = "formal_selected"
    FORMAL_WATCH = "formal_watch"
    INTERSECTION = "intersection"
    ONLY_EARLY_RUNNER = "only_early_runner"
    SECOND_ENTRY = "second_entry"
    NO_TRADE = "no_trade"
    CONFIRMATION_ONLY = "confirmation_only"


class OutcomeVerdict(str, Enum):
    PROFIT = "profit"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    NO_ENTRY = "no_entry"
    MISSING_DATA = "missing_data"


class OutcomeDataStatus(str, Enum):
    OK = "ok"
    MISSING_PRICE_FRAME = "missing_price_frame"
    MISSING_TRADE_DAY_BAR = "missing_trade_day_bar"
    MISSING_NEXT_TRADE_DAY_BAR = "missing_next_trade_day_bar"
    INCOMPLETE_PRICE_BAR = "incomplete_price_bar"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class TickerOutcome(BaseModel):
    """Outcome for a single ticker within one decision."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    ticker: str
    signal_date: str
    outcome_category: OutcomeCategory
    verdict: OutcomeVerdict
    data_status: OutcomeDataStatus = OutcomeDataStatus.OK

    # Price-based outcome fields (T+1 data).
    trade_close: float | None = None
    next_open: float | None = None
    next_high: float | None = None
    next_close: float | None = None
    next_open_return: float | None = None
    next_high_return: float | None = None
    next_close_return: float | None = None
    next_open_to_close_return: float | None = None
    next_trade_date: str | None = None

    # Context from the pre-trade decision.
    regime_gate_level: str | None = None
    market_gate: str | None = None
    profile: str | None = None
    score_target: float | None = None
    confirm_score: float | None = None
    entry_status: str | None = None

    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


class OutcomeLedgerHeader(BaseModel):
    """Header of an outcome ledger file."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    decision_id: str
    signal_date: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    outcome_count: int = 0
    categories_covered: list[str] = Field(default_factory=list)
    regimes_covered: list[str] = Field(default_factory=list)

    # Aggregate statistics.
    sample_count: int = 0
    profit_count: int = 0
    loss_count: int = 0
    breakeven_count: int = 0
    no_entry_count: int = 0
    missing_data_count: int = 0
    win_rate: float | None = None
    coverage: float | None = None


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------

def build_ticker_outcome(
    *,
    decision_id: str,
    ticker: str,
    signal_date: str,
    outcome_category: str,
    verdict: str,
    price_outcome: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> TickerOutcome:
    """Build a ``TickerOutcome`` from raw price outcome and decision context.

    ``price_outcome`` is expected to come from ``_extract_next_day_outcome``
    or equivalent.
    """
    po = dict(price_outcome or {})
    ctx = dict(context or {})
    data_status = str(po.get("data_status", "ok"))

    return TickerOutcome(
        decision_id=decision_id,
        ticker=ticker,
        signal_date=signal_date,
        outcome_category=outcome_category,
        verdict=verdict,
        data_status=data_status,
        trade_close=po.get("trade_close"),
        next_open=po.get("next_open"),
        next_high=po.get("next_high"),
        next_close=po.get("next_close"),
        next_open_return=po.get("next_open_return"),
        next_high_return=po.get("next_high_return"),
        next_close_return=po.get("next_close_return"),
        next_open_to_close_return=po.get("next_open_to_close_return"),
        next_trade_date=po.get("next_trade_date"),
        regime_gate_level=ctx.get("regime_gate_level"),
        market_gate=ctx.get("market_gate"),
        profile=ctx.get("profile"),
        score_target=ctx.get("score_target"),
        confirm_score=ctx.get("confirm_score"),
        entry_status=ctx.get("entry_status"),
    )


def classify_verdict(
    *,
    next_close_return: float | None = None,
    next_open_return: float | None = None,
    entry_status: str | None = None,
    data_status: str = "ok",
    profit_threshold: float = 0.005,
    loss_threshold: float = -0.005,
) -> str:
    """Classify a ticker outcome as profit / loss / breakeven / no_entry / missing_data.

    Uses the best available return metric:
    1. ``next_close_return`` if available (full-day outcome).
    2. ``next_open_return`` if close is missing (partial outcome).
    3. ``no_entry`` if the ticker was never entered.
    4. ``missing_data`` if price data is unavailable.
    """
    if data_status != "ok":
        return "missing_data"
    if entry_status in {"no_entry", "skipped", "gate_blocked"}:
        return "no_entry"
    ret = next_close_return if next_close_return is not None else next_open_return
    if ret is None:
        return "missing_data"
    if ret > profit_threshold:
        return "profit"
    if ret < loss_threshold:
        return "loss"
    return "breakeven"


def build_ledger_header(
    *,
    decision_id: str,
    signal_date: str,
    outcomes: list[TickerOutcome],
) -> OutcomeLedgerHeader:
    """Build the ledger header with aggregate statistics."""
    total = len(outcomes)
    profit_count = sum(1 for o in outcomes if o.verdict == OutcomeVerdict.PROFIT)
    loss_count = sum(1 for o in outcomes if o.verdict == OutcomeVerdict.LOSS)
    breakeven_count = sum(1 for o in outcomes if o.verdict == OutcomeVerdict.BREAKEVEN)
    no_entry_count = sum(1 for o in outcomes if o.verdict == OutcomeVerdict.NO_ENTRY)
    missing_data_count = sum(1 for o in outcomes if o.verdict == OutcomeVerdict.MISSING_DATA)

    decided = profit_count + loss_count + breakeven_count
    win_rate = round(profit_count / decided, 4) if decided > 0 else None
    coverage = round(decided / total, 4) if total > 0 else None

    categories = sorted({o.outcome_category.value for o in outcomes})
    regimes = sorted({
        o.regime_gate_level
        for o in outcomes
        if o.regime_gate_level and o.regime_gate_level != "n/a"
    })

    return OutcomeLedgerHeader(
        decision_id=decision_id,
        signal_date=signal_date,
        outcome_count=total,
        categories_covered=categories,
        regimes_covered=regimes,
        sample_count=total,
        profit_count=profit_count,
        loss_count=loss_count,
        breakeven_count=breakeven_count,
        no_entry_count=no_entry_count,
        missing_data_count=missing_data_count,
        win_rate=win_rate,
        coverage=coverage,
    )


# ---------------------------------------------------------------------------
# Incremental evidence summary (for operator_summary cross-ref)
# ---------------------------------------------------------------------------

def compute_incremental_evidence(
    ledger_headers: list[OutcomeLedgerHeader],
) -> dict[str, Any]:
    """Compute incremental evidence statistics across multiple ledger runs.

    Returns a dict suitable for the ``incremental_evidence`` section of
    ``operator_summary.json``.
    """
    if not ledger_headers:
        return {
            "status": "insufficient",
            "sample_count": 0,
            "coverage": None,
            "confidence": None,
            "evidence_ref": None,
        }

    total_samples = sum(h.sample_count for h in ledger_headers)
    total_profit = sum(h.profit_count for h in ledger_headers)
    total_decided = sum(
        h.profit_count + h.loss_count + h.breakeven_count for h in ledger_headers
    )
    overall_win_rate = round(total_profit / total_decided, 4) if total_decided > 0 else None
    overall_coverage = (
        round(
            sum(h.profit_count + h.loss_count + h.breakeven_count for h in ledger_headers)
            / total_samples,
            4,
        )
        if total_samples > 0
        else None
    )

    # Simple confidence: if we have >20 decided samples, consider sufficient.
    status = "sufficient" if total_decided >= 20 else "insufficient" if total_decided < 5 else "partial"

    return {
        "status": status,
        "sample_count": total_samples,
        "coverage": overall_coverage,
        "confidence": overall_win_rate,
        "evidence_ref": f"{len(ledger_headers)} ledger files",
    }


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def write_outcome_ledger(
    header: OutcomeLedgerHeader,
    outcomes: list[TickerOutcome],
    path: Path,
) -> Path:
    """Write an outcome ledger to disk using atomic temp-file-and-rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "header": header.model_dump(mode="json"),
        "outcomes": [o.model_dump(mode="json") for o in outcomes],
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".outcome_ledger_",
        suffix=".tmp",
    )
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).rename(path)
    except BaseException:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def read_outcome_ledger(path: Path) -> tuple[OutcomeLedgerHeader, list[TickerOutcome]]:
    """Read and validate an outcome ledger from disk."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    header = OutcomeLedgerHeader(**raw["header"])
    outcomes = [TickerOutcome(**o) for o in raw.get("outcomes", [])]
    return header, outcomes
