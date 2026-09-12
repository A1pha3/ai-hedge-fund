"""gap>5% 执行面判定包 CLI (R194 Op1) — 长期优化宪章杠杆 A 的最后一米。

证据 (T+1 高开>5% 入场子集期望 −4.04%, 聚合罚分两半同号 +5.63pp/+3.13pp,
跨强度 4/4 同向) 已在夜刷 ``winrate_payoff_decomposition`` 报告的
``gap_anatomy`` 块里, 但 owner 的"是否启动前向影子/政策化"决策输入此前要
逐字段拼读。本工具把读数一次装配成可审计决策包:

- 聚合负块: gap_anatomy.buckets 按档位标签分高开组 (≥ gap_high_threshold,
  标签 5~10%/>10%) 与低开组, 组合 n/E 与罚分 (low_e − high_e, 正 = 高开更差);
- R15 判据单一真值转发: split_half.judgable_count/consistent_count/
  verdict_hint **原文转发不重推导** (报告是判据的唯一事实源, 装配面自建
  第二套判据正是单一实现纪律要防的分叉);
- 跨强度同向: within_strength 逐桶 gap_high E < gap_low E 计数;
- 桶梯度表: 全部桶 n/E 原样列出。

使用纪律:
- 纯披露 (宪法 #2): 本工具不进入任何计划/评分/仓位/执行决策路径;
  判定汇总 ≠ 剔除决策 — 政策化属 owner gate, 且前向影子先行。
- fail-open 家族纪律 (R85/R115/R149/R181/R193 同族): 报告缺失/损坏/
  gap_anatomy 形状不符/桶畸形 → 对应读数 None + 缺失具名, 绝不猜测、
  绝不部分渲染; 渲染面畸形输入 → 整节省略不崩溃。
- 输出确定性: 载荷无墙钟 (as-of = 报告文件名日期段), 同输入同字节。

用法::

    uv run python scripts/gap_execution_pack.py [--reports-dir data/reports]
        [--out-dir data/reports] [--print]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.screening.offensive.gap_disclosure import (  # noqa: E402
    _HIGH_GAP_BUCKETS,
    GAP_HIGH_THRESHOLD,
    latest_decomposition_report,
    report_filename_date,
)

PACK_SCHEMA = "gap_execution_pack_v1"
DISCLAIMER = (
    "判定汇总 ≠ 剔除决策: gap 政策化属 owner gate, 且前向影子先行"
    "(纸面记录『本会买但跳过』的高开入场); 纯披露零策略语义变更 (宪法 #2)。"
)


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value == value
        and value not in (float("inf"), float("-inf"))
    )


def _combined(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """桶行组合: n 求和, E 按桶 n 加权 (任一桶缺 n/E → 整组 None, 不部分猜)。"""
    total_n = 0
    weighted = 0.0
    for row in rows:
        n = row.get("n")
        e = row.get("expectancy")
        if not _finite(n) or n <= 0 or not _finite(e):
            return None
        total_n += int(n)
        weighted += float(n) * float(e)
    if total_n <= 0:
        return None
    return {"n": total_n, "expectancy": weighted / total_n}


def aggregate_reading(gap_anatomy: object) -> dict[str, Any] | None:
    """聚合负块读数: 高开组 vs 低开组 (罚分 = low_e − high_e, 正 = 高开更差)。"""
    if not isinstance(gap_anatomy, dict):
        return None
    buckets = gap_anatomy.get("buckets")
    if not isinstance(buckets, list) or not buckets:
        return None
    high: list[dict[str, Any]] = []
    low: list[dict[str, Any]] = []
    for row in buckets:
        if not isinstance(row, dict):
            continue
        label = row.get("bucket")
        if label in _HIGH_GAP_BUCKETS:
            high.append(row)
        elif isinstance(label, str):
            low.append(row)
    high_combined = _combined(high)
    low_combined = _combined(low)
    if high_combined is None or low_combined is None:
        return None
    return {
        "gap_high_threshold": gap_anatomy.get("gap_high_threshold"),
        "high": high_combined,
        "low": low_combined,
        "penalty": low_combined["expectancy"] - high_combined["expectancy"],
    }


def within_strength_reading(gap_anatomy: object) -> dict[str, Any] | None:
    """跨强度同向计数: 逐桶 gap_high E < gap_low E (畸形桶跳过不计数)。"""
    if not isinstance(gap_anatomy, dict):
        return None
    rows = gap_anatomy.get("within_strength")
    if not isinstance(rows, list) or not rows:
        return None
    same_direction = 0
    judged = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        high_block = row.get("gap_high")
        low_block = row.get("gap_low")
        if not isinstance(high_block, dict) or not isinstance(low_block, dict):
            continue
        high_e = high_block.get("expectancy")
        low_e = low_block.get("expectancy")
        if not _finite(high_e) or not _finite(low_e):
            continue
        judged += 1
        if high_e < low_e:
            same_direction += 1
    if judged == 0:
        return None
    return {"buckets_total": judged, "buckets_high_worse": same_direction}


def conditional_reading(split_half: object) -> dict[str, Any] | None:
    """R15 判据单一真值转发 (字段原文, 不重推导); 形状不符 → None。"""
    if not isinstance(split_half, dict):
        return None
    verdict_hint = split_half.get("verdict_hint")
    if not isinstance(verdict_hint, str) or not verdict_hint:
        return None
    reading: dict[str, Any] = {"verdict_hint": verdict_hint}
    for key in ("judgable_count", "consistent_count"):
        value = split_half.get(key)
        if _finite(value):
            reading[key] = int(value)
    return reading


def bucket_gradient(gap_anatomy: object) -> list[dict[str, Any]]:
    """桶梯度表 (原样透传桶标签/n/E/CI; 畸形桶跳过)。"""
    if not isinstance(gap_anatomy, dict):
        return []
    buckets = gap_anatomy.get("buckets")
    if not isinstance(buckets, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in buckets:
        if not isinstance(row, dict):
            continue
        label = row.get("bucket")
        if not isinstance(label, str) or not _finite(row.get("n")):
            continue
        entry: dict[str, Any] = {
            "bucket": label,
            "n": int(row["n"]),
        }
        if _finite(row.get("expectancy")):
            entry["expectancy"] = float(row["expectancy"])
        if _finite(row.get("cluster_ci_low_90")):
            entry["cluster_ci_low_90"] = float(row["cluster_ci_low_90"])
        rows.append(entry)
    return rows


def assemble_pack(
    *,
    report_date: str,
    gap_anatomy: object,
) -> dict[str, Any]:
    """机械合取汇总 (判定 ≠ 剔除决策; 无墙钟, as-of = 报告日期)。"""
    aggregate = aggregate_reading(gap_anatomy)
    within = within_strength_reading(gap_anatomy)
    conditional = conditional_reading(
        gap_anatomy.get("split_half") if isinstance(gap_anatomy, dict) else None
    )
    payload: dict[str, Any] = {
        "schema": PACK_SCHEMA,
        "as_of": report_date,
        "gap_high_threshold": GAP_HIGH_THRESHOLD,
        "aggregate": aggregate,
        "within_strength": within,
        "conditional_r15": conditional,
        "bucket_gradient": bucket_gradient(gap_anatomy),
        "disclaimer": DISCLAIMER,
    }
    readings = [aggregate is not None, within is not None, conditional is not None]
    payload["readings_ready"] = sum(readings)
    payload["missing_readings"] = [
        name
        for name, ok in (
            ("aggregate", readings[0]),
            ("within_strength", readings[1]),
            ("conditional_r15", readings[2]),
        )
        if not ok
    ]
    return payload


def render_md(payload: object) -> str:
    """操作员面渲染 (fail-open: 畸形字段整节省略, 绝不崩溃)。"""
    if not isinstance(payload, dict):
        return ""
    as_of = payload.get("as_of")
    if not isinstance(as_of, str) or not as_of:
        return ""
    lines = [f"# gap>5% 执行面判定包（court 证据 as-of {as_of}）", ""]
    ready = payload.get("readings_ready")
    if _finite(ready):
        lines += [f"读数齐备：{int(ready)}/3", ""]
    else:
        return ""

    aggregate = payload.get("aggregate")
    lines += ["## 聚合负块（全期）", ""]
    if isinstance(aggregate, dict) and isinstance(aggregate.get("high"), dict) and isinstance(aggregate.get("low"), dict):
        high, low = aggregate["high"], aggregate["low"]

        def _pct(value: object) -> str:
            return f"{float(value) * 100:+.2f}%"

        if _finite(high.get("n")) and _finite(high.get("expectancy")) and _finite(low.get("n")) and _finite(low.get("expectancy")) and _finite(aggregate.get("penalty")):
            threshold = payload.get("gap_high_threshold")
            threshold_note = (
                f"{float(threshold):.0%}" if _finite(threshold) else "5%"
            )
            lines += [
                f"高开≥{threshold_note}：E {_pct(high['expectancy'])}（n={int(high['n'])}） · "
                f"低开<：E {_pct(low['expectancy'])}（n={int(low['n'])}） · "
                f"罚分 {_pct(aggregate['penalty'])}（正 = 高开更差）",
                "",
            ]
        else:
            lines += ["缺失：聚合读数不完整", ""]
    else:
        lines += ["缺失：聚合读数不完整", ""]

    within = payload.get("within_strength")
    lines += ["## 跨强度方向（gap_high vs gap_low，逐强度桶）", ""]
    if isinstance(within, dict) and _finite(within.get("buckets_total")) and _finite(within.get("buckets_high_worse")):
        lines += [
            f"高开更差桶数：{int(within['buckets_high_worse'])}/{int(within['buckets_total'])}",
            "",
        ]
    else:
        lines += ["缺失：跨强度读数不完整", ""]

    conditional = payload.get("conditional_r15")
    lines += ["## 分桶条件化（R15 判据 · 报告单一真值原文）", ""]
    if isinstance(conditional, dict) and isinstance(conditional.get("verdict_hint"), str):
        counts = ""
        if _finite(conditional.get("judgable_count")) and _finite(conditional.get("consistent_count")):
            counts = (
                f"（judgable {int(conditional['judgable_count'])} · "
                f"consistent {int(conditional['consistent_count'])}）"
            )
        lines += [f"{conditional['verdict_hint']}{counts}", ""]
    else:
        lines += ["缺失：R15 判据读数不完整", ""]

    gradient = payload.get("bucket_gradient")
    if isinstance(gradient, list) and gradient:
        lines += ["## 桶梯度（T+1 开盘缺口 → T+10 E）", ""]
        cells = []
        for row in gradient:
            if not isinstance(row, dict) or not isinstance(row.get("bucket"), str):
                continue
            if _finite(row.get("expectancy")) and _finite(row.get("n")):
                cells.append(f"{row['bucket']} {_pct(row['expectancy'])}（n={int(row['n'])}）")
        if cells:
            lines += [" · ".join(cells), ""]
    lines += ["## 纪律", "", DISCLAIMER, ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--out-dir", default="data/reports")
    parser.add_argument("--print", action="store_true", help="渲染 MD 到 stdout")
    args = parser.parse_args()

    found = latest_decomposition_report(Path(args.reports_dir))
    if found is None:
        print("gap_execution_pack: 无可用 decomposition 报告", file=sys.stderr)
        return 2
    report_path, report = found
    report_date = report_filename_date(report_path) or ""
    universes = report.get("universes") if isinstance(report, dict) else None
    gap_anatomy = (
        universes.get("production_aligned", {}).get("gap_anatomy")
        if isinstance(universes, dict)
        else None
    )
    payload = assemble_pack(report_date=report_date, gap_anatomy=gap_anatomy)

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = _PROJECT_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"gap_execution_pack_{report_date}.json"
    md_path = out_dir / f"gap_execution_pack_{report_date}.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_md(payload), encoding="utf-8")
    if args.print:
        sys.stdout.write(render_md(payload))
    print(f"pack: {json_path}")
    print(f"pack: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
