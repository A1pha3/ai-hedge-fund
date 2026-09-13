#!/usr/bin/env python
"""v3 官方 Trial 执行面审计 (R209 Op1): 每条准入行的入场/出场判定重推导。

缺陷背景 (2026-09-13 宿主 trial root 法证实锤): 官方 Trial 对准入行的
执行结局零工件记录 —— 2026-09-07 会话 CHAMPION 行 002815.SZ (限价 1601)
在入场会话 2026-09-08 最低 1695 未触及限价 → 判定表 ``limit_not_touched``
NO_FILL, 该结局在资本/决策/spine 任一库都无痕迹 (只能 4 库手工 SQL 法证
发现); 同窗 CHALLENGER 行 600162.SH 成交在 550 = min(open 555, limit 550)
—— 判定表的触及价, 非 OPEN_AUCTION 开盘价。两者都是锁定判定表
(``resolve_open_execution``) 的正确输出, 但「哪条准入线为何没进场/为何
成交在非开盘价」在运营面不可见。

本工具是**只读重推导审计**: 从 decisions 库读 pair 行 → 从 bars 证据库
(bar-set blob) 重建 ``DailyBar`` → 经 canonical ``resolve_open_execution``
单一实现重推导每条线的入场/出场判定, 并与双臂 capital ``positions``
对账 (工具判定 FILLED ↔ 台账持仓)。判定语义零分叉 (不复制判定表),
命令时刻镜像 ``paired_trial.advance_market_session`` 的派生闭包
(会话日 15:00 北京时间 = 07:00 UTC, 截止 +5 分钟; 该处若改为常量导出
应同步)。

诚实边界 (与 v3_trial_status 同款读取侧纪律):
- **只读**: 全部 sqlite 经 ``mode=ro&immutable=1`` 冷读, 字节级零写入
  (测试钉死); 活 writer 未 checkpoint 的增量不可见, 失败方向=欠新鲜。
- **判定是重推导**: 工具回答「锁定判定表在已发布 bar 证据下会怎么判」,
  不是成交事实本身; FILLED 行与台账持仓的对账才是两者的一致性面。
- 候选快照价 (``entry_price_micros``) 从 evidence 库按行绑定的
  evidence_id 冷读, 用于披露「入场限价 == 信号快照价」的结构性计数;
  快照缺席 → None (不猜测)。
- 缺 decisions/bars 库 = 合法启动形态 (R37), 空 pairs 披露 exit 0;
  库损坏 per-section 报 error 且整体 exit 3 (P2-1: 宽吞会假装没看到)。

用法:
    .venv/bin/python scripts/v3_trial_execution_audit.py
    .venv/bin/python scripts/v3_trial_execution_audit.py --json
    .venv/bin/python scripts/v3_trial_execution_audit.py \
        --trial-root data/v3_trial_root --trial-id trial-btst-regime-r1

退出码: 0 正常 (含空 world); 2 trial root 缺失 (操作员错误);
3 任一 section 损坏 (fail-closed 披露)。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from src.screening.offensive.v3.contracts.decision import ShadowOrderLine
from src.screening.offensive.v3.execution.lifecycle import (
    DailyBar,
    ExecutionSide,
    OpenExecutionVerdict,
    resolve_open_execution,
)
from src.screening.offensive.v3.orchestration.session_driver import (
    UNCONDITIONAL_EXIT_LIMIT_CENTS,
)

DEFAULT_TRIAL_ROOT = Path("data/v3_trial_root")
DEFAULT_TRIAL_ID = "trial-btst-regime-r1"
ARMS = ("CHAMPION", "CHALLENGER")
CAPITAL_ARM_NAMES = ("champion", "challenger")
HELD_POSITION_STATES = ("OPEN", "EXIT_PENDING")
_COMMAND_AT_TIME = time(7, 0, tzinfo=timezone.utc)
_SEND_DEADLINE_MINUTES = 5


class TrialExecutionAuditError(ValueError):
    """操作员错误 (非报告状态): trial root 不存在。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _reject_constant(name: str) -> float:
    raise ValueError(f"non-JSON constant in payload: {name}")


def _loads_strict(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_constant)


def _connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def _command_at(session: date) -> datetime:
    return datetime.combine(session, _COMMAND_AT_TIME)


def _send_deadline(session: date) -> datetime:
    return _command_at(session) + timedelta(minutes=_SEND_DEADLINE_MINUTES)


def _blob_payload(trial_root: Path, content_hash: str) -> Any:
    digest = content_hash.split(":", 1)[1] if ":" in content_hash else content_hash
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError(f"blob hash malformed: {content_hash[:16]}…")
    path = trial_root / "blobs" / digest[:2] / digest[2:4] / digest
    return _loads_strict(path.read_text(encoding="utf-8"))


def _parse_session(value: object) -> date | None:
    if isinstance(value, str) and len(value) == 10:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    # 8 位紧凑形 (evidence_id 尾段形态: market:bars:20260908)
    if isinstance(value, str) and len(value) == 8 and value.isdigit():
        try:
            return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        except ValueError:
            return None
    return None


def load_decisions(
    trial_root: Path, trial_id: str, section_errors: list[dict]
) -> dict[str, dict] | None:
    """pair 行冷读; 缺库 → None (合法启动形态), 损坏 → section error。

    返回 {signal_session: {"arms": {arm: {"kind", "reason"?, "lines"?,
    "target_entry_session"?}}}}; 判定行是 canonical ``ShadowOrderLine``
    (严格模型重建, 畸形行 section error 不入报告)。
    """
    path = trial_root / "decisions.sqlite3"
    if not path.is_file():
        return None
    try:
        conn = _connect_ro(path)
        try:
            rows = conn.execute(
                "SELECT signal_session, arm, decision_json FROM trial_arm_decisions"
                " WHERE trial_id = ? ORDER BY signal_session, arm",
                (trial_id,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        section_errors.append(
            {"section": "decisions", "code": "decisions_db_corrupt", "detail": str(exc)}
        )
        return None
    pairs: dict[str, dict] = {}
    for signal_session, arm, decision_json in rows:
        try:
            decision = _loads_strict(decision_json)
        except (ValueError, TypeError) as exc:
            section_errors.append(
                {
                    "section": "decisions",
                    "code": "decision_json_corrupt",
                    "detail": f"{signal_session}/{arm}: {exc}",
                }
            )
            continue
        if not isinstance(decision, dict):
            section_errors.append(
                {
                    "section": "decisions",
                    "code": "decision_json_corrupt",
                    "detail": f"{signal_session}/{arm}: not an object",
                }
            )
            continue
        slot = pairs.setdefault(str(signal_session), {"arms": {}})
        lines_raw = decision.get("counterfactual_lines")
        if not isinstance(lines_raw, list):
            slot["arms"][str(arm)] = {
                "kind": "no_trade",
                "reason": decision.get("reason"),
                "lines": [],
            }
            continue
        lines = []
        for raw in lines_raw:
            try:
                # 严格 CanonicalModel 的 date 字段只经 JSON 面接受 ISO 串
                # (dict 直 validate 会 date_type 拒绝; R38 同款重建路径)。
                lines.append(
                    ShadowOrderLine.model_validate_json(json.dumps(raw))
                )
            except ValueError as exc:
                section_errors.append(
                    {
                        "section": "decisions",
                        "code": "decision_line_corrupt",
                        "detail": f"{signal_session}/{arm}: {exc}",
                    }
                )
        slot["arms"][str(arm)] = {
            "kind": "admitted",
            "lines": lines,
            "target_entry_session": decision.get("target_entry_session"),
        }
    return pairs


def load_bar_sets(
    trial_root: Path, section_errors: list[dict]
) -> dict[date, dict[str, DailyBar]] | None:
    """bar-set 证据冷读: evidence head (每 id 取最大 commit_sequence) →
    blob → {(session, security_id): DailyBar}。"""
    path = trial_root / "bars-evidence.sqlite3"
    if not path.is_file():
        return None
    try:
        conn = _connect_ro(path)
        try:
            rows = conn.execute(
                "SELECT record_json, commit_sequence FROM evidence_records"
                " ORDER BY commit_sequence, rowid"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        section_errors.append(
            {"section": "bar_sets", "code": "bars_db_corrupt", "detail": str(exc)}
        )
        return None
    heads: dict[str, tuple[int, dict]] = {}
    for record_json, commit_sequence in rows:
        try:
            record = _loads_strict(record_json)
            evidence = record["evidence"]
            evidence_id = evidence["evidence_id"]
            payload_hash = evidence["payload_content_hash"]
        except (ValueError, TypeError, KeyError) as exc:
            section_errors.append(
                {
                    "section": "bar_sets",
                    "code": "bar_record_corrupt",
                    "detail": str(exc),
                }
            )
            continue
        prior = heads.get(evidence_id)
        if prior is None or commit_sequence >= prior[0]:
            heads[evidence_id] = (commit_sequence, evidence)
    bar_sets: dict[date, dict[str, DailyBar]] = {}
    for evidence_id, (_, evidence) in sorted(heads.items()):
        try:
            payload = _blob_payload(trial_root, evidence["payload_content_hash"])
        except (OSError, ValueError) as exc:
            section_errors.append(
                {
                    "section": "bar_sets",
                    "code": "bar_blob_unreadable",
                    "detail": f"{evidence_id}: {exc}",
                }
            )
            continue
        # 会话取载荷真相字段 (blob 内容自证); evidence_id 尾段双格式兜底
        # (真实形态 market:bars:20260908 是 8 位紧凑, 非 ISO)。
        session = None
        if isinstance(payload, dict):
            session = _parse_session(payload.get("session"))
        if session is None:
            session = _parse_session(evidence_id.rsplit(":", 1)[-1])
        if session is None:
            continue
        bars = payload.get("bars") if isinstance(payload, dict) else None
        if not isinstance(bars, list):
            continue
        day = bar_sets.setdefault(session, {})
        for entry in bars:
            if not isinstance(entry, dict):
                continue
            security_id = entry.get("security_id")
            bar_session = _parse_session(entry.get("session"))
            if not isinstance(security_id, str) or bar_session is None:
                continue
            try:
                day[security_id] = DailyBar(
                    security_id=security_id,
                    session=bar_session,
                    open_cents=int(entry["open_cents"]),
                    high_cents=int(entry["high_cents"]),
                    low_cents=int(entry["low_cents"]),
                    close_cents=int(entry["close_cents"]),
                    limit_up_cents=int(entry["limit_up_cents"]),
                    limit_down_cents=int(entry["limit_down_cents"]),
                    suspended=bool(entry.get("suspended", False)),
                )
            except (KeyError, TypeError, ValueError):
                continue
    return bar_sets


def load_snapshot_prices(
    trial_root: Path, evidence_ids: set[str], section_errors: list[dict]
) -> dict[str, int]:
    """候选快照价 (entry_price_micros // 10_000) 按 evidence_id 冷读;
    快照缺席/损坏 → 该 id 不在结果里 (披露面 None, 不猜测)。"""
    prices: dict[str, int] = {}
    if not evidence_ids:
        return prices
    path = trial_root / "evidence.sqlite3"
    if not path.is_file():
        return prices
    try:
        conn = _connect_ro(path)
        try:
            rows = conn.execute(
                "SELECT evidence_id, record_json, commit_sequence FROM evidence_records"
                " ORDER BY commit_sequence, rowid"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        section_errors.append(
            {
                "section": "candidate_snapshots",
                "code": "evidence_db_corrupt",
                "detail": str(exc),
            }
        )
        return prices
    heads: dict[str, tuple[int, str]] = {}
    for evidence_id, record_json, commit_sequence in rows:
        if evidence_id not in evidence_ids:
            continue
        prior = heads.get(evidence_id)
        if prior is None or commit_sequence >= prior[0]:
            heads[evidence_id] = (commit_sequence, record_json)
    for evidence_id, (_, record_json) in heads.items():
        try:
            record = _loads_strict(record_json)
            payload_hash = record["evidence"]["payload_content_hash"]
            payload = _blob_payload(trial_root, payload_hash)
            micros = payload["entry_price_micros"]
        except (ValueError, TypeError, KeyError, OSError) as exc:
            section_errors.append(
                {
                    "section": "candidate_snapshots",
                    "code": "candidate_snapshot_unreadable",
                    "detail": f"{evidence_id}: {exc}",
                }
            )
            continue
        if type(micros) is not int or micros <= 0:
            continue
        prices[evidence_id] = micros // 10_000
    return prices


def load_arm_positions(
    trial_root: Path, section_errors: list[dict]
) -> dict[str, dict] | None:
    """双臂 capital held positions 冷读; 全缺 → None (对账面 missing)。"""
    arms: dict[str, dict] = {}
    for arm in CAPITAL_ARM_NAMES:
        path = trial_root / "arms" / arm / "capital.sqlite3"
        if not path.is_file():
            arms[arm] = {"status": "missing", "positions": {}}
            continue
        try:
            conn = _connect_ro(path)
            try:
                rows = conn.execute(
                    "SELECT economic_lot_id, security_id, state FROM positions"
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            section_errors.append(
                {
                    "section": "positions",
                    "code": "positions_db_corrupt",
                    "detail": f"{arm}: {exc}",
                }
            )
            arms[arm] = {"status": "error", "positions": {}}
            continue
        held = {}
        for lot_id, security_id, state in rows:
            if state in HELD_POSITION_STATES:
                held[str(lot_id)] = str(security_id)
        arms[arm] = {"status": "ok", "positions": held}
    if all(arms[arm]["status"] == "missing" for arm in CAPITAL_ARM_NAMES):
        return None
    return arms


def _resolve_entry(
    line: ShadowOrderLine, entry_session: date, bar_sets: dict[date, dict[str, DailyBar]] | None
) -> tuple[Any, DailyBar | None]:
    bar = None if bar_sets is None else bar_sets.get(entry_session, {}).get(line.security_id)
    resolution = resolve_open_execution(
        side=ExecutionSide.ENTRY,
        limit_price_cents=line.limit_price_cents,
        bar=bar,
        command_at=_command_at(entry_session),
        send_deadline=_send_deadline(entry_session),
    )
    return resolution, bar


def _audit_line(
    line: ShadowOrderLine,
    entry_session: date,
    bar_sets: dict[date, dict[str, DailyBar]] | None,
    snapshot_prices: dict[str, int],
) -> dict:
    resolution, bar = _resolve_entry(line, entry_session, bar_sets)
    entry = {
        "verdict": resolution.verdict.value,
        "reason": resolution.reason,
        "fill_price_cents": resolution.fill_price_cents,
        "bar": None
        if bar is None
        else {
            "open_cents": bar.open_cents,
            "high_cents": bar.high_cents,
            "low_cents": bar.low_cents,
            "close_cents": bar.close_cents,
        },
    }
    off_open = (
        resolution.fill_price_cents - bar.open_cents
        if resolution.verdict is OpenExecutionVerdict.FILLED and bar is not None
        else None
    )
    if resolution.verdict is OpenExecutionVerdict.FILLED:
        exit_bar = (
            None
            if bar_sets is None
            else bar_sets.get(line.target_exit_session, {}).get(line.security_id)
        )
        if exit_bar is None:
            exit_audit: dict = {
                "verdict": "not_due",
                "reason": "exit_session_bars_absent",
            }
        else:
            exit_resolution = resolve_open_execution(
                side=ExecutionSide.EXIT,
                limit_price_cents=UNCONDITIONAL_EXIT_LIMIT_CENTS,
                bar=exit_bar,
                command_at=_command_at(line.target_exit_session),
                send_deadline=_send_deadline(line.target_exit_session),
            )
            exit_audit = {
                "verdict": exit_resolution.verdict.value,
                "reason": exit_resolution.reason,
                "fill_price_cents": exit_resolution.fill_price_cents,
            }
    else:
        exit_audit = {"verdict": "not_applicable", "reason": "entry_not_filled"}
    snapshot = snapshot_prices.get(line.evidence_id)
    return {
        "shadow_line_id": line.shadow_line_id,
        "security_id": line.security_id,
        "economic_lot_id": f"lot:{line.shadow_line_id}",
        "entry_session": entry_session.isoformat(),
        "limit_price_cents": line.limit_price_cents,
        "entry_snapshot_price_cents": snapshot,
        "entry": entry,
        "off_open_cents": off_open,
        "exit": exit_audit,
    }


def audit_trial_execution(trial_root: Path, trial_id: str) -> dict:
    """审计入口: 重推导全部 pair 行的执行判定并汇总披露。"""
    root = Path(trial_root)
    if not root.is_dir():
        raise TrialExecutionAuditError("trial_root_missing", str(root))
    section_errors: list[dict] = []
    pairs_raw = load_decisions(root, trial_id, section_errors)
    bar_sets = load_bar_sets(root, section_errors)
    snapshot_ids: set[str] = set()
    if pairs_raw:
        for slot in pairs_raw.values():
            for arm_slot in slot["arms"].values():
                for line in arm_slot.get("lines", []):
                    snapshot_ids.add(line.evidence_id)
    snapshot_prices = load_snapshot_prices(root, snapshot_ids, section_errors)

    pairs: dict[str, dict] = {}
    aggregate = {
        "admitted_lines": 0,
        "entry_filled": 0,
        "entry_no_fill": 0,
        "entry_unknown": 0,
        "no_fill_reasons": {},
        "filled_off_open": 0,
        "limit_equals_entry_snapshot": 0,
    }
    tool_filled_by_arm: dict[str, set[str]] = {
        arm: set() for arm in CAPITAL_ARM_NAMES
    }
    if pairs_raw:
        for signal_session in sorted(pairs_raw):
            slot = pairs_raw[signal_session]
            out_arms: dict[str, dict] = {}
            for arm in ARMS:
                arm_slot = slot["arms"].get(arm)
                if arm_slot is None:
                    continue
                if arm_slot["kind"] == "no_trade":
                    out_arms[arm] = {
                        "kind": "no_trade",
                        "reason": arm_slot["reason"],
                        "lines": [],
                    }
                    continue
                entry_session = _parse_session(arm_slot["target_entry_session"])
                audited_lines = []
                for line in arm_slot["lines"]:
                    if entry_session is None:
                        section_errors.append(
                            {
                                "section": "decisions",
                                "code": "entry_session_malformed",
                                "detail": f"{signal_session}/{arm}: {arm_slot['target_entry_session']!r}",
                            }
                        )
                        continue
                    audited = _audit_line(
                        line, entry_session, bar_sets, snapshot_prices
                    )
                    audited_lines.append(audited)
                    aggregate["admitted_lines"] += 1
                    verdict = audited["entry"]["verdict"]
                    if verdict == "FILLED":
                        aggregate["entry_filled"] += 1
                        tool_filled_by_arm[arm.lower()].add(audited["economic_lot_id"])
                        if audited["off_open_cents"]:
                            aggregate["filled_off_open"] += 1
                    elif verdict == "NO_FILL":
                        aggregate["entry_no_fill"] += 1
                        reason = audited["entry"]["reason"]
                        aggregate["no_fill_reasons"][reason] = (
                            aggregate["no_fill_reasons"].get(reason, 0) + 1
                        )
                    else:
                        aggregate["entry_unknown"] += 1
                    if (
                        audited["entry_snapshot_price_cents"] is not None
                        and audited["entry_snapshot_price_cents"]
                        == audited["limit_price_cents"]
                    ):
                        aggregate["limit_equals_entry_snapshot"] += 1
                out_arms[arm] = {"kind": "admitted", "lines": audited_lines}
            pairs[signal_session] = {"arms": out_arms}
    reconciliation = _reconcile(
        tool_filled_by_arm, load_arm_positions(root, section_errors)
    )
    return {
        "trial_id": trial_id,
        "pairs": pairs,
        "aggregate": aggregate,
        "reconciliation": reconciliation,
        "section_errors": section_errors,
    }


def _reconcile(
    tool_filled_by_arm: dict[str, set[str]], arms: dict[str, dict] | None
) -> dict:
    if arms is None:
        return {"status": "missing"}
    report: dict[str, dict] = {}
    for arm in CAPITAL_ARM_NAMES:
        arm_info = arms.get(arm) or {"status": "missing", "positions": {}}
        if arm_info["status"] != "ok":
            report[arm] = {"status": arm_info["status"], "findings": []}
            continue
        held = arm_info["positions"]
        findings = []
        for lot_id in sorted(tool_filled_by_arm[arm] - set(held)):
            findings.append(
                {"kind": "expected_fill_without_position", "lot_id": lot_id}
            )
        for lot_id in sorted(set(held) - tool_filled_by_arm[arm]):
            findings.append(
                {"kind": "position_without_tool_fill", "lot_id": lot_id}
            )
        report[arm] = {
            "status": "ok",
            "positions_seen": len(held),
            "findings": findings,
        }
    return {"arms": report}


def render_human(report: dict) -> str:
    agg = report["aggregate"]
    lines = [
        f"trial {report['trial_id']} 执行面审计"
        f" (判定重推导, 非成交事实):"
        f" 准入 {agg['admitted_lines']} 行 ·"
        f" FILLED {agg['entry_filled']} ·"
        f" NO_FILL {agg['entry_no_fill']} ·"
        f" UNKNOWN {agg['entry_unknown']}"
    ]
    for reason, count in sorted(agg["no_fill_reasons"].items()):
        lines.append(f"  未成交原因 {reason}: {count}")
    lines.append(
        f"  成交在触及价 (偏离开盘) {agg['filled_off_open']} 行 ·"
        f" 限价==信号快照价 {agg['limit_equals_entry_snapshot']}/{agg['admitted_lines']} 行"
    )
    recon = report.get("reconciliation") or {}
    for arm, info in (recon.get("arms") or {}).items():
        for finding in info.get("findings", []):
            lines.append(f"  对账 {arm}: {finding['kind']} {finding['lot_id']}")
    for error in report.get("section_errors", []):
        lines.append(f"  section 错误 {error['section']}: {error['code']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trial-root", default=str(DEFAULT_TRIAL_ROOT))
    parser.add_argument("--trial-id", default=DEFAULT_TRIAL_ID)
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    args = parser.parse_args(argv)
    try:
        report = audit_trial_execution(Path(args.trial_root), args.trial_id)
    except TrialExecutionAuditError as exc:
        print(f"{exc.code}: {exc.detail}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_human(report))
    return 3 if report["section_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
