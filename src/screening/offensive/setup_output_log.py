"""Live BTST setup-output logger — out-of-sample accumulation.

Every ``--daily-action`` run appends the full scanned candidate set (both
plan-eligible and filtered-out) with the setup's structured diagnostics
(``trigger_strength``, fund flow, pre-runup, industry, thresholds) to a per-day
JSONL file. Over time this accumulates a real out-of-sample record of the FULL
setup's live outputs so cross-cycle robustness can eventually be validated on
genuine forward data (the retroactive replay is blocked by thin historical
fund-flow/industry depth).

Design:
  - one file per signal day (``YYYYMMDD.jsonl``), atomically overwritten on
    rerun → idempotent, never duplicates;
  - append-only across days; forward returns are joined later from price_cache;
  - never raises into the trading path (best-effort observation).
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
_DEFAULT_DIR = Path("data/reports/setup_output_log")
_DEFAULT_CALENDAR = Path("data/reports/trade_calendar.json")

logger = logging.getLogger(__name__)


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


def log_setup_outputs(
    signal_date: date,
    candidates: Iterable[Any],
    blocked: Iterable[Any],
    *,
    regime: str = "unknown",
    out_dir: Path | str = _DEFAULT_DIR,
) -> Path:
    """Persist the full scanned setup output for ``signal_date`` (idempotent).

    ``candidates`` are the plan-eligible actions; ``blocked`` are the
    filtered-out / degraded ones. Returns the written per-day file path.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    compact = signal_date.strftime("%Y%m%d")
    logged_at = datetime.now(timezone.utc).isoformat()

    records = [
        _record(a, signal_date=compact, regime=regime, plan_eligible=True, logged_at=logged_at)
        for a in candidates
    ] + [
        _record(a, signal_date=compact, regime=regime, plan_eligible=False, logged_at=logged_at)
        for a in blocked
    ]

    payload = "\n".join(
        json.dumps(rec, ensure_ascii=False, allow_nan=False, sort_keys=True) for rec in records
    )
    if payload:
        payload += "\n"

    target = out / f"{compact}.jsonl"
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
