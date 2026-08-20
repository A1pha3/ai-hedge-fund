"""replay_assembly + offline_rig — Phase 5b (2026-08-20).

锁定: 纯组装零写入、marks 分→micros 换算与 bars 同源 (估值/执行共享一根
bar)、regime/candidate session 交叉拒绝、selected_candidates None 语义
保留 (引擎侧 fail-closed 不在本层伪造)。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.screening.offensive.v3.evidence.offline_rig import build_offline_evidence_rig
from src.screening.offensive.v3.execution.lifecycle import DailyBar
from src.screening.offensive.v3.orchestration.replay_assembly import (
    ReplayAssemblyError,
    assemble_replay_session_facts,
)

SESSION = date(2026, 8, 20)


def _bar(sec: str = "000001.SZ") -> DailyBar:
    return DailyBar(
        security_id=sec, session=SESSION, open_cents=1105, high_cents=1114,
        low_cents=1103, close_cents=1105, limit_up_cents=1221, limit_down_cents=999,
    )


@pytest.fixture()
def rig(tmp_path: Path):
    return build_offline_evidence_rig(
        database_path=tmp_path / "ev.sqlite3", blobs_dir=tmp_path / "blobs",
        namespace="market-bars",
    )


def _published(rig, session: date = SESSION):
    return rig.bar_publisher.publish(session=session, bars={"000001.SZ": _bar()})


def test_assembles_marks_from_same_bars_micros(rig):
    facts = assemble_replay_session_facts(
        repository=rig.repository, session=SESSION, bar_record=_published(rig),
        selected_candidates=(),
    )
    assert facts.marks["000001.SZ"] == 11_050_000  # 1105 分 → micros
    assert facts.bars["000001.SZ"].close_cents == 1105
    assert facts.snapshot_evidence is not None and facts.selected_candidates == ()


def test_none_candidates_semantics_preserved(rig):
    facts = assemble_replay_session_facts(
        repository=rig.repository, session=SESSION, bar_record=_published(rig)
    )
    assert facts.selected_candidates is None  # 引擎侧 fail-closed 语义原样传递


def test_regime_session_mismatch_rejected(rig):
    # 轻量桩: 组装器只读 signal_session (真实 ActiveRegimeObservation 在 5c 接线)
    class _Obs:
        signal_session = SESSION + timedelta(days=1)

    class _Active:
        observation = _Obs()
        observation_hash = "0" * 64

    with pytest.raises(ReplayAssemblyError) as ei:
        assemble_replay_session_facts(
            repository=rig.repository, session=SESSION, bar_record=_published(rig),
            regime_observation=_Active(),
        )
    assert ei.value.code == "regime_session_mismatch"


def test_court_csv_to_bars_conversion(tmp_path):
    """种子换算: 元→分 round, 围栏=前收×板块幅度 (主板10%/创业20%)."""
    from scripts.v3_seed_market_bars import bars_from_court_csv

    csv = tmp_path / "daily_20260820.csv"
    csv.write_text(
        "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount\n"
        "000001.SZ,20260820,11.10,11.14,11.03,11.05,11.10,-0.45,1,1\n"
        "300001.SZ,20260820,10.00,12.00,9.90,11.90,10.00,19.0,1,1\n",
        encoding="utf-8",
    )
    bars = bars_from_court_csv(csv, SESSION)
    assert bars["000001.SZ"].limit_up_cents == 1221  # 1110 × 1.10
    assert bars["300001.SZ"].limit_up_cents == 1200  # 1000 × 1.20
    assert bars["300001.SZ"].limit_down_cents == 800  # 1000 × 0.80
    assert bars["300001.SZ"].close_cents == 1190


def test_fence_rounding_is_exchange_half_up(tmp_path):
    """.5 边界钉死: 1015×1.1=1116.5 → 1117 (交易所), 非银行家 1116."""
    from scripts.v3_seed_market_bars import bars_from_court_csv

    csv = tmp_path / "daily_20260820.csv"
    csv.write_text(
        "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount\n"
        "000001.SZ,20260820,10.15,10.20,10.10,10.15,10.15,0.0,1,1\n",
        encoding="utf-8",
    )
    bars = bars_from_court_csv(csv, SESSION)
    assert bars["000001.SZ"].limit_up_cents == 1117  # half-up, 不是 round() 的 1116


def test_marks_filter_and_missing_marked_bar(rig):
    import pytest as _pytest

    from src.screening.offensive.v3.orchestration.replay_assembly import ReplayAssemblyError as E

    rec = rig.bar_publisher.publish(session=SESSION, bars={"000001.SZ": _bar(), "600000.SH": _bar("600000.SH")})
    facts = assemble_replay_session_facts(
        repository=rig.repository, session=SESSION, bar_record=rec,
        selected_candidates=(), marked_securities={"000001.SZ"},
    )
    assert set(facts.marks) == {"000001.SZ"}  # 持仓集过滤, flat 证券无 mark
    assert set(facts.bars) == {"000001.SZ", "600000.SH"}  # bars 不受过滤
    with _pytest.raises(E) as ei:
        assemble_replay_session_facts(
            repository=rig.repository, session=SESSION, bar_record=rec,
            selected_candidates=(), marked_securities={"NOBAR.SZ"},
        )
    assert ei.value.code == "marked_security_bar_missing"
