"""预注册强度阈值触发器稳定账本的只读取面 (R85 Op1)。

单一实现: 判定快照的**落账**在 ``scripts/winrate_payoff_decomposition.py``
(数据增长耦合: court 重建 → 分解刷新 → 账本追加, R84); 本模块提供跨消费者
共享的读取面 — ``--daily-action`` 操作员视图经此读取触发器当前状态,
不复制加载/计数逻辑。分解脚本从本模块导入并 re-export (兼容既有测试)。

诚实边界:
- 本模块只读账本并计数, 不做『稳定』判定 — 连亮多少次才算稳定 (阈值 K)
  属 owner 预注册范围 (AGENTS.md 项 1);
- 账本缺失/损坏行 advisory 跳过 (诊断面语义), 不假装有判定记录;
- 条件/合取的判定语义 (lit/armed) 由落账侧冻结, 读取侧不重推导 — 账本里
  是什么就披露什么 (与『配置不是权限』纪律一致: 披露 ≠ 任何行为改变)。
"""

from __future__ import annotations

import json
from pathlib import Path

LEDGER_PATH = Path("data/reports/threshold_trigger_ledger.jsonl")


def _resolve(ledger_path: Path | str | None) -> Path:
    """None → 模块默认路径 (调用方可 monkeypatch LEDGER_PATH 注入测试账本)。"""
    return Path(ledger_path) if ledger_path is not None else LEDGER_PATH


def load_trigger_ledger(ledger_path: Path | str | None = None) -> list[dict]:
    """读触发器账本, 按日期升序; 损坏行 advisory 跳过 (诊断面语义)。

    兼容两种记录形态: R81 旧形态 (无 ``court`` 字段) 与 R84 起带 court
    绑定的新形态 — 读取侧对字段不加严, 披露面自行判空。
    """
    path = _resolve(ledger_path)
    records: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return records
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("date"):
            records.append(rec)
    return sorted(records, key=lambda r: str(r["date"]))


def trigger_stability(records: list[dict]) -> dict[str, object]:
    """连亮计数 (R81 Op2 引入; R85 Op2 修 max 语义): 两族字段语义 —
    ``condition_*_streak`` / ``conjunction_streak`` = **最新锚定**连亮 (从最新
    记录向前数, 未点亮/未判定断链 — 保守: 未知不延长连亮);
    ``max_conjunction_streak`` = **全历史**最大连续武装段 (独立正向扫描,
    断链不吞历史 — R85 Op2 修复: 旧实现把 max 收敛进最新锚定循环, 该值
    恒等于当前连亮, 与字段名/MD 披露『历史最多』不符)。
    只计数不判定 — 『稳定』阈值属 owner。
    """
    dates = [str(r.get("date")) for r in records]
    out: dict[str, object] = {
        "records": len(records),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "condition_1_streak": 0,
        "condition_1_last_lit": None,
        "condition_2_streak": 0,
        "condition_2_last_lit": None,
        "conjunction_streak": 0,
        "conjunction_last_armed": None,
        "max_conjunction_streak": 0,
    }
    if not records:
        return out
    latest = records[-1]
    c1, c2 = latest.get("condition_1") or {}, latest.get("condition_2") or {}
    out["condition_1_last_lit"] = c1.get("lit")
    out["condition_2_last_lit"] = c2.get("lit")
    out["conjunction_last_armed"] = latest.get("conjunction_armed")
    run_c1 = run_c2 = run_and = True
    for rec in reversed(records):
        r1 = rec.get("condition_1") or {}
        r2 = rec.get("condition_2") or {}
        lit1 = r1.get("lit") is True
        lit2 = r2.get("lit") is True
        armed = rec.get("conjunction_armed") is True
        if run_c1 and lit1:
            out["condition_1_streak"] = int(out["condition_1_streak"]) + 1
        else:
            run_c1 = False
        if run_c2 and lit2:
            out["condition_2_streak"] = int(out["condition_2_streak"]) + 1
        else:
            run_c2 = False
        if run_and and armed:
            out["conjunction_streak"] = int(out["conjunction_streak"]) + 1
        else:
            run_and = False
    # 全历史最大武装段: 独立正向扫描, 与最新锚定循环解耦
    historical_max = 0
    current_run = 0
    for rec in records:
        if rec.get("conjunction_armed") is True:
            current_run += 1
            historical_max = max(historical_max, current_run)
        else:
            current_run = 0
    out["max_conjunction_streak"] = historical_max
    return out


__all__ = ["LEDGER_PATH", "load_trigger_ledger", "trigger_stability"]
