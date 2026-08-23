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
