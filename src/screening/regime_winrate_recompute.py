"""NS-5 daily scheduling 重算 — regime 历史胜率从 tracking_history 重算.

C234 (2026-06-28) 加了 as_of + staleness 诚实披露, 但 "重算" 半环缺失 —
硬编码 ``REGIME_HISTORICAL_WINRATES`` / ``REGIME_MULTIHORIZON_MEDIANS`` 仍
是 2026-06-25 v2 扩样本回测值, owner 因子改动 (C220-C236) 后已 stale.

本模块补 "重算" 半环:
- :func:`compute_regime_historical_winrates_from_records` — 纯函数, 从
  tracking_history records + date→regime map 重算 per-regime × per-horizon
  winrate/avg/median, 输出结构匹配 ``REGIME_HISTORICAL_WINRATES`` /
  ``REGIME_MULTIHORIZON_MEDIANS`` (让 owner 可直接替换硬编码值).
- :func:`build_date_to_regime_map` — 从 ``data/reports/auto_screening_*.json``
  报告构建 date→regime 映射 (each report has ``date`` +
  ``market_state.regime_gate_level``).

设计原则:
- **纯函数 + loader 分离**: 重算逻辑无 I/O 副作用, loader 单独处理 JSON 读取.
  测试用合成 records + 合成 map 即可, 不需真实报告.
- **结构匹配**: 输出 dict 结构与 ``REGIME_HISTORICAL_WINRATES`` /
  ``REGIME_MULTIHORIZON_MEDIANS`` 一致, owner 可直接 copy-paste 替换.
- **min_samples gate**: n < min_samples 的 regime 不入 result (insufficient),
  避免小样本污染.
- **case-insensitive regime**: 归一化到小写 ('Crisis' → 'crisis'), 与
  ``compute_regime_winrate_summary`` 一致.
- **unknown regime skipped**: 非 {normal, crisis, risk_off} 值跳过, 不污染 result.

CLI 入口: ``--refresh-regime-winrates`` (在 main.py), 串联两者 + 输出 JSON
供 owner 审阅/替换. launchd daily scheduling 由 owner 部署 (autodev 不部署).
"""
from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 合法 regime 值 (与 regime_winrate.REGIME_HISTORICAL_WINRATES keys 一致)
_VALID_REGIMES: frozenset[str] = frozenset({"normal", "crisis", "risk_off"})

# 默认 horizons — 匹配 REGIME_MULTIHORIZON_MEDIANS 结构 (t5/t10/t15/t20/t25/t30)
_DEFAULT_HORIZONS: tuple[str, ...] = ("t5", "t10", "t15", "t20", "t25", "t30")

# horizon key → tracking_history field name 映射
_HORIZON_TO_FIELD: dict[str, str] = {
    "t5": "next_5day_return",
    "t10": "next_10day_return",
    "t15": "next_15day_return",
    "t20": "next_20day_return",
    "t25": "next_25day_return",
    "t30": "next_30day_return",
}

# 默认 min_samples=0 (无 gate) — 纯函数让 owner 自决阈值; CLI 入口可显式传
# min_samples=10 以过滤小样本 (与 regime_winrate "扩样本后 ~119" 同门槛).
# 测试用合成 records 多为 n<10, 默认无 gate 让小样本 case 直接走通.
_DEFAULT_MIN_SAMPLES: int = 0


@dataclass
class RegimeRecomputeResult:
    """regime 历史胜率重算结果 (匹配 REGIME_HISTORICAL_WINRATES +
    REGIME_MULTIHORIZON_MEDIANS 结构).

    Attributes:
        regime_winrates: ``{regime: {winrate, avg_return, median_return,
            sample_count}}`` — T+30 口径, 匹配 REGIME_HISTORICAL_WINRATES.
            winrate: 0-1 (T+30 正收益比例); avg_return/median_return: 百分点.
        regime_multihorizon_medians: ``{regime: {horizon: {median, winrate, n}}}``
            — per-horizon (t5/t10/.../t30), 匹配 REGIME_MULTIHORIZON_MEDIANS.
        as_of: 重算时点 (date.today() 默认; 测试可注入).
        total_records: 输入 records 总数.
        matched_records: 成功匹配到 regime 的 records 数 (剩余的 recommended_date
            不在 date_to_regime 中, 跳过).
    """

    regime_winrates: dict[str, dict[str, Any]] = field(default_factory=dict)
    regime_multihorizon_medians: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    as_of: date = field(default_factory=date.today)
    total_records: int = 0
    matched_records: int = 0

    def to_dict(self) -> dict[str, Any]:
        """序列化到 JSON-able dict (CLI 输出 JSON 用).

        ``as_of`` 转 ISO 字符串 (``YYYY-MM-DD``) 以支持 ``json.dumps``.
        """
        return {
            "regime_winrates": self.regime_winrates,
            "regime_multihorizon_medians": self.regime_multihorizon_medians,
            "as_of": self.as_of.isoformat(),
            "total_records": self.total_records,
            "matched_records": self.matched_records,
        }


def _optional_float(value: Any) -> float | None:
    """安全转 float; None/NaN/Inf/非数值 → None."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    if result in (float("inf"), float("-inf")):
        return None
    return result


def _compute_stats(returns: list[float]) -> dict[str, Any]:
    """算 winrate/avg/median (returns 非空, 已过滤 None)."""
    n = len(returns)
    wins = sum(1 for r in returns if r > 0)
    return {
        "winrate": wins / n if n > 0 else 0.0,
        "avg_return": sum(returns) / n if n > 0 else 0.0,
        "median_return": statistics.median(returns) if n > 0 else 0.0,
        "sample_count": n,
    }


def _compute_multihorizon_stats(returns: list[float]) -> dict[str, Any]:
    """算 per-horizon median/winrate/n (returns 非空, 已过滤 None)."""
    n = len(returns)
    wins = sum(1 for r in returns if r > 0)
    return {
        "median": statistics.median(returns) if n > 0 else 0.0,
        "winrate": wins / n if n > 0 else 0.0,
        "n": n,
    }


def compute_regime_historical_winrates_from_records(
    records: list[dict[str, Any]],
    date_to_regime: dict[str, str],
    *,
    horizons: tuple[str, ...] = _DEFAULT_HORIZONS,
    min_samples: int = _DEFAULT_MIN_SAMPLES,
    as_of: date | None = None,
) -> RegimeRecomputeResult:
    """从 tracking_history records + date→regime map 重算 regime 历史胜率.

    纯函数: 无 I/O, 无副作用. 测试用合成 records + 合成 map 即可.

    Args:
        records: tracking_history record dict 列表. 每条至少含
            ``recommended_date`` (YYYYMMDD str) + 各 horizon return 字段
            (``next_5day_return`` / ``next_10day_return`` / ... / ``next_30day_return``).
            缺失 return 字段视为该 horizon 未 mature (跳过该 horizon).
        date_to_regime: ``{YYYYMMDD: regime}`` 映射, regime ∈
            {normal, crisis, risk_off}. 大小写不敏感 (归一化到小写).
            非 ``_VALID_REGIMES`` 值跳过.
        horizons: 计算 horizons (默认 t5/t10/t15/t20/t25/t30).
        min_samples: regime 最低样本数门槛. n < min_samples 的 regime 不入
            result (insufficient). 默认 0 (无 gate, 让 owner 自决阈值).
        as_of: 重算时点. ``None`` → ``date.today()`` (生产路径).
            测试可注入固定日期以避免时间漂移.

    Returns:
        :class:`RegimeRecomputeResult` — regime_winrates (T+30 口径, 匹配
        REGIME_HISTORICAL_WINRATES) + regime_multihorizon_medians (匹配
        REGIME_MULTIHORIZON_MEDIANS) + as_of + total_records + matched_records.
    """
    if as_of is None:
        as_of = date.today()

    total = len(records)
    if total == 0 or not date_to_regime:
        return RegimeRecomputeResult(
            as_of=as_of,
            total_records=total,
            matched_records=0,
        )

    # 归一化 date_to_regime: 大小写不敏感 + 过滤非法 regime
    normalized_map: dict[str, str] = {}
    for d, r in date_to_regime.items():
        regime_lower = str(r or "").strip().lower()
        if regime_lower in _VALID_REGIMES:
            normalized_map[str(d)] = regime_lower

    # 按 regime 分组 records
    regime_records: dict[str, list[dict[str, Any]]] = {r: [] for r in _VALID_REGIMES}
    matched = 0
    for rec in records:
        rec_date = str(rec.get("recommended_date") or "")
        regime = normalized_map.get(rec_date)
        if regime is None:
            continue  # 无 regime 映射或非法 regime → 跳过
        regime_records[regime].append(rec)
        matched += 1

    # 算 per-regime stats
    regime_winrates: dict[str, dict[str, Any]] = {}
    regime_multihorizon_medians: dict[str, dict[str, dict[str, Any]]] = {}

    for regime, recs in regime_records.items():
        if not recs:
            continue  # 该 regime 无任何 matched record → 不入 result (避免空样本污染)
        if len(recs) < min_samples:
            continue  # insufficient, 不入 result

        # T+30 口径 (regime_winrates)
        t30_field = _HORIZON_TO_FIELD["t30"]
        t30_returns = [
            r for r in (_optional_float(rec.get(t30_field)) for rec in recs)
            if r is not None
        ]
        if not t30_returns:
            continue  # T+30 全部 None (records 全未 mature) → 跳过该 regime
        if len(t30_returns) < min_samples:
            # T+30 mature 样本不足 (records 多数未 mature) → 跳过该 regime
            # 避免 sample_count=100 但 t30_returns=2 的误导
            continue

        regime_winrates[regime] = _compute_stats(t30_returns)

        # per-horizon (regime_multihorizon_medians)
        multi: dict[str, dict[str, Any]] = {}
        for horizon in horizons:
            field_name = _HORIZON_TO_FIELD.get(horizon)
            if field_name is None:
                continue
            horizon_returns = [
                r for r in (_optional_float(rec.get(field_name)) for rec in recs)
                if r is not None
            ]
            if not horizon_returns:
                continue  # 该 horizon 全 None → 不入 multi
            if len(horizon_returns) < min_samples:
                # 该 horizon 样本不足 → 不入 multi (与 REGIME_MULTIHORIZON_MEDIANS
                # 只含成熟 horizon 的语义一致)
                continue
            multi[horizon] = _compute_multihorizon_stats(horizon_returns)

        if multi:  # 至少一个 horizon 有足够样本才入 result
            regime_multihorizon_medians[regime] = multi

    return RegimeRecomputeResult(
        regime_winrates=regime_winrates,
        regime_multihorizon_medians=regime_multihorizon_medians,
        as_of=as_of,
        total_records=total,
        matched_records=matched,
    )


def build_date_to_regime_map(reports_dir: Path) -> dict[str, str]:
    """从 ``data/reports/auto_screening_*.json`` 构建 date→regime 映射.

    每个 auto_screening 报告含 ``date`` (YYYYMMDD str) +
    ``market_state.regime_gate_level`` (normal/crisis/risk_off). 缺失
    regime_gate_level 时默认 'normal' (与 market_state_helpers 一致).

    损坏 JSON / 缺 date 字段的报告 → 跳过 (不 raise). 非 auto_screening_*.json
    文件忽略.

    Args:
        reports_dir: 报告目录 (通常 ``data/reports/``).

    Returns:
        ``{YYYYMMDD: regime}`` 映射, regime 已归一化到小写.
    """
    if not reports_dir.exists():
        logger.warning("regime_winrate_recompute: reports_dir 不存在: %s", reports_dir)
        return {}

    mapping: dict[str, str] = {}
    for report_path in sorted(reports_dir.glob("auto_screening_*.json")):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "regime_winrate_recompute: 跳过损坏报告 %s: %s",
                report_path.name,
                exc,
            )
            continue

        if not isinstance(payload, dict):
            continue

        report_date = payload.get("date")
        if not report_date:
            continue

        market_state = payload.get("market_state") or {}
        regime = str(
            market_state.get("regime_gate_level") or "normal"
        ).strip().lower()

        mapping[str(report_date)] = regime

    return mapping


def run_refresh_cli(
    *,
    reports_dir: Path | None = None,
    output_path: Path | None = None,
    min_samples: int = 10,
) -> int:
    """CLI runner — 串联 loader + 纯函数 + JSON 输出.

    供 dispatcher ``--refresh-regime-winrates`` 调用. 流程:
        1. resolve reports_dir (默认 ``data/reports``)
        2. load tracking_history.json records
        3. build date→regime map from auto_screening_*.json
        4. compute regime winrates (默认 min_samples=10 过滤小样本)
        5. output JSON to stdout or ``output_path``

    Args:
        reports_dir: 报告目录 (含 auto_screening_*.json + tracking_history.json).
            ``None`` → 从 cwd 向上查找 (与 ``resolve_report_dir`` 一致).
        output_path: 输出 JSON 文件路径. ``None`` → stdout.
        min_samples: regime 最低样本数门槛. 默认 10 (生产口径).

    Returns:
        0 成功; 1 输入缺失 (无 tracking_history 或 reports dir).
    """
    # 延迟导入避免循环依赖
    from src.screening.consecutive_recommendation import (
        load_tracking_history,
        resolve_report_dir,
    )

    if reports_dir is None:
        reports_dir = resolve_report_dir()
    if not reports_dir.exists():
        print(f"[RefreshRegimeWinrates] reports_dir 不存在: {reports_dir}")
        return 1

    records = load_tracking_history(reports_dir)
    if not records:
        print(
            f"[RefreshRegimeWinrates] tracking_history.json 为空或缺失 "
            f"(reports_dir={reports_dir})"
        )
        return 1

    date_to_regime = build_date_to_regime_map(reports_dir)
    if not date_to_regime:
        print(
            f"[RefreshRegimeWinrates] 未从 auto_screening_*.json 构建到 date→regime "
            f"映射 (reports_dir={reports_dir})"
        )
        return 1

    result = compute_regime_historical_winrates_from_records(
        records=records,
        date_to_regime=date_to_regime,
        min_samples=min_samples,
    )
    payload = result.to_dict()
    payload["min_samples_threshold"] = min_samples
    payload["reports_dir"] = str(reports_dir)

    json_str = json.dumps(payload, ensure_ascii=False, indent=2)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_str + "\n", encoding="utf-8")
        print(
            f"[RefreshRegimeWinrates] 已写入 {output_path} "
            f"(total={result.total_records}, matched={result.matched_records}, "
            f"regimes={list(result.regime_winrates.keys())})"
        )
    else:
        print(json_str)
    return 0


__all__ = [
    "RegimeRecomputeResult",
    "compute_regime_historical_winrates_from_records",
    "build_date_to_regime_map",
    "run_refresh_cli",
]
