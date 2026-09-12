"""gap 前向影子配对读数包 (R197 Op1) — 宪章杠杆 A 政策化评估的机械输入。

R196 交付的影子记录机 (``gap_shadow.jsonl`` sidecar) 持续积累 T+1 开盘 gap
归属事实; 本工具把它与 paper journal 的成熟 EXIT (realized P&L) 装配成
影子窗配对读数, 回答 owner 的唯一决策问题: 「影子期内, 被影子标记为
would-skip 的高开入场, 相对其余入场, 实际表现差多少?」

- 配对读数: would_skip 成员 vs keep 成员在成熟 EXIT 上的 n/E/胜率,
  罚分 = E_keep − E_skip (正 = 跳过高开有利; 镜像 gap_execution_pack
  罚分方向约定);
- 真相来源单一实现: realized P&L 从 close_matured 写入 EXIT reasoning 的
  ``realized=+X.XX%`` 严格解析, 不可解析具名披露并排除 —— 绝不重算第二套
  P&L; would_skip 取自记录预注册字段不重算 (载入面语义校验在 gap_shadow
  单一实现, R196 Op2);
- 键位对账: 影子记录无 BUY 匹配 (orphan) / BUY 无影子记录 (unshadowed,
  未到期未观测) 具名计数 —— sidecar 与 journal 的分歧不再无痕;
- 纪律面: 不可观测态 (would_skip=None) 排除并按 status 具名; 未成熟
  (无 EXIT) 排除计数; 任一组 n<30 只披露不判定; 零样本组 mean=None
  不伪造; 阈值混存按 threshold 分组披露 (预注册演化可见)。

使用纪律:
- 纯披露 (宪法 #2): 只读装配, 不进入任何计划/评分/仓位/执行决策路径;
  影子读数 ≠ 政策决策 — 政策化属 owner gate。
- fail-open 家族纪律 (R85/R115/R149/R181/R193/R194 同族): 渲染面畸形
  输入 → 整节省略不崩溃。
- 输出确定性: 载荷无墙钟 (窗口 = 记录真相日期), 同输入同字节。

用法::

    uv run python scripts/gap_shadow_pack.py [--journal-dir data/paper_trading]
        [--out-dir data/reports] [--print]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.screening.offensive.gap_shadow import (  # noqa: E402
    GAP_SHADOW_FILENAME,
    load_shadow_entries,
    shadow_keys,
)

MIN_N_FOR_JUDGMENT = 30

_REALIZED_RE = re.compile(r"realized=([+-]\d+\.\d{2})%")

DISCLAIMER = (
    "纯披露 (宪法 #2): 影子配对读数 ≠ 政策决策。n<30 只披露不判定; "
    "影子期数据齐备后的政策化属 owner gate (前向配对证据 + 预注册纪律)。"
)


class GapShadowJournalReadError(Exception):
    """journal.jsonl 结构损坏 (读面 fail-closed, 不猜测)。"""


def parse_exit_realized(reasoning: Any) -> float | None:
    """从 EXIT reasoning 严格解析 close_matured 记录的 realized 小数; 不可解析 → None."""
    if not isinstance(reasoning, str):
        return None
    m = _REALIZED_RE.search(reasoning)
    if m is None:
        return None
    return float(m.group(1)) / 100.0


def load_journal_actions(journal_path: Path | str) -> list[dict[str, Any]]:
    """直读 journal.jsonl (jsonl 行); 文件缺失 → []; 损坏行 → 类型化异常."""
    p = Path(journal_path)
    if not p.exists():
        return []
    actions: list[dict[str, Any]] = []
    for line_no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GapShadowJournalReadError(f"journal_corrupt: line {line_no}: {exc}") from exc
        if not isinstance(rec, dict):
            raise GapShadowJournalReadError(f"journal_corrupt: line {line_no}: not an object")
        actions.append(rec)
    return actions


def _bucket(pnls: list[float]) -> dict[str, Any]:
    wins = sum(1 for v in pnls if v > 0)
    return {
        "n": len(pnls),
        "mean": (sum(pnls) / len(pnls)) if pnls else None,
        "win_rate": (wins / len(pnls)) if pnls else None,
    }


def assemble_shadow_reading(
    entries: list[dict[str, Any]],
    journal_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """装配影子窗配对读数 (纯装配, 不写盘; 恒等式见各具名计数)."""
    buys: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in journal_actions:
        if str(rec.get("action", "")) != "BUY":
            continue
        key = (str(rec.get("date", "")), str(rec.get("ticker", "")))
        if key in buys:
            continue  # 历史重复 BUY 只取首条 (镜像 close_matured 口径)
        buys[key] = rec
    exits: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in journal_actions:
        if str(rec.get("action", "")) != "EXIT":
            continue
        key = (str(rec.get("date", "")), str(rec.get("ticker", "")))
        if key not in exits:
            exits[key] = rec

    skip_pnls: list[float] = []
    keep_pnls: list[float] = []
    counts = {
        "orphan_entries": 0,       # 影子记录无 BUY 匹配
        "unshadowed_buys": 0,      # BUY 无影子记录 (未到期未观测)
        "pending": 0,              # 有影子记录但未成熟 (无 EXIT)
        "unparseable_exits": 0,    # EXIT realized 不可解析 (排除, 不伪造)
        "unobservable": 0,         # would_skip=None (按 status 分组另计)
    }
    unobservable_by_status: dict[str, int] = {}
    thresholds: dict[str, int] = {}

    entry_keys = shadow_keys(entries)
    for e in entries:
        thresholds[str(e.get("threshold"))] = thresholds.get(str(e.get("threshold")), 0) + 1
        if e.get("would_skip") is None:
            counts["unobservable"] += 1
            status = str(e.get("gap_status"))
            unobservable_by_status[status] = unobservable_by_status.get(status, 0) + 1
            continue
        key = (str(e.get("signal_date", "")), str(e.get("ticker", "")))
        if key not in buys:
            counts["orphan_entries"] += 1
            continue
        exit_rec = exits.get(key)
        if exit_rec is None:
            counts["pending"] += 1
            continue
        realized = parse_exit_realized(exit_rec.get("reasoning"))
        if realized is None:
            counts["unparseable_exits"] += 1
            continue
        (skip_pnls if e["would_skip"] else keep_pnls).append(realized)

    for key in buys:
        if key not in entry_keys:
            counts["unshadowed_buys"] += 1

    skip_bucket = _bucket(skip_pnls)
    keep_bucket = _bucket(keep_pnls)
    penalty = (
        keep_bucket["mean"] - skip_bucket["mean"]
        if keep_bucket["mean"] is not None and skip_bucket["mean"] is not None
        else None
    )
    judgable = skip_bucket["n"] >= MIN_N_FOR_JUDGMENT and keep_bucket["n"] >= MIN_N_FOR_JUDGMENT
    dates = sorted({str(e.get("signal_date", "")) for e in entries if e.get("signal_date")})

    return {
        "window": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
        "counts": counts,
        "unobservable_by_status": unobservable_by_status,
        "thresholds": thresholds,
        "skip": skip_bucket,
        "keep": keep_bucket,
        "penalty_keep_minus_skip": penalty,
        "min_n_for_judgment": MIN_N_FOR_JUDGMENT,
        "judgable": judgable,
        "verdict_hint": (
            "影子窗配对样本达判读门槛 — 读数供 owner 政策化评估参考"
            if judgable
            else f"n<{MIN_N_FOR_JUDGMENT}: 只披露不判定 (样本不支持任何政策结论)"
        ),
    }


def _pct(v: Any) -> str:
    return f"{v:+.2%}" if isinstance(v, (int, float)) else "--"


def render_md(reading: Any) -> str:
    """渲染决策包 MD; 畸形输入整节省略不崩溃 (fail-open 家族纪律)."""
    if not isinstance(reading, dict):
        return "gap_shadow_pack: reading 形状不符, 无内容可渲染\n"
    lines = ["# gap 前向影子配对读数包", ""]
    window = reading.get("window") if isinstance(reading.get("window"), dict) else {}
    if isinstance(window, dict) and window.get("start") and window.get("end"):
        lines += [f"影子窗: {window['start']} → {window['end']}", ""]
    counts = reading.get("counts") if isinstance(reading.get("counts"), dict) else None
    if counts:
        parts = [f"{name} {counts[name]}" for name in
                 ("orphan_entries", "unshadowed_buys", "pending", "unparseable_exits", "unobservable")
                 if isinstance(counts.get(name), int)]
        if parts:
            lines += [f"键位对账: {' · '.join(parts)}", ""]
    skip = reading.get("skip") if isinstance(reading.get("skip"), dict) else {}
    keep = reading.get("keep") if isinstance(reading.get("keep"), dict) else {}
    if isinstance(skip, dict) and isinstance(keep, dict):
        lines += [
            "| 组 | n | E[realized] | 胜率 |",
            "|---|---|---|---|",
            f"| would-skip (高开>阈值) | {skip.get('n', '--')} | {_pct(skip.get('mean'))} | {_pct(skip.get('win_rate'))} |",
            f"| keep (其余) | {keep.get('n', '--')} | {_pct(keep.get('mean'))} | {_pct(keep.get('win_rate'))} |",
            "",
        ]
    penalty = reading.get("penalty_keep_minus_skip")
    if isinstance(penalty, (int, float)):
        lines += [f"罚分 (E_keep − E_skip): {penalty:+.2%}  (正 = 跳过高开有利)", ""]
    if isinstance(reading.get("thresholds"), dict) and reading["thresholds"]:
        th = " · ".join(f"threshold={k}: {v} 条" for k, v in sorted(reading["thresholds"].items()))
        lines += [f"阈值分布 (预注册溯源): {th}", ""]
    if isinstance(reading.get("verdict_hint"), str):
        lines += [f"判定: {reading['verdict_hint']}", ""]
    lines += ["## 纪律", "", DISCLAIMER, ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--journal-dir", default="data/paper_trading")
    parser.add_argument("--out-dir", default="data/reports")
    parser.add_argument("--print", action="store_true", help="渲染 MD 到 stdout")
    args = parser.parse_args()

    journal_dir = Path(args.journal_dir)
    if not journal_dir.is_absolute():
        journal_dir = _PROJECT_ROOT / journal_dir
    entries = load_shadow_entries(journal_dir / GAP_SHADOW_FILENAME)
    journal_actions = load_journal_actions(journal_dir / "journal.jsonl")
    payload = assemble_shadow_reading(entries, journal_actions)

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = _PROJECT_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    window_end = (payload.get("window") or {}).get("end") or "unknown"
    json_path = out_dir / f"gap_shadow_pack_{window_end}.json"
    md_path = out_dir / f"gap_shadow_pack_{window_end}.md"
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
