"""Security tests for the verified Daily Action snapshot loader.

Confirms the loader fails closed against symlinked manifests, symlinked
ancestors, malformed encodings, and symlinked cache files, reusing the
self-consistent v2 fixture from ``test_daily_action_verified_snapshot``.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from src.screening.offensive.daily_action_snapshot import (
    load_verified_daily_action_snapshot,
)
from tests.offensive.test_daily_action_verified_snapshot import (
    _MANIFEST_NAME,
    SIGNAL_DATE,
    _build_and_publish,
)


def test_loader_rejects_invalid_utf8_manifest(tmp_path: Path):
    (tmp_path / _MANIFEST_NAME).write_bytes(b"\xff\xfe")
    result = load_verified_daily_action_snapshot(
        SIGNAL_DATE, reports_dir=tmp_path, data_dir=tmp_path
    )
    assert result.snapshot is None
    assert result.global_reason == "readiness_manifest_invalid"


def test_symlinked_manifest_final_component_is_rejected(tmp_path: Path):
    real = tmp_path / "real_manifest.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / _MANIFEST_NAME
    link.symlink_to(real)
    result = load_verified_daily_action_snapshot(
        SIGNAL_DATE, reports_dir=tmp_path, data_dir=tmp_path
    )
    assert result.snapshot is None
    assert result.global_reason == "readiness_manifest_invalid"


def test_symlinked_reports_ancestor_is_rejected(tmp_path: Path):
    real_reports = tmp_path / "real_reports"
    real_reports.mkdir()
    (real_reports / _MANIFEST_NAME).write_text("{}", encoding="utf-8")
    linked_reports = tmp_path / "reports"
    linked_reports.symlink_to(real_reports, target_is_directory=True)
    result = load_verified_daily_action_snapshot(
        SIGNAL_DATE, reports_dir=linked_reports, data_dir=tmp_path
    )
    assert result.snapshot is None
    assert result.global_reason == "readiness_manifest_invalid"


def test_symlinked_price_cache_blocks_ticker(tmp_path: Path):
    fixture = _build_and_publish(tmp_path)
    # Replace the price cache with a symlink to an identical-looking file so the
    # secure read rejects the indirection rather than trusting the payload.
    real_elsewhere = tmp_path / "shadow_price.csv"
    real_elsewhere.write_bytes(fixture.price_path.read_bytes())
    fixture.price_path.unlink()
    fixture.price_path.symlink_to(real_elsewhere)
    result = load_verified_daily_action_snapshot(**fixture.loader_args)
    assert "price_read_failed" in result.ticker_blocks["000001"]


def test_absolute_paths_stay_within_trusted_tree(tmp_path: Path):
    fixture = _build_and_publish(tmp_path)
    result = load_verified_daily_action_snapshot(
        SIGNAL_DATE,
        reports_dir=os.fspath(fixture.reports_dir),
        data_dir=os.fspath(fixture.data_dir),
    )
    assert result.snapshot is not None
    assert result.snapshot.signal_date == date(2026, 7, 13)
