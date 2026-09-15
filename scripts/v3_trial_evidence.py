#!/usr/bin/env python
"""v3_trial_evidence — 官方 Trial 累积前向证据只读消费面 (R225 Op1)。

trial-btst-regime-r1 自 2026-08-28 启动以来在真实 trial root 累积了双臂
NAV 阶梯与 pair 决策, 但没有任何工具把它们变成可操作读数; 且 Observe 期
实锤: 密封 SAP 的 ``block_rule='monthly'`` (owner 批准值, seal 忠实记录)
与冻结评估器 ``_sap_block_length`` 的数字块长语法结构性不相容 —— 固定评估
日 2026-11-26 的官方终评估必然 ``invalid_block_rule`` fail-closed。本工具
把该事实从评估日爆雷变成今天类型化响亮披露 (``frozen_evaluation.status =
'blocked'``), owner 可据此决定修复路径 (评估器语法扩展 vs SAP 修订)。

只读纪律 (与 v3_trial_status / v3_trial_execution_audit 同款):
- 全部 sqlite 经 ``mode=ro&immutable=1`` 冷读, 对 trial root 字节级零突变
  (测试钉死); 不构造任何 src repository (它们会落 WAL/DDL 写副作用)。
- 冻结统计零 fork: 配对 delta 与分量下界只经
  ``src...evidence.paired_statistics`` 的公开纯函数; ``_sap_block_length``
  私有复用 (单一实现), 工具内无任何重实现的统计数学。官方场景装配
  (``_scenario_assessment`` 的 bootstrap∧HAC∧时序折痕 min-selection) 不在
  v1 复制 —— 该装配消费 replay 工件 (``PairedReplayResult``), live 前向
  trial 的终评估接线属独立 frontier 项; 因此本工具披露的分量读数标注
  ``official_assembly_not_replicated``, 不是官方 LCB。
- coverage 官方谓词 (成熟 outcome / decision-day / ESS) 依赖 Outcome
  Finalizer 与消费台账对 live trial 的接线, v1 不可推导 → 显式 ``null``
  不猜测; 资本面代理计数 (CLOSED 持仓等) 单独披露并标注 proxy。
- 纯诊断 (宪法 #2): 只披露不判定; 缺列/改名列/损坏 JSON 一律 typed
  fail-closed, 不猜测语义。发现是运营事实, 不是权限或证据结论。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.screening.offensive.v3.evidence.paired_statistics import (
    PairedNavPoint,
    PairedStatisticsError,
    block_bootstrap_lcb,
    newey_west_lcb,
    paired_daily_log_growth,
)
# 单一实现纪律: 块长语法只此一处 (数字提取 + fail-closed), 私有复用。
from src.screening.offensive.v3.evidence.paired_statistics import (  # noqa: E402
    _sap_block_length,
)
from scripts.v3_trial_operational_audit import (  # noqa: E402
    TrialAuditError,
    read_bar_sessions,
)

TRIAL_DB = "governance.sqlite3"
DECISIONS_DB = "decisions.sqlite3"
BARS_DB = "bars-evidence.sqlite3"

NAV_REQUIRED_COLUMNS = (
    "as_of",
    "observation_kind",
    "log_growth_kind",
    "log_growth_nav_numerator",
    "log_growth_nav_denominator",
)
POSITIONS_REQUIRED_COLUMNS = ("security_id", "state", "settled_quantity_units")

COVERAGE_THRESHOLDS = {
    "mature_outcomes": 150,
    "decision_days": 60,
    "effective_sample_size": 60.0,
    "tickers": 80,
    "months": 12,
}


class TrialEvidenceError(RuntimeError):
    """Fail-closed rejection of an evidence consumption input."""

    def __init__(self, code: str, details: Mapping[str, Any] | None = None):
        super().__init__(f"{code}: {details or {}}")
        self.code = code
        self.details = dict(details or {})


def _ro_connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def _require_columns(
    conn: sqlite3.Connection, table: str, required: Sequence[str]
) -> None:
    columns = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")
    }
    missing = [name for name in required if name not in columns]
    if missing:
        raise TrialEvidenceError(
            "schema_drift", {"table": table, "missing_columns": missing}
        )


# ---------------------------------------------------------------------------
# 治理事实 (密封 trial/SAP manifest)
# ---------------------------------------------------------------------------


def load_governance_facts(root: Path, trial_id: str) -> dict[str, Any]:
    """冷读密封 trial + SAP manifest; trial 未知 = 启动未完成 (not_seeded)。"""
    path = root / TRIAL_DB
    if not path.is_file():
        return {}
    conn = _ro_connect(path)
    try:
        _require_columns(
            conn,
            "sealed_trials",
            ("trial_id", "trial_manifest_json", "sap_manifest_json"),
        )
        row = conn.execute(
            "SELECT trial_manifest_json, sap_manifest_json FROM sealed_trials"
            " WHERE trial_id = ?",
            (trial_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {}
    try:
        trial = json.loads(str(row[0]))
        sap = json.loads(str(row[1]))
    except json.JSONDecodeError as exc:
        raise TrialEvidenceError(
            "governance_manifest_corrupt", {"error": str(exc)}
        ) from exc
    return {"trial": trial, "sap": sap}


# ---------------------------------------------------------------------------
# 双臂 NAV 阶梯 (精确有理数, 与评估器 _points_for 同语义)
# ---------------------------------------------------------------------------


def _read_arm_nav_rows(root: Path, arm: str) -> list[dict[str, Any]]:
    path = root / "arms" / arm / "capital.sqlite3"
    conn = _ro_connect(path)
    try:
        _require_columns(conn, "nav_observations", NAV_REQUIRED_COLUMNS)
        rows = conn.execute(
            "SELECT as_of, observation_kind, log_growth_nav_numerator,"
            " log_growth_nav_denominator FROM nav_observations ORDER BY as_of"
        ).fetchall()
    finally:
        conn.close()
    parsed: list[dict[str, Any]] = []
    for as_of, kind, numerator, denominator in rows:
        if str(kind) != "AS_OBSERVED":
            raise TrialEvidenceError(
                "unsupported_observation_kind",
                {"arm": arm, "as_of": str(as_of), "kind": str(kind)},
            )
        parsed.append(
            {
                "as_of": str(as_of),
                "numerator": numerator,
                "denominator": denominator,
            }
        )
    return parsed


def _arm_ratio_sessions(rows: Sequence[Mapping[str, Any]]) -> list[date]:
    """有前值比的观察日 (跳过 NO_PRIOR/None 比值行, 评估器同语义)。"""
    sessions: list[date] = []
    for row in rows:
        if row["numerator"] is None or row["denominator"] is None:
            continue
        day = date.fromisoformat(row["as_of"][:10])
        if not sessions or sessions[-1] != day:
            sessions.append(day)
    return sessions


def build_paired_points(
    root: Path, arms: Sequence[str] = ("champion", "challenger")
) -> tuple[PairedNavPoint, ...]:
    """双臂精确有理数 NAV 阶梯; 不对齐/非 AS_OBSERVED typed fail-closed。"""
    per_arm: dict[str, list[date]] = {}
    per_arm_rows: dict[str, list[dict[str, Any]]] = {}
    for arm in arms:
        rows = _read_arm_nav_rows(root, arm)
        per_arm_rows[arm] = rows
        per_arm[arm] = _arm_ratio_sessions(rows)
    reference = per_arm[arms[0]]
    for arm in arms[1:]:
        if per_arm[arm] != reference:
            raise TrialEvidenceError(
                "session_alignment",
                {
                    "arm": arm,
                    "sessions": len(per_arm[arm]),
                    f"{arms[0]}_sessions": len(reference),
                },
            )
    if len(reference) < 2:
        raise TrialEvidenceError(
            "too_short", {"ratio_sessions": len(reference)}
        )
    points: list[PairedNavPoint] = []
    index_by_arm_date: dict[str, dict[date, dict[str, int]]] = {}
    for arm in arms:
        lookup: dict[date, dict[str, int]] = {}
        for row in per_arm_rows[arm]:
            if row["numerator"] is None or row["denominator"] is None:
                continue
            day = date.fromisoformat(row["as_of"][:10])
            lookup.setdefault(
                day,
                {
                    "numerator": _as_int(row["numerator"], arm, day),
                    "denominator": _as_int(row["denominator"], arm, day),
                },
            )
        index_by_arm_date[arm] = lookup
    for day in reference:
        point = {"session": day}
        for arm in arms:
            rationals = index_by_arm_date[arm][day]
            point[f"{arm}_nav_numerator"] = rationals["numerator"]
            point[f"{arm}_nav_denominator"] = rationals["denominator"]
        points.append(
            PairedNavPoint(
                session=day,
                champion_nav_numerator=point["champion_nav_numerator"],
                champion_nav_denominator=point["champion_nav_denominator"],
                challenger_nav_numerator=point["challenger_nav_numerator"],
                challenger_nav_denominator=point["challenger_nav_denominator"],
            )
        )
    return tuple(points)


def _as_int(value: Any, arm: str, day: date) -> int:
    if type(value) is not int:
        raise TrialEvidenceError(
            "nav_rational_invalid",
            {"arm": arm, "as_of": day.isoformat(), "value": repr(value)},
        )
    return value


# ---------------------------------------------------------------------------
# 冻结评估尝试 (分量读数; 官方场景装配不复制)
# ---------------------------------------------------------------------------


def compute_frozen_component_bounds(
    points: Sequence[PairedNavPoint], sap: Mapping[str, Any]
) -> dict[str, Any]:
    """SAP 冻结参数下的分量下界; 块长语法不相容 = typed blocked 披露。"""
    params = {
        "bootstrap_method": sap.get("bootstrap_method"),
        "block_rule": sap.get("block_rule"),
        "repetitions": sap.get("repetitions"),
        "seed": sap.get("seed"),
        "one_sided_confidence_level": sap.get("one_sided_confidence_level"),
    }
    try:
        block_length = _sap_block_length(str(params["block_rule"]))
    except PairedStatisticsError as exc:
        return {
            "status": "blocked",
            "code": exc.code,
            "sap_block_rule": params["block_rule"],
            "note": (
                "密封 SAP 与冻结评估器块长语法不相容; 官方终评估"
                " (fixed_assessment_date) 会以同一 code fail-closed"
            ),
        }
    try:
        deltas = paired_daily_log_growth(points)
        confidence = float(params["one_sided_confidence_level"] or 0.0)
        bootstrap = block_bootstrap_lcb(
            deltas,
            method=str(params["bootstrap_method"]),
            block_length=block_length,
            repetitions=int(params["repetitions"] or 0),
            seed=int(params["seed"] or 0),
            confidence=confidence,
        )
        hac = newey_west_lcb(
            deltas, lag=min(4, len(deltas) - 1), confidence=confidence
        )
    except PairedStatisticsError as exc:
        return {
            "status": "blocked",
            "code": exc.code,
            "sap_block_rule": params["block_rule"],
        }
    mean = sum(deltas) / len(deltas)
    return {
        "status": "ok",
        "n_deltas": len(deltas),
        "mean_delta": mean,
        "bootstrap_lcb": bootstrap,
        "hac_lcb": hac,
        "block_length": block_length,
        "official_assembly_not_replicated": (
            "_scenario_assessment 的最保守 min-selection (bootstrap∧HAC∧"
            "时序折痕) 未在 v1 复制 —— 单一实现纪律; 本段分量读数不是官方"
            " LCB, 官方装配消费 replay 工件, live trial 终评估接线属"
            " 独立 frontier 项"
        ),
    }


# ---------------------------------------------------------------------------
# 决策 / 持仓 / coverage / pending / freshness
# ---------------------------------------------------------------------------


def _read_decisions(root: Path, trial_id: str) -> list[dict[str, Any]]:
    path = root / DECISIONS_DB
    if not path.is_file():
        return []
    conn = _ro_connect(path)
    try:
        _require_columns(
            conn, "trial_arm_decisions", ("signal_session", "arm", "decision_json")
        )
        rows = conn.execute(
            "SELECT signal_session, arm, decision_json FROM"
            " trial_arm_decisions WHERE trial_id = ? ORDER BY signal_session",
            (trial_id,),
        ).fetchall()
    finally:
        conn.close()
    parsed: list[dict[str, Any]] = []
    for session, arm, decision_json in rows:
        try:
            decision = json.loads(str(decision_json))
        except json.JSONDecodeError as exc:
            raise TrialEvidenceError(
                "decision_json_corrupt",
                {"signal_session": str(session), "arm": str(arm), "error": str(exc)},
            ) from exc
        if not type(decision) is dict:
            raise TrialEvidenceError(
                "decision_json_corrupt",
                {"signal_session": str(session), "arm": str(arm)},
            )
        if decision.get("artifact_kind") == "shadow_decision":
            if not decision.get("target_entry_session"):
                raise TrialEvidenceError(
                    "decision_entry_missing",
                    {"signal_session": str(session), "arm": str(arm)},
                )
            shape = "run"
        elif "reason" in decision:
            shape = "no_trade"
        else:
            raise TrialEvidenceError(
                "decision_shape_unknown",
                {"signal_session": str(session), "arm": str(arm)},
            )
        parsed.append(
            {
                "signal_session": str(session),
                "arm": str(arm),
                "shape": shape,
                "decision": decision,
            }
        )
    return parsed


def _read_positions(root: Path, arm: str) -> dict[str, list[dict[str, Any]]]:
    path = root / "arms" / arm / "capital.sqlite3"
    conn = _ro_connect(path)
    try:
        _require_columns(conn, "positions", POSITIONS_REQUIRED_COLUMNS)
        rows = conn.execute(
            "SELECT security_id, state, settled_quantity_units FROM positions"
            " ORDER BY security_id, position_lineage_id"
        ).fetchall()
    finally:
        conn.close()
    result: dict[str, list[dict[str, Any]]] = {"OPEN": [], "CLOSED": []}
    for security_id, state, quantity in rows:
        bucket = result.get(str(state))
        if bucket is None:
            raise TrialEvidenceError(
                "position_state_unknown",
                {"arm": arm, "security_id": str(security_id), "state": str(state)},
            )
        bucket.append(
            {
                "security_id": str(security_id),
                "settled_quantity_units": quantity,
            }
        )
    return result


def _arm_pending_exits(
    root: Path,
    arm: str,
    run_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """OPEN 持仓 + 决策行 target_exit_session 交叉 (行键 = security)。"""
    positions = _read_positions(root, arm)
    exit_by_security: dict[str, str] = {}
    for row in run_rows:
        if str(row["arm"]) != str(arm).upper():
            continue
        for line in row["decision"].get("counterfactual_lines") or []:
            security = line.get("security_id")
            exit_session = line.get("target_exit_session")
            if security is not None and exit_session is not None:
                exit_by_security.setdefault(str(security), str(exit_session))
    enriched = [
        {**position, "target_exit_session": exit_by_security.get(position["security_id"])}
        for position in positions["OPEN"]
    ]
    return {
        "open_positions": len(positions["OPEN"]),
        "closed_positions": len(positions["CLOSED"]),
        "positions": enriched,
    }


def _months_spanned(sessions: Sequence[date]) -> int:
    return len({(day.year, day.month) for day in sessions})


def collect_evidence(
    root: Path,
    trial_id: str,
    arms: Sequence[str] = ("champion", "challenger"),
) -> dict[str, Any]:
    """全量只读证据 payload; 缺治理库 = 合法启动形态 (not_seeded)。"""
    facts = load_governance_facts(root, trial_id)
    if not facts:
        return {
            "trial_id": trial_id,
            "status": "not_seeded",
            "paired_points": 0,
        }
    try:
        bars = read_bar_sessions(root)
    except TrialAuditError as exc:
        raise TrialEvidenceError(exc.code, exc.details) from exc
    decisions = _read_decisions(root, trial_id)
    run_rows = [row for row in decisions if row["shape"] == "run"]
    try:
        points = build_paired_points(root, arms)
    except FileNotFoundError as exc:
        raise TrialEvidenceError(
            "arm_ledger_missing", {"path": str(exc)}
        ) from exc
    sessions = [point.session for point in points]
    ladder_sessions = [sessions[0]] if sessions else []
    if len(sessions) > 1:
        ladder_sessions = sessions
    ratio_sessions = _arm_ratio_sessions(
        _read_arm_nav_rows(root, arms[0])
    )
    pending_exits = {
        arm: _arm_pending_exits(root, arm, run_rows) for arm in arms
    }
    tickers = {
        arm: len(
            {
                position["security_id"]
                for bucket in _read_positions(root, arm).values()
                for position in bucket
            }
        )
        for arm in arms
    }
    coverage = {
        "thresholds": COVERAGE_THRESHOLDS,
        "official_mature_outcomes": None,
        "official_decision_days": None,
        "official_effective_sample_size": None,
        "note": (
            "官方谓词依赖 Outcome Finalizer / 消费台账对 live trial 的接线,"
            " v1 不可推导显式 null; 资本面代理计数单独披露 (proxy, 非官方"
            " outcome 判定)"
        ),
        "proxies": {
            "sessions_with_pairs_any": len({row["signal_session"] for row in decisions}),
            "sessions_with_run_pairs": len({row["signal_session"] for row in run_rows}),
            "mature_outcome_proxy": {
                arm: pending_exits[arm]["closed_positions"] for arm in arms
            },
            "mature_outcome_proxy_champion": pending_exits[arms[0]]["closed_positions"],
            "mature_outcome_proxy_challenger": pending_exits[arms[-1]]["closed_positions"],
            "distinct_tickers_champion": tickers[arms[0]],
            "distinct_tickers_challenger": tickers[arms[-1]],
            "months_spanned_ladder": _months_spanned(ratio_sessions),
        },
    }
    latest_nav_as_of = max(ratio_sessions).isoformat() if ratio_sessions else None
    latest_bar = max(bars) if bars else None
    payload: dict[str, Any] = {
        "trial_id": trial_id,
        "status": "ok",
        "trial": {
            "minimum_economic_effect": facts["trial"].get("minimum_economic_effect"),
            "fixed_assessment_date": facts["trial"].get("fixed_assessment_date"),
        },
        "sap": {
            "primary_metric": facts["sap"].get("primary_metric"),
            "execution_mode": facts["sap"].get("execution_mode"),
            "bootstrap_method": facts["sap"].get("bootstrap_method"),
            "block_rule": facts["sap"].get("block_rule"),
            "repetitions": facts["sap"].get("repetitions"),
            "seed": facts["sap"].get("seed"),
            "one_sided_confidence_level": facts["sap"].get(
                "one_sided_confidence_level"
            ),
        },
        "paired_points": len(points),
        "first_session": sessions[0].isoformat() if sessions else None,
        "last_session": sessions[-1].isoformat() if sessions else None,
        "frozen_evaluation": compute_frozen_component_bounds(
            points, facts["sap"]
        ),
        "coverage": coverage,
        "pending_exits": pending_exits,
        "freshness": {
            "latest_bar_session": latest_bar,
            "latest_nav_as_of": latest_nav_as_of,
        },
        "decision_summary": {
            "total": len(decisions),
            "run": len(run_rows),
            "no_trade": len(decisions) - len(run_rows),
        },
    }
    return payload


def render_human(payload: Mapping[str, Any]) -> str:
    lines: list[str] = []
    if payload.get("status") == "not_seeded":
        return (
            f"v3 Trial 证据消费面: trial {payload['trial_id']} 尚未封存"
            " (governance 缺行) — 合法启动形态, 零读数\n"
        )
    lines.append(f"━━━ v3 Trial 前向证据 ({payload['trial_id']}) ━━━")
    lines.append(
        "阶梯: {} 比率点 ({} → {}) · 决策 {} 行 / RUN {} / 无交易 {}".format(
            payload["paired_points"],
            payload["first_session"],
            payload["last_session"],
            payload["decision_summary"]["total"],
            payload["decision_summary"]["run"],
            payload["decision_summary"]["no_trade"],
        )
    )
    frozen = payload["frozen_evaluation"]
    if frozen["status"] == "blocked":
        lines.append(
            "冻结评估: ⚠ BLOCKED code={} (SAP block_rule={!r}) — {}".format(
                frozen.get("code"),
                frozen.get("sap_block_rule"),
                frozen.get("note", "官方终评估将同码 fail-closed"),
            )
        )
    else:
        lines.append(
            "冻结评估分量: n={} · mean_delta={:.8f} · bootstrap_lcb={:.8f}"
            " · hac_lcb={:.8f} (block_length={}; 非官方 LCB)".format(
                frozen["n_deltas"],
                frozen["mean_delta"],
                frozen["bootstrap_lcb"],
                frozen["hac_lcb"],
                frozen["block_length"],
            )
        )
    coverage = payload["coverage"]
    proxies = coverage["proxies"]
    lines.append(
        "coverage 代理 (官方谓词不可推导=null): RUN 会话 {} · 成熟 proxy"
        " chal={} / champ={} · 月跨度 {} (阈值 12) · 票数 champ={} (阈值 80)".format(
            proxies["sessions_with_run_pairs"],
            proxies["mature_outcome_proxy_challenger"],
            proxies["mature_outcome_proxy_champion"],
            proxies["months_spanned_ladder"],
            proxies["distinct_tickers_champion"],
        )
    )
    for arm, pending in payload["pending_exits"].items():
        for position in pending["positions"]:
            lines.append(
                "待出场 [{}]: {} ×{} → 评估日 {}".format(
                    arm,
                    position["security_id"],
                    position["settled_quantity_units"],
                    position.get("target_exit_session") or "未知",
                )
            )
    freshness = payload["freshness"]
    lines.append(
        "新鲜度: 最新 bar {} · 最新 NAV {}".format(
            freshness["latest_bar_session"], freshness["latest_nav_as_of"]
        )
    )
    return "\n".join(lines) + "\n"


def render_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="v3 官方 Trial 累积前向证据只读消费面 (零写入)"
    )
    parser.add_argument("--trial-root", default="data/v3_trial_root")
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--arms", default="champion,challenger")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        payload = collect_evidence(
            Path(args.trial_root), args.trial_id, tuple(args.arms.split(","))
        )
    except TrialEvidenceError as exc:
        print(
            json.dumps(
                {"ok": False, "errors": [exc.code], "details": exc.details},
                ensure_ascii=False,
            )
        )
        return 3
    if args.as_json:
        print(render_json(payload))
    else:
        print(render_human(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
