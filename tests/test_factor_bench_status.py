"""板凳重评状态工具契约 (R70)。重评触发器可观测化: deferred 候选在 court
门内样本较记账时增长 ≥RE_EVAL_GROWTH 后 re_eval_due=true; registry 缺失
fail-closed; 同输入恒同输出 (确定性)。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from factor_bench_status import (  # noqa: E402
    BenchStatusError,
    bench_status,
)


def _write_registry(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _triage_row(name: str, verdict: str, usable_rows: int, **kw) -> dict:
    row = {
        "fingerprint": f"sha256:{name}",
        "name": name,
        "first_seen": True,
        "unique_candidate_ordinal": 1,
        "run_count": 1,
        "registered_at": "2026-08-30T00:00:00Z",
        "verdict": verdict,
        "usable_rows": usable_rows,
        "gated_days": 100,
    }
    row.update(kw)
    return row


def _court_factory_registry(tmp_path: Path) -> tuple[Path, Path]:
    factory = _write_registry(tmp_path / "registry.jsonl", [])
    triage = _write_registry(tmp_path / "triage.jsonl", [])
    return factory, triage


def _court_path(tmp_path: Path, gated_rows: int) -> Path:
    """合成 court 表: 恰 gated_rows 行能过生产对齐门 (fill/gate/regime 全绿)。"""
    import pandas as pd

    rows = []
    for i in range(gated_rows):
        rows.append({
            "signal_date": "20260105",
            "ts_code": f"{i:06d}.SZ",
            "regime": "normal",
            "fillable": True,
            "gate_blocked": False,
            "degraded": False,
            "st_name": False,
            "industry_missing": False,
            "excluded_ticker": False,
            "price_ge_3": True,
            "trigger_strength": 0.6,
            "gross_ret_t10": 0.01,
        })
    path = tmp_path / "court.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_missing_triage_registry_typed(tmp_path: Path) -> None:
    factory, triage = _court_factory_registry(tmp_path)
    triage.unlink()
    court = _court_path(tmp_path, 100)
    with pytest.raises(BenchStatusError) as exc:
        bench_status(factory_registry=factory, triage_registry=triage,
                     court_path=court)
    assert exc.value.code == "triage_registry_missing"


def test_missing_factory_registry_typed(tmp_path: Path) -> None:
    factory, triage = _court_factory_registry(tmp_path)
    factory.unlink()
    court = _court_path(tmp_path, 100)
    with pytest.raises(BenchStatusError) as exc:
        bench_status(factory_registry=factory, triage_registry=triage,
                     court_path=court)
    assert exc.value.code == "factory_registry_missing"


def test_missing_court_typed(tmp_path: Path) -> None:
    factory, triage = _court_factory_registry(tmp_path)
    with pytest.raises(BenchStatusError) as exc:
        bench_status(factory_registry=factory, triage_registry=triage,
                     court_path=tmp_path / "nope.csv")
    assert exc.value.code == "court_table_missing"


def test_deferred_growth_past_threshold_due(tmp_path: Path) -> None:
    factory, triage = _court_factory_registry(tmp_path)
    _write_registry(triage, [_triage_row("seal_quality_v0", "deferred", 100)])
    court = _court_path(tmp_path, 120)  # 120 >= 100*1.2 → due
    out = bench_status(factory_registry=factory, triage_registry=triage,
                       court_path=court)
    row = {r["name"]: r for r in out["triage_candidates"]}["seal_quality_v0"]
    assert row["verdict"] == "deferred"
    assert row["re_eval_due"] is True
    assert out["re_eval_due_any"] is True


def test_deferred_below_threshold_not_due(tmp_path: Path) -> None:
    factory, triage = _court_factory_registry(tmp_path)
    _write_registry(triage, [_triage_row("seal_quality_v0", "deferred", 100)])
    court = _court_path(tmp_path, 119)  # 119 < 120 → not due
    out = bench_status(factory_registry=factory, triage_registry=triage,
                       court_path=court)
    row = out["triage_candidates"][0]
    assert row["re_eval_due"] is False
    assert out["re_eval_due_any"] is False


def test_challenger_ready_never_due(tmp_path: Path) -> None:
    factory, triage = _court_factory_registry(tmp_path)
    _write_registry(triage, [_triage_row("x_v0", "challenger_ready", 10)])
    court = _court_path(tmp_path, 200)
    out = bench_status(factory_registry=factory, triage_registry=triage,
                       court_path=court)
    assert out["triage_candidates"][0]["re_eval_due"] is False


def test_latest_record_wins_per_name(tmp_path: Path) -> None:
    factory, triage = _court_factory_registry(tmp_path)
    old = _triage_row("seal_quality_v0", "challenger_ready", 10,
                      run_count=1, registered_at="2026-08-01T00:00:00Z")
    new = _triage_row("seal_quality_v0", "deferred", 1000,
                      run_count=2, registered_at="2026-08-30T00:00:00Z")
    _write_registry(triage, [old, new])
    court = _court_path(tmp_path, 1200)
    out = bench_status(factory_registry=factory, triage_registry=triage,
                       court_path=court)
    assert len(out["triage_candidates"]) == 1
    assert out["triage_candidates"][0]["verdict"] == "deferred"
    assert out["triage_candidates"][0]["run_count"] == 2
    assert out["triage_candidates"][0]["re_eval_due"] is True


def test_deterministic_output(tmp_path: Path) -> None:
    factory, triage = _court_factory_registry(tmp_path)
    _write_registry(triage, [
        _triage_row("a_v0", "deferred", 100),
        _triage_row("b_v0", "deferred", 50),
    ])
    court = _court_path(tmp_path, 130)
    one = bench_status(factory_registry=factory, triage_registry=triage,
                       court_path=court)
    two = bench_status(factory_registry=factory, triage_registry=triage,
                       court_path=court)
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
    # 输出按名字排序 — 与 registry 行序无关
    assert [r["name"] for r in one["triage_candidates"]] == [
        "a_v0", "b_v0"]
