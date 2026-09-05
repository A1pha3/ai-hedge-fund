"""owner K 预注册决策包 CLI (R129 Op2) — 强度 + 日层两族统一操作面。

R112-R115 (强度族) 与 R129 Op1 (日层族) 建齐了 K 预注册的机械判定机器
(注册文件 tri-state 装载 / 反回溯观测日志 / 资格窗口判定 / 单一事实源
披露), 但 owner 的预注册动作此前只有裸手写 JSON 一条路 — 无资格推演、
无形状校验反馈、无两族差异指引。本工具把「选 K」需要的全部事实拼装成
一份决策包; **判定逻辑零新增** — stability / qualification / disclosure /
hash 全部导入 src 单一实现, 本脚本只做读取与呈现。

使用纪律:
- 默认 preview 对文件系统零写入 (测试钉死);
- ``--write`` 是 **owner 亲自执行** 的预注册动作 (依据 owner_grants
  `campaign-standing-authorization-2026-08-28` 的决策权归属: 预注册参数
  属产品方向决策, agent 会话绝不代写); 已存在的注册文件拒绝覆写 —
  改写注册 = 新内容 hash = 新观测起算窗, 静默替换正是反回溯机器要封死
  的回溯向量, 因此宁可在 owner 手动移除旧文件后再写;
- 候选 K 推演是 **假想注册** 的资格判定 (registered_date=--registered-date),
  明确标注未注册; 注册前的武装不追溯计数 (反前瞻), 所以注册日晚于亮
  起点时达标数会低于 preview 中的全历史连亮 — 这是设计而非缺陷;
- 资格达成 ≠ 任何行为改变: 正式评估始终是 owner 门 (宪法 #2, R98 决策包)。

两族差异 (owner 需要知道的):
- 强度族: 双锚 — k_070 (0.70 锚合取 = 条件①∧②, 阈值上调评估) 与可选
  k_060 (0.60 锚合取 = 条件③∧②, 0.50→0.60 上调评估); 注册文件字段
  ``k_070``/``k_060``;
- 日层族: 单锚 — 合取 = C1(20+ 桶 CI>0)∧C2(中间桶转负), cohort 规模
  条件化正式评估; 注册文件字段 ``k``。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from src.screening.offensive import cohort_trigger as _ct
from src.screening.offensive import threshold_trigger as _tt

STRENGTH_ANCHOR = "production_aligned/t10"
COHORT_ANCHOR = "production_aligned/t10/cohort_size"


def _fmt_stability(stab: Mapping[str, Any], family: str) -> list[str]:
    records = int(stab.get("records") or 0)
    folded = int(stab.get("folded_duplicates") or 0)
    lines = [
        f"  账本 {records} 条"
        + (f" · 折叠同数据重复观测 {folded} 条" if folded > 0 else "")
        + f"（{stab.get('first_date')}→{stab.get('last_date')}）"
    ]
    if family == "strength":
        lines.append(
            f"  最新锚定: 条件① 连亮 {stab.get('condition_1_streak')} "
            f"(last_lit={stab.get('condition_1_last_lit')}) · "
            f"条件② 连亮 {stab.get('condition_2_streak')} "
            f"(last_lit={stab.get('condition_2_last_lit')}) · "
            f"条件③ 连亮 {stab.get('condition_3_streak')} "
            f"(last_lit={stab.get('condition_3_last_lit')})"
        )
        lines.append(
            f"  合取连亮 {stab.get('conjunction_streak')} · "
            f"060 锚合取连亮 {stab.get('conjunction_060_streak')} · "
            f"历史最多合取连亮 {stab.get('max_conjunction_streak')} · "
            f"历史最多 060 锚合取连亮 {stab.get('max_conjunction_060_streak')}"
        )
    else:
        lines.append(
            f"  最新锚定: C1(20+ 桶 CI>0) 连亮 {stab.get('strong_bucket_streak')} "
            f"(last_lit={stab.get('strong_bucket_last_lit')}) · "
            f"C2(中间桶转负) 连亮 {stab.get('mid_buckets_streak')} "
            f"(last_lit={stab.get('mid_buckets_last_lit')})"
        )
        lines.append(
            f"  日层合取连亮 {stab.get('conjunction_streak')} · "
            f"历史最多日层合取连亮 {stab.get('max_conjunction_streak')}"
        )
    return lines


def _candidate_line(
    label: str, qual: Mapping[str, Any], registered_date: str
) -> str:
    q = qual["q"]
    k = qual.get("k")
    qualified = bool(qual["qualified"])
    verdict = "达标 → 资格达成（正式评估仍属 owner 门）" if qualified else "未达标"
    return (
        f"  候选 {label}（registered_date={registered_date}）: "
        f"资格连亮 {q}/{k} → {verdict}"
    )


def build_packet(
    *,
    family: str,
    records: list[dict] | None,
    ledger_path: Path,
    k_registration_path: Path,
    k_observation_log_path: Path,
    candidates: Mapping[str, int],
    registered_date: str,
) -> dict[str, Any]:
    """单族决策包 (纯装配; 数值全部来自 src 单一实现)。"""
    out: dict[str, Any] = {"family": family}
    if records is None:
        out["no_ledger"] = True
        return out
    stab = (
        _tt.trigger_stability(records)
        if family == "strength"
        else _ct.cohort_trigger_stability(records)
    )
    out["stability"] = stab
    if family == "strength":
        state, reg = _tt.load_k_registration(k_registration_path)
        if state == "registered" and reg is not None:
            obs = _tt.load_k_observations(k_observation_log_path)
            out["registration"] = _tt.k_qualification_disclosure(
                records, registration=(state, reg), observation_log=obs
            )
        else:
            out["registration"] = {"state": state}
    else:
        state, reg = _ct.load_cohort_k_registration(k_registration_path)
        if state == "registered" and reg is not None:
            obs = _tt.load_k_observations(k_observation_log_path)
            out["registration"] = _ct.cohort_k_qualification_disclosure(
                records, registration=(state, reg), observation_log=obs
            )
        else:
            out["registration"] = {"state": state}

    draft: dict[str, Any] = {"anchor": STRENGTH_ANCHOR if family == "strength" else COHORT_ANCHOR}
    if family == "strength":
        draft["registered_date"] = registered_date
        if "k_070" in candidates:
            draft["k_070"] = candidates["k_070"]
        if "k_060" in candidates:
            draft["k_060"] = candidates["k_060"]
    else:
        draft["registered_date"] = registered_date
        if "k" in candidates:
            draft["k"] = candidates["k"]
    out["draft"] = draft

    # 候选 K 推演 = 假想注册 (未落盘) 的资格判定, 单一实现判定
    if family == "strength":
        hypo: dict[str, Any] = {
            "anchor": STRENGTH_ANCHOR,
            "registered_date": registered_date,
        }
        if "k_070" in candidates:
            hypo["k_070"] = candidates["k_070"]
            qual = _tt.trigger_qualification(records, hypo)
            out["candidate_070"] = {
                "q": qual["q_070"],
                "k": candidates["k_070"],
                "qualified": bool(qual["qualified_070"]),
            }
        if "k_060" in candidates:
            hypo["k_060"] = candidates["k_060"]
            qual = _tt.trigger_qualification(records, hypo)
            out["candidate_060"] = {
                "q": qual["q_060"],
                "k": candidates["k_060"],
                "qualified": (
                    None if qual["qualified_060"] is None
                    else bool(qual["qualified_060"])
                ),
            }
    else:
        if "k" in candidates:
            hypo = {
                "anchor": COHORT_ANCHOR,
                "registered_date": registered_date,
                "k_070": candidates["k"],
            }
            qual = _ct.cohort_trigger_qualification(records, hypo)
            out["candidate_070"] = {
                "q": qual["q"],
                "k": candidates["k"],
                "qualified": bool(qual["qualified"]),
            }
    return out


def _render_family(packet: Mapping[str, Any], candidates: Mapping[str, int], registered_date: str) -> list[str]:
    family_label = "强度族" if packet["family"] == "strength" else "日层族"
    lines = [f"== {family_label} =="]
    if packet.get("no_ledger"):
        lines.append("  账本缺失/空 — 判定面未建立, 无 K 预注册对象 (先积累判定快照)")
        return lines
    lines.extend(_fmt_stability(packet["stability"], packet["family"]))

    reg = packet["registration"]
    state = reg.get("state")
    if state == "registered":
        reg_line = reg["line_070"] if packet["family"] == "strength" else reg["line"]
        lines.append(f"  既有注册: 已预注册 — {reg_line}")
    elif state == "malformed":
        lines.append("  既有注册: 损坏 — 按渲染/报告披露句处理 (owner 修正后生效)")
    else:
        lines.append("  既有注册: 未预注册（连亮达标数属 owner 预注册动作）")

    if packet["family"] == "strength":
        if "candidate_070" in packet:
            lines.append(_candidate_line("k_070", packet["candidate_070"], registered_date))
        if "candidate_060" in packet:
            q060 = packet["candidate_060"]
            if q060["q"] is None:
                lines.append("  候选 k_060: 账本无 060 锚记录 — 推演不可判 (旧形态)")
            else:
                lines.append(_candidate_line("k_060", q060, registered_date))
    else:
        if "candidate_070" in packet:
            lines.append(_candidate_line("k (日层单锚)", packet["candidate_070"], registered_date))

    lines.append("  注册草案（--write 落盘 或 owner 手写; 落盘后夜刷 build 先观测后披露）:")
    lines.append("  " + json.dumps(packet["draft"], ensure_ascii=False, sort_keys=True))
    lines.append(
        "  机制: 注册生效起算日 = max(声明日, 夜刷首次观测日) — 回溯改写声明日期"
        "不获追溯计数; 资格达成 ≠ 行为改变, 正式评估始终是 owner 门"
    )
    return lines


def _validate_candidates(
    candidates: Mapping[str, int], registered_date: str
) -> str | None:
    """候选形状校验 (F3); 返回 None = 合法, 否则为拒绝理由。"""
    import re as _re

    for name in sorted(candidates):
        value = candidates[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return f"{name} 必须 >=1 的整数 (得到 {value!r})"
    if not _re.fullmatch(r"\d{8}", registered_date or ""):
        return f"registered_date 必须 YYYYMMDD (得到 {registered_date!r})"
    if "k_060" in candidates and "k_070" not in candidates:
        return "强度族注册必须含 k_070 (k_060 是可选第二锚, 不能单独注册)"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strength-ledger", type=Path, default=_tt.LEDGER_PATH)
    parser.add_argument("--strength-k-registration", type=Path, default=_tt.K_REGISTRATION_PATH)
    parser.add_argument("--strength-k-observation-log", type=Path, default=_tt.K_OBSERVATION_LOG_PATH)
    parser.add_argument("--cohort-ledger", type=Path, default=_ct.COHORT_TRIGGER_LEDGER_PATH)
    parser.add_argument("--cohort-k-registration", type=Path, default=_ct.COHORT_K_REGISTRATION_PATH)
    parser.add_argument("--cohort-k-observation-log", type=Path, default=_ct.COHORT_K_OBSERVATION_LOG_PATH)
    parser.add_argument("--k070", type=int, help="候选 K: 0.70 锚合取 (强度族)")
    parser.add_argument("--k060", type=int, help="候选 K: 0.60 锚合取 (强度族, 可选)")
    parser.add_argument("--cohort-k", type=int, help="候选 K: 日层单锚 (日层族)")
    parser.add_argument(
        "--registered-date",
        type=str,
        default=date.today().strftime("%Y%m%d"),
        help="候选注册声明日 (YYYYMMDD; 默认今日 — 资格只数注册日后的亮)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="落盘注册草案 (owner 亲自执行的预注册动作; 已存在拒绝覆写)",
    )
    args = parser.parse_args(argv)

    candidates: dict[str, int] = {}
    if args.k070 is not None:
        candidates["k_070"] = args.k070
    if args.k060 is not None:
        candidates["k_060"] = args.k060
    if args.cohort_k is not None:
        candidates["k"] = args.cohort_k

    if args.write and not candidates:
        print("--write 需要至少一个候选 K (--k070/--k060/--cohort-k) — 缺参拒绝")
        return 2
    # F3 (R129 Op3): 候选值形状前置校验, preview 与 write 双面 fail-closed —
    # 负数/零/非整数 K 会让假想资格推演在 trigger_qualification 形状复验
    # 直接 ValueError 裸逃逸; 畸形 registered_date 与仅 k_060 的强度注册
    # 则会落成 loader 判 malformed 的文件 (工具知情写坏文件 = owner 认知陷阱)。
    invalid_reason = _validate_candidates(candidates, args.registered_date)
    if invalid_reason is not None:
        print(f"候选参数非法: {invalid_reason}")
        return 2

    families: list[tuple[str, Path, Path, Path]] = [
        (
            "strength",
            args.strength_ledger,
            args.strength_k_registration,
            args.strength_k_observation_log,
        ),
        (
            "cohort",
            args.cohort_ledger,
            args.cohort_k_registration,
            args.cohort_k_observation_log,
        ),
    ]

    exit_code = 0
    lines: list[str] = ["owner K 预注册决策包 (preview, 零写入)" + (" — write 模式" if args.write else "")]
    written: list[Path] = []
    for family, ledger_path, reg_path, obs_path in families:
        records = (
            _tt.load_trigger_ledger(ledger_path)
            if family == "strength"
            else _ct.load_cohort_trigger_ledger(ledger_path)
        )
        packet = build_packet(
            family=family,
            records=records,
            ledger_path=ledger_path,
            k_registration_path=reg_path,
            k_observation_log_path=obs_path,
            candidates=candidates,
            registered_date=args.registered_date,
        )
        lines.extend(_render_family(packet, candidates, args.registered_date))

        if args.write and family == "strength" and "k_070" in candidates:
            draft = dict(packet["draft"])
            if reg_path.exists():
                print(f"强度族注册文件已存在，拒绝覆写: {reg_path} "
                      "(改写注册 = 新观测起算窗; 确认变更请先手动移除旧文件)")
                exit_code = 1
            else:
                reg_path.parent.mkdir(parents=True, exist_ok=True)
                reg_path.write_text(
                    json.dumps(draft, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                written.append(reg_path)
        if args.write and family == "cohort" and "k" in candidates:
            draft = dict(packet["draft"])
            if reg_path.exists():
                print(f"日层族注册文件已存在，拒绝覆写: {reg_path} "
                      "(改写注册 = 新观测起算窗; 确认变更请先手动移除旧文件)")
                exit_code = 1
            else:
                reg_path.parent.mkdir(parents=True, exist_ok=True)
                reg_path.write_text(
                    json.dumps(draft, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                written.append(reg_path)

    if written:
        lines.append(
            "已写入注册文件: " + ", ".join(str(p) for p in written)
            + " — 夜刷 build 将先观测后披露; 观测日志是反回溯凭证"
        )
    print("\n".join(lines))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
