#!/usr/bin/env python
"""v3 官方前向 Trial 只读观测面 (R107 Op1; R105 登记观测面缺口的收口).

一条命令拼出此前需要 15+ 次手工 sqlite 查询的 trial 图景 (R105 入册的
运营摩擦: spine enrollment / 双臂 decision reason / arms NAV / evidence
命名空间 / nightly 链)。owner 日常监控唯一活跃改进路径 (前向证据积累、
首个 RUN 生命周期) 的输入面。

诚实边界 (与 threshold_trigger.py 同款读取侧纪律):
- **只读**: 全部 sqlite 经 ``mode=ro&immutable=1`` 冷读 (夜间链 PAIR_ENUM
  同款纪律) — 不创建/触碰 ``-shm``、不能 checkpoint、不能写主库; 字节级
  零写入 (含文件集不变) 有测试钉死。**新鲜度边界如实**: immutable 只见
  已 checkpoint 的主文件——活 writer (夜间链 23:05 窗口内) 未落盘增量
  不可见, 失败方向=欠新鲜, 与夜间链 advance 枚举面语义一致; 干净关闭的
  writer (每阶段结束) 已 checkpoint, 冷读可见全部已提交数据。
- **verbatim 披露, 不重推导**: per-arm 决策按 decision_json 原文披露
  kind/reason/line_count; canonical ``classify_pair_session`` 的
  RUN/NO_SIGNAL/BLOCKED 语义属 frozen evaluator, 本工具的 summary 计数
  是披露面口径 (no_trade = 两臂均 no-trade; run = 任一臂有入场线)。
- **缺库是合法启动形态** (R37: decisions 缺失 → 首 decide 自建;
  arms 缺失 → genesis-seed 未跑): per-section 报 ``missing``, 整体
  exit 0; **损坏库 per-section 报 ``error`` 不吞** (P2-1 纪律)。
- trial root 目录不存在 = 操作员错误 → exit 2。

用法:
    .venv/bin/python scripts/v3_trial_status.py
    .venv/bin/python scripts/v3_trial_status.py --trial-root data/v3_trial_root --json
    .venv/bin/python scripts/v3_trial_status.py --nightly-history logs/cron/v3_nightly_history.jsonl
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

DEFAULT_TRIAL_ROOT = Path("data/v3_trial_root")
DEFAULT_NIGHTLY_HISTORY = Path("logs/cron/v3_nightly_history.jsonl")
ARMS = ("champion", "challenger")
EVIDENCE_DBS = ("evidence.sqlite3", "bars-evidence.sqlite3")


class TrialStatusError(ValueError):
    """操作员错误 (非报告状态): trial root 不存在。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _connect_ro(path: Path) -> sqlite3.Connection:
    """只读冷连接 (immutable): 不创建 -shm、不写主库, 只见已 checkpoint 数据。"""
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def _section_ok(**fields: Any) -> dict[str, Any]:
    return {"status": "ok", **fields}


def _section_missing(detail: str) -> dict[str, Any]:
    return {"status": "missing", "detail": detail}


def _section_error(exc: BaseException) -> dict[str, Any]:
    return {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}


def _collect_trial(root: Path) -> dict[str, Any]:
    db = root / "decisions.sqlite3"
    if not db.is_file():
        return _section_missing("decisions store not initialized (no decide yet)")
    try:
        conn = _connect_ro(db)
        try:
            rows = conn.execute(
                "SELECT trial_id, registered_at, genesis_manifest_json"
                " FROM trial_registrations"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _section_error(exc)
    registrations = []
    for trial_id, registered_at, genesis_json in rows:
        genesis: dict[str, Any] = {}
        try:
            manifest = json.loads(genesis_json)
            if isinstance(manifest, dict):
                genesis = {
                    "sealed_at": manifest.get("sealed_at"),
                    "champion_normalized_hash": manifest.get(
                        "champion_normalized_hash"
                    ),
                    "challenger_normalized_hash": manifest.get(
                        "challenger_normalized_hash"
                    ),
                }
        except (json.JSONDecodeError, TypeError):
            genesis = {"parse_error": True}
        registrations.append(
            {
                "trial_id": trial_id,
                "registered_at": str(registered_at),
                "genesis": genesis,
            }
        )
    return _section_ok(registrations=registrations)


def _collect_spine(root: Path) -> dict[str, Any]:
    db = root / "spine.sqlite3"
    if not db.is_file():
        return _section_missing("spine not registered (enroll-spine 未跑)")
    try:
        conn = _connect_ro(db)
        try:
            enrolled = conn.execute(
                "SELECT research_program_id, signal_session, assessment_date,"
                " enrolled_at FROM expected_sessions ORDER BY signal_session"
            ).fetchall()
            revisions = conn.execute(
                "SELECT signal_session, revision, status, recorded_at"
                " FROM session_status_revisions ORDER BY signal_session, revision"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _section_error(exc)
    terminal: dict[str, dict[str, Any]] = {}
    for session, revision, status, recorded_at in revisions:
        terminal[str(session)] = {
            "status": status,
            "revision": revision,
            "recorded_at": str(recorded_at),
        }
    sessions = [
        {
            "signal_session": str(session),
            "assessment_date": str(assessment),
            "terminal_status": terminal.get(str(session)),
        }
        for program, session, assessment, enrolled_at in enrolled
    ]
    return _section_ok(
        enrolled_count=len(sessions),
        first_session=sessions[0]["signal_session"] if sessions else None,
        last_session=sessions[-1]["signal_session"] if sessions else None,
        terminal_status_count=len(terminal),
        sessions=sessions,
    )


def _classify_decision_json(raw: str) -> dict[str, Any]:
    """读侧 verbatim 分类 (不重推导 canonical classify_pair_session)。"""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return {"kind": "unparseable"}
    if not isinstance(obj, dict):
        return {"kind": "unparseable"}
    if obj.get("decision_kind") == "shadow_decision" or isinstance(
        obj.get("counterfactual_lines"), list
    ):
        lines = obj.get("counterfactual_lines")
        return {
            "kind": "run",
            "line_count": len(lines) if isinstance(lines, list) else None,
        }
    if isinstance(obj.get("reason"), str):
        return {"kind": "no_trade", "reason": obj["reason"]}
    return {"kind": "unknown"}


def _collect_decisions(root: Path) -> dict[str, Any]:
    db = root / "decisions.sqlite3"
    if not db.is_file():
        return _section_missing("decisions store not initialized (no decide yet)")
    try:
        conn = _connect_ro(db)
        try:
            rows = conn.execute(
                "SELECT signal_session, arm, decision_json, created_at"
                " FROM trial_arm_decisions ORDER BY signal_session, arm"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _section_error(exc)
    sessions: dict[str, dict[str, dict[str, Any]]] = {}
    for session, arm, decision_json, created_at in rows:
        arm_row = dict(_classify_decision_json(decision_json))
        arm_row["created_at"] = str(created_at)
        sessions.setdefault(str(session), {})[str(arm)] = arm_row
    run_sessions = 0
    no_trade_sessions = 0
    for arm_rows in sessions.values():
        if any(row.get("kind") == "run" for row in arm_rows.values()):
            run_sessions += 1
        elif arm_rows and all(
            row.get("kind") == "no_trade" for row in arm_rows.values()
        ):
            no_trade_sessions += 1
    return _section_ok(
        session_count=len(sessions),
        run_sessions=run_sessions,
        no_trade_sessions=no_trade_sessions,
        sessions=sessions,
    )


def _collect_arm(root: Path, arm: str) -> dict[str, Any]:
    db = root / "arms" / arm / "capital.sqlite3"
    if not db.is_file():
        return _section_missing(f"arm ledger not restored (genesis-seed 未跑): arms/{arm}")
    try:
        conn = _connect_ro(db)
        try:
            navs = conn.execute(
                "SELECT as_of, nav_cents, capital_version, issued_unit_quanta"
                " FROM nav_observations ORDER BY capital_version"
            ).fetchall()
            positions = conn.execute(
                "SELECT security_id, state, settled_quantity_units"
                " FROM positions WHERE state != 'CLOSED' ORDER BY security_id"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _section_error(exc)
    latest_nav = (
        {
            "as_of": str(navs[-1][0]),
            "nav_cents": navs[-1][1],
            "capital_version": navs[-1][2],
        }
        if navs
        else None
    )
    return _section_ok(
        nav_observation_count=len(navs),
        latest_nav=latest_nav,
        open_position_count=len(positions),
        open_positions=[
            {
                "security_id": security,
                "state": state,
                "settled_quantity_units": quantity,
            }
            for security, state, quantity in positions
        ],
    )


def _collect_evidence_db(db: Path) -> dict[str, Any]:
    if not db.is_file():
        return _section_missing(f"{db.name} not seeded (seed-evidence 未跑)")
    try:
        conn = _connect_ro(db)
        try:
            rows = conn.execute(
                "SELECT issuer_namespace, evidence_kind, COUNT(*), MAX(ingested_at)"
                " FROM evidence_records GROUP BY issuer_namespace, evidence_kind"
                " ORDER BY issuer_namespace, evidence_kind"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _section_error(exc)
    namespaces = [
        {
            "namespace": namespace,
            "kind": kind,
            "count": count,
            "latest_ingested_at": str(latest),
        }
        for namespace, kind, count, latest in rows
    ]
    return _section_ok(namespaces=namespaces)


def _collect_nightly(path: Path, tail: int) -> dict[str, Any]:
    if not path.is_file():
        return _section_missing(f"nightly history not found: {path}")
    entries: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    entries.append({"date": None, "stage": None, "rc": None, "detail": "unparseable_line"})
                    continue
                if isinstance(entry, dict):
                    entries.append(
                        {
                            "date": entry.get("date"),
                            "stage": entry.get("stage"),
                            "rc": entry.get("rc"),
                            "detail": entry.get("detail"),
                        }
                    )
    except OSError as exc:
        return _section_error(exc)
    failed = sum(1 for e in entries if isinstance(e.get("rc"), int) and e["rc"] != 0)
    dated = [e["date"] for e in entries if e.get("date")]
    return _section_ok(
        entry_count=len(entries),
        failed_stage_count=failed,
        last_date=dated[-1] if dated else None,
        tail=entries[-tail:],
    )


def collect_report(
    trial_root: Path,
    nightly_history: Path,
    tail: int,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "trial_root": str(trial_root),
        "trial": _collect_trial(trial_root),
        "spine": _collect_spine(trial_root),
        "decisions": _collect_decisions(trial_root),
        "arms": {arm: _collect_arm(trial_root, arm) for arm in ARMS},
        "evidence": {
            name: _collect_evidence_db(trial_root / name) for name in EVIDENCE_DBS
        },
        "nightly": _collect_nightly(nightly_history, tail),
    }
    decisions = report["decisions"]
    report["summary"] = {
        "decided_sessions": decisions.get("session_count")
        if decisions.get("status") == "ok"
        else None,
        "run_sessions": decisions.get("run_sessions")
        if decisions.get("status") == "ok"
        else None,
        "no_trade_sessions": decisions.get("no_trade_sessions")
        if decisions.get("status") == "ok"
        else None,
        "sections_degraded": [
            name
            for name, section in (
                ("trial", report["trial"]),
                ("spine", report["spine"]),
                ("decisions", report["decisions"]),
                *(("arms." + arm, report["arms"][arm]) for arm in ARMS),
                *(
                    ("evidence." + name, report["evidence"][name])
                    for name in EVIDENCE_DBS
                ),
                ("nightly", report["nightly"]),
            )
            if section.get("status") != "ok"
        ],
    }
    return report


def _render_human(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"━━━ v3 官方 Trial 状态 ({report['trial_root']}) ━━━")
    lines.append("")

    trial = report["trial"]
    if trial["status"] == "ok":
        for reg in trial["registrations"]:
            genesis = reg["genesis"]
            lines.append(
                f"trial: {reg['trial_id']} · registered {reg['registered_at']}"
                f" · genesis sealed {genesis.get('sealed_at')}"
            )
    else:
        lines.append(f"trial: [{trial['status']}] {trial.get('detail') or trial.get('error')}")

    spine = report["spine"]
    if spine["status"] == "ok":
        lines.append(
            f"spine: enrolled {spine['enrolled_count']} sessions"
            f" ({spine['first_session']} → {spine['last_session']})"
            f" · 终态 {spine['terminal_status_count']}"
        )
    else:
        lines.append(f"spine: [{spine['status']}] {spine.get('detail') or spine.get('error')}")

    decisions = report["decisions"]
    if decisions["status"] == "ok":
        lines.append(
            f"decisions: {decisions['session_count']} sessions ·"
            f" run {decisions['run_sessions']} · no_trade {decisions['no_trade_sessions']}"
        )
        for session, arm_rows in decisions["sessions"].items():
            parts = []
            for arm in ("CHAMPION", "CHALLENGER"):
                row = arm_rows.get(arm)
                if row is None:
                    parts.append(f"{arm}=absent")
                elif row["kind"] == "no_trade":
                    parts.append(f"{arm}={row['reason']}")
                elif row["kind"] == "run":
                    parts.append(f"{arm}=RUN({row.get('line_count')} lines)")
                else:
                    parts.append(f"{arm}={row['kind']}")
            lines.append(f"  {session} · " + " · ".join(parts))
    else:
        lines.append(
            f"decisions: [{decisions['status']}]"
            f" {decisions.get('detail') or decisions.get('error')}"
        )

    for arm in ARMS:
        section = report["arms"][arm]
        if section["status"] == "ok":
            nav = section["latest_nav"]
            nav_text = (
                f"NAV ¥{nav['nav_cents'] / 100:,.2f} @ {nav['as_of']}"
                if nav
                else "NAV 无观察行"
            )
            lines.append(
                f"arm {arm}: {nav_text} · 观察行 {section['nav_observation_count']}"
                f" · 持仓 {section['open_position_count']}"
            )
            for position in section["open_positions"]:
                lines.append(
                    f"    {position['security_id']} {position['state']}"
                    f" ×{position['settled_quantity_units']}"
                )
        else:
            lines.append(
                f"arm {arm}: [{section['status']}]"
                f" {section.get('detail') or section.get('error')}"
            )

    for name in EVIDENCE_DBS:
        section = report["evidence"][name]
        if section["status"] == "ok":
            coverage = " · ".join(
                f"{ns['namespace']}/{ns['kind']}={ns['count']}"
                for ns in section["namespaces"]
            )
            lines.append(f"evidence {name}: {coverage or '零记录'}")
        else:
            lines.append(
                f"evidence {name}: [{section['status']}]"
                f" {section.get('detail') or section.get('error')}"
            )

    nightly = report["nightly"]
    if nightly["status"] == "ok":
        lines.append(
            f"nightly: 最后链日 {nightly['last_date']} · 失败阶段 {nightly['failed_stage_count']}"
            f"/{nightly['entry_count']}"
        )
        for entry in nightly["tail"][-6:]:
            lines.append(
                f"    {entry.get('date')} {entry.get('stage')} rc={entry.get('rc')}"
                f" {str(entry.get('detail'))[:70]}"
            )
    else:
        lines.append(
            f"nightly: [{nightly['status']}]"
            f" {nightly.get('detail') or nightly.get('error')}"
        )

    degraded = report["summary"]["sections_degraded"]
    if degraded:
        lines.append(f"降级 section: {', '.join(degraded)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v3 官方 Trial 只读状态 (零写入)")
    parser.add_argument("--trial-root", default=str(DEFAULT_TRIAL_ROOT))
    parser.add_argument("--nightly-history", default=str(DEFAULT_NIGHTLY_HISTORY))
    parser.add_argument("--tail", type=int, default=12, help="nightly tail 条数")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非人读摘要")
    args = parser.parse_args(argv)

    trial_root = Path(args.trial_root)
    if not trial_root.is_dir():
        print(
            json.dumps(
                {"error": "trial_root_not_found", "trial_root": str(trial_root)},
                ensure_ascii=False,
            )
        )
        return 2
    report = collect_report(
        trial_root=trial_root,
        nightly_history=Path(args.nightly_history),
        tail=max(args.tail, 0),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(_render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
