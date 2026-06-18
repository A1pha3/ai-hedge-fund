"""Unit tests for src/screening/candidate_pool_persistence_helpers.py

Covers snapshot load/write round-trips, shadow hydration, and the cooldown
registry helpers (add/get/load/save) which use dependency injection.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.screening.candidate_pool_persistence_helpers import (
    _hydrate_shadow_candidate_payload,
    add_cooldown,
    get_cooled_tickers,
    load_candidate_pool_shadow_snapshot,
    load_candidate_pool_snapshot,
    load_cooldown_registry,
    normalize_shadow_summary,
    save_cooldown_registry,
    write_candidate_pool_shadow_snapshot,
    write_candidate_pool_snapshot,
)
from src.screening.models import CandidateStock

# ---------------------------------------------------------------------------
# load / write candidate_pool_snapshot (non-shadow)
# ---------------------------------------------------------------------------


def test_load_candidate_pool_snapshot_roundtrip(tmp_path: Path) -> None:
    payload = [
        {"ticker": "000001", "name": "平安银行", "industry_sw": "银行", "market_cap": 5.0},
        {"ticker": "000002", "name": "万科A"},
    ]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    candidates = load_candidate_pool_snapshot(snapshot_path, candidate_stock_cls=CandidateStock)
    assert len(candidates) == 2
    assert candidates[0].ticker == "000001"
    assert candidates[0].market_cap == 5.0
    assert candidates[1].name == "万科A"


def test_load_candidate_pool_snapshot_empty_list(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "empty.json"
    snapshot_path.write_text("[]", encoding="utf-8")
    assert load_candidate_pool_snapshot(snapshot_path, candidate_stock_cls=CandidateStock) == []


def test_write_candidate_pool_snapshot_creates_dir_and_writes(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "reports"
    snapshot_path = snapshot_dir / "snap.json"
    candidates = [CandidateStock(ticker="000001", name="X")]
    write_candidate_pool_snapshot(snapshot_path, candidates, snapshot_dir=snapshot_dir)

    assert snapshot_dir.exists()
    written = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert len(written) == 1
    assert written[0]["ticker"] == "000001"
    assert written[0]["name"] == "X"


def test_snapshot_write_then_load_roundtrip(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "reports"
    snapshot_path = snapshot_dir / "snap.json"
    original = [
        CandidateStock(ticker="000001", name="A", market_cap=3.0, disclosure_risk=True),
        CandidateStock(ticker="000002", name="B"),
    ]
    write_candidate_pool_snapshot(snapshot_path, original, snapshot_dir=snapshot_dir)
    loaded = load_candidate_pool_snapshot(snapshot_path, candidate_stock_cls=CandidateStock)
    assert len(loaded) == 2
    assert loaded[0].market_cap == 3.0
    assert loaded[0].disclosure_risk is True


# ---------------------------------------------------------------------------
# normalize_shadow_summary
# ---------------------------------------------------------------------------


def test_normalize_shadow_summary_both_keys_present_passthrough() -> None:
    summary = {"shadow_recall_complete": True, "shadow_recall_status": "explicit", "tickers": []}
    out = normalize_shadow_summary(summary, shadow_candidates=[])
    assert out == summary


def test_normalize_shadow_summary_has_entries_computed_legacy() -> None:
    out = normalize_shadow_summary({"tickers": [{"ticker": "000001"}]}, shadow_candidates=[])
    assert out["shadow_recall_complete"] is True
    assert out["shadow_recall_status"] == "computed_legacy"


def test_normalize_shadow_summary_has_shadow_candidates_computed_legacy() -> None:
    out = normalize_shadow_summary({}, shadow_candidates=[CandidateStock(ticker="000001", name="X")])
    assert out["shadow_recall_complete"] is True
    assert out["shadow_recall_status"] == "computed_legacy"


def test_normalize_shadow_summary_no_entries_legacy_unknown() -> None:
    out = normalize_shadow_summary({}, shadow_candidates=[])
    assert out["shadow_recall_complete"] is False
    assert out["shadow_recall_status"] == "legacy_unknown"


def test_normalize_shadow_summary_none_input() -> None:
    out = normalize_shadow_summary(None, shadow_candidates=[])  # type: ignore[arg-type]
    # dict(None) → {}, no entries → legacy_unknown
    assert out["shadow_recall_complete"] is False
    assert out["shadow_recall_status"] == "legacy_unknown"


def test_normalize_shadow_summary_partial_keys_not_overridden() -> None:
    """Only one of the two keys present: neither setdefault fires for the missing one?"""
    # 'shadow_recall_complete' present but 'shadow_recall_status' absent + has entries
    out = normalize_shadow_summary(
        {"shadow_recall_complete": True, "tickers": [{"ticker": "000001"}]},
        shadow_candidates=[],
    )
    # Early return only triggers when BOTH keys present; here status gets setdefault
    assert out["shadow_recall_complete"] is True
    assert out["shadow_recall_status"] == "computed_legacy"


# ---------------------------------------------------------------------------
# _hydrate_shadow_candidate_payload
# ---------------------------------------------------------------------------


def test_hydrate_no_summary_row_passthrough() -> None:
    payload = {"ticker": "000001", "name": "X"}
    assert _hydrate_shadow_candidate_payload(payload, None) == payload


def test_hydrate_applies_field_mapping() -> None:
    payload = {"ticker": "000001", "name": "X"}
    summary_row = {
        "candidate_pool_rank": 3,
        "candidate_pool_lane": "shadow_focus",
        "candidate_pool_shadow_reason": "below_cutoff",
        "avg_amount_share_of_cutoff": 0.85,
        "shadow_focus_selected": True,
    }
    hydrated = _hydrate_shadow_candidate_payload(payload, summary_row)
    assert hydrated["candidate_pool_rank"] == 3
    assert hydrated["candidate_pool_lane"] == "shadow_focus"
    assert hydrated["candidate_pool_shadow_reason"] == "below_cutoff"
    assert hydrated["candidate_pool_avg_amount_share_of_cutoff"] == 0.85
    assert hydrated["shadow_focus_selected"] is True


def test_hydrate_does_not_mutate_original_payload() -> None:
    payload = {"ticker": "000001"}
    original = dict(payload)
    _hydrate_shadow_candidate_payload(payload, {"candidate_pool_rank": 1})
    assert payload == original  # original dict unchanged


# ---------------------------------------------------------------------------
# load / write shadow snapshot
# ---------------------------------------------------------------------------


def test_write_then_load_shadow_snapshot_roundtrip(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "reports"
    snapshot_path = snapshot_dir / "shadow.json"
    selected = [CandidateStock(ticker="000001", name="A", market_cap=5.0)]
    shadow = [CandidateStock(ticker="000002", name="B")]
    shadow_summary = {
        "shadow_recall_complete": True,
        "shadow_recall_status": "computed",
        "tickers": [{"ticker": "000002", "candidate_pool_lane": "shadow_focus"}],
    }
    write_candidate_pool_shadow_snapshot(
        snapshot_path,
        selected_candidates=selected,
        shadow_candidates=shadow,
        shadow_summary=shadow_summary,
        snapshot_dir=snapshot_dir,
    )

    loaded = load_candidate_pool_shadow_snapshot(
        snapshot_path,
        candidate_stock_cls=CandidateStock,
        normalize_shadow_summary_fn=normalize_shadow_summary,
    )
    assert len(loaded["selected_candidates"]) == 1
    assert loaded["selected_candidates"][0].ticker == "000001"
    assert len(loaded["shadow_candidates"]) == 1
    assert loaded["shadow_candidates"][0].ticker == "000002"
    # Hydration: shadow candidate gets lane from summary row
    assert loaded["shadow_candidates"][0].candidate_pool_lane == "shadow_focus"


def test_load_shadow_snapshot_missing_keys_defaults_empty(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "shadow.json"
    snapshot_path.write_text("{}", encoding="utf-8")

    loaded = load_candidate_pool_shadow_snapshot(
        snapshot_path,
        candidate_stock_cls=CandidateStock,
        normalize_shadow_summary_fn=normalize_shadow_summary,
    )
    assert loaded["selected_candidates"] == []
    assert loaded["shadow_candidates"] == []
    assert loaded["shadow_summary"]["shadow_recall_complete"] is False


def test_load_shadow_snapshot_empty_summary_dedupes_rows() -> None:
    """Rows with empty/whitespace ticker are dropped from shadow_summary_rows."""
    payload = {
        "selected_candidates": [],
        "shadow_candidates": [{"ticker": "000001", "name": "A"}],
        "shadow_summary": {"tickers": [{"ticker": "   "}, {"ticker": ""}, {}]},
    }
    snapshot_path = Path(__file__).parent / "_tmp_shadow_empty.json"
    try:
        snapshot_path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_candidate_pool_shadow_snapshot(
            snapshot_path,
            candidate_stock_cls=CandidateStock,
            normalize_shadow_summary_fn=normalize_shadow_summary,
        )
        assert len(loaded["shadow_candidates"]) == 1
    finally:
        snapshot_path.unlink(missing_ok=True)


def test_load_shadow_snapshot_corrupted_file_does_not_crash(tmp_path: Path) -> None:
    """R93 BH-017/R88 family residue: a corrupted shadow snapshot (truncated write
    from a previous interrupted run) must not crash the candidate-pool front door.
    ``write_candidate_pool_shadow_snapshot`` writes non-atomically; if interrupted
    mid-flush the next ``--auto`` load would raise JSONDecodeError. Load must
    degrade gracefully (empty) like the cooldown loader does."""
    snapshot_path = tmp_path / "shadow_corrupt.json"
    # Truncated/partial JSON — exactly what a mid-write crash leaves behind.
    snapshot_path.write_text('{"selected_candidates": [/* truncated', encoding="utf-8")

    loaded = load_candidate_pool_shadow_snapshot(
        snapshot_path,
        candidate_stock_cls=CandidateStock,
        normalize_shadow_summary_fn=normalize_shadow_summary,
    )
    assert loaded["selected_candidates"] == []
    assert loaded["shadow_candidates"] == []


def test_write_shadow_snapshot_is_atomic(tmp_path: Path) -> None:
    """R93 write-side fix: writes must be atomic (temp file + os.replace) so an
    interruption during write never corrupts an existing valid snapshot. Verify
    by checking the file only appears at its final path with complete content."""
    snapshot_path = tmp_path / "snapshots" / "shadow.json"
    selected = [CandidateStock(ticker="000001", name="平安")]
    shadow = [CandidateStock(ticker="000002", name="万科")]
    summary = {"tickers": [{"ticker": "000002"}]}

    write_candidate_pool_shadow_snapshot(
        snapshot_path,
        selected_candidates=selected,
        shadow_candidates=shadow,
        shadow_summary=summary,
        snapshot_dir=tmp_path / "snapshots",
    )

    # Final file is complete and loadable (atomic write leaves no partial state).
    assert snapshot_path.exists()
    loaded = load_candidate_pool_shadow_snapshot(
        snapshot_path,
        candidate_stock_cls=CandidateStock,
        normalize_shadow_summary_fn=normalize_shadow_summary,
    )
    assert len(loaded["selected_candidates"]) == 1
    assert loaded["selected_candidates"][0].ticker == "000001"
    # No leftover temp files in the snapshot dir.
    leftover_tmps = [p for p in snapshot_path.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftover_tmps == []


# ---------------------------------------------------------------------------
# cooldown registry: load / save
# ---------------------------------------------------------------------------


def test_load_cooldown_registry_missing_file(tmp_path: Path) -> None:
    assert load_cooldown_registry(tmp_path / "nope.json") == {}


def test_load_cooldown_registry_invalid_json(tmp_path: Path) -> None:
    cooldown_file = tmp_path / "broken.json"
    cooldown_file.write_text("{invalid json", encoding="utf-8")
    assert load_cooldown_registry(cooldown_file) == {}


def test_load_cooldown_registry_valid(tmp_path: Path) -> None:
    cooldown_file = tmp_path / "ok.json"
    cooldown_file.write_text('{"000001": "20260701"}', encoding="utf-8")
    assert load_cooldown_registry(cooldown_file) == {"000001": "20260701"}


def test_save_cooldown_registry_creates_dir_and_writes(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "reports"
    cooldown_file = snapshot_dir / "cooldown.json"
    save_cooldown_registry({"000001": "20260701"}, cooldown_file=cooldown_file, snapshot_dir=snapshot_dir)
    assert cooldown_file.exists()
    assert json.loads(cooldown_file.read_text(encoding="utf-8")) == {"000001": "20260701"}


# ---------------------------------------------------------------------------
# cooldown registry: add / get
# ---------------------------------------------------------------------------


def test_add_cooldown_sets_expire_to_days_times_1_5() -> None:
    stored: dict[str, str] = {}

    def _load() -> dict[str, str]:
        return dict(stored)

    def _save(reg: dict[str, str]) -> None:
        stored.clear()
        stored.update(reg)

    add_cooldown("000001", "20260601", days=10, load_cooldown_registry_fn=_load, save_cooldown_registry_fn=_save)
    # expire = 20260601 + 15 days = 20260616
    expected = (datetime(2026, 6, 1) + timedelta(days=15)).strftime("%Y%m%d")
    assert stored == {"000001": expected}


def test_add_cooldown_preserves_existing_entries() -> None:
    stored = {"000099": "20260801"}

    def _load() -> dict[str, str]:
        return dict(stored)

    def _save(reg: dict[str, str]) -> None:
        stored.clear()
        stored.update(reg)

    add_cooldown("000001", "20260601", days=4, load_cooldown_registry_fn=_load, save_cooldown_registry_fn=_save)
    assert "000099" in stored
    assert "000001" in stored


def test_get_cooled_tickers_returns_unexpired_and_cleans_expired() -> None:
    stored = {"000001": "20260701", "000002": "20260501", "000003": "20260613"}

    def _load() -> dict[str, str]:
        return dict(stored)

    def _save(reg: dict[str, str]) -> None:
        stored.clear()
        stored.update(reg)

    cooled = get_cooled_tickers("20260613", load_cooldown_registry_fn=_load, save_cooldown_registry_fn=_save)
    # 000001 (20260701 > 20260613) → cooled; 000002 (20260501 < ...) → expired; 000003 (== date, not >) → expired
    assert cooled == {"000001"}
    # Expired entries removed from registry
    assert "000002" not in stored
    assert "000003" not in stored
    assert "000001" in stored


def test_get_cooled_tickers_no_expired_no_save() -> None:
    stored = {"000001": "20260701"}
    save_calls: list = []

    def _load() -> dict[str, str]:
        return dict(stored)

    def _save(reg: dict[str, str]) -> None:
        save_calls.append(reg)
        stored.clear()
        stored.update(reg)

    cooled = get_cooled_tickers("20260613", load_cooldown_registry_fn=_load, save_cooldown_registry_fn=_save)
    assert cooled == {"000001"}
    assert save_calls == []  # nothing expired → no save


def test_get_cooled_tickers_empty_registry() -> None:
    stored: dict[str, str] = {}

    def _load() -> dict[str, str]:
        return dict(stored)

    def _save(reg: dict[str, str]) -> None:
        stored.update(reg)

    cooled = get_cooled_tickers("20260613", load_cooldown_registry_fn=_load, save_cooldown_registry_fn=_save)
    assert cooled == set()


def test_add_then_get_cooldown_integration() -> None:
    stored: dict[str, str] = {}

    def _load() -> dict[str, str]:
        return dict(stored)

    def _save(reg: dict[str, str]) -> None:
        stored.clear()
        stored.update(reg)

    # Add a 10-day cooldown on 20260601 → expires 20260616
    add_cooldown("000001", "20260601", days=10, load_cooldown_registry_fn=_load, save_cooldown_registry_fn=_save)
    # On 20260610 it's still cooling
    assert get_cooled_tickers("20260610", load_cooldown_registry_fn=_load, save_cooldown_registry_fn=_save) == {"000001"}
    # On 20260616 it has expired (expire == date is not > date)
    assert get_cooled_tickers("20260616", load_cooldown_registry_fn=_load, save_cooldown_registry_fn=_save) == set()
