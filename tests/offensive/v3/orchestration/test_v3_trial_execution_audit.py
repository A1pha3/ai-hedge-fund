"""v3_trial_execution_audit 审计工具的 fixture 世界测试 (R209 Op1)。

全 hermetic: tmp trial root (decisions/bars/evidence 三库 + blobs + 双臂
positions), 零宿主 data/ 读取 (R120b 家族纪律)。判定断言锚定
``resolve_open_execution`` 锁定判定表的缩小几何 (002815 limit_not_touched /
600162 触及价成交两个真实案例的形态复刻)。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.v3_trial_execution_audit import (
    audit_trial_execution,
    main as audit_main,
    render_human,
)

TRIAL_ID = "trial-audit-t1"
S_ENTRY = "2026-09-02"
S_EXIT = "2026-09-16"


def _decisions_db(trial_root: Path) -> sqlite3.Connection:
    trial_root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(trial_root / "decisions.sqlite3")
    conn.execute(
        """
        CREATE TABLE trial_arm_decisions (
            trial_id TEXT, signal_session TEXT, decision_cycle_id TEXT,
            arm TEXT, shared_input_hash TEXT, arm_policy_fingerprint TEXT,
            arm_capital_checkpoint_hash TEXT, regime_observation_hash TEXT,
            decision_json TEXT, created_at TEXT, artifact_hash TEXT
        )
        """
    )
    return conn


def _evidence_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    return conn


def _write_blob(trial_root: Path, payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    blob = trial_root / "blobs" / digest[:2] / digest[2:4] / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(raw)
    return "sha256:" + digest


def _insert_evidence_record(
    conn: sqlite3.Connection,
    *,
    evidence_id: str,
    payload_hash: str,
    commit_sequence: int = 1,
) -> None:
    record = {
        "evidence": {
            "evidence_id": evidence_id,
            "payload_content_hash": payload_hash,
        },
        "revision": 1,
        "commit_sequence": commit_sequence,
    }
    conn.execute(
        "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "market-bars",
            evidence_id,
            1,
            "bar_set",
            json.dumps(record),
            payload_hash,
            "2026-09-02T07:00:00Z",
            "2026-09-02T07:00:00Z",
            commit_sequence,
            None,
            None,
        ),
    )


def _bar(
    security_id: str,
    session: str,
    *,
    open_cents: int,
    high_cents: int,
    low_cents: int,
    close_cents: int,
    limit_up_cents: int,
    limit_down_cents: int,
    suspended: bool = False,
) -> dict:
    return {
        "security_id": security_id,
        "session": session,
        "open_cents": open_cents,
        "high_cents": high_cents,
        "low_cents": low_cents,
        "close_cents": close_cents,
        "limit_up_cents": limit_up_cents,
        "limit_down_cents": limit_down_cents,
        "suspended": suspended,
    }


def _line(
    line_id: str,
    security_id: str,
    *,
    limit: int,
    evidence_id: str,
    exit_session: str = S_EXIT,
) -> dict:
    quantity = 100
    fee = 5
    return {
        "shadow_line_id": line_id,
        "security_id": security_id,
        "producer_namespace": "btst",
        "family_id": "btst.limit-up-breakout",
        "economic_lineage_id": "eline-t1",
        "research_program_id": "research.btst.regime",
        "stage_id": "stage-t1-001",
        "trial_id": TRIAL_ID,
        "stage_manifest_hash": "a" * 64,
        "evidence_id": evidence_id,
        "evidence_artifact_hash": "b" * 64,
        "evidence_payload_hash": "c" * 64,
        "target_quantity_units": quantity,
        "lot_size_units": 100,
        "lot_rule_version": "cn-a-share-lot.v1",
        "order_type": "LIMIT",
        "limit_price_cents": limit,
        "worst_case_price_cents": limit,
        "price_boundary_version": "cn-price-limit.v1",
        "time_in_force": "OPEN_AUCTION",
        "exit_session_ordinal": 10,
        "estimated_fee_cents": fee,
        "estimated_cash_reserve_cents": limit * quantity + fee,
        "cost_assumption_version": "cn-a-share-costs.v1",
        "execution_assumption_version": "t0-close-t1-open-t10-open.v1",
        "target_exit_session": exit_session,
    }


def _admitted_decision(entry_session: str, lines: list[dict]) -> str:
    return json.dumps(
        {
            "target_entry_session": entry_session,
            "counterfactual_lines": lines,
            "execution_authority": "NONE",
        },
        ensure_ascii=False,
    )


def _no_trade_decision() -> str:
    return json.dumps(
        {"reason": "NO_SIGNAL", "decision_cycle_id": "daily-action-x"},
        ensure_ascii=False,
    )


def _insert_decision(
    conn: sqlite3.Connection, *, session: str, arm: str, decision_json: str
) -> None:
    conn.execute(
        "INSERT INTO trial_arm_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            TRIAL_ID,
            session,
            f"daily-action-{session.replace('-', '')}",
            arm,
            "h" * 64,
            None,
            "k" * 64,
            "m" * 64,
            decision_json,
            "2026-09-01T15:05:00Z",
            "z" * 64,
        ),
    )


@pytest.fixture()
def world(tmp_path: Path) -> Path:
    """缩小几何: L1=触及失败 NO_FILL / L2=触及成交且低于开盘价 / 一 no-trade pair。"""
    trial_root = tmp_path / "trial_root"
    bars_conn = _evidence_db(trial_root / "bars-evidence.sqlite3")

    entry_bars = {
        "session": S_ENTRY,
        "bars": [
            _bar(
                "002815.SZ",
                S_ENTRY,
                open_cents=1711,
                high_cents=1761,
                low_cents=1695,
                close_cents=1708,
                limit_up_cents=1761,
                limit_down_cents=1441,
            ),
            _bar(
                "600162.SH",
                S_ENTRY,
                open_cents=555,
                high_cents=563,
                low_cents=518,
                close_cents=522,
                limit_up_cents=605,
                limit_down_cents=495,
            ),
        ],
    }
    exit_bars = {
        "session": S_EXIT,
        "bars": [
            _bar(
                "600162.SH",
                S_EXIT,
                open_cents=490,
                high_cents=500,
                low_cents=456,
                close_cents=461,
                limit_up_cents=543,
                limit_down_cents=445,
            ),
        ],
    }
    for evidence_id, payload in (
        (f"market:bars:{S_ENTRY}", entry_bars),
        (f"market:bars:{S_EXIT}", exit_bars),
    ):
        _insert_evidence_record(bars_conn, evidence_id=evidence_id, payload_hash=_write_blob(trial_root, payload))
    bars_conn.commit()
    bars_conn.close()

    line1 = _line(
        "shadow-line-l1",
        "002815.SZ",
        limit=1601,
        evidence_id="btst:l1:selected",
    )
    line2 = _line(
        "shadow-line-l2",
        "600162.SH",
        limit=550,
        evidence_id="btst:l2:selected",
    )
    ev_conn = _evidence_db(trial_root / "evidence.sqlite3")
    for line, snapshot_micros in (
        (line1, 1601 * 10_000),
        (line2, 550 * 10_000),
    ):
        _insert_evidence_record(
            ev_conn,
            evidence_id=line["evidence_id"],
            payload_hash=_write_blob(
                trial_root, {"entry_price_micros": snapshot_micros}
            ),
        )
    ev_conn.commit()
    ev_conn.close()

    dec_conn = _decisions_db(trial_root)
    _insert_decision(
        dec_conn,
        session="2026-09-01",
        arm="CHAMPION",
        decision_json=_admitted_decision(S_ENTRY, [line1]),
    )
    _insert_decision(
        dec_conn,
        session="2026-09-01",
        arm="CHALLENGER",
        decision_json=_admitted_decision(S_ENTRY, [line2]),
    )
    _insert_decision(
        dec_conn,
        session=S_ENTRY,
        arm="CHAMPION",
        decision_json=_no_trade_decision(),
    )
    _insert_decision(
        dec_conn,
        session=S_ENTRY,
        arm="CHALLENGER",
        decision_json=_no_trade_decision(),
    )
    dec_conn.commit()
    dec_conn.close()

    arms = trial_root / "arms"
    for arm in ("champion", "challenger"):
        arm_dir = arms / arm
        arm_dir.mkdir(parents=True)
        conn = sqlite3.connect(arm_dir / "capital.sqlite3")
        conn.execute(
            """
            CREATE TABLE positions (
                position_lineage_id TEXT, economic_lot_id TEXT,
                security_id TEXT, state TEXT
            )
            """
        )
        conn.commit()
        conn.close()
    filled_lot = f"lot:{line2['shadow_line_id']}"
    conn = sqlite3.connect(arms / "challenger" / "capital.sqlite3")
    conn.execute(
        "INSERT INTO positions VALUES (?,?,?,?)",
        (f"shadow:{line2['shadow_line_id']}", filled_lot, "600162.SH", "OPEN"),
    )
    conn.commit()
    conn.close()
    return trial_root


def test_no_fill_line_disclosed_with_numbers(world: Path) -> None:
    report = audit_trial_execution(world, TRIAL_ID)
    line = report["pairs"]["2026-09-01"]["arms"]["CHAMPION"]["lines"][0]
    assert line["entry"]["verdict"] == "NO_FILL"
    assert line["entry"]["reason"] == "limit_not_touched"
    assert line["entry"]["fill_price_cents"] is None
    assert line["entry"]["bar"]["low_cents"] == 1695
    assert line["limit_price_cents"] == 1601
    assert line["exit"] == {"verdict": "not_applicable", "reason": "entry_not_filled"}


def test_filled_line_touch_price_and_off_open(world: Path) -> None:
    report = audit_trial_execution(world, TRIAL_ID)
    line = report["pairs"]["2026-09-01"]["arms"]["CHALLENGER"]["lines"][0]
    assert line["entry"]["verdict"] == "FILLED"
    assert line["entry"]["reason"] == "limit_touched"
    assert line["entry"]["fill_price_cents"] == 550
    assert line["entry"]["bar"]["open_cents"] == 555
    assert line["off_open_cents"] == 550 - 555
    assert line["exit"]["verdict"] == "FILLED"
    assert line["exit"]["fill_price_cents"] == 490


def test_no_trade_pair_classified(world: Path) -> None:
    report = audit_trial_execution(world, TRIAL_ID)
    champion = report["pairs"][S_ENTRY]["arms"]["CHAMPION"]
    assert champion["kind"] == "no_trade"
    assert champion["reason"] == "NO_SIGNAL"
    assert champion["lines"] == []


def test_aggregate_counts(world: Path) -> None:
    report = audit_trial_execution(world, TRIAL_ID)
    agg = report["aggregate"]
    assert agg["admitted_lines"] == 2
    assert agg["entry_filled"] == 1
    assert agg["entry_no_fill"] == 1
    assert agg["no_fill_reasons"] == {"limit_not_touched": 1}
    assert agg["filled_off_open"] == 1
    assert agg["limit_equals_entry_snapshot"] == 2


def test_reconciliation_positions(world: Path) -> None:
    report = audit_trial_execution(world, TRIAL_ID)
    recon = report["reconciliation"]
    assert recon["arms"]["challenger"]["positions_seen"] == 1
    assert recon["arms"]["challenger"]["findings"] == []
    assert recon["arms"]["champion"]["findings"] == []

    conn = sqlite3.connect(world / "arms" / "challenger" / "capital.sqlite3")
    conn.execute("DELETE FROM positions")
    conn.execute(
        "INSERT INTO positions VALUES (?,?,?,?)",
        ("shadow:ghost", "lot:shadow-line-ghost", "600162.SH", "OPEN"),
    )
    conn.commit()
    conn.close()

    report2 = audit_trial_execution(world, TRIAL_ID)
    findings = report2["reconciliation"]["arms"]["challenger"]["findings"]
    kinds = sorted(f["kind"] for f in findings)
    assert kinds == ["expected_fill_without_position", "position_without_tool_fill"]


def test_missing_entry_bar_resolves_unknown(world: Path) -> None:
    conn = sqlite3.connect(world / "bars-evidence.sqlite3")
    conn.execute(
        "DELETE FROM evidence_records WHERE evidence_id = ?",
        (f"market:bars:{S_ENTRY}",),
    )
    conn.commit()
    conn.close()
    report = audit_trial_execution(world, TRIAL_ID)
    line = report["pairs"]["2026-09-01"]["arms"]["CHALLENGER"]["lines"][0]
    assert line["entry"]["verdict"] == "UNKNOWN"
    assert line["entry"]["reason"] == "missing_bar"
    assert line["entry"]["bar"] is None
    assert line["off_open_cents"] is None
    assert report["aggregate"]["entry_unknown"] == 2
    assert report["aggregate"]["entry_filled"] == 0


def test_missing_candidate_snapshot_disclosed(world: Path) -> None:
    conn = sqlite3.connect(world / "evidence.sqlite3")
    conn.execute(
        "DELETE FROM evidence_records WHERE evidence_id = ?",
        ("btst:l1:selected",),
    )
    conn.commit()
    conn.close()
    report = audit_trial_execution(world, TRIAL_ID)
    line = report["pairs"]["2026-09-01"]["arms"]["CHAMPION"]["lines"][0]
    assert line["entry_snapshot_price_cents"] is None
    assert report["aggregate"]["limit_equals_entry_snapshot"] == 1


def test_one_price_limit_up_is_unknown(world: Path) -> None:
    locked = _bar(
        "000001.SZ",
        S_ENTRY,
        open_cents=1761,
        high_cents=1761,
        low_cents=1761,
        close_cents=1761,
        limit_up_cents=1761,
        limit_down_cents=1441,
    )
    conn = sqlite3.connect(world / "bars-evidence.sqlite3")
    row = conn.execute(
        "SELECT payload_content_hash FROM evidence_records WHERE evidence_id = ?",
        (f"market:bars:{S_ENTRY}",),
    ).fetchone()
    digest = row[0].split(":", 1)[1]
    blob = world / "blobs" / digest[:2] / digest[2:4] / digest
    payload = json.loads(blob.read_text())
    payload["bars"].append(locked)
    new_hash = _write_blob(world, payload)
    # 信封是真相源: record_json 内嵌哈希与列必须同步改写 (blob-before-envelope
    # 纪律 — loader 读信封哈希, 不读列)。
    row_json = json.loads(
        conn.execute(
            "SELECT record_json FROM evidence_records WHERE evidence_id = ?",
            (f"market:bars:{S_ENTRY}",),
        ).fetchone()[0]
    )
    row_json["evidence"]["payload_content_hash"] = new_hash
    conn.execute(
        "UPDATE evidence_records SET payload_content_hash = ?, record_json = ?"
        " WHERE evidence_id = ?",
        (
            new_hash,
            json.dumps(row_json),
            f"market:bars:{S_ENTRY}",
        ),
    )
    conn.commit()
    conn.close()

    line = _line(
        "shadow-line-l3",
        "000001.SZ",
        limit=1601,
        evidence_id="btst:l3:selected",
    )
    dec_conn = sqlite3.connect(world / "decisions.sqlite3")
    _insert_decision(
        dec_conn,
        session="2026-08-31",
        arm="CHAMPION",
        decision_json=_admitted_decision(S_ENTRY, [line]),
    )
    dec_conn.commit()
    dec_conn.close()

    report = audit_trial_execution(world, TRIAL_ID)
    audited = report["pairs"]["2026-08-31"]["arms"]["CHAMPION"]["lines"][0]
    assert audited["entry"]["verdict"] == "UNKNOWN"
    assert audited["entry"]["reason"] == "one_price_limit_up"


def test_missing_decisions_db_is_legal_startup(tmp_path: Path) -> None:
    trial_root = tmp_path / "empty_root"
    trial_root.mkdir()
    report = audit_trial_execution(trial_root, TRIAL_ID)
    assert report["pairs"] == {}
    assert report["section_errors"] == []
    assert audit_main(["--trial-root", str(trial_root), "--trial-id", TRIAL_ID]) == 0


def test_corrupt_bars_db_fails_closed(world: Path) -> None:
    (world / "bars-evidence.sqlite3").write_bytes(b"not a sqlite file at all")
    report = audit_trial_execution(world, TRIAL_ID)
    assert report["section_errors"], "corrupt bars db must be disclosed"
    assert report["section_errors"][0]["section"] == "bar_sets"
    assert audit_main(["--trial-root", str(world), "--trial-id", TRIAL_ID]) == 3


def test_trial_root_missing_is_operator_error(tmp_path: Path) -> None:
    assert (
        audit_main(
            ["--trial-root", str(tmp_path / "nope"), "--trial-id", TRIAL_ID]
        )
        == 2
    )


def test_zero_write_byte_level(world: Path) -> None:
    def snapshot(root: Path) -> list[tuple[str, int, int]]:
        return sorted(
            (str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob("*")
            if p.is_file()
        )

    before = snapshot(world)
    audit_trial_execution(world, TRIAL_ID)
    assert snapshot(world) == before


def test_main_json_output_and_human_render(world: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = audit_main(["--trial-root", str(world), "--trial-id", TRIAL_ID, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["trial_id"] == TRIAL_ID
    text = render_human(payload)
    assert "NO_FILL" in text
    assert "limit_not_touched" in text


# ---- R209 Op2 对抗收口: 6 BLIND 定谳的钉 (行为当前正确, 无钉守卫) ----


def _insert_superseding_evidence(
    conn: sqlite3.Connection,
    *,
    evidence_id: str,
    payload_hash: str,
    commit_sequence: int,
) -> None:
    record = {
        "evidence": {
            "evidence_id": evidence_id,
            "payload_content_hash": payload_hash,
        },
        "revision": 2,
        "commit_sequence": commit_sequence,
    }
    conn.execute(
        "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "market-bars",
            evidence_id,
            2,
            "bar_set",
            json.dumps(record),
            payload_hash,
            "t",
            "t",
            commit_sequence,
            1,
            None,
        ),
    )


def test_exit_not_due_when_exit_bars_absent(world: Path) -> None:
    """M14 钉: FILLED 入场 + 出场会话 bar 缺席 → 出场 not_due (不冒充 UNKNOWN)。"""
    conn = sqlite3.connect(world / "bars-evidence.sqlite3")
    conn.execute(
        "DELETE FROM evidence_records WHERE evidence_id = ?",
        (f"market:bars:{S_EXIT}",),
    )
    conn.commit()
    conn.close()
    report = audit_trial_execution(world, TRIAL_ID)
    line = report["pairs"]["2026-09-01"]["arms"]["CHALLENGER"]["lines"][0]
    assert line["entry"]["verdict"] == "FILLED"
    assert line["exit"] == {"verdict": "not_due", "reason": "exit_session_bars_absent"}


def test_terminal_position_state_not_counted(world: Path) -> None:
    """M10 钉: 终态持仓 (bust/correction 法律终态) 不入对账 held 集。"""
    conn = sqlite3.connect(world / "arms" / "challenger" / "capital.sqlite3")
    conn.execute(
        "INSERT INTO positions VALUES (?,?,?,?)",
        ("shadow:closed", "lot:shadow-line-closed", "600162.SH", "CLOSED"),
    )
    conn.commit()
    conn.close()
    report = audit_trial_execution(world, TRIAL_ID)
    recon = report["reconciliation"]["arms"]["challenger"]
    assert recon["positions_seen"] == 1
    assert recon["findings"] == []


def test_evidence_head_wins_on_revision(world: Path) -> None:
    """M11 钉: 同 evidence_id 多 revision 时 commit_sequence 最大的 head 胜 —
    bar-set 循环与候选快照循环两处同形选择面都钉 (探针须分别命中)。"""
    superseded_entry = {
        "session": S_ENTRY,
        "bars": [
            _bar(
                "002815.SZ",
                S_ENTRY,
                open_cents=1711,
                high_cents=1761,
                low_cents=1695,
                close_cents=1708,
                limit_up_cents=1761,
                limit_down_cents=1441,
            ),
            _bar(
                "600162.SH",
                S_ENTRY,
                open_cents=555,
                high_cents=563,
                low_cents=999,
                close_cents=522,
                limit_up_cents=605,
                limit_down_cents=495,
            ),
        ],
    }
    conn = sqlite3.connect(world / "bars-evidence.sqlite3")
    _insert_superseding_evidence(
        conn,
        evidence_id=f"market:bars:{S_ENTRY}",
        payload_hash=_write_blob(world, superseded_entry),
        commit_sequence=2,
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(world / "evidence.sqlite3")
    _insert_superseding_evidence(
        conn,
        evidence_id="btst:l2:selected",
        payload_hash=_write_blob(world, {"entry_price_micros": 999 * 10_000}),
        commit_sequence=2,
    )
    conn.commit()
    conn.close()

    report = audit_trial_execution(world, TRIAL_ID)
    line = report["pairs"]["2026-09-01"]["arms"]["CHALLENGER"]["lines"][0]
    # bar 头部: 新 revision low=999 → 限价 550 不再触及 → NO_FILL
    assert line["entry"]["verdict"] == "NO_FILL"
    assert line["entry"]["reason"] == "limit_not_touched"
    # 快照头部: 新 revision 快照价 999 (L1 的 1601 快照未动, 故计数为 1)
    assert line["entry_snapshot_price_cents"] == 999
    assert report["aggregate"]["limit_equals_entry_snapshot"] == 1


def test_malformed_blob_hash_fails_closed(world: Path) -> None:
    """M12 钉: 信封携带穿越形状哈希 → section error, 绝不读 blobs 外路径。"""
    conn = sqlite3.connect(world / "bars-evidence.sqlite3")
    record = {
        "evidence": {
            "evidence_id": f"market:bars:{S_ENTRY}",
            "payload_content_hash": "sha256:../../evil",
        },
        "revision": 9,
        "commit_sequence": 9,
    }
    conn.execute(
        "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "market-bars",
            f"market:bars:{S_ENTRY}",
            9,
            "bar_set",
            json.dumps(record),
            "sha256:../../evil",
            "t",
            "t",
            9,
            None,
            None,
        ),
    )
    conn.commit()
    conn.close()
    report = audit_trial_execution(world, TRIAL_ID)
    assert any(
        e["section"] == "bar_sets" and e["code"] == "bar_blob_unreadable"
        for e in report["section_errors"]
    )
    assert audit_main(["--trial-root", str(world), "--trial-id", TRIAL_ID]) == 3


def test_trial_filter_isolation(world: Path) -> None:
    """M13 钉: --trial-id 过滤是硬隔离 — 其他 trial 的行绝不入报告。"""
    other_line = _line(
        "shadow-line-other",
        "600162.SH",
        limit=550,
        evidence_id="btst:other:selected",
    )
    other = json.loads(_admitted_decision(S_ENTRY, [other_line]))
    other["target_entry_session"] = S_ENTRY
    conn = sqlite3.connect(world / "decisions.sqlite3")
    conn.execute(
        "INSERT INTO trial_arm_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "trial-OTHER",
            "2026-08-15",
            "daily-action-x",
            "CHAMPION",
            "h" * 64,
            None,
            "k" * 64,
            "m" * 64,
            json.dumps(other),
            "t",
            "z" * 64,
        ),
    )
    conn.commit()
    conn.close()
    report = audit_trial_execution(world, TRIAL_ID)
    assert "2026-08-15" not in report["pairs"]
    assert report["aggregate"]["admitted_lines"] == 2


def test_command_time_mirror_pinned_to_paired_trial() -> None:
    """M06 钉: 工具派生命令时刻与 paired_trial.advance_market_session 的
    派生闭包是同一镜像 — 词法双向钉 (任一侧漂移即红)。"""
    import re

    tool_src = Path("scripts/v3_trial_execution_audit.py").read_text(
        encoding="utf-8"
    )
    runner_src = Path(
        "src/screening/offensive/v3/orchestration/paired_trial.py"
    ).read_text(encoding="utf-8")
    tool_match = re.search(
        r"_COMMAND_AT_TIME = time\((\d+), (\d+)", tool_src
    )
    assert tool_match, "tool command-time constant missing"
    runner_match = re.search(r"time\((\d+), (\d+)\)", runner_src)
    assert runner_match, "paired_trial command-time literal missing"
    assert (
        (int(tool_match.group(1)), int(tool_match.group(2)))
        == (int(runner_match.group(1)), int(runner_match.group(2)))
    ), "command-time mirror drifted between tool and paired_trial"
    deadline_tool = re.search(r"_SEND_DEADLINE_MINUTES = (\d+)", tool_src)
    deadline_runner = re.search(r"_td\(minutes=(\d+)\)", runner_src)
    assert deadline_tool and deadline_runner
    assert deadline_tool.group(1) == deadline_runner.group(1), (
        "send-deadline mirror drifted between tool and paired_trial"
    )
