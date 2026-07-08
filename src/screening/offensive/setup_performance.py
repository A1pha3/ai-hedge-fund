"""Paper-trading setup performance evaluator.

Uses the realized EXIT records in ``data/paper_trading_backtest/journal.jsonl``
as the local first-principles evidence for setup/regime decisions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


_REALIZED_RE = re.compile(r"realized=([+-]?\d+(?:\.\d+)?)%")


@dataclass(frozen=True)
class SetupPerformance:
    """Summary of realized closed-trade returns for one setup/regime slice."""

    n: int
    winrate: float
    expected_return: float
    avg_gain: float
    avg_loss: float
    by_regime: dict[str, "SetupPerformance"] = field(default_factory=dict)


@dataclass(frozen=True)
class SetupPerformanceReport:
    """Setup performance grouped from a paper-trading journal."""

    total_exits: int
    by_setup: dict[str, SetupPerformance]
    skipped_exits: int = 0  # EXIT records without parseable realized marker (NS-18 disclosure)


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _parse_realized_return(reasoning: object) -> float | None:
    match = _REALIZED_RE.search(str(reasoning or ""))
    if not match:
        return None
    return float(match.group(1)) / 100.0


def _summarize_returns(returns: Iterable[float]) -> SetupPerformance:
    values = list(returns)
    n = len(values)
    if n == 0:
        return SetupPerformance(n=0, winrate=0.0, expected_return=0.0, avg_gain=0.0, avg_loss=0.0)
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    return SetupPerformance(
        n=n,
        winrate=len(wins) / n,
        expected_return=sum(values) / n,
        avg_gain=sum(wins) / len(wins) if wins else 0.0,
        avg_loss=sum(losses) / len(losses) if losses else 0.0,
    )


def summarize_setup_performance(
    journal_path: Path | str = Path("data/paper_trading_backtest/journal.jsonl"),
    *,
    regimes_by_date: dict[str, str] | None = None,
) -> SetupPerformanceReport:
    """Summarize realized EXIT performance by setup and optional regime.

    ``journal_path`` should point at the backtest journal, not the runtime
    paper-trading instance. Only EXIT records with a parseable
    ``realized=...%`` marker are counted.
    """
    by_setup: dict[str, list[float]] = {}
    by_setup_regime: dict[str, dict[str, list[float]]] = {}
    regimes_by_date = regimes_by_date or {}

    total_journal_exits = 0
    for rec in _load_jsonl(Path(journal_path)):
        if rec.get("action") != "EXIT":
            continue
        total_journal_exits += 1
        realized = _parse_realized_return(rec.get("reasoning"))
        if realized is None:
            continue
        setup = str(rec.get("setup") or "unknown")
        by_setup.setdefault(setup, []).append(realized)

        regime = regimes_by_date.get(str(rec.get("date") or ""), "")
        if regime:
            by_setup_regime.setdefault(setup, {}).setdefault(str(regime), []).append(realized)

    skipped = total_journal_exits - sum(len(v) for v in by_setup.values())

    summaries: dict[str, SetupPerformance] = {}
    for setup, returns in by_setup.items():
        by_regime = {
            regime: _summarize_returns(values)
            for regime, values in sorted(by_setup_regime.get(setup, {}).items())
        }
        base = _summarize_returns(returns)
        summaries[setup] = SetupPerformance(
            n=base.n,
            winrate=base.winrate,
            expected_return=base.expected_return,
            avg_gain=base.avg_gain,
            avg_loss=base.avg_loss,
            by_regime=by_regime,
        )

    return SetupPerformanceReport(
        total_exits=sum(summary.n for summary in summaries.values()),
        by_setup=dict(sorted(summaries.items())),
        skipped_exits=skipped,
    )
