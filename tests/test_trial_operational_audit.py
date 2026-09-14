"""v3_trial_operational_audit — 官方 Trial 运营对账审计的 hermetic 测试 (R215 Op1).

夹具镜像生产 trial root 的存储形态 (列名与决策 JSON 双形状逐字段同构),
全部临时目录内构造; 不触真实 data/. 钉死的正确性面:
- 分类: no_trade (reason) 与 shadow_decision (schema_major==4 +
  counterfactual_lines) 双形状, 未知形状 typed 标记;
- 对账: unmatched_decided_line (决策行无台账痕迹) / orphan_position
  (持仓无决策来源) / exit_overdue (OPEN 且 target_exit ≤ as_of) /
  finalize_backlog / decide_missing / deadline_missed / bars_gap;
- 臂台账: NAV 总对数增长与 MDD 精确算术;
- 只读保证: 审计前后 trial root 全部文件字节哈希不变;
- fail-closed: 缺库 / 缺列 (schema_drift) / decision_json 损坏 / 空宇宙
  全 typed 拒绝;
- 渲染: md 契约节 + JSON 确定性 (同输入逐字节一致, 无墙钟);
- CLI: 端到端 0 退出 + typed 错误 2 退出。
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.v3_trial_operational_audit import (  # noqa: E402
    DECISION_SHAPE_NO_TRADE,
    DECISION_SHAPE_SHADOW,
    FINDING_BARS_GAP,
    FINDING_DEADLINE_MISSED,
    FINDING_DECIDE_MISSING,
    FINDING_EXIT_OVERDUE,
    FINDING_FINALIZE_BACKLOG,
    FINDING_ORPHAN_POSITION,
    FINDING_UNMATCHED_LINE,
    TrialAuditError,
    build_audit,
    derive_as_of,
    main,
    render_json,
    render_md,
)

TRIAL_ID = "trial-btst-regime-r1"
PROGRAM = "research.btst.regime"

LINE_L1 = "shadow-line-btst:sha256:" + "a1" * 32 + ":600162:btst_breakout"
LINE_L2 = "shadow-line-btst:sha256:" + "b2" * 32 + ":002815:btst_breakout"
LINE_ORPHAN = "shadow-line-btst:sha256:" + "c3" * 32 + ":300999:btst_breakout"


def _hex(n: int) -> str:
    return hashlib.sha256(str(n).encode()).hexdigest()


def _create_db(
    path: Path,
    tables: dict[str, tuple[str, ...]],
    rows: dict[str, tuple[tuple[str, ...], list[tuple]]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    for table, columns in tables.items():
        cols_sql = columns if isinstance(columns, str) else ", ".join(columns)
        con.execute(f"CREATE TABLE {table} ({cols_sql})")
        spec = rows.get(table)
        if spec is None:
            continue
        insert_cols, data = spec
        collist = ", ".join(insert_cols)
        placeholders = ", ".join("?" for _ in insert_cols)
        for row in data:
            con.execute(f"INSERT INTO {table} ({collist}) VALUES ({placeholders})", row)
    con.commit()
    con.close()


def _no_trade_json(session: str, reason: str) -> str:
    return json.dumps(
        {
            "portfolio_id": "pf-trial-btst-regime-r1",
            "signal_session": session,
            "decision_cycle_id": f"daily-action-{session}",
            "reason": reason,
            "detail": {},
            "kernel_input_hash": _hex(1),
        }
    )


def _shadow_json(session: str, entry: str, lines: list[dict]) -> str:
    return json.dumps(
        {
            "artifact_kind": "shadow_decision",
            "schema_major": 4,
            "portfolio_id": "pf-trial-btst-regime-r1",
            "signal_session": session,
            "counterfactual_lines": lines,
            "target_entry_session": entry,
        }
    )


def _line(line_id: str, security: str, exit_session: str) -> dict:
    return {
        "shadow_line_id": line_id,
        "security_id": security,
        "target_exit_session": exit_session,
        "target_quantity_units": 100,
    }


SPINE_TABLES = {
    "expected_sessions": (
        "research_program_id TEXT, signal_session TEXT, assessment_date TEXT, enrolled_at TEXT"
    ),
    "session_status_revisions": (
        "research_program_id TEXT, signal_session TEXT, revision INTEGER,"
        " status TEXT, calendar_revision_hash TEXT, recorded_at TEXT"
    ),
}

DECISIONS_TABLES = {
    "trial_arm_decisions": (
        "trial_id TEXT, signal_session TEXT, decision_cycle_id TEXT, arm TEXT,"
        " shared_input_hash TEXT, arm_policy_fingerprint TEXT,"
        " arm_capital_checkpoint_hash TEXT, regime_observation_hash TEXT,"
        " decision_json TEXT, created_at TEXT, artifact_hash TEXT"
    ),
}

CAPITAL_TABLES = {
    "economic_events": (
        "economic_event_id TEXT, idempotency_key TEXT, stream_version INTEGER,"
        " event_kind TEXT, portfolio_id TEXT, position_lineage_id TEXT,"
        " economic_lot_id TEXT, execution_mode TEXT, source_authority TEXT,"
        " effective_at TEXT, recorded_at TEXT, correction_of_event_id TEXT,"
        " payload_json TEXT, payload_content_hash TEXT, canonical_event_json TEXT"
    ),
    "positions": (
        "position_lineage_id TEXT, economic_lot_id TEXT, security_id TEXT, state TEXT,"
        " settled_quantity_units INTEGER, tradable_quantity_units INTEGER,"
        " share_receivable_quantity_units INTEGER, cost_basis_cents INTEGER,"
        " producer_namespace TEXT, research_program_id TEXT, economic_lineage_id TEXT,"
        " stage_id TEXT, opened_by_event_id TEXT, updated_by_event_id TEXT, updated_at TEXT"
    ),
    "nav_observations": (
        "nav_observation_id TEXT, portfolio_id TEXT, observation_kind TEXT,"
        " supersedes_observation_id TEXT, as_of TEXT, recorded_at TEXT,"
        " capital_version INTEGER, created_by_event_id TEXT, nav_cents INTEGER,"
        " issued_unit_quanta INTEGER, live_unit_quanta INTEGER,"
        " unit_price_numerator INTEGER, unit_price_denominator INTEGER,"
        " log_growth_kind TEXT, log_growth_nav_numerator INTEGER,"
        " log_growth_nav_denominator INTEGER"
    ),
}


def build_trial_root(
    tmp_path: Path,
    *,
    champion_line_exit: str = "2026-09-10",
    with_orphan_position: bool = True,
) -> Path:
    """镜像生产 trial root 五库形态的最小夹具 (语义见模块 docstring)."""
    root = tmp_path / "trial"
    (root / "arms").mkdir(parents=True)

    enrolled = [
        (PROGRAM, "2026-08-27", "2026-09-10", "e0"),
        (PROGRAM, "2026-08-28", "2026-09-11", "e1"),
        (PROGRAM, "2026-09-01", "2026-09-15", "e2"),
        (PROGRAM, "2026-09-02", "2026-09-16", "e3"),
        (PROGRAM, "2026-09-08", "2026-09-22", "e4"),
        (PROGRAM, "2026-09-15", "2026-09-29", "e5"),
    ]
    _create_db(
        root / "spine.sqlite3",
        SPINE_TABLES,
        {
            "expected_sessions": (
                ("research_program_id", "signal_session", "assessment_date", "enrolled_at"),
                enrolled,
            )
        },
    )

    decisions = [
        (TRIAL_ID, "2026-08-28", "c1", "CHAMPION", _no_trade_json("2026-08-28", "DEADLINE_MISSED"), "t1"),
        (TRIAL_ID, "2026-08-28", "c1", "CHALLENGER", _no_trade_json("2026-08-28", "DEADLINE_MISSED"), "t1"),
        (
            TRIAL_ID,
            "2026-09-01",
            "c2",
            "CHAMPION",
            _shadow_json(
                "2026-09-01",
                "2026-09-02",
                [_line(LINE_L1, "600162.SH", champion_line_exit)],
            ),
            "t2",
        ),
        (TRIAL_ID, "2026-09-01", "c2", "CHALLENGER", _no_trade_json("2026-09-01", "NO_SIGNAL"), "t2"),
        (
            TRIAL_ID,
            "2026-09-08",
            "c3",
            "CHAMPION",
            _shadow_json(
                "2026-09-08",
                "2026-09-09",
                [_line(LINE_L2, "002815.SZ", "2026-09-22")],
            ),
            "t3",
        ),
        (TRIAL_ID, "2026-09-08", "c3", "CHALLENGER", _no_trade_json("2026-09-08", "NO_SIGNAL"), "t3"),
    ]
    _create_db(
        root / "decisions.sqlite3",
        DECISIONS_TABLES,
        {
            "trial_arm_decisions": (
                ("trial_id", "signal_session", "decision_cycle_id", "arm", "decision_json", "created_at"),
                decisions,
            )
        },
    )

    bars = [
        (f"market:bars:{yyyymmdd}", ingested)
        for yyyymmdd, ingested in [
            ("20260828", "b1"),
            ("20260901", "b2"),
            ("20260908", "b3"),
            ("20260910", "b4"),
        ]
    ]
    _create_db(
        root / "bars-evidence.sqlite3",
        {"evidence_records": ("evidence_id TEXT, ingested_at TEXT")},
        {"evidence_records": (("evidence_id", "ingested_at"), bars)},
    )

    champion_events = [
        (
            f"fill:champion:{LINE_L1}:ENTRY:1",
            "TRADE_EXECUTED",
            f"shadow:{LINE_L1}",
            f"lot:{LINE_L1}",
            "2026-09-02T07:00:00Z",
        ),
        (
            f"fee:champion:{LINE_L1}",
            "FEE_CHARGED",
            f"shadow:{LINE_L1}",
            f"lot:{LINE_L1}",
            "2026-09-02T07:00:00Z",
        ),
        (
            "champion:valuation:20260910",
            "VALUATION",
            None,
            None,
            "2026-09-10T07:00:00Z",
        ),
    ]
    champion_positions = [
        (f"shadow:{LINE_L1}", f"lot:{LINE_L1}", "600162.SH", "OPEN", "2026-09-02T07:00:00Z"),
    ]
    champion_nav = [
        ("nav-a", "2026-08-28", "AS_OBSERVED", 10000000),
        ("nav-b", "2026-09-01", "AS_OBSERVED", 9995000),
        ("nav-c", "2026-09-10", "AS_OBSERVED", 9972797),
    ]
    _create_db(
        root / "arms" / "champion" / "capital.sqlite3",
        CAPITAL_TABLES,
        {
            "economic_events": (
                ("idempotency_key", "event_kind", "position_lineage_id", "economic_lot_id", "effective_at"),
                champion_events,
            ),
            "positions": (
                ("position_lineage_id", "economic_lot_id", "security_id", "state", "updated_at"),
                champion_positions,
            ),
            "nav_observations": (
                ("nav_observation_id", "as_of", "observation_kind", "nav_cents"),
                champion_nav,
            ),
        },
    )

    challenger_positions = []
    if with_orphan_position:
        challenger_positions = [
            (f"shadow:{LINE_ORPHAN}", f"lot:{LINE_ORPHAN}", "300999.SZ", "OPEN", "2026-09-02T07:00:00Z"),
        ]
    challenger_nav = [
        ("nav-a", "2026-08-28", "AS_OBSERVED", 10000000),
        ("nav-b", "2026-09-10", "AS_OBSERVED", 10000000),
    ]
    _create_db(
        root / "arms" / "challenger" / "capital.sqlite3",
        CAPITAL_TABLES,
        {
            "economic_events": (
                ("idempotency_key", "event_kind", "position_lineage_id", "economic_lot_id", "effective_at"),
                [],
            ),
            "positions": (
                ("position_lineage_id", "economic_lot_id", "security_id", "state", "updated_at"),
                challenger_positions,
            ),
            "nav_observations": (
                ("nav_observation_id", "as_of", "observation_kind", "nav_cents"),
                challenger_nav,
            ),
        },
    )
    return root


@pytest.fixture()
def trial_root(tmp_path: Path) -> Path:
    return build_trial_root(tmp_path)


def test_no_trade_shape_classified(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    decision = audit.decisions[("2026-08-28", "CHAMPION")]
    assert decision.shape == DECISION_SHAPE_NO_TRADE
    assert decision.reason == "DEADLINE_MISSED"
    assert decision.lines == ()


def test_shadow_shape_lines_parsed(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    champion = audit.decisions[("2026-09-01", "CHAMPION")]
    assert champion.shape == DECISION_SHAPE_SHADOW
    assert len(champion.lines) == 1
    assert champion.lines[0].shadow_line_id == LINE_L1
    assert champion.lines[0].target_exit_session == "2026-09-10"
    assert champion.target_entry_session == "2026-09-02"


def test_as_of_derived_from_bars(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    assert audit.as_of == "2026-09-10"


def test_unmatched_decided_line_finding(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    unmatched = [f for f in audit.findings if f.code == FINDING_UNMATCHED_LINE]
    assert len(unmatched) == 1
    assert unmatched[0].arm == "CHAMPION"  # 决策面原样大写
    assert unmatched[0].signal_session == "2026-09-08"
    assert "002815.SZ" in unmatched[0].detail


def test_filled_line_not_unmatched(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    unmatched_ids = [
        f.detail for f in audit.findings if f.code == FINDING_UNMATCHED_LINE
    ]
    assert all("600162.SH" not in detail for detail in unmatched_ids)


def test_exit_overdue_open_position(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    overdue = [f for f in audit.findings if f.code == FINDING_EXIT_OVERDUE]
    assert len(overdue) == 1
    assert overdue[0].arm == "champion"
    assert "600162.SH" in overdue[0].detail


def test_exit_in_future_not_overdue(tmp_path: Path) -> None:
    root = build_trial_root(tmp_path, champion_line_exit="2026-09-22")
    audit = build_audit(root, TRIAL_ID, PROGRAM)
    assert not [f for f in audit.findings if f.code == FINDING_EXIT_OVERDUE]


def test_orphan_position_finding(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    orphans = [f for f in audit.findings if f.code == FINDING_ORPHAN_POSITION]
    assert len(orphans) == 1
    assert orphans[0].arm == "challenger"
    assert "300999.SZ" in orphans[0].detail


def test_no_orphan_without_extra_position(tmp_path: Path) -> None:
    root = build_trial_root(tmp_path, with_orphan_position=False)
    audit = build_audit(root, TRIAL_ID, PROGRAM)
    assert not [f for f in audit.findings if f.code == FINDING_ORPHAN_POSITION]


def test_finalize_backlog_and_decide_missing(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    finalize = [f for f in audit.findings if f.code == FINDING_FINALIZE_BACKLOG]
    assert [(f.signal_session) for f in finalize] == ["2026-08-27"]
    missing = [f for f in audit.findings if f.code == FINDING_DECIDE_MISSING]
    assert [(f.signal_session) for f in missing] == ["2026-09-02"]


def test_deadline_missed_finding(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    missed = [f for f in audit.findings if f.code == FINDING_DEADLINE_MISSED]
    assert [(f.signal_session) for f in missed] == ["2026-08-28"]


def test_bars_gap_finding(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    gaps = sorted(f.signal_session for f in audit.findings if f.code == FINDING_BARS_GAP)
    assert gaps == ["2026-08-27", "2026-09-02"]


def test_future_session_not_flagged(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    future_flags = [
        f
        for f in audit.findings
        if f.signal_session == "2026-09-15"
        and f.code in {FINDING_BARS_GAP, FINDING_DECIDE_MISSING, FINDING_FINALIZE_BACKLOG}
    ]
    assert future_flags == []


def test_nav_summary_exact_arithmetic(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    by_arm = {s.arm: s for s in audit.arm_summaries}
    champion = by_arm["champion"]
    assert (champion.nav_first[1], champion.nav_last[1]) == (10000000, 9972797)
    assert champion.total_log_growth == pytest.approx(math.log(9972797 / 10000000))
    assert champion.max_drawdown == pytest.approx(math.log(9972797 / 10000000))
    assert champion.fills == 1
    assert champion.open_positions == 1
    challenger = by_arm["challenger"]
    assert challenger.total_log_growth == 0.0
    assert challenger.max_drawdown == 0.0


def test_audit_zero_mutation(trial_root: Path) -> None:
    def snapshot(root: Path) -> dict[str, str]:
        out: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return out

    before = snapshot(trial_root)
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    render_md(audit)
    render_json(audit)
    assert snapshot(trial_root) == before


def test_store_missing_typed(tmp_path: Path) -> None:
    with pytest.raises(TrialAuditError) as excinfo:
        build_audit(tmp_path / "nope", TRIAL_ID, PROGRAM)
    assert excinfo.value.code == "store_missing"


def test_schema_drift_typed(tmp_path: Path) -> None:
    root = build_trial_root(tmp_path)
    (root / "decisions.sqlite3").unlink()
    con = sqlite3.connect(root / "decisions.sqlite3")
    con.execute(
        "CREATE TABLE trial_arm_decisions (trial_id TEXT, signal_session TEXT,"
        " arm TEXT, decision_json TEXT)"
    )
    con.commit()
    con.close()
    with pytest.raises(TrialAuditError) as excinfo:
        build_audit(root, TRIAL_ID, PROGRAM)
    assert excinfo.value.code == "schema_drift"
    assert "created_at" in excinfo.value.details["missing_columns"]


def test_decision_json_invalid_typed(tmp_path: Path) -> None:
    root = build_trial_root(tmp_path)
    con = sqlite3.connect(root / "decisions.sqlite3")
    con.execute(
        "UPDATE trial_arm_decisions SET decision_json = 'not-json' WHERE signal_session = '2026-09-01'"
    )
    con.commit()
    con.close()
    with pytest.raises(TrialAuditError) as excinfo:
        build_audit(root, TRIAL_ID, PROGRAM)
    assert excinfo.value.code == "decision_json_invalid"


def test_derive_as_of_empty_world_typed() -> None:
    with pytest.raises(TrialAuditError) as excinfo:
        derive_as_of({}, [])
    assert excinfo.value.code == "empty_trial_world"


def test_render_md_contract(trial_root: Path) -> None:
    audit = build_audit(trial_root, TRIAL_ID, PROGRAM)
    md = render_md(audit)
    assert f"# 官方 Trial 运营对账审计 — {TRIAL_ID}" in md
    assert "**2026-09-10**" in md
    assert "| 2026-08-28 | 2026-09-11 | DEADLINE_MISSED | DEADLINE_MISSED | ✓ |" in md
    assert "| 2026-09-15 | 2026-09-29 | — | — | ✗ |" in md
    assert FINDING_UNMATCHED_LINE in md
    assert FINDING_EXIT_OVERDUE in md
    assert "## 纪律" in md
    assert "字节级零突变" in md
    assert f"剩余报名会话 (>2026-09-10): 1 (首个 2026-09-15)" in md


def test_render_json_deterministic(trial_root: Path) -> None:
    first = render_json(build_audit(trial_root, TRIAL_ID, PROGRAM))
    second = render_json(build_audit(trial_root, TRIAL_ID, PROGRAM))
    assert first == second
    payload = json.loads(first)
    assert payload["finding_counts"][FINDING_UNMATCHED_LINE] == 1
    assert payload["finding_counts"][FINDING_EXIT_OVERDUE] == 1
    assert payload["as_of"] == "2026-09-10"
    assert len(payload["decisions"]) == 6


def test_cli_end_to_end(tmp_path: Path) -> None:
    root = build_trial_root(tmp_path)
    out_md = tmp_path / "audit.md"
    out_json = tmp_path / "audit.json"
    rc = main(
        [
            "--trial-root", str(root),
            "--trial-id", TRIAL_ID,
            "--research-program", PROGRAM,
            "--output-md", str(out_md),
            "--output-json", str(out_json),
        ]
    )
    assert rc == 0
    assert out_md.exists() and out_json.exists()
    assert json.loads(out_json.read_text())["as_of"] == "2026-09-10"


def test_cli_typed_error_exit_2(tmp_path: Path) -> None:
    rc = main(
        [
            "--trial-root", str(tmp_path / "missing"),
            "--trial-id", TRIAL_ID,
            "--research-program", PROGRAM,
        ]
    )
    assert rc == 2
