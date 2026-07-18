"""Unit tests for src/screening/candidate_pool_run_helpers.py

Covers the shadow-aware candidate-pool cache-load fallback branches and the
finalization path. All collaborators are injected, so tests use plain stubs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from src.screening.candidate_pool_run_helpers import (
    _finalize_candidate_pool_with_shadow_outputs,
    _try_load_cached_candidate_pool_with_shadow,
    build_candidate_pool_with_shadow,
)
from src.screening.models import CandidateStock


def _cand(ticker: str) -> CandidateStock:
    return CandidateStock(ticker=ticker, name=ticker)


# ---------------------------------------------------------------------------
# _try_load_cached_candidate_pool_with_shadow
# ---------------------------------------------------------------------------


def _cache_load_kwargs(**overrides: Any) -> dict:
    base: dict[str, Any] = dict(
        trade_date="20260613",
        use_cache=True,
        snapshot_path=Path("/fake/main.json"),
        legacy_snapshot_path=Path("/fake/legacy.json"),
        shadow_snapshot_path=Path("/fake/shadow.json"),
        max_candidate_pool_size=10,
        focus_signature="",
    )
    base.update(overrides)
    return base


def test_try_load_both_snapshots_exist_returns_shadow_payload(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    shadow_path = tmp_path / "shadow.json"
    shadow_path.write_text("{}")  # exists
    main_path = tmp_path / "main.json"
    main_path.write_text("{}")  # exists

    loaded_shadow_payload = {
        "selected_candidates": [_cand("000001")],
        "shadow_candidates": [_cand("000002")],
        "shadow_summary": {"shadow_recall_complete": True},
    }
    legacy_writes: list = []
    load_shadow_calls: list = []

    def _load_shadow(path):
        load_shadow_calls.append(path)
        return loaded_shadow_payload

    def _write_legacy(path, cands):
        legacy_writes.append((path, cands))

    with caplog.at_level(logging.DEBUG, logger="src.screening.candidate_pool_run_helpers"):
        result = _try_load_cached_candidate_pool_with_shadow(
            **_cache_load_kwargs(
                snapshot_path=main_path,
                shadow_snapshot_path=shadow_path,
                legacy_snapshot_path=tmp_path / "legacy.json",
            ),
            load_candidate_pool_shadow_snapshot_fn=_load_shadow,
            write_candidate_pool_snapshot_fn=_write_legacy,
            load_candidate_pool_snapshot_fn=lambda path: [],
            build_shadow_summary_from_selected_candidates_fn=lambda *a, **k: {},
            write_candidate_pool_shadow_snapshot_fn=lambda *a, **k: None,
        )
    assert result is not None
    selected, shadow, summary, cached = result
    assert len(selected) == 1
    assert len(shadow) == 1
    assert summary == {"shadow_recall_complete": True}
    assert cached == []  # 4th element empty in full-cache branch
    # legacy snapshot written from shadow payload's selected
    assert len(legacy_writes) == 1
    # 0dad80ab 起加载日志降级为 logger.debug (不再 print)
    assert sum("从缓存加载" in record.message for record in caplog.records) == 1


def test_try_load_both_snapshots_load_raises_returns_none(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    shadow_path = tmp_path / "shadow.json"
    shadow_path.write_text("{}")
    main_path = tmp_path / "main.json"
    main_path.write_text("{}")

    def _load_shadow(path):
        raise RuntimeError("boom")

    with caplog.at_level(logging.WARNING, logger="src.screening.candidate_pool_run_helpers"):
        result = _try_load_cached_candidate_pool_with_shadow(
            **_cache_load_kwargs(snapshot_path=main_path, shadow_snapshot_path=shadow_path),
            load_candidate_pool_shadow_snapshot_fn=_load_shadow,
            write_candidate_pool_snapshot_fn=lambda *a, **k: None,
            load_candidate_pool_snapshot_fn=lambda path: [],
            build_shadow_summary_from_selected_candidates_fn=lambda *a, **k: {},
            write_candidate_pool_shadow_snapshot_fn=lambda *a, **k: None,
        )
    assert result is None
    # NS-17 / BH-017 family: silent fallback must emit via structured logging,
    # not print(), so cron/launchd operators can diagnose cache corruption.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, f"expected 1 WARNING, got {len(warnings)}"
    assert "shadow" in warnings[0].message
    assert "缓存读取失败" in warnings[0].message


def test_try_load_main_only_no_focus_backfills_empty_shadow(tmp_path: Path, capfd: pytest.CaptureFixture) -> None:
    main_path = tmp_path / "main.json"
    main_path.write_text("{}")  # main exists, no shadow

    cached_cands = [_cand("000001"), _cand("000002")]
    shadow_summary_writes: list = []
    legacy_writes: list = []

    def _build_summary(cands, *, pool_size):
        return {"computed": True, "n": len(cands)}

    result = _try_load_cached_candidate_pool_with_shadow(
        **_cache_load_kwargs(snapshot_path=main_path, shadow_snapshot_path=tmp_path / "nope.json", legacy_snapshot_path=tmp_path / "legacy.json", focus_signature=""),
        load_candidate_pool_shadow_snapshot_fn=lambda path: {},
        write_candidate_pool_snapshot_fn=lambda path, cands: legacy_writes.append((path, cands)),
        load_candidate_pool_snapshot_fn=lambda path: cached_cands,
        build_shadow_summary_from_selected_candidates_fn=_build_summary,
        write_candidate_pool_shadow_snapshot_fn=lambda *a, **k: shadow_summary_writes.append(k),
    )
    assert result is not None
    selected, shadow, summary, cached = result
    assert selected == cached_cands
    assert shadow == []
    assert summary == {"computed": True, "n": 2}
    assert cached == cached_cands
    assert len(legacy_writes) == 1
    assert len(shadow_summary_writes) == 1


def test_try_load_main_only_with_focus_returns_fallback_tuple(tmp_path: Path) -> None:
    """When focus_signature is set, main-cache backfill is skipped → fallback ([],[],{},cached)."""
    main_path = tmp_path / "main.json"
    main_path.write_text("{}")

    cached_cands = [_cand("000001")]
    result = _try_load_cached_candidate_pool_with_shadow(
        **_cache_load_kwargs(snapshot_path=main_path, shadow_snapshot_path=tmp_path / "nope.json", focus_signature="focus_sig"),
        load_candidate_pool_shadow_snapshot_fn=lambda path: {},
        write_candidate_pool_snapshot_fn=lambda *a, **k: None,
        load_candidate_pool_snapshot_fn=lambda path: cached_cands,
        build_shadow_summary_from_selected_candidates_fn=lambda *a, **k: {},
        write_candidate_pool_shadow_snapshot_fn=lambda *a, **k: None,
    )
    assert result is not None
    selected, shadow, summary, cached = result
    assert selected == []
    assert shadow == []
    assert summary == {}
    assert cached == cached_cands


def test_try_load_main_only_empty_cache_returns_none(tmp_path: Path) -> None:
    main_path = tmp_path / "main.json"
    main_path.write_text("{}")

    result = _try_load_cached_candidate_pool_with_shadow(
        **_cache_load_kwargs(snapshot_path=main_path, shadow_snapshot_path=tmp_path / "nope.json", focus_signature=""),
        load_candidate_pool_shadow_snapshot_fn=lambda path: {},
        write_candidate_pool_snapshot_fn=lambda *a, **k: None,
        load_candidate_pool_snapshot_fn=lambda path: [],  # empty cache
        build_shadow_summary_from_selected_candidates_fn=lambda *a, **k: {},
        write_candidate_pool_shadow_snapshot_fn=lambda *a, **k: None,
    )
    assert result is None


def test_try_load_use_cache_false_returns_none(tmp_path: Path) -> None:
    main_path = tmp_path / "main.json"
    main_path.write_text("{}")
    shadow_path = tmp_path / "shadow.json"
    shadow_path.write_text("{}")

    result = _try_load_cached_candidate_pool_with_shadow(
        **_cache_load_kwargs(use_cache=False, snapshot_path=main_path, shadow_snapshot_path=shadow_path),
        load_candidate_pool_shadow_snapshot_fn=lambda path: {"x": 1},
        write_candidate_pool_snapshot_fn=lambda *a, **k: None,
        load_candidate_pool_snapshot_fn=lambda path: [],
        build_shadow_summary_from_selected_candidates_fn=lambda *a, **k: {},
        write_candidate_pool_shadow_snapshot_fn=lambda *a, **k: None,
    )
    assert result is None


def test_try_load_main_only_read_raises_no_crash(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    main_path = tmp_path / "main.json"
    main_path.write_text("{}")

    def _load_main(path):
        raise RuntimeError("corrupt")

    with caplog.at_level(logging.WARNING, logger="src.screening.candidate_pool_run_helpers"):
        result = _try_load_cached_candidate_pool_with_shadow(
            **_cache_load_kwargs(snapshot_path=main_path, shadow_snapshot_path=tmp_path / "nope.json", focus_signature=""),
            load_candidate_pool_shadow_snapshot_fn=lambda path: {},
            write_candidate_pool_snapshot_fn=lambda *a, **k: None,
            load_candidate_pool_snapshot_fn=_load_main,
            build_shadow_summary_from_selected_candidates_fn=lambda *a, **k: {},
            write_candidate_pool_shadow_snapshot_fn=lambda *a, **k: None,
        )
    assert result is None
    # NS-17 / BH-017 family: main-pool cache read failure must reach logs.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, f"expected 1 WARNING, got {len(warnings)}"
    assert "主池缓存读取失败" in warnings[0].message


# ---------------------------------------------------------------------------
# _finalize_candidate_pool_with_shadow_outputs
# ---------------------------------------------------------------------------


def test_finalize_writes_snapshots_and_attaches_diagnostics() -> None:
    candidates = [_cand("000001"), _cand("000002")]
    cooldown_review = [_cand("000003")]
    focus_diag = [{"ticker": "000001", "dropped": True}]
    selected = [_cand("000001")]
    shadow = [_cand("000002")]
    summary: dict[str, Any] = {"shadow_recall_complete": True}

    writes: list = []
    finalize_calls: list = []

    def _finalize(diag_map, *, candidate_tickers, cooldown_review_tickers, selected_tickers, shadow_tickers):
        finalize_calls.append((diag_map, candidate_tickers, selected_tickers))
        return [{"finalized": True}]

    def _write_snap(path, cands):
        writes.append(("main", path, cands))

    def _write_shadow(path, *, selected_candidates, shadow_candidates, shadow_summary):
        writes.append(("shadow", path, len(selected_candidates)))

    result = _finalize_candidate_pool_with_shadow_outputs(
        snapshot_path=Path("/s.json"),
        legacy_snapshot_path=Path("/l.json"),
        shadow_snapshot_path=Path("/sh.json"),
        candidates=candidates,
        cooldown_review_candidates=cooldown_review,
        focus_filter_diagnostics=focus_diag,
        selected_candidates=selected,
        shadow_candidates=shadow,
        shadow_summary=summary,
        max_candidate_pool_size=10,
        write_candidate_pool_snapshot_fn=_write_snap,
        write_candidate_pool_shadow_snapshot_fn=_write_shadow,
        finalize_focus_filter_diagnostics_fn=_finalize,
    )
    out_selected, out_shadow, out_summary = result
    assert out_selected == selected
    assert out_shadow == shadow
    assert out_summary["focus_filter_diagnostics"] == [{"finalized": True}]
    # 2 main writes (snapshot + legacy) + 1 shadow write
    main_writes = [w for w in writes if w[0] == "main"]
    shadow_writes = [w for w in writes if w[0] == "shadow"]
    assert len(main_writes) == 2
    assert len(shadow_writes) == 1
    # finalize called with correct ticker sets
    _, candidate_tickers, selected_tickers = finalize_calls[0]
    assert candidate_tickers == {"000001", "000002"}
    assert selected_tickers == {"000001"}


# ---------------------------------------------------------------------------
# build_candidate_pool_with_shadow — cache-hit shortcut
# ---------------------------------------------------------------------------


def test_build_returns_cached_when_full_cache_present(tmp_path: Path) -> None:
    main_path = tmp_path / "main.json"
    main_path.write_text("{}")
    shadow_path = tmp_path / "shadow.json"
    shadow_path.write_text("{}")

    cached_selected = [_cand("000001")]
    cached_shadow = [_cand("000002")]
    cached_summary = {"shadow_recall_complete": True}

    compute_calls: list = []

    def _compute(*args, **kwargs):
        compute_calls.append(True)
        return [], [], []

    result = build_candidate_pool_with_shadow(
        trade_date="20260613",
        use_cache=True,
        cooldown_tickers=None,
        snapshot_path=main_path,
        legacy_snapshot_path=tmp_path / "legacy.json",
        shadow_snapshot_path=shadow_path,
        max_candidate_pool_size=10,
        shadow_focus_signature_fn=lambda: "",
        load_candidate_pool_shadow_snapshot_fn=lambda path: {
            "selected_candidates": cached_selected,
            "shadow_candidates": cached_shadow,
            "shadow_summary": cached_summary,
        },
        write_candidate_pool_snapshot_fn=lambda *a, **k: None,
        load_candidate_pool_snapshot_fn=lambda path: [],
        build_shadow_summary_from_selected_candidates_fn=lambda *a, **k: {},
        write_candidate_pool_shadow_snapshot_fn=lambda *a, **k: None,
        compute_candidate_pool_candidates_fn=_compute,
        build_shadow_candidate_pool_payload_fn=lambda *a, **k: ([], [], {}),
        finalize_focus_filter_diagnostics_fn=lambda *a, **k: [],
    )
    assert result == (cached_selected, cached_shadow, cached_summary)
    assert compute_calls == []  # compute never called on cache hit


def test_build_recomputes_when_no_cache(tmp_path: Path) -> None:
    candidates = [_cand("000001"), _cand("000002")]
    cooldown_review = [_cand("000003")]
    selected = [_cand("000001")]
    shadow = [_cand("000002")]

    def _compute(trade_date, *, cooldown_tickers):
        return candidates, cooldown_review, [{"ticker": "000001"}]

    def _build_shadow(cands, *, pool_size, cooldown_review_candidates, focus_filter_diagnostics):
        return selected, shadow, {"shadow_recall_complete": True, "computed": True}

    result = build_candidate_pool_with_shadow(
        trade_date="20260613",
        use_cache=False,
        cooldown_tickers=None,
        snapshot_path=tmp_path / "main.json",
        legacy_snapshot_path=tmp_path / "legacy.json",
        shadow_snapshot_path=tmp_path / "shadow.json",
        max_candidate_pool_size=10,
        shadow_focus_signature_fn=lambda: "",
        load_candidate_pool_shadow_snapshot_fn=lambda path: {},
        write_candidate_pool_snapshot_fn=lambda *a, **k: None,
        load_candidate_pool_snapshot_fn=lambda path: [],
        build_shadow_summary_from_selected_candidates_fn=lambda *a, **k: {},
        write_candidate_pool_shadow_snapshot_fn=lambda *a, **k: None,
        compute_candidate_pool_candidates_fn=_compute,
        build_shadow_candidate_pool_payload_fn=_build_shadow,
        finalize_focus_filter_diagnostics_fn=lambda *a, **k: [],
    )
    assert result == (selected, shadow, {"shadow_recall_complete": True, "computed": True, "focus_filter_diagnostics": []})


def test_build_recompute_failure_falls_back_to_cached_main(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """When recompute returns empty candidates but a cached main exists, keep the cache.

    Requires a non-empty focus_signature so _try_load skips the main-cache
    backfill and returns ([], [], {}, cached) — otherwise the cache-hit
    short-circuit returns before reaching the recompute path.
    """
    main_path = tmp_path / "main.json"
    main_path.write_text("{}")
    cached_cands = [_cand("000099")]

    def _compute(trade_date, *, cooldown_tickers):
        return [], [], []  # recompute failure

    with caplog.at_level(logging.WARNING, logger="src.screening.candidate_pool_run_helpers"):
        result = build_candidate_pool_with_shadow(
            trade_date="20260613",
            use_cache=True,
            cooldown_tickers=None,
            snapshot_path=main_path,
            legacy_snapshot_path=tmp_path / "legacy.json",
            shadow_snapshot_path=tmp_path / "shadow.json",  # does NOT exist
            max_candidate_pool_size=10,
            shadow_focus_signature_fn=lambda: "focus_sig",  # non-empty → skip backfill
            load_candidate_pool_shadow_snapshot_fn=lambda path: {},
            write_candidate_pool_snapshot_fn=lambda *a, **k: None,
            load_candidate_pool_snapshot_fn=lambda path: cached_cands,
            build_shadow_summary_from_selected_candidates_fn=lambda cands, *, pool_size: {"computed": True},
            write_candidate_pool_shadow_snapshot_fn=lambda *a, **k: None,
            compute_candidate_pool_candidates_fn=_compute,
            build_shadow_candidate_pool_payload_fn=lambda *a, **k: ([], [], {}),
            finalize_focus_filter_diagnostics_fn=lambda *a, **k: [],
        )
    selected, shadow, summary = result
    assert selected == cached_cands
    assert shadow == []
    assert summary["shadow_recall_status"] == "selected_cache_fallback_after_recompute_failure"
    # NS-17 / BH-017 family: recompute-failure fallback must reach logs.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, f"expected 1 WARNING, got {len(warnings)}"
    assert "候选池重算失败" in warnings[0].message
