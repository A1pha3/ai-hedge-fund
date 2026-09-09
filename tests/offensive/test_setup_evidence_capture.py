"""R160 Op1 — 发布侧 setup 信号证据捕获 (setup_evidence_capture) 测试。

锚定事实: setup_output_log 的写入口此前只在 --daily-action dispatcher; 操作员
漏跑该命令的晚上 (2026-07-30~08-11 七个交易日, 其中六天 --auto 已跑) 信号证据
不留痕。发布侧捕获必须在发布点跑 — loader 重验 PIT 指纹需当日缓存, 事后缓存被
后续刷新覆写即无法补录 (丢失日实测: 4 canonical 缺失 / 3 空扫描)。

测试世界: readiness_v2_testkit 的真实 PIT 管道 fixture (refresh → publish →
load), 不 mock 证据层; 仅注入 BtstBreakoutSetup.detect 控制 hit 形态。
"""

from __future__ import annotations

import json
import types
from datetime import date
from pathlib import Path

import pytest

from src.screening.offensive.daily_action import scan_from_verified_snapshot
from src.screening.offensive.daily_action_snapshot import (
    load_verified_daily_action_snapshot,
)
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.setup_evidence_capture import (
    capture_setup_evidence_for_publication,
    plan_layer_blocked_candidates,
)
from tests.offensive.readiness_v2_testkit import (
    SIGNAL_DATE,
    run_injected_auto_refresh_for_20260713,
)

_BTST_HIT_TICKER = "300001"


def _world(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "world"
    root.mkdir()
    run_injected_auto_refresh_for_20260713(root)
    return root / "data" / "reports", root / "data"


def _out_dir(tmp_path: Path) -> Path:
    out = tmp_path / "setup_output_log"
    out.mkdir()
    return out


def _injected_detect(hit_ticker: str | None):
    from src.screening.offensive.setups.base import DetectionResult

    def injected(self, ticker, trade_date, context):
        hit = hit_ticker is not None and ticker == hit_ticker
        return DetectionResult(
            hit=hit,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=1.0 if hit else 0.0,
            invalidation_condition="fixture invalidation",
            metadata={"range_based_stop_pct": -0.08},
            degraded=False,
            degradation_reason="",
        )

    return injected


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_capture_writes_eligible_row_from_published_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports_dir, data_dir = _world(tmp_path)
    out = _out_dir(tmp_path)
    monkeypatch.setattr(
        BtstBreakoutSetup, "detect", _injected_detect(_BTST_HIT_TICKER)
    )

    written = capture_setup_evidence_for_publication(
        SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir, out_dir=out
    )

    assert written is not None and written.exists()
    rows = _rows(written)
    eligible = {r["ticker"] for r in rows if r["plan_eligible"]}
    assert eligible == {_BTST_HIT_TICKER}
    for row in rows:
        assert row["signal_date"] == "20260713"
        assert row["regime"] == "normal"
        assert row["schema_version"]


def test_capture_returns_none_without_canonical_and_writes_nothing(
    tmp_path: Path,
) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    out = _out_dir(tmp_path)

    written = capture_setup_evidence_for_publication(
        SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir, out_dir=out
    )

    assert written is None
    assert not any(out.iterdir())


def test_capture_returns_none_when_canonical_invalid(tmp_path: Path) -> None:
    reports_dir, data_dir = _world(tmp_path)
    canonical = reports_dir / "daily_action_readiness_20260713.json"
    canonical.write_text("{not json", encoding="utf-8")
    out = _out_dir(tmp_path)

    written = capture_setup_evidence_for_publication(
        SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir, out_dir=out
    )

    assert written is None
    assert not any(out.iterdir())


def test_capture_writes_empty_file_for_empty_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """零命中日也必须有文件 — 覆盖哨点以文件存在性为准 (『跑过且什么都没看到』)。"""
    reports_dir, data_dir = _world(tmp_path)
    out = _out_dir(tmp_path)
    monkeypatch.setattr(BtstBreakoutSetup, "detect", _injected_detect(None))

    written = capture_setup_evidence_for_publication(
        SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir, out_dir=out
    )

    assert written is not None and written.exists()
    assert _rows(written) == []


def test_capture_rerun_merges_and_eligible_row_survives_miss_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """8-20 事件不变量: 晚到重扫 (数据抖动→miss) 不得抹掉既有 plan_eligible 行。"""
    reports_dir, data_dir = _world(tmp_path)
    out = _out_dir(tmp_path)
    monkeypatch.setattr(
        BtstBreakoutSetup, "detect", _injected_detect(_BTST_HIT_TICKER)
    )
    first = capture_setup_evidence_for_publication(
        SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir, out_dir=out
    )
    assert first is not None

    monkeypatch.setattr(BtstBreakoutSetup, "detect", _injected_detect(None))
    second = capture_setup_evidence_for_publication(
        SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir, out_dir=out
    )

    assert second == first
    eligible = {r["ticker"] for r in _rows(first) if r["plan_eligible"]}
    assert eligible == {_BTST_HIT_TICKER}


def test_capture_matches_dispatcher_face_row_for_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """捕获面与 --daily-action 写入面必须逐行同构 (同 loader/同扫描/同写入器)。"""
    reports_dir, data_dir = _world(tmp_path)
    capture_out = _out_dir(tmp_path)
    dispatcher_out = tmp_path / "dispatcher_out"
    dispatcher_out.mkdir()
    monkeypatch.setattr(
        BtstBreakoutSetup, "detect", _injected_detect(_BTST_HIT_TICKER)
    )

    captured = capture_setup_evidence_for_publication(
        SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir, out_dir=capture_out
    )

    # dispatcher 面: 同一 loader + 同一扫描 + 同一过滤 + 同一合并写入器。
    from src.screening.offensive.setup_output_log import log_setup_outputs

    verified = load_verified_daily_action_snapshot(
        SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
    )
    assert verified is not None and verified.snapshot is not None
    scan = scan_from_verified_snapshot(verified.snapshot)
    dispatcher_written = log_setup_outputs(
        verified.snapshot.signal_date,
        scan.candidates,
        plan_layer_blocked_candidates(scan),
        regime=verified.snapshot.regime,
        out_dir=dispatcher_out,
    )

    assert captured is not None
    assert captured.name == dispatcher_written.name == "20260713.jsonl"

    def strip(rows: list[dict]) -> list[tuple]:
        return sorted(
            tuple(sorted((k, str(v)) for k, v in r.items() if k != "logged_at"))
            for r in rows
        )

    assert strip(_rows(captured)) == strip(_rows(dispatcher_written))


def test_capture_needs_no_ledger_and_signature_has_no_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """纯证据捕获: 无台账文件的世界照常工作, 函数面无 repository 参数。"""
    import inspect

    reports_dir, data_dir = _world(tmp_path)
    assert not (data_dir / "daily_action_ledger.sqlite3").exists()
    out = _out_dir(tmp_path)
    monkeypatch.setattr(BtstBreakoutSetup, "detect", _injected_detect(None))

    written = capture_setup_evidence_for_publication(
        SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir, out_dir=out
    )

    assert written is not None
    assert "repository" not in inspect.signature(capture_setup_evidence_for_publication).parameters


def test_plan_layer_blocked_candidates_filters_data_contract_rejects() -> None:
    blocked = (
        types.SimpleNamespace(ticker="000001", reason="c2_flow_below_mean"),
        types.SimpleNamespace(ticker="002999", reason="candidate_not_plan_eligible"),
    )
    scan = types.SimpleNamespace(blocked_candidates=blocked)

    kept = plan_layer_blocked_candidates(scan)

    assert [b.ticker for b in kept] == ["000001"]


def test_publication_capture_wiring_healthy_attempt_and_error_triad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from src.screening import auto_pipeline

    calls: list[tuple[date, Path, Path, Path]] = []
    monkeypatch.setattr(
        "src.screening.offensive.setup_evidence_capture.capture_setup_evidence_for_publication",
        lambda signal_date, *, reports_dir, data_dir, out_dir=None: calls.append(
            (signal_date, Path(reports_dir), Path(data_dir), Path(out_dir))
        )
        or (Path(out_dir) / "x.jsonl"),
    )

    healthy = types.SimpleNamespace(
        status="healthy", manifest=types.SimpleNamespace(trade_date=SIGNAL_DATE)
    )
    auto_pipeline._capture_setup_evidence_after_publication(
        healthy, reports_dir=tmp_path / "reports", data_dir=tmp_path / "data"
    )
    assert calls == [
        (
            SIGNAL_DATE,
            tmp_path / "reports",
            tmp_path / "data",
            tmp_path / "reports" / "setup_output_log",
        )
    ]

    attempt = types.SimpleNamespace(status="attempt", manifest=None)
    auto_pipeline._capture_setup_evidence_after_publication(
        attempt, reports_dir=tmp_path / "reports", data_dir=tmp_path / "data"
    )
    assert len(calls) == 1  # attempt 不捕获

    def explode(*a, **k):
        raise RuntimeError("capture_failed")

    monkeypatch.setattr(
        "src.screening.offensive.setup_evidence_capture.capture_setup_evidence_for_publication",
        explode,
    )
    auto_pipeline._capture_setup_evidence_after_publication(
        healthy, reports_dir=tmp_path / "reports", data_dir=tmp_path / "data"
    )  # 异常被吞并 (advisory), 绝不阻断 --auto


def test_publication_capture_logs_success_and_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """F-a 观测性: 成功 info / healthy 后重验跳过 warning — 夜刷日志可判读。"""
    import logging

    from src.screening import auto_pipeline

    written = tmp_path / "setup_output_log" / "20260713.jsonl"
    monkeypatch.setattr(
        "src.screening.offensive.setup_evidence_capture.capture_setup_evidence_for_publication",
        lambda *a, **k: written,
    )
    healthy = types.SimpleNamespace(
        status="healthy", manifest=types.SimpleNamespace(trade_date=SIGNAL_DATE)
    )
    with caplog.at_level(logging.INFO, logger="src.screening.auto_pipeline"):
        auto_pipeline._capture_setup_evidence_after_publication(
            healthy, reports_dir=tmp_path, data_dir=tmp_path
        )
    assert any(
        "setup 信号证据已捕获" in r.getMessage() and r.levelno == logging.INFO
        for r in caplog.records
    )

    caplog.clear()
    monkeypatch.setattr(
        "src.screening.offensive.setup_evidence_capture.capture_setup_evidence_for_publication",
        lambda *a, **k: None,
    )
    with caplog.at_level(logging.INFO, logger="src.screening.auto_pipeline"):
        auto_pipeline._capture_setup_evidence_after_publication(
            healthy, reports_dir=tmp_path, data_dir=tmp_path
        )
    assert any(
        "捕获跳过" in r.getMessage() and r.levelno == logging.WARNING
        for r in caplog.records
    )
