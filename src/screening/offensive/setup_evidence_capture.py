"""发布侧 setup 信号证据捕获 (--daily-action 缺席日的覆盖保护, R160 Op1)。

背景: ``setup_output_log`` 的写入口此前只在 ``--daily-action`` dispatcher —
操作员漏跑该命令的晚上, 即使 ``--auto`` 已完成缓存刷新并发布就绪清单, 信号证据
也不留痕 (2026-07-30~08-11 七个交易日覆盖断层, 其中六天 ``--auto`` 已跑)。
历史不可补录: 生产 loader 对 canonical 重验 PIT 指纹需当日缓存, 而缓存已被后续
刷新覆写 (丢失日实测: 4 天 canonical 缺失 / 3 天空扫描); 发布点正是缓存仍新鲜、
重验可过的唯一时刻, 因此捕获必须接在发布之后。

安全性: 纯证据捕获 — 不创建计划、不打开 LedgerRepository、无任何交易语义;
经生产 loader 重读 canonical (与 ``--daily-action`` 同一读路径, 授权≡验证),
以同一 ``scan_from_verified_snapshot`` 确定性重扫, 经同一 ``log_setup_outputs``
合并写入器落盘 — 合并不变量保证既有 ``plan_eligible`` 行不会被晚到的非
eligible 重扫覆盖, 晚间 ``--daily-action`` 重跑按 ``(ticker, setup)`` 键确定性
折叠, 其 fail-closed 写入面逐字节不变。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from src.screening.offensive.daily_action import scan_from_verified_snapshot
from src.screening.offensive.daily_action_snapshot import (
    load_verified_daily_action_snapshot,
)
from src.screening.offensive.setup_output_log import log_setup_outputs

logger = logging.getLogger(__name__)


def plan_layer_blocked_candidates(scan: Any) -> tuple:
    """panel 层被拒候选单一实现 (主日志与 scan_run 刷新快照共用): detect 前的
    数据契约拒票 (candidate_not_plan_eligible) 不入任何证据行 — 样本外对照组
    纯度政策的单一表达, 两个写证据的调用点不得各自内联漂移。"""
    return tuple(
        b
        for b in getattr(scan, "blocked_candidates", ()) or ()
        if getattr(b, "reason", "") != "candidate_not_plan_eligible"
    )


def capture_setup_evidence_for_publication(
    signal_date: date,
    *,
    reports_dir: Path | str,
    data_dir: Path | str,
    out_dir: Path | str | None = None,
) -> Path | None:
    """就绪清单发布后落 setup 信号证据行; 返回写入路径或 ``None``。

    canonical 缺失/验证失败返回 ``None`` (调用方 advisory 记录) — 发布面产出
    attempt 而非 healthy canonical 时本就没有可消费的信号事实。捕获失败由调用
    方兜底: 此时无计划在座, advisory WARNING 与容量/漏斗/scan_run 的 fail-open
    同族; ``--daily-action`` 面的 fail-closed (写失败阻断新计划) 语义不变。
    """
    verified = load_verified_daily_action_snapshot(
        signal_date, reports_dir=Path(reports_dir), data_dir=Path(data_dir)
    )
    snapshot = verified.snapshot if verified is not None else None
    if snapshot is None:
        return None
    scan = scan_from_verified_snapshot(snapshot)
    return log_setup_outputs(
        snapshot.signal_date,
        scan.candidates,
        plan_layer_blocked_candidates(scan),
        regime=snapshot.regime,
        out_dir=out_dir,
    )
