"""v3_trial_evidence 官方 Trial 证据消费面的 fixture 世界测试 (R225 Op1)。

全 hermetic: tmp trial root (governance/decisions/bars-evidence 三库 + 双臂
nav_observations/positions), 零宿主 data/ 读取 (R120b 家族纪律)。冻结统计
只经 ``src...evidence.paired_statistics`` 单一实现, 本工具零公式 fork;
密封 SAP ``block_rule='monthly'`` 与冻结评估器数字块长语法的结构性不相容
(2026-11-26 固定评估日会 invalid_block_rule 砖死) 是本消费面的类型化响亮
披露对象——真实 trial root 必现。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.v3_trial_evidence import (
    TrialEvidenceError,
    build_paired_points,
    collect_evidence,
    main as evidence_main,
    render_json,
)


TRIAL_ID = "trial-evidence-t1"
PROGRAM = "research.btst.regime"

NAV_COLUMNS = (
    "nav_observation_id, portfolio_id, observation_kind,"
    " supersedes_observation_id, as_of, recorded_at, capital_version,"
    " created_by_event_id, nav_cents, issued_unit_quanta, live_unit_quanta,"
    " unit_price_numerator, unit_price_denominator, log_growth_kind,"
    " log_growth_nav_numerator, log_growth_nav_denominator"
)


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def _make_arm_ledger(root: Path, arm: str, ratios: list[tuple[str, int | None, int | None]],
                     positions: list[tuple[str, str, int]]) -> None:
    """ratios: (as_of, num, den); genesis 行 num/den 为 None。"""
    path = root / "arms" / arm / "capital.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        f"CREATE TABLE nav_observations ({NAV_COLUMNS})"
    )
    for index, (as_of, num, den) in enumerate(ratios):
        kind = "NO_PRIOR_OBSERVATION" if num is None else "FINITE"
        conn.execute(
            "INSERT INTO nav_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"nav-{arm}-{index}", f"pf-{TRIAL_ID}", "AS_OBSERVED", None,
                f"{as_of}T07:00:00+00:00", f"{as_of}T07:00:00+00:00", index,
                None, 10000000 + index, 10000000, 10000000, 1, 1, kind,
                num, den,
            ),
        )
    conn.execute(
        """
        CREATE TABLE positions (
            position_lineage_id TEXT, economic_lot_id TEXT, security_id TEXT,
            state TEXT, settled_quantity_units INTEGER,
            tradable_quantity_units INTEGER,
            share_receivable_quantity_units INTEGER, cost_basis_cents INTEGER,
            producer_namespace TEXT, research_program_id TEXT,
            economic_lineage_id TEXT, stage_id TEXT,
            opened_by_event_id TEXT, updated_by_event_id TEXT, updated_at TEXT
        )
        """
    )
    for lineage, security, state in positions:
        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lineage, lineage + "-lot", security, state, 300, 300, 0, 165000,
             "btst", PROGRAM, "eline-t1", "stage-t1", "e1", "e1",
             "2026-09-09T07:00:00+00:00"),
        )
    conn.commit()
    conn.close()


def _make_governance(
    root: Path, *, block_rule: str = "monthly", bootstrap_method: str = "wild"
) -> None:
    path = root / "governance.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE sealed_trials (
            trial_id TEXT, research_program_id TEXT, economic_lineage_id TEXT,
            role TEXT, trial_manifest_hash TEXT, trial_manifest_json TEXT,
            sap_manifest_hash TEXT, sap_manifest_json TEXT,
            attempt_budget_reservation_id TEXT, sealed_at TEXT
        )
        """
    )
    trial_manifest = {
        "trial_id": TRIAL_ID,
        "research_program_id": PROGRAM,
        "minimum_economic_effect": 0.001,
        "fixed_assessment_date": "2026-11-26T04:00:00+00:00",
    }
    sap_manifest = {
        "sap_id": TRIAL_ID,
        "primary_metric": "PORTFOLIO_LOG_GROWTH",
        "execution_mode": "daily_bar_proxy",
        "one_sided_confidence_level": "0.95",
        "bootstrap_method": bootstrap_method,
        "repetitions": 10000,
        "seed": 42,
        "block_rule": block_rule,
    }
    conn.execute(
        "INSERT INTO sealed_trials VALUES (?,?,?,?,?,?,?,?,?,?)",
        (TRIAL_ID, PROGRAM, "eline-t1", "REGIME_TRIAL", "h1",
         json.dumps(trial_manifest), "h2", json.dumps(sap_manifest),
         "res-1", "2026-08-28T03:55:00Z"),
    )
    conn.commit()
    conn.close()


def _make_decisions(root: Path, rows: list[tuple[str, str, dict | str]]) -> None:
    path = root / "decisions.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trial_arm_decisions (
            trial_id TEXT, signal_session TEXT, decision_cycle_id TEXT,
            arm TEXT, shared_input_hash TEXT, arm_policy_fingerprint TEXT,
            arm_capital_checkpoint_hash TEXT, regime_observation_hash TEXT,
            decision_json TEXT, created_at TEXT, artifact_hash TEXT
        )
        """
    )
    for session, arm, decision in rows:
        payload = decision if isinstance(decision, str) else json.dumps(decision)
        conn.execute(
            "INSERT INTO trial_arm_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (TRIAL_ID, session, f"cyc-{session}", arm, "h", "h", "h", "h",
             payload, "2026-09-01T00:00:00Z", "ah"),
        )
    conn.commit()
    conn.close()


def _run_decision(session: str, security: str, exit_session: str) -> dict:
    return {
        "artifact_kind": "shadow_decision",
        "schema_major": 4,
        "portfolio_id": f"pf-{TRIAL_ID}",
        "signal_session": session,
        "target_entry_session": session,
        "counterfactual_lines": [
            {
                "shadow_line_id": f"shadow-line-{session}",
                "security_id": security,
                "target_quantity_units": 300,
                "target_exit_session": exit_session,
                "limit_price_cents": 550,
            }
        ],
    }


NO_TRADE = {"reason": "NO_SIGNAL", "signal_session": "x"}


def _make_bars(root: Path, sessions: list[str]) -> None:
    path = root / "bars-evidence.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE evidence_records (
            issuer_namespace TEXT, evidence_id TEXT, revision INTEGER,
            evidence_kind TEXT, record_json TEXT, payload_content_hash TEXT,
            ingested_at TEXT, activated_at TEXT, commit_sequence INTEGER,
            supersedes_revision INTEGER, dependency_root TEXT
        )
        """
    )
    for index, session in enumerate(sessions):
        raw = session.replace("-", "")
        conn.execute(
            "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("btst", f"market:bars:{raw}", 1, "snapshot", "{}", "h",
             f"2026-09-0{index + 1}T07:00:00+00:00", None, index + 1, None,
             None),
        )
    conn.commit()
    conn.close()


_RATIOS_A = [
    ("2026-09-01", None, None),
    ("2026-09-01", 1, 1),
    ("2026-09-02", 9990000, 10000000),
    ("2026-09-03", 9980000, 9990000),
    ("2026-09-04", 9990000, 9980000),
]


def _world(
    tmp_path: Path, *, block_rule: str = "monthly", bootstrap_method: str = "wild"
) -> Path:
    root = tmp_path / "trial-root"
    root.mkdir(parents=True)
    _make_governance(root, block_rule=block_rule, bootstrap_method=bootstrap_method)
    _make_decisions(root, [
        ("2026-09-01", "CHAMPION", NO_TRADE),
        ("2026-09-02", "CHAMPION", NO_TRADE),
        ("2026-09-03", "CHAMPION", _run_decision("2026-09-03", "600162.SH", "2026-09-17")),
        ("2026-09-03", "CHALLENGER", _run_decision("2026-09-03", "600162.SH", "2026-09-17")),
    ])
    _make_arm_ledger(root, "champion", _RATIOS_A,
                     [("lot-open-1", "600162.SH", "OPEN"),
                      ("lot-closed-1", "002815.SZ", "CLOSED")])
    _make_arm_ledger(root, "challenger", _RATIOS_A,
                     [("lot-open-2", "600162.SH", "OPEN")])
    _make_bars(root, ["2026-09-03", "2026-09-04"])
    return root


def test_ladder_skips_no_prior_and_keeps_ratio_points(tmp_path) -> None:
    root = _world(tmp_path)
    points = build_paired_points(root)
    # genesis 无前值行被跳过 (与评估器 _points_for 同语义), 4 个比率点
    assert [p.session.isoformat() for p in points] == [
        "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
    ]
    assert points[0].champion_nav_numerator == 1
    assert points[2].challenger_nav_denominator == 9990000


def test_ladder_arm_misalignment_typed(tmp_path) -> None:
    root = _world(tmp_path)
    # challenger 重写为少一个比率会话 (同根双臂不对齐)
    ledger = root / "arms" / "challenger" / "capital.sqlite3"
    ledger.unlink()
    _make_arm_ledger(root, "challenger", _RATIOS_A[:-1], [])
    with pytest.raises(TrialEvidenceError) as excinfo:
        build_paired_points(root)
    assert excinfo.value.code == "session_alignment"


def test_unsupported_observation_kind_typed(tmp_path) -> None:
    root = _world(tmp_path)
    conn = sqlite3.connect(root / "arms" / "champion" / "capital.sqlite3")
    conn.execute(
        "UPDATE nav_observations SET observation_kind='RESTATED_FINAL'"
        " WHERE as_of LIKE '2026-09-04%'"
    )
    conn.commit()
    conn.close()
    with pytest.raises(TrialEvidenceError) as excinfo:
        build_paired_points(root)
    assert excinfo.value.code == "unsupported_observation_kind"


def test_frozen_evaluation_blocked_on_sealed_monthly_block_rule(tmp_path) -> None:
    """密封 SAP block_rule='monthly' (真实 trial 的 owner 批准值) 与冻结
    评估器数字块长语法结构性不相容 —— 消费面必须类型化响亮披露。"""
    root = _world(tmp_path, block_rule="monthly")
    payload = collect_evidence(root, TRIAL_ID)
    frozen = payload["frozen_evaluation"]
    assert frozen["status"] == "blocked"
    assert frozen["code"] == "invalid_block_rule"
    assert frozen["sap_block_rule"] == "monthly"


def test_component_bounds_ok_when_numeric_block_rule(tmp_path) -> None:
    root = _world(tmp_path, block_rule="2", bootstrap_method="stationary")
    payload = collect_evidence(root, TRIAL_ID)
    frozen = payload["frozen_evaluation"]
    assert frozen["status"] == "ok"
    assert frozen["n_deltas"] == 4
    # 双臂有理数逐点相同 → 配对 delta 恒 0, 均值 0
    assert frozen["mean_delta"] == 0.0
    assert frozen["bootstrap_lcb"] == 0.0
    assert frozen["hac_lcb"] == 0.0
    assert "official_assembly_not_replicated" in frozen


def test_frozen_evaluation_deterministic(tmp_path) -> None:
    root = _world(tmp_path, block_rule="2")
    first = collect_evidence(root, TRIAL_ID)["frozen_evaluation"]
    second = collect_evidence(root, TRIAL_ID)["frozen_evaluation"]
    assert first == second


def test_coverage_proxy_counts_and_official_predicates_none(tmp_path) -> None:
    root = _world(tmp_path)
    payload = collect_evidence(root, TRIAL_ID)
    coverage = payload["coverage"]
    assert coverage["proxies"]["sessions_with_pairs_any"] == 3
    assert coverage["proxies"]["sessions_with_run_pairs"] == 1
    assert coverage["proxies"]["mature_outcome_proxy_champion"] == 1
    assert coverage["proxies"]["mature_outcome_proxy_challenger"] == 0
    assert coverage["proxies"]["distinct_tickers_champion"] == 2
    # 官方谓词不可推导 (Outcome Finalizer 未接 live trial), 显式 None
    assert coverage["official_mature_outcomes"] is None
    assert coverage["official_decision_days"] is None
    assert coverage["official_effective_sample_size"] is None


def test_pending_exits_disclosure(tmp_path) -> None:
    root = _world(tmp_path)
    payload = collect_evidence(root, TRIAL_ID)
    pending = payload["pending_exits"]
    champion = pending["champion"]
    assert champion["open_positions"] == 1
    assert champion["positions"][0]["security_id"] == "600162.SH"
    assert champion["positions"][0]["target_exit_session"] == "2026-09-17"


def test_freshness_latest_bar_vs_latest_nav(tmp_path) -> None:
    root = _world(tmp_path)
    payload = collect_evidence(root, TRIAL_ID)
    freshness = payload["freshness"]
    assert freshness["latest_bar_session"] == "2026-09-04"
    assert freshness["latest_nav_as_of"] == "2026-09-04"


def test_zero_write_guarantee(tmp_path) -> None:
    root = _world(tmp_path)

    def tree_digest() -> dict[str, str]:
        out: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                out[str(path.relative_to(root))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
        return out

    before = tree_digest()
    collect_evidence(root, TRIAL_ID)
    assert tree_digest() == before


def test_missing_databases_is_legal_startup(tmp_path) -> None:
    root = tmp_path / "empty-root"
    root.mkdir()
    payload = collect_evidence(root, TRIAL_ID)
    assert payload["status"] == "not_seeded"
    assert payload["paired_points"] == 0


def test_corrupt_decision_json_typed(tmp_path) -> None:
    root = _world(tmp_path)
    _make_decisions(root, [("2026-09-04", "CHAMPION", "{not-json")])
    with pytest.raises(TrialEvidenceError) as excinfo:
        collect_evidence(root, TRIAL_ID)
    assert excinfo.value.code == "decision_json_corrupt"


def test_unknown_decision_shape_typed(tmp_path) -> None:
    root = _world(tmp_path)
    _make_decisions(root, [("2026-09-04", "CHAMPION", {"weird": "shape"})])
    with pytest.raises(TrialEvidenceError) as excinfo:
        collect_evidence(root, TRIAL_ID)
    assert excinfo.value.code == "decision_shape_unknown"


def test_schema_drift_typed(tmp_path) -> None:
    root = _world(tmp_path)
    conn = sqlite3.connect(root / "arms" / "champion" / "capital.sqlite3")
    conn.execute("ALTER TABLE nav_observations DROP COLUMN log_growth_kind")
    conn.commit()
    conn.close()
    with pytest.raises(TrialEvidenceError) as excinfo:
        collect_evidence(root, TRIAL_ID)
    assert excinfo.value.code == "schema_drift"


def test_json_render_reproducible_and_cli_exit_zero(tmp_path, capsys) -> None:
    root = _world(tmp_path)
    rc = evidence_main([
        "--trial-root", str(root), "--trial-id", TRIAL_ID, "--json",
    ])
    assert rc == 0
    first = capsys.readouterr().out
    rc = evidence_main([
        "--trial-root", str(root), "--trial-id", TRIAL_ID, "--json",
    ])
    assert rc == 0
    second = capsys.readouterr().out
    assert first == second
    payload = json.loads(first)
    assert payload["sap"]["block_rule"] == "monthly"
    assert payload["trial"]["minimum_economic_effect"] == 0.001


def test_corrupt_store_exit_three(tmp_path, capsys) -> None:
    root = _world(tmp_path)
    _make_decisions(root, [("2026-09-04", "CHAMPION", "{not-json")])
    rc = evidence_main([
        "--trial-root", str(root), "--trial-id", TRIAL_ID, "--json",
    ])
    assert rc == 3
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["errors"] == ["decision_json_corrupt"]


def test_frozen_evaluation_blocked_on_unregistered_wild_method(tmp_path) -> None:
    """密封 SAP bootstrap_method='wild' (真实 trial 值) 不在冻结评估器
    预注册方法表 {moving, stationary, circular} —— 第二处终评估砖点,
    消费面同样类型化披露 (块长语法修好后 method 缺陷独立显形)。"""
    root = _world(tmp_path, block_rule="2", bootstrap_method="wild")
    payload = collect_evidence(root, TRIAL_ID)
    frozen = payload["frozen_evaluation"]
    assert frozen["status"] == "blocked"
    assert frozen["code"] == "unregistered_method"
