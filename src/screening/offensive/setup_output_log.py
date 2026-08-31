"""Live BTST setup-output logger — out-of-sample accumulation.

Every ``--daily-action`` run appends the full scanned candidate set (both
plan-eligible and filtered-out) with the setup's structured diagnostics
(``trigger_strength``, fund flow, pre-runup, industry, thresholds) to a per-day
JSONL file. Over time this accumulates a real out-of-sample record of the FULL
setup's live outputs so cross-cycle robustness can eventually be validated on
genuine forward data (the retroactive replay is blocked by thin historical
fund-flow/industry depth).

Design:
  - one file per signal day (``YYYYMMDD.jsonl``); reruns MERGE into the existing
    file instead of blind overwrite — a (ticker, setup) row keeps the
    ``plan_eligible=True`` version, latest run wins on equal eligibility
    (deterministic merge, sorted output). Without this, a late-evening rerun
    with degraded data silently erases earlier runs' hits from the out-of-sample
    record (2026-08-20 incident: the 18:09 hit became a real ledger position,
    then vanished from the 22:47 rewrite);
  - ledger write guard: tickers named in ``plan_backed_tickers`` (trades the
    ledger holds for this signal date) must survive the merge with a
    plan_eligible row — an unrecoverable loss is logged as a loud warning
    (ledger↔log reconciliation alarm), never silently absorbed;
  - the log directory chain is validated (every component lstat-walked, symlink
    or non-directory rejected) BEFORE any write — a guarded artifact deserves a
    guarded home;
  - append-only across days; forward returns are joined later from price_cache;
  - write failures propagate to the caller: the dispatcher blocks new-plan
    creation for that run rather than creating plans without their evidence row.

Siblings (same directory, diagnostic-face evidence, fail-open on write):
  - ``YYYYMMDD.capacity.jsonl`` — plan-layer capacity blocks (R79);
  - ``YYYYMMDD.funnel.json`` — scan funnel aggregates, overwrite-idempotent (R80);
  - ``YYYYMMDD.scan_runs.jsonl`` — append-only per-refresh scan snapshots
    (R82): the merge above intentionally collapses per-refresh views, so the
    cross-refresh flip measurement and any refresh-divergence forensics read
    from this artifact instead (see ``log_scan_run``/``refresh_flip_summary``).
"""

from __future__ import annotations

import json
import logging
import math
import os
import stat
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.utils.secure_files import read_regular_bytes

SCHEMA_VERSION = 1
_DEFAULT_DIR = Path("data/reports/setup_output_log")
_DEFAULT_CALENDAR = Path("data/reports/trade_calendar.json")
_MAX_LOG_FILE_BYTES = 16 * 1024 * 1024  # 16 MB — 单日 JSONL 的宽松上界

logger = logging.getLogger(__name__)


class SetupOutputLogError(Exception):
    """日志目录安全校验失败 (目录链含 symlink/非目录组件) — 写入前 fail-closed."""


def _finite(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _record(action: Any, *, signal_date: str, regime: str, plan_eligible: bool, logged_at: str) -> dict:
    md = getattr(action, "metadata", None) or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "signal_date": signal_date,
        "logged_at": logged_at,
        "ticker": str(getattr(action, "ticker", "")),
        "setup": str(getattr(action, "setup", "")),
        "plan_eligible": bool(plan_eligible),
        "degraded": bool(getattr(action, "degraded", False)),
        "trigger_strength": _finite(getattr(action, "trigger_strength", 0.0)),
        "entry_price": _finite(getattr(action, "entry_price", 0.0)),
        "kelly_pct": _finite(getattr(action, "kelly_pct", 0.0)),
        "regime": str(regime),
        "block_reason": str(getattr(action, "block_reason", "") or ""),
        "degradation_reason": str(getattr(action, "degradation_reason", "") or ""),
        # Flattened setup diagnostics (present only for detected candidates).
        "pct_change": _finite(md.get("pct_change")),
        "main_net_inflow": _finite(md.get("main_net_inflow")),
        "industry_pct": _finite(md.get("industry_pct")),
        "pre_5d_runup_pct": _finite(md.get("pre_5d_runup_pct")),
        "limit_up_pct_threshold": _finite(md.get("limit_up_pct_threshold")),
    }


def _require_secure_directory(out: Path) -> None:
    """日志目录链全组件 lstat walk: 任一 symlink/非目录组件写入前拒绝.

    守卫之物配守卫之甲: 本文件自写守卫起承载 panel 样本外证据, 目录链被
    预置 symlink 重定向 = 证据写穿到任意路径. 与 O_NOFOLLOW 同级的静态
    防预置 (竞态窗口定性同仓库 path_guards 纪律: lstat→open 之间不抗竞态).
    """
    absolute = Path(os.path.abspath(out))
    components = absolute.parts
    for index in range(1, len(components) + 1):
        prefix = Path(*components[:index])
        try:
            info = os.lstat(prefix)
        except FileNotFoundError as exc:
            raise SetupOutputLogError(f"日志目录组件缺失: {prefix}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise SetupOutputLogError(f"日志目录链含 symlink: {prefix}")
        if not stat.S_ISDIR(info.st_mode):
            raise SetupOutputLogError(f"日志路径组件非目录: {prefix}")


def _load_existing_records(target: Path) -> list[dict]:
    """安全读取既有当日日志; 缺失→空; 损坏→告警后按空处理 (守卫会接手)."""
    if not target.exists():
        return []
    records: list[dict] = []
    try:
        raw = read_regular_bytes(target, max_bytes=_MAX_LOG_FILE_BYTES)
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    except (OSError, ValueError, json.JSONDecodeError):
        logger.warning(
            "既有 setup_output_log 损坏, 无法参与合并 (按空文件处理): %s",
            target,
            exc_info=True,
        )
        return []
    return records


def _merge_records(existing: list[dict], new: list[dict]) -> list[dict]:
    """确定性合并: (ticker, setup) 去重 — eligible 优先, 同资格晚运行覆盖.

    不变量: 行只增不灭 — 除非新行以同键且同等或更高资格覆盖, 旧行永不消失
    (2026-08-20 事件: 覆盖写曾把早运行的 plan_eligible 行整行抹掉).
    """
    merged: dict[tuple[str, str], dict] = {}
    for record in existing + new:
        key = (str(record.get("ticker", "")), str(record.get("setup", "")))
        previous = merged.get(key)
        if (
            previous is None
            or bool(record.get("plan_eligible"))
            or not bool(previous.get("plan_eligible"))
        ):
            merged[key] = record
    return [merged[key] for key in sorted(merged)]


def log_setup_outputs(
    signal_date: date,
    candidates: Iterable[Any],
    blocked: Iterable[Any],
    *,
    regime: str = "unknown",
    out_dir: Path | str = _DEFAULT_DIR,
    plan_backed_tickers: Iterable[str] = (),
) -> Path:
    """Persist the full scanned setup output for ``signal_date`` (merge-on-rerun).

    ``candidates`` are the plan-eligible actions; ``blocked`` are the
    filtered-out / degraded ones. ``plan_backed_tickers`` are tickers the ledger
    holds planned trades for on this signal date — their plan_eligible rows must
    survive the merge; an unrecoverable loss raises a loud reconciliation
    warning (the write itself still proceeds so the per-day coverage sentinel
    keeps working). Returns the written per-day file path.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _require_secure_directory(out)
    compact = signal_date.strftime("%Y%m%d")
    logged_at = datetime.now(timezone.utc).isoformat()

    new_records = [
        _record(a, signal_date=compact, regime=regime, plan_eligible=True, logged_at=logged_at)
        for a in candidates
    ] + [
        _record(a, signal_date=compact, regime=regime, plan_eligible=False, logged_at=logged_at)
        for a in blocked
    ]

    target = out / f"{compact}.jsonl"
    records = _merge_records(_load_existing_records(target), new_records)

    # 台账↔日志对账守卫: 计划-backed 行必须以 plan_eligible 存活. 合并已尽力
    # 保留既有行; 此处仍缺失 = 证据不可恢复 (如首跑日志写失败) — 大声告警,
    # 绝不静默 (panel 证据不完整必须可见).
    eligible_now = {
        str(record.get("ticker", "")) for record in records if record.get("plan_eligible")
    }
    missing = sorted(set(plan_backed_tickers) - eligible_now)
    if missing:
        logger.warning(
            "⚠ 台账↔日志对账失败: %s 的计划股票 %s 在日志(含既有合并)中无 "
            "plan_eligible 行 — 该信号日 panel 证据不完整, 请核查当日运行记录",
            compact,
            ",".join(missing),
        )

    payload = "\n".join(
        json.dumps(rec, ensure_ascii=False, allow_nan=False, sort_keys=True) for rec in records
    )
    if payload:
        payload += "\n"

    fd, tmp = tempfile.mkstemp(dir=str(out), prefix=f".{compact}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def _capacity_skip_row(
    skip: Any, *, signal_date: str, logged_at: str
) -> dict | None:
    """duck-type CapacitySkip → 结构化行; 无 ticker 的行拒绝为 None。"""
    ticker = getattr(skip, "ticker", None)
    if not ticker:
        return None
    return {
        "schema_version": SCHEMA_VERSION,
        "signal_date": signal_date,
        "ticker": str(ticker),
        "reason": str(getattr(skip, "reason", "") or "unknown"),
        "industry": str(getattr(skip, "industry", "") or ""),
        "detail": str(getattr(skip, "detail", "") or ""),
        "logged_at": logged_at,
    }


def log_capacity_skips(
    signal_date: date,
    skips: Iterable[Any],
    *,
    out_dir: Path | str = _DEFAULT_DIR,
) -> Path:
    """把计划层容量拦截 (CapacitySkip) 落为当日兄弟工件 ``YYYYMMDD.capacity.jsonl``。

    2026-08-27 实证: open_weight 58.86% 下 14 只 plan_eligible 全部被
    portfolio_cap 拦截、台账零计划, 事件本身零持久痕迹 — 检测行有本模块的
    合并守卫, 容量拦截却只存在于 service_run 内存对象, 『为什么当日信号没
    变成交易』的历史不可重建。本工件补齐计划层的证据耐久性。

    语义分流 (与主日志的 fail-closed 不同): 容量拦截是**可重推导的派生证据**
    (渲染层每次重算), 丢失不孤儿任何计划 — 写失败由调用方 fail-open (WARNING),
    不阻断计划创建; 主日志则是计划的存在性证据, 写失败必须阻断 (2026-08-23
    Item 3 纪律)。重跑合并: (ticker, reason) 键晚运行覆盖, 确定性排序; 目录
    链守卫与原子写与主日志同一实现。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _require_secure_directory(out)
    compact = signal_date.strftime("%Y%m%d")
    logged_at = datetime.now(timezone.utc).isoformat()

    new_records = [
        row
        for row in (
            _capacity_skip_row(s, signal_date=compact, logged_at=logged_at)
            for s in skips
        )
        if row is not None
    ]
    target = out / f"{compact}.capacity.jsonl"
    existing = _load_existing_records(target)
    merged: dict[tuple[str, str], dict] = {}
    for record in existing:
        key = (str(record.get("ticker", "")), str(record.get("reason", "")))
        merged[key] = record
    for record in new_records:  # 晚运行覆盖同键
        key = (record["ticker"], record["reason"])
        merged[key] = record
    records = [merged[k] for k in sorted(merged)]

    payload = "\n".join(
        json.dumps(rec, ensure_ascii=False, allow_nan=False, sort_keys=True) for rec in records
    )
    if payload:
        payload += "\n"

    fd, tmp = tempfile.mkstemp(dir=str(out), prefix=f".{compact}_capacity_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def load_capacity_skips(
    signal_date: date,
    *,
    out_dir: Path | str = _DEFAULT_DIR,
) -> list[dict]:
    """只读回读当日容量拦截行; 文件缺失/损坏行跳过, 绝不抛 (advisory 消费面)。"""
    compact = signal_date.strftime("%Y%m%d")
    target = Path(out_dir) / f"{compact}.capacity.jsonl"
    if not target.exists():
        return []
    rows: list[dict] = []
    for line in read_regular_bytes(target, max_bytes=_MAX_LOG_FILE_BYTES).decode("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # 半截行不致命 — 派生证据的消费面宁缺毋抛
        if isinstance(row, dict):
            rows.append(row)
    return rows


def log_scan_funnel(
    signal_date: date,
    funnel: Any,
    *,
    out_dir: Path | str = _DEFAULT_DIR,
) -> Path:
    """把扫描漏斗 (ScanFunnel 聚合标量) 落为当日兄弟工件 ``YYYYMMDD.funnel.json``。

    漏斗数字此前只存在于当次渲染文本, snapshot 过期后**不可重推导** (重跑
    --daily-action 需要当日 verified snapshot, 次日即被覆盖) — 零命中/低命中日
    的检测面取证只能手工复现检测路径 (2026-08-30 R78 Op1 即如此)。本工件把
    『为什么当日没有信号』从信息真空变成可审计证据, per-condition 分桶
    (``detect_miss_stages``) 让普跌分发日 C2 全挡这类结构自解释。

    语义分流 (与主日志不同, 与 capacity 工件同族): 漏斗是**诊断面证据**, 丢失
    不孤儿任何计划 — 写失败由调用方 fail-open (WARNING); 主日志则是计划的存在
    性证据, 写失败必须阻断 (2026-08-23 Item 3 纪律)。单日单文件, 重跑覆盖 =
    幂等 (聚合标量, 晚运行即真相 — 与检测行的「合并保行」不同, 聚合数没有
    保行问题)。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _require_secure_directory(out)
    compact = signal_date.strftime("%Y%m%d")

    def _stages() -> dict[str, int]:
        raw = getattr(funnel, "detect_miss_stages", None) or {}
        return {str(k): int(v) for k, v in raw.items() if v}

    payload = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "signal_date": compact,
            "universe": getattr(funnel, "universe", None),
            "verify_blocked": int(getattr(funnel, "verify_blocked", 0) or 0),
            "excluded_permanent": int(getattr(funnel, "excluded_permanent", 0) or 0),
            "data_rejected": int(getattr(funnel, "data_rejected", 0) or 0),
            "scannable": int(getattr(funnel, "scannable", 0) or 0),
            "prefilter_passed": int(getattr(funnel, "prefilter_passed", 0) or 0),
            "hits": int(getattr(funnel, "hits", 0) or 0),
            "detect_miss_stages": _stages(),
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
    ) + "\n"
    target = out / f"{compact}.funnel.json"
    fd, tmp = tempfile.mkstemp(dir=str(out), prefix=f".{compact}_funnel_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def load_scan_funnel(
    signal_date: date,
    *,
    out_dir: Path | str = _DEFAULT_DIR,
) -> dict | None:
    """只读回读当日漏斗工件; 缺失/损坏 → None (advisory 消费面, 宁缺毋抛)。"""
    compact = signal_date.strftime("%Y%m%d")
    target = Path(out_dir) / f"{compact}.funnel.json"
    if not target.exists():
        return None
    try:
        raw = read_regular_bytes(target, max_bytes=_MAX_LOG_FILE_BYTES)
        row = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        logger.warning("漏斗工件损坏, 按缺失处理: %s", target, exc_info=True)
        return None
    return row if isinstance(row, dict) else None


# ---- R82 Op1: 逐刷新扫描快照 (跨刷新翻转可测量 + 刷新分歧可重建) ----


def _scan_run_candidate(action: Any, *, plan_eligible: bool) -> dict:
    """单候选的刷新级最小诊断面 — 翻转测量只关心身份/资格/强度/原因."""
    return {
        "ticker": str(getattr(action, "ticker", "")),
        "setup": str(getattr(action, "setup", "")),
        "plan_eligible": bool(plan_eligible),
        "degraded": bool(getattr(action, "degraded", False)),
        "trigger_strength": _finite(getattr(action, "trigger_strength", 0.0)),
        "block_reason": str(getattr(action, "block_reason", "") or ""),
    }


def log_scan_run(
    signal_date: date,
    candidates: Iterable[Any],
    blocked: Iterable[Any],
    *,
    regime: str = "unknown",
    funnel: Any = None,
    snapshot_id: str | None = None,
    out_dir: Path | str = _DEFAULT_DIR,
) -> Path:
    """把单次刷新的完整扫描视图 append 到当日 ``YYYYMMDD.scan_runs.jsonl``。

    主日志 ``log_setup_outputs`` 的合并语义 (eligible 优先/同资格晚运行覆盖)
    会折叠逐刷新视图: 18:09 的 strength 0.595 在 22:47 重跑后被覆盖, 跨刷新
    翻转 (2026-08-20 300009 事件型) 不可回溯; 而 admission 的实际语义是跨刷新
    并集, 与 court 单快照先验的分歧因此无测量面。本工件 append-only 每运行一
    行, 既有字节永不改写 — 胜率的噪声分量 (翻转率/近阈值强度分布) 首次可测,
    任何刷新分歧可事后重建。

    语义分流 (与漏斗/容量同族): **诊断面证据**, 丢失不孤儿任何计划 — 写失败
    由调用方 fail-open (WARNING); 文件超过单日上界后跳过追加并告警 (不截断
    既有字节)。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _require_secure_directory(out)
    compact = signal_date.strftime("%Y%m%d")
    target = out / f"{compact}.scan_runs.jsonl"
    if target.exists() and target.stat().st_size >= _MAX_LOG_FILE_BYTES:
        logger.warning(
            "逐刷新快照超单日上界, 跳过追加 (既有字节不变): %s", target
        )
        return target

    funnel_payload = None
    if funnel is not None:
        stages_raw = getattr(funnel, "detect_miss_stages", None) or {}
        funnel_payload = {
            "universe": getattr(funnel, "universe", None),
            "verify_blocked": int(getattr(funnel, "verify_blocked", 0) or 0),
            "excluded_permanent": int(getattr(funnel, "excluded_permanent", 0) or 0),
            "data_rejected": int(getattr(funnel, "data_rejected", 0) or 0),
            "scannable": int(getattr(funnel, "scannable", 0) or 0),
            "prefilter_passed": int(getattr(funnel, "prefilter_passed", 0) or 0),
            "hits": int(getattr(funnel, "hits", 0) or 0),
            "detect_miss_stages": {
                str(k): int(v) for k, v in stages_raw.items() if v
            },
        }
    row = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "scan_run",
        "signal_date": compact,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": snapshot_id,
        "regime": str(regime),
        "funnel": funnel_payload,
        "candidates": [
            _scan_run_candidate(a, plan_eligible=True) for a in candidates
        ]
        + [_scan_run_candidate(a, plan_eligible=False) for a in blocked],
    }
    payload = json.dumps(row, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n"
    # append-only: O_APPEND 单次 write, 既有字节永不改写 (与主日志 mkstemp+
    # replace 全量重写的合并语义相反 — 这正是本工件存在的理由)。
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return target


def load_scan_runs(
    signal_date: date,
    *,
    out_dir: Path | str = _DEFAULT_DIR,
) -> list[dict]:
    """只读回读当日逐刷新快照; 缺失 → []; 损坏行跳过告警 (advisory 消费面)。"""
    compact = signal_date.strftime("%Y%m%d")
    target = Path(out_dir) / f"{compact}.scan_runs.jsonl"
    if not target.exists():
        return []
    try:
        raw = read_regular_bytes(target, max_bytes=_MAX_LOG_FILE_BYTES)
    except OSError:
        logger.warning("逐刷新快照读取失败, 按缺失处理: %s", target, exc_info=True)
        return []
    runs: list[dict] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("逐刷新快照损坏行跳过: %s", target)
            continue
        if isinstance(row, dict):
            runs.append(row)
    return runs


def refresh_flip_summary(runs: Iterable[dict]) -> dict:
    """跨刷新资格翻转统计 — 胜率噪声分量的第一手测量。

    admission 实际语义是跨刷新并集 (主日志 merge 保 eligible 行 + 计划幂等
    存活), court 先验却按单快照测量; ``union_minus_last_refresh`` 量化"早刷
    新纳入、末刷新不再支持"的噪声进入量, ``flipped_candidates`` 给出近阈值翻
    转规模 (2026-08-20 300009 事件型)。纯函数, 只消费 ``load_scan_runs`` 输
    出, 不读盘不写盘。
    """
    by_key: dict[tuple[str, str], list[dict]] = {}
    ordered = list(runs)
    for run in ordered:
        for cand in run.get("candidates") or []:
            if not isinstance(cand, dict):
                continue
            key = (str(cand.get("ticker", "")), str(cand.get("setup", "")))
            by_key.setdefault(key, []).append(cand)

    per_candidate: list[dict] = []
    for key, observations in sorted(by_key.items()):
        eligibilities = [bool(o.get("plan_eligible")) for o in observations]
        strengths = [
            float(o["trigger_strength"])
            for o in observations
            if isinstance(o.get("trigger_strength"), (int, float))
        ]
        per_candidate.append(
            {
                "ticker": key[0],
                "setup": key[1],
                "runs_seen": len(observations),
                "eligible_runs": sum(eligibilities),
                "flipped": len(set(eligibilities)) > 1,
                "strength_min": min(strengths) if strengths else None,
                "strength_max": max(strengths) if strengths else None,
            }
        )

    union_eligible = {
        key
        for key, observations in by_key.items()
        if any(bool(o.get("plan_eligible")) for o in observations)
    }
    last_eligible: set[tuple[str, str]] = set()
    if ordered:
        for cand in ordered[-1].get("candidates") or []:
            if isinstance(cand, dict) and bool(cand.get("plan_eligible")):
                last_eligible.add(
                    (str(cand.get("ticker", "")), str(cand.get("setup", "")))
                )
    return {
        "runs": len(ordered),
        "candidates_seen": len(by_key),
        "flipped_candidates": sum(1 for entry in per_candidate if entry["flipped"]),
        "union_minus_last_refresh": [
            {"ticker": key[0], "setup": key[1]}
            for key in sorted(union_eligible - last_eligible)
        ],
        "per_candidate": per_candidate,
    }


def audit_signal_log_coverage(
    sessions: Iterable[str],
    *,
    before: str,
    log_dir: Path | str = _DEFAULT_DIR,
) -> list[str]:
    """Return past signal days with no setup_output_log file (ascending).

    对抗审查修复 BUG-1 (2026-08-17): 2026-08-05..08-11 五个交易日 --daily-action
    未运行, 系统无任何检测 — 当期最强 setup 信号 (华正新材 08-05, strength 0.79)
    就此漏掉。判定语义: 日志文件存在 (含 0 字节 = 跑过但当日无信号) 即覆盖;
    文件不存在 = 当日从未运行。只审计严格早于 ``before`` 的信号日 — 当次运行
    会写 ``before`` 自己的日志, 不属于缺口。目录读取失败返回 [] (advisory,
    绝不阻断主流程)。
    """
    try:
        existing = {p.stem for p in Path(log_dir).glob("*.jsonl")}
    except OSError:
        return []
    return sorted(
        s
        for s in sessions
        if isinstance(s, str) and len(s) == 8 and s.isdigit() and s < before and s not in existing
    )


def warn_missing_signal_log_sessions(
    *,
    before: str,
    calendar_path: Path | str = _DEFAULT_CALENDAR,
    log_dir: Path | str = _DEFAULT_DIR,
    max_show: int = 10,
    lookback_sessions: int = 30,
) -> list[str]:
    """Read the authoritative trade calendar and warn about missing signal days.

    ``--auto`` (cache_refresh 收尾) 与 ``--daily-action`` (信号解析后) 各挂一次:
    两个哨点互为冗余, 任一在跑就能发现对方的断跑。告警窗口有界 (``before``
    往前 ``lookback_sessions`` 个交易日) — 权威日历从 2020 起算, 无界审计在
    从未运行的环境里会产生上千天的噪声。advisory only — 读取/解析失败静默
    返回 [], 不改变任何交易语义。
    """
    try:
        sessions = json.loads(Path(calendar_path).read_text(encoding="utf-8"))
        if not isinstance(sessions, list):
            return []
    except (OSError, json.JSONDecodeError):
        return []
    recent = [s for s in sessions if isinstance(s, str) and s < before][-lookback_sessions:]
    gaps = audit_signal_log_coverage(recent, before=before, log_dir=log_dir)
    if gaps:
        logger.warning(
            "⚠ 信号覆盖断层: 最近 %d 个交易日中 %d 个无 setup_output_log "
            "(--daily-action 未运行, 这些日的 setup 信号已永久丢失, 无法补录): %s%s",
            len(recent),
            len(gaps),
            ",".join(gaps[-max_show:]),
            " ..." if len(gaps) > max_show else "",
        )
    return gaps
