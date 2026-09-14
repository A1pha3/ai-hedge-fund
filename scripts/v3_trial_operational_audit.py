#!/usr/bin/env python3
"""v3_trial_operational_audit — 官方 Trial 运营对账审计 (只读, R215 Op1).

把生产 trial root 的四个事实面 (spine 报名 / decide 覆盖 / bar-set 推进 /
双臂资本生命周期) 在一个只读仪器里对账, 让以下漂移从隐形变可见:
- unmatched_decided_line: 已决策的 kernel 行在臂台账无任何生命周期痕迹
  (无 fill / 无 lot / 无 position) — 决策与资本真相脱钩;
- orphan_position: 臂台账持仓找不到对应决策行 — 资本真相无决策来源;
- exit_overdue: OPEN 持仓 target_exit_session <= as_of 仍未了结;
- finalize_backlog: 已过 assessment_date 且无决策 pair 的已报名会话
  (runbook: 唯一官方出口是 finalize-missed 补 NO_RUN);
- decide_missing: 会话日 <= as_of 但既无 pair 也无 spine 终态;
- deadline_missed: decide 命中 DEADLINE_MISSED 的会话 (机械性错过);
- bars_gap: 会话日 <= as_of 的已报名会话缺 bar-set 证据 (advance 前提).

读数纪律:
- 全部存储经 ``mode=ro&immutable=1`` 只读连接消费; 审计对 trial root
  字节级零突变 (有测试钉死). 不构造任何 src repository (它们会落
  WAL/DDL 写副作用).
- 所需列做 required-subset 断言; 缺列/改名列 → typed ``schema_drift``
  (存储 schema 演化时本工具 fail-closed 而非静默误读).
- ``as_of`` 从 bar-set 证据派生 (不取墙钟), 同输入报告逐字节可复现.
- 纯诊断 (宪法 #2): 只披露不判定; 不改任何策略/gate/排程/仓位语义.
- 决策形状双态识别: schema_major==4 ShadowDecision (counterfactual_lines)
  与 kernel NoTrade (reason 字段); 其他形状 typed 标记不猜测。
- 无痕迹行核销 (R220 Op1): unmatched 行经锁定判定表 ``resolve_open_execution``
  (单一实现, 无公式 fork) 在『命令未迟到』投影下重评估 — 未触及限价在任何
  命令时序下都不成交, 判定 NO_FILL → ``no_fill_verified`` 核销 (忠实无成交,
  非结算缺失); touched / UNKNOWN (缺 bar / 停牌 / 一字涨停锁) 一律保留为
  unmatched 发现并附核销失败原因. 核销只 import 纯模型与纯函数, 绝不构造
  repository / engine (零连接副作用).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.screening.offensive.v3.contracts import ExecutionSide
from src.screening.offensive.v3.evidence.market_bars import DailyBarSetEvidence
from src.screening.offensive.v3.execution.lifecycle import (
    DailyBar,
    OpenExecutionVerdict,
    REASON_MISSING_BAR,
    REASON_ONE_PRICE_LIMIT_UP,
    REASON_PERMIT_QUANTITY_ZERO,
    REASON_SUSPENDED_BAR,
    resolve_open_execution,
)

SPINE_DB = "spine.sqlite3"
DECISIONS_DB = "decisions.sqlite3"
BARS_DB = "bars-evidence.sqlite3"
ARMS_DIR = "arms"

ARM_CHAMPION = "champion"
ARM_CHALLENGER = "challenger"
DEFAULT_ARMS = (ARM_CHAMPION, ARM_CHALLENGER)

DECISION_SHAPE_SHADOW = "shadow_decision"
DECISION_SHAPE_NO_TRADE = "no_trade"
DECISION_SHAPE_UNKNOWN = "unknown_shape"

REASON_NO_SIGNAL = "NO_SIGNAL"
REASON_CAPACITY_EXHAUSTED = "CAPACITY_EXHAUSTED"
REASON_DEADLINE_MISSED = "DEADLINE_MISSED"

FINDING_UNMATCHED_LINE = "unmatched_decided_line"
FINDING_ORPHAN_POSITION = "orphan_position"
FINDING_EXIT_OVERDUE = "exit_overdue"
FINDING_FINALIZE_BACKLOG = "finalize_backlog"
FINDING_DECIDE_MISSING = "decide_missing"
FINDING_DEADLINE_MISSED = "deadline_missed"
FINDING_BARS_GAP = "bars_gap"
FINDING_UNKNOWN_SHAPE = "unknown_decision_shape"

BAR_EVIDENCE_PREFIX = "market:bars:"

#: 每张被读表的必需列 (required ⊆ actual; 多余列容忍, 缺列/改名 typed 拒).
REQUIRED_COLUMNS: dict[str, dict[str, tuple[str, ...]]] = {
    SPINE_DB: {
        "expected_sessions": (
            "research_program_id",
            "signal_session",
            "assessment_date",
            "enrolled_at",
        ),
        "session_status_revisions": (
            "signal_session",
            "revision",
            "status",
            "recorded_at",
        ),
    },
    DECISIONS_DB: {
        "trial_arm_decisions": (
            "trial_id",
            "signal_session",
            "arm",
            "decision_json",
            "created_at",
        ),
    },
    BARS_DB: {
        "evidence_records": (
            "evidence_id",
            "ingested_at",
            "revision",
            "record_json",
        ),
    },
    "capital.sqlite3": {
        "economic_events": (
            "idempotency_key",
            "event_kind",
            "position_lineage_id",
            "economic_lot_id",
            "effective_at",
        ),
        "positions": (
            "position_lineage_id",
            "economic_lot_id",
            "security_id",
            "state",
            "updated_at",
        ),
        "nav_observations": ("as_of", "nav_cents", "observation_kind"),
    },
}


class TrialAuditError(Exception):
    """Typed fail-closed audit failure (never silently misread)."""

    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict:
        return {"code": self.code, "details": self.details}


def _ro_connect(db_path: Path) -> sqlite3.Connection:
    """只读 + immutable 连接; 缺库 typed 拒绝, 零写副作用."""
    if not db_path.is_file():
        raise TrialAuditError("store_missing", {"store": str(db_path)})
    uri = f"file:{db_path}?mode=ro&immutable=1"
    try:
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise TrialAuditError("store_unreadable", {"store": str(db_path), "error": str(exc)}) from exc


def _require_columns(con: sqlite3.Connection, store: str, table: str) -> None:
    required = REQUIRED_COLUMNS[store].get(table)
    if required is None:
        return
    actual = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    if not actual:
        raise TrialAuditError("schema_drift", {"store": store, "table": table, "reason": "table_missing"})
    missing = sorted(set(required) - actual)
    if missing:
        raise TrialAuditError(
            "schema_drift",
            {"store": store, "table": table, "missing_columns": missing},
        )


# ---------------------------------------------------------------------------
# 读取层 (每个事实面一个纯函数)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnrolledSession:
    research_program_id: str
    signal_session: str
    assessment_date: str
    enrolled_at: str


@dataclass(frozen=True)
class SpineRevision:
    signal_session: str
    revision: int
    status: str
    recorded_at: str


def read_spine(root: Path) -> tuple[list[EnrolledSession], list[SpineRevision]]:
    con = _ro_connect(root / SPINE_DB)
    try:
        _require_columns(con, SPINE_DB, "expected_sessions")
        _require_columns(con, SPINE_DB, "session_status_revisions")
        enrolled = [
            EnrolledSession(str(r[0]), str(r[1]), str(r[2]), str(r[3]))
            for r in con.execute(
                "SELECT research_program_id, signal_session, assessment_date, enrolled_at"
                " FROM expected_sessions ORDER BY signal_session"
            )
        ]
        revisions = [
            SpineRevision(str(r[0]), int(r[1]), str(r[2]), str(r[3]))
            for r in con.execute(
                "SELECT signal_session, revision, status, recorded_at"
                " FROM session_status_revisions ORDER BY signal_session, revision"
            )
        ]
    finally:
        con.close()
    return enrolled, revisions


@dataclass(frozen=True)
class DecidedLine:
    shadow_line_id: str
    security_id: str
    target_exit_session: str | None
    # R220 Op1: 核销面所需行字段 (缺失/异型归 None → 该行不可核销, 不崩溃;
    # bool 毒化按 R147 纪律归 None)
    limit_price_cents: int | None = None
    target_quantity_units: int | None = None


@dataclass(frozen=True)
class ParsedDecision:
    signal_session: str
    arm: str
    shape: str
    reason: str | None
    lines: tuple[DecidedLine, ...]
    target_entry_session: str | None
    created_at: str


def _opt_int(raw: dict, key: str) -> int | None:
    """严格 int 提取 (bool 毒化归 None — R147 纪律); 缺失/异型不可核销."""
    value = raw.get(key)
    return value if type(value) is int else None


def parse_decision(signal_session: str, arm: str, decision_json: str, created_at: str) -> ParsedDecision:
    try:
        payload = json.loads(decision_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise TrialAuditError(
            "decision_json_invalid",
            {"signal_session": signal_session, "arm": arm, "error": str(exc)},
        ) from exc
    if not isinstance(payload, dict):
        raise TrialAuditError(
            "decision_json_invalid",
            {"signal_session": signal_session, "arm": arm, "error": "payload_not_object"},
        )
    if payload.get("schema_major") == 4 and isinstance(payload.get("counterfactual_lines"), list):
        lines = []
        for raw in payload["counterfactual_lines"]:
            if not isinstance(raw, dict) or not isinstance(raw.get("shadow_line_id"), str):
                raise TrialAuditError(
                    "decision_json_invalid",
                    {"signal_session": signal_session, "arm": arm, "error": "line_missing_shadow_line_id"},
                )
            lines.append(
                DecidedLine(
                    shadow_line_id=raw["shadow_line_id"],
                    security_id=str(raw.get("security_id")),
                    target_exit_session=(
                        str(raw["target_exit_session"])
                        if raw.get("target_exit_session") is not None
                        else None
                    ),
                    limit_price_cents=_opt_int(raw, "limit_price_cents"),
                    target_quantity_units=_opt_int(raw, "target_quantity_units"),
                )
            )
        entry = payload.get("target_entry_session")
        return ParsedDecision(
            signal_session=signal_session,
            arm=arm,
            shape=DECISION_SHAPE_SHADOW,
            reason=None,
            lines=tuple(lines),
            target_entry_session=str(entry) if entry is not None else None,
            created_at=created_at,
        )
    reason = payload.get("reason", payload.get("global_reason"))
    if isinstance(reason, str) and reason:
        return ParsedDecision(
            signal_session=signal_session,
            arm=arm,
            shape=DECISION_SHAPE_NO_TRADE,
            reason=reason,
            lines=(),
            target_entry_session=None,
            created_at=created_at,
        )
    return ParsedDecision(
        signal_session=signal_session,
        arm=arm,
        shape=DECISION_SHAPE_UNKNOWN,
        reason=None,
        lines=(),
        target_entry_session=None,
        created_at=created_at,
    )


def read_decisions(root: Path, trial_id: str) -> dict[tuple[str, str], ParsedDecision]:
    """(signal_session, arm) → ParsedDecision; 重复键 typed 拒绝."""
    con = _ro_connect(root / DECISIONS_DB)
    try:
        _require_columns(con, DECISIONS_DB, "trial_arm_decisions")
        rows = con.execute(
            "SELECT signal_session, arm, decision_json, created_at FROM trial_arm_decisions"
            " WHERE trial_id = ? ORDER BY signal_session, arm",
            (trial_id,),
        ).fetchall()
    finally:
        con.close()
    decisions: dict[tuple[str, str], ParsedDecision] = {}
    for session, arm, decision_json, created_at in rows:
        # 决策面 arm 值按生产约定归一为大写作键 (CHAMPION/CHALLENGER);
        # ParsedDecision.arm 保留来源原值.
        key = (str(session), str(arm).upper())
        if key in decisions:
            raise TrialAuditError("duplicate_decision_row", {"key": list(key)})
        decisions[key] = parse_decision(key[0], str(arm), decision_json, str(created_at))
    return decisions


def read_bar_sessions(root: Path) -> dict[str, str]:
    """signal_session(YYYY-MM-DD) → ingested_at (market:bars: 证据).

    R220 Op2 修订感知: 同 evidence_id 的多行是合法修订链, 取 max revision
    为活跃投影 (与 _entry_bars_for_sessions 同一规则); 不同 evidence_id
    映射同会话仍 fail-closed (id 内嵌会话, 正常不可达, 防御 id 语义漂移).
    """
    con = _ro_connect(root / BARS_DB)
    try:
        _require_columns(con, BARS_DB, "evidence_records")
        rows = con.execute(
            "SELECT evidence_id, ingested_at, revision FROM evidence_records"
            " ORDER BY ingested_at"
        ).fetchall()
    finally:
        con.close()
    latest: dict[str, tuple[int | None, str]] = {}
    for evidence_id, ingested_at, revision in rows:
        evidence_id = str(evidence_id)
        rev = revision if type(revision) is int else None
        prior = latest.get(evidence_id)
        if prior is None or (rev is not None and (prior[0] is None or rev > prior[0])):
            latest[evidence_id] = (rev, str(ingested_at))
    bars: dict[str, str] = {}
    for evidence_id, (_rev, ingested_at) in latest.items():
        if not evidence_id.startswith(BAR_EVIDENCE_PREFIX):
            continue
        raw = evidence_id[len(BAR_EVIDENCE_PREFIX):]
        if len(raw) != 8 or not raw.isdigit():
            raise TrialAuditError("bar_evidence_id_invalid", {"evidence_id": evidence_id})
        session = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
        if session in bars:
            raise TrialAuditError("duplicate_bar_set", {"signal_session": session})
        bars[session] = ingested_at
    return bars


#: 核销投影 (R220 Op1): 审计无法从耐久工件恢复 advance 的命令时序, 故以
#: 『命令未迟到』投影评估锁定判定表 — 该投影只可能给出非迟到路径的判定;
#: touched / UNKNOWN 仍保留为发现, 因此投影不会把疑似结算缺失伪装成忠实
#: 无成交。迟到命令在核心语义里是 UNKNOWN (保现金, 零资本痕迹) — 与
#: NO_FILL 同为零痕迹, 但不可核销, 如实保留。
_PROJECTION_COMMAND_AT = datetime.min.replace(tzinfo=timezone.utc)
_PROJECTION_SEND_DEADLINE = datetime.max.replace(tzinfo=timezone.utc)

_UNVERIFIED_REASON_ZH = {
    REASON_MISSING_BAR: "bar 缺失",
    REASON_SUSPENDED_BAR: "停牌",
    REASON_ONE_PRICE_LIMIT_UP: "一字涨停锁",
}


@dataclass(frozen=True)
class LineResolution:
    """单行无痕迹核销评估 (resolved=True → no_fill_verified)."""

    resolved: bool
    kind: str
    reason: str
    note: str
    day_low_cents: int | None = None


def classify_unmatched_line(
    line: DecidedLine,
    entry_session: str | None,
    bars: dict[str, DailyBar] | None,
) -> LineResolution:
    """把一个无痕迹决策行按核心结算语义重评估为已核销或不可核销.

    数量为 0 的行走核心 ``settle_proxy_open`` 首分支同款短路 (恒 NO_FILL,
    不触判定表); 其余行走锁定判定表 ``resolve_open_execution`` (单一实现,
    无公式 fork)。
    """

    if line.target_quantity_units == 0:
        return LineResolution(
            resolved=True,
            kind="no_fill_verified",
            reason=REASON_PERMIT_QUANTITY_ZERO,
            note="数量为 0 (permit quantity zero) — 忠实无成交",
        )
    if (
        line.limit_price_cents is None
        or line.target_quantity_units is None
        or line.limit_price_cents <= 0
        or line.target_quantity_units < 0
    ):
        return LineResolution(
            resolved=False,
            kind="unverified_missing_fields",
            reason="missing_fields",
            note="行缺 limit/quantity 字段或取值非法, 无法核销",
        )
    if entry_session is None:
        return LineResolution(
            resolved=False,
            kind="unverified_missing_fields",
            reason="missing_fields",
            note="决策缺 target_entry_session, 无法核销",
        )
    bar = (bars or {}).get(line.security_id)
    resolution = resolve_open_execution(
        side=ExecutionSide.ENTRY,
        limit_price_cents=line.limit_price_cents,
        bar=bar,
        command_at=_PROJECTION_COMMAND_AT,
        send_deadline=_PROJECTION_SEND_DEADLINE,
    )
    if resolution.verdict is OpenExecutionVerdict.NO_FILL:
        return LineResolution(
            resolved=True,
            kind="no_fill_verified",
            reason=resolution.reason,
            note=(
                f"entry {entry_session} 限价 {line.limit_price_cents} 未触及"
                f" (当日最低 {bar.low_cents}) — 忠实无成交"
            ),
            day_low_cents=bar.low_cents,
        )
    if resolution.verdict is OpenExecutionVerdict.FILLED:
        return LineResolution(
            resolved=False,
            kind="unverified_limit_touched",
            reason=resolution.reason,
            note=(
                f"entry {entry_session} 限价已触及"
                f" (当日最低 {bar.low_cents} ≤ {line.limit_price_cents})"
                " 而台账零痕迹 — 疑似结算缺失"
            ),
            day_low_cents=bar.low_cents,
        )
    zh = _UNVERIFIED_REASON_ZH.get(resolution.reason, resolution.reason)
    return LineResolution(
        resolved=False,
        kind="unverified_unknown",
        reason=resolution.reason,
        note=f"entry {entry_session} 无法核销无成交 ({zh})",
    )


@dataclass(frozen=True)
class NoFillResolution:
    """已核销的无痕迹决策行 (审计对账面的 resolved 类别, 非发现)."""

    arm: str
    signal_session: str
    security_id: str
    shadow_line_id: str
    entry_session: str | None
    limit_price_cents: int | None
    reason: str
    day_low_cents: int | None


def _entry_bars_for_sessions(
    root: Path, entry_sessions: set[str]
) -> dict[str, dict[str, DailyBar]]:
    """entry 会话 (YYYY-MM-DD) → security_id → DailyBar (bar-set 证据冷读).

    真实链与 ``bars_from_record`` 同构: record_json → 信封内层
    ``payload_content_hash`` → blobs 布局冷读 → sha256 复核 →
    ``DailyBarSetEvidence`` 严格解码 (单一实现) → 会话归属交叉核对。
    """

    if not entry_sessions:
        return {}
    con = _ro_connect(root / BARS_DB)
    try:
        _require_columns(con, BARS_DB, "evidence_records")
        out: dict[str, dict[str, DailyBar]] = {}
        for session in sorted(entry_sessions):
            compact = session.replace("-", "")
            if len(compact) != 8 or not compact.isdigit():
                raise TrialAuditError("entry_session_invalid", {"entry_session": session})
            row = con.execute(
                "SELECT record_json FROM evidence_records"
                " WHERE evidence_id = ? ORDER BY revision DESC LIMIT 1",
                (f"market:bars:{compact}",),
            ).fetchone()
            if row is None or row[0] is None:
                # 该 entry 会话无 bar-set 证据 → 分类面如实 unverified
                continue
            try:
                record = json.loads(row[0])
            except (json.JSONDecodeError, TypeError) as exc:
                raise TrialAuditError(
                    "bar_record_json_invalid",
                    {"evidence_id": f"market:bars:{compact}", "error": str(exc)},
                ) from exc
            envelope = record.get("evidence") if isinstance(record, dict) else None
            content_hash = (
                envelope.get("payload_content_hash")
                if isinstance(envelope, dict)
                else None
            )
            if not isinstance(content_hash, str) or len(content_hash) != 64:
                raise TrialAuditError(
                    "bar_payload_unbound",
                    {"evidence_id": f"market:bars:{compact}"},
                )
            blob_path = (
                root / "blobs" / content_hash[:2] / content_hash[2:4] / content_hash
            )
            if not blob_path.is_file():
                raise TrialAuditError(
                    "bar_payload_missing",
                    {"evidence_id": f"market:bars:{compact}", "path": str(blob_path)},
                )
            blob = blob_path.read_bytes()
            if hashlib.sha256(blob).hexdigest() != content_hash:
                raise TrialAuditError(
                    "bar_payload_corrupt",
                    {"evidence_id": f"market:bars:{compact}"},
                )
            try:
                bar_set = DailyBarSetEvidence.model_validate_json(blob, strict=True)
            except Exception as exc:  # noqa: BLE001 — 解码失败 fail-closed
                raise TrialAuditError(
                    "bar_set_decode_failed",
                    {"evidence_id": f"market:bars:{compact}", "error": str(exc)},
                ) from exc
            if bar_set.session.isoformat() != session:
                raise TrialAuditError(
                    "bar_session_mismatch",
                    {
                        "evidence_id": f"market:bars:{compact}",
                        "bar_session": bar_set.session.isoformat(),
                        "entry_session": session,
                    },
                )
            out[session] = {b.security_id: b.to_bar() for b in bar_set.bars}
        return out
    finally:
        con.close()


@dataclass(frozen=True)
class PositionRow:
    lineage_id: str
    lot_id: str
    security_id: str
    state: str
    updated_at: str


@dataclass(frozen=True)
class ArmLedger:
    arm: str
    event_kinds: dict[str, int]
    traced_line_ids: set[str]
    filled_line_ids: set[str]
    positions: tuple[PositionRow, ...]
    nav_series: tuple[tuple[str, int], ...]


def _lineage_to_line_id(lineage: str) -> str | None:
    """台账 lineage 形如 ``shadow:{shadow_line_id}``; 返回其中的 line id."""
    prefix = "shadow:"
    if lineage.startswith(prefix):
        return lineage[len(prefix):]
    return None


def read_arm_ledger(root: Path, arm: str) -> ArmLedger:
    db_path = root / ARMS_DIR / arm / "capital.sqlite3"
    con = _ro_connect(db_path)
    try:
        _require_columns(con, "capital.sqlite3", "economic_events")
        _require_columns(con, "capital.sqlite3", "positions")
        _require_columns(con, "capital.sqlite3", "nav_observations")
        event_kinds: dict[str, int] = {}
        traced: set[str] = set()
        filled: set[str] = set()
        for idem, kind, lineage, lot in con.execute(
            "SELECT idempotency_key, event_kind, position_lineage_id, economic_lot_id"
            " FROM economic_events"
        ):
            event_kinds[str(kind)] = event_kinds.get(str(kind), 0) + 1
            for haystack in (str(idem), str(lineage or ""), str(lot or "")):
                candidate = _lineage_to_line_id(haystack)
                if candidate is not None:
                    traced.add(candidate)
            if str(kind) == "TRADE_EXECUTED":
                candidate = _lineage_to_line_id(str(lineage or ""))
                if candidate is not None:
                    filled.add(candidate)
        positions = tuple(
            PositionRow(str(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]))
            for r in con.execute(
                "SELECT position_lineage_id, economic_lot_id, security_id, state, updated_at"
                " FROM positions ORDER BY position_lineage_id"
            )
        )
        nav = tuple(
            (str(r[0]), int(r[1]))
            for r in con.execute(
                "SELECT as_of, nav_cents FROM nav_observations ORDER BY as_of, nav_observation_id"
                if _has_nav_observation_id(con)
                else "SELECT as_of, nav_cents FROM nav_observations ORDER BY as_of"
            )
        )
    finally:
        con.close()
    return ArmLedger(
        arm=arm,
        event_kinds=event_kinds,
        traced_line_ids=traced,
        filled_line_ids=filled,
        positions=positions,
        nav_series=nav,
    )


def _has_nav_observation_id(con: sqlite3.Connection) -> bool:
    cols = {row[1] for row in con.execute("PRAGMA table_info(nav_observations)")}
    return "nav_observation_id" in cols


# ---------------------------------------------------------------------------
# 对账层
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    code: str
    arm: str | None
    signal_session: str | None
    detail: str


@dataclass
class ArmSummary:
    arm: str
    open_positions: int = 0
    closed_positions: int = 0
    fills: int = 0
    nav_first: tuple[str, int] | None = None
    nav_last: tuple[str, int] | None = None
    nav_marks: int = 0
    total_log_growth: float | None = None
    max_drawdown: float | None = None


@dataclass
class TrialAudit:
    trial_root: str
    trial_id: str
    research_program: str
    arms: tuple[str, ...]
    as_of: str
    enrolled_sessions: tuple[EnrolledSession, ...]
    decisions: dict[tuple[str, str], ParsedDecision]
    bar_sessions: dict[str, str]
    ledgers: dict[str, ArmLedger]
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    arm_summaries: tuple[ArmSummary, ...] = field(default_factory=tuple)
    no_fill_resolutions: tuple[NoFillResolution, ...] = field(default_factory=tuple)

    @property
    def decided_sessions(self) -> set[str]:
        return {session for session, _arm in self.decisions}

    @property
    def finding_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.code] = counts.get(finding.code, 0) + 1
        return counts


def derive_as_of(bar_sessions: dict[str, str], enrolled: list[EnrolledSession]) -> str:
    """as_of = 最新 bar-set 会话; 无 bar-set 时回退最新已报名会话 (typed 拒空宇宙)."""
    if bar_sessions:
        return max(bar_sessions)
    if enrolled:
        return max(s.signal_session for s in enrolled)
    raise TrialAuditError("empty_trial_world", {})


def build_audit(
    trial_root: Path,
    trial_id: str,
    research_program: str,
    arms: tuple[str, ...] = DEFAULT_ARMS,
) -> TrialAudit:
    enrolled, _revisions = read_spine(trial_root)
    decisions = read_decisions(trial_root, trial_id)
    bar_sessions = read_bar_sessions(trial_root)
    # 决策面 arm 值是大写 (CHAMPION/CHALLENGER), 臂台账目录是小写 —
    # 统一以小写为台账键, 查找时归一, 发现里如实保留来源侧写法.
    ledgers = {arm.lower(): read_arm_ledger(trial_root, arm) for arm in arms}
    as_of = derive_as_of(bar_sessions, enrolled)

    findings: list[Finding] = []
    program_enrolled = [
        s for s in enrolled if s.research_program_id == research_program
    ]
    if not program_enrolled:
        raise TrialAuditError(
            "program_not_enrolled",
            {"research_program": research_program, "trial_root": str(trial_root)},
        )

    # F1 unmatched_decided_line / F7 unknown shape / no-fill 核销 (R220 Op1)
    unmatched: list[tuple[str, str, ParsedDecision, DecidedLine]] = []
    for (session, arm), decision in sorted(decisions.items()):
        if decision.shape == DECISION_SHAPE_UNKNOWN:
            findings.append(
                Finding(FINDING_UNKNOWN_SHAPE, arm, session, "decision_json shape 未识别")
            )
        for line in decision.lines:
            ledger = ledgers.get(arm.lower())
            if ledger is not None and line.shadow_line_id not in ledger.traced_line_ids:
                unmatched.append((session, arm, decision, line))
    entry_sessions = {
        decision.target_entry_session
        for _s, _a, decision, _l in unmatched
        if decision.target_entry_session is not None
    }
    entry_bars = (
        _entry_bars_for_sessions(trial_root, entry_sessions)
        if entry_sessions
        else {}
    )
    no_fill_resolutions: list[NoFillResolution] = []
    for session, arm, decision, line in unmatched:
        resolution = classify_unmatched_line(
            line,
            decision.target_entry_session,
            entry_bars.get(decision.target_entry_session or ""),
        )
        if resolution.resolved:
            no_fill_resolutions.append(
                NoFillResolution(
                    arm=arm,
                    signal_session=session,
                    security_id=line.security_id,
                    shadow_line_id=line.shadow_line_id,
                    entry_session=decision.target_entry_session,
                    limit_price_cents=line.limit_price_cents,
                    reason=resolution.reason,
                    day_low_cents=resolution.day_low_cents,
                )
            )
            continue
        findings.append(
            Finding(
                FINDING_UNMATCHED_LINE,
                arm,
                session,
                f"{line.security_id} {line.shadow_line_id[:48]}… {resolution.note}",
            )
        )
    no_fill_resolutions.sort(
        key=lambda r: (r.arm.lower(), r.signal_session, r.security_id, r.shadow_line_id)
    )

    # F2 orphan_position / F3 exit_overdue (决策行 target_exit 联查)
    decided_lines: dict[tuple[str, str], DecidedLine] = {}
    for (_session, arm), decision in decisions.items():
        for line in decision.lines:
            decided_lines[(arm.lower(), line.shadow_line_id)] = line
    for arm, ledger in ledgers.items():
        for position in ledger.positions:
            line_id = _lineage_to_line_id(position.lineage_id)
            line = decided_lines.get((arm, line_id)) if line_id is not None else None
            if line is None:
                findings.append(
                    Finding(FINDING_ORPHAN_POSITION, arm, None, f"{position.security_id} {position.lineage_id[:48]}…")
                )
                continue
            if (
                position.state == "OPEN"
                and line.target_exit_session is not None
                and line.target_exit_session <= as_of
            ):
                findings.append(
                    Finding(
                        FINDING_EXIT_OVERDUE,
                        arm,
                        None,
                        f"{position.security_id} exit {line.target_exit_session} ≤ as_of {as_of}",
                    )
                )

    # F4 finalize_backlog / F5 decide_missing / F6 deadline_missed / F8 bars_gap
    for session_row in program_enrolled:
        session = session_row.signal_session
        per_session = [d for (s, _a), d in decisions.items() if s == session]
        has_pair = bool(per_session)
        if session_row.assessment_date <= as_of and not has_pair:
            findings.append(
                Finding(FINDING_FINALIZE_BACKLOG, None, session, f"assessment {session_row.assessment_date}")
            )
        if (
            session <= as_of
            and not has_pair
            and session_row.assessment_date > as_of
        ):
            findings.append(
                Finding(FINDING_DECIDE_MISSING, None, session, f"decide 未发生 (as_of {as_of})")
            )
        if any(d.reason == REASON_DEADLINE_MISSED for d in per_session):
            findings.append(Finding(FINDING_DEADLINE_MISSED, None, session, "DEADLINE_MISSED"))
        if session <= as_of and session not in bar_sessions:
            findings.append(Finding(FINDING_BARS_GAP, None, session, "无 bar-set 证据"))

    arm_summaries = []
    for arm in arms:
        ledger = ledgers[arm]
        summary = ArmSummary(
            arm=arm,
            fills=len(ledger.filled_line_ids),
            nav_marks=len(ledger.nav_series),
        )
        for position in ledger.positions:
            if position.state == "OPEN":
                summary.open_positions += 1
            else:
                summary.closed_positions += 1
        if ledger.nav_series:
            summary.nav_first = ledger.nav_series[0]
            summary.nav_last = ledger.nav_series[-1]
            first_nav = ledger.nav_series[0][1]
            if first_nav > 0:
                summary.total_log_growth = math.log(ledger.nav_series[-1][1] / first_nav)
            peak = first_nav
            max_dd = 0.0
            for _as_of_i, nav in ledger.nav_series:
                peak = max(peak, nav)
                if peak > 0:
                    max_dd = min(max_dd, math.log(nav / peak))
            summary.max_drawdown = max_dd
        arm_summaries.append(summary)

    return TrialAudit(
        trial_root=str(trial_root),
        trial_id=trial_id,
        research_program=research_program,
        arms=tuple(arms),
        as_of=as_of,
        enrolled_sessions=tuple(program_enrolled),
        decisions=decisions,
        bar_sessions=bar_sessions,
        ledgers=ledgers,
        findings=tuple(findings),
        arm_summaries=tuple(arm_summaries),
        no_fill_resolutions=tuple(no_fill_resolutions),
    )


# ---------------------------------------------------------------------------
# 渲染层 (确定性: 无墙钟, 排序稳定)
# ---------------------------------------------------------------------------


def _session_matrix_rows(audit: TrialAudit) -> list[str]:
    rows = [
        "| 会话 | assessment | champion | challenger | bar-set |",
        "|---|---|---|---|---|",
    ]
    for session_row in audit.enrolled_sessions:
        session = session_row.signal_session
        cells = []
        for arm in audit.arms:
            decision = audit.decisions.get((session, arm.upper()))
            if decision is None:
                cells.append("—")
            else:
                cells.append(_classify([decision]))
        bar = "✓" if session in audit.bar_sessions else "✗"
        rows.append(
            f"| {session} | {session_row.assessment_date} | {cells[0]} | {cells[1]} | {bar} |"
        )
    return rows


def _classify(decisions_for_session: list[ParsedDecision]) -> str:
    if any(d.shape == DECISION_SHAPE_SHADOW and d.lines for d in decisions_for_session):
        lines = sum(len(d.lines) for d in decisions_for_session if d.lines)
        return f"has_lines({lines})"
    reasons = {d.reason for d in decisions_for_session if d.reason}
    if len(reasons) == 1:
        return next(iter(reasons))
    if not reasons and any(d.shape == DECISION_SHAPE_UNKNOWN for d in decisions_for_session):
        return DECISION_SHAPE_UNKNOWN
    if len(reasons) > 1:
        return "mixed:" + ",".join(sorted(reasons))
    return "decided_empty"


def render_md(audit: TrialAudit) -> str:
    counts = audit.finding_counts
    lines = [
        f"# 官方 Trial 运营对账审计 — {audit.trial_id}",
        "",
        f"- trial root: `{audit.trial_root}`",
        f"- research program: `{audit.research_program}`",
        f"- as_of (最新 bar-set 会话): **{audit.as_of}**",
        f"- arms: {', '.join(audit.arms)}",
        f"- 已报名会话: {len(audit.enrolled_sessions)} · 已决策: {len(audit.decided_sessions)} "
        f"· bar-set: {len(audit.bar_sessions)} · 决策行: {len(audit.decisions)}",
        "",
        "## 会话覆盖矩阵",
        "",
        *_session_matrix_rows(audit),
        "",
        "## 发现 (findings)",
        "",
    ]
    if not audit.findings:
        lines.append("无 — 四个事实面在 as_of 内对账一致。")
    else:
        lines.append("| 发现 | arm | 会话 | 详情 |")
        lines.append("|---|---|---|---|")
        for finding in audit.findings:
            lines.append(
                f"| {finding.code} | {finding.arm or '—'} | {finding.signal_session or '—'} | {finding.detail} |"
            )
    if audit.no_fill_resolutions:
        lines += [
            "",
            "## 无痕迹行核销 (no-fill verified)",
            "",
            "| arm | 会话 | 证券 | entry | 限价(分) | 当日最低(分) | 判定 |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in audit.no_fill_resolutions:
            low = str(row.day_low_cents) if row.day_low_cents is not None else "—"
            limit = str(row.limit_price_cents) if row.limit_price_cents is not None else "—"
            lines.append(
                f"| {row.arm} | {row.signal_session} | {row.security_id} "
                f"| {row.entry_session or '—'} | {limit} | {low} | {row.reason} |"
            )
    lines += ["", "## 臂台账摘要", "", "| arm | fills | OPEN | CLOSED | nav 首末 | 总对数增长 | MDD |", "|---|---|---|---|---|---|---|"]
    for summary in audit.arm_summaries:
        nav_span = "—"
        growth = "—"
        mdd = "—"
        if summary.nav_first and summary.nav_last:
            nav_span = f"{summary.nav_first[1]} → {summary.nav_last[1]}"
            growth = f"{summary.total_log_growth:+.6f}" if summary.total_log_growth is not None else "—"
            mdd = f"{summary.max_drawdown:.6f}" if summary.max_drawdown is not None else "—"
        lines.append(
            f"| {summary.arm} | {summary.fills} | {summary.open_positions} | {summary.closed_positions}"
            f" | {nav_span} | {growth} | {mdd} |"
        )
    remaining = [s for s in audit.enrolled_sessions if s.signal_session > audit.as_of]
    next_undecided = next(
        (s for s in audit.enrolled_sessions if s.signal_session not in audit.decided_sessions),
        None,
    )
    lines += [
        "",
        "## 跑道与待办",
        "",
        f"- 剩余报名会话 (>{audit.as_of}): {len(remaining)}"
        + (f" (首个 {remaining[0].signal_session})" if remaining else ""),
        f"- 下一个未决策会话: {next_undecided.signal_session if next_undecided else '—'}",
        f"- finalize backlog: {counts.get(FINDING_FINALIZE_BACKLOG, 0)}",
        f"- decide_missing: {counts.get(FINDING_DECIDE_MISSING, 0)}",
        f"- deadline_missed: {counts.get(FINDING_DEADLINE_MISSED, 0)}",
        f"- unmatched_decided_line: {counts.get(FINDING_UNMATCHED_LINE, 0)}",
        f"- no_fill_verified (已核销, 非发现): {len(audit.no_fill_resolutions)}",
        f"- exit_overdue: {counts.get(FINDING_EXIT_OVERDUE, 0)}",
        f"- bars_gap: {counts.get(FINDING_BARS_GAP, 0)}",
        "",
        "## 纪律",
        "",
        "- 只读审计 (`mode=ro&immutable=1`), 对 trial root 字节级零突变;"
        " 不构造 src repository (避免 WAL/DDL 写副作用)。",
        "- as_of 从 bar-set 证据派生, 不取墙钟; 同输入报告逐字节可复现。",
        "- 纯诊断 (宪法 #2): 只披露不判定; 缺列/改名列/损坏 decision_json 一律"
        " typed fail-closed, 不猜测语义。",
        "- 发现是运营对账事实, 不是权限或证据结论; 处置属 owner/操作员。",
        "- 无痕迹行核销 (R220 Op1): 以锁定判定表单一实现在『命令未迟到』投影"
        "下重评估; 未触及限价在任何时序下都不成交, 该投影不扩大核销面"
        " (touched / UNKNOWN 一律保留为发现)。",
    ]
    return "\n".join(lines) + "\n"


def audit_to_dict(audit: TrialAudit) -> dict:
    return {
        "trial_root": audit.trial_root,
        "trial_id": audit.trial_id,
        "research_program": audit.research_program,
        "arms": list(audit.arms),
        "as_of": audit.as_of,
        "enrolled_sessions": [
            {
                "signal_session": s.signal_session,
                "assessment_date": s.assessment_date,
            }
            for s in audit.enrolled_sessions
        ],
        "decisions": {
            f"{session}|{arm}": {
                "shape": decision.shape,
                "reason": decision.reason,
                "lines": len(decision.lines),
                "created_at": decision.created_at,
            }
            for (session, arm), decision in sorted(audit.decisions.items())
        },
        "bar_sessions": {k: audit.bar_sessions[k] for k in sorted(audit.bar_sessions)},
        "findings": [
            {
                "code": f.code,
                "arm": f.arm,
                "signal_session": f.signal_session,
                "detail": f.detail,
            }
            for f in audit.findings
        ],
        "finding_counts": audit.finding_counts,
        "no_fill_resolutions": [
            {
                "arm": r.arm,
                "signal_session": r.signal_session,
                "security_id": r.security_id,
                "shadow_line_id": r.shadow_line_id,
                "entry_session": r.entry_session,
                "limit_price_cents": r.limit_price_cents,
                "reason": r.reason,
                "day_low_cents": r.day_low_cents,
            }
            for r in audit.no_fill_resolutions
        ],
        "arm_summaries": [
            {
                "arm": s.arm,
                "fills": s.fills,
                "open_positions": s.open_positions,
                "closed_positions": s.closed_positions,
                "nav_marks": s.nav_marks,
                "nav_first_cents": s.nav_first[1] if s.nav_first else None,
                "nav_last_cents": s.nav_last[1] if s.nav_last else None,
                "total_log_growth": s.total_log_growth,
                "max_drawdown": s.max_drawdown,
            }
            for s in audit.arm_summaries
        ],
    }


def render_json(audit: TrialAudit) -> str:
    return json.dumps(audit_to_dict(audit), ensure_ascii=False, sort_keys=True, indent=1) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Official trial operational audit (read-only)")
    parser.add_argument("--trial-root", required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--research-program", required=True)
    parser.add_argument("--arms", default=",".join(DEFAULT_ARMS))
    parser.add_argument("--output-md")
    parser.add_argument("--output-json")
    args = parser.parse_args(argv)

    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    if not arms:
        print(json.dumps({"ok": False, "error": {"code": "invalid_arms"}}), file=sys.stderr)
        return 2
    try:
        audit = build_audit(
            Path(args.trial_root), args.trial_id, args.research_program, arms
        )
    except TrialAuditError as exc:
        print(json.dumps({"ok": False, "error": exc.to_dict()}, ensure_ascii=False), file=sys.stderr)
        return 2
    md = render_md(audit)
    if args.output_md:
        Path(args.output_md).write_text(md, encoding="utf-8")
    if args.output_json:
        Path(args.output_json).write_text(render_json(audit), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
