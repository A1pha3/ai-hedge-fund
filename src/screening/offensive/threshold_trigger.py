"""预注册强度阈值触发器稳定账本的只读取面 (R85 Op1)。

单一实现: 判定快照的**落账**在 ``scripts/winrate_payoff_decomposition.py``
(数据增长耦合: court 重建 → 分解刷新 → 账本追加, R84); 本模块提供跨消费者
共享的读取面 — ``--daily-action`` 操作员视图经此读取触发器当前状态,
不复制加载/计数逻辑。分解脚本从本模块导入并 re-export (兼容既有测试)。

诚实边界:
- 本模块读账本并计数; 连亮多少次才算稳定 (阈值 K) 属 owner 预注册范围
  (AGENTS.md 项 1) — R112 起 owner 可经 ``threshold_trigger_k.json`` 预注册
  K, 本模块随后做**机械**资格判定 (资格连亮只数注册日后的记录, 前瞻偏差
  机械封死); 资格达成 ≠ 任何行为改变, 正式评估仍是 owner 门;
- 账本缺失/损坏行 advisory 跳过 (诊断面语义), 不假装有判定记录;
- 条件/合取的判定语义 (lit/armed) 由落账侧冻结, 读取侧不重推导 — 账本里
  是什么就披露什么 (与『配置不是权限』纪律一致: 披露 ≠ 任何行为改变)。
"""

from __future__ import annotations

import json
from pathlib import Path

LEDGER_PATH = Path("data/reports/threshold_trigger_ledger.jsonl")
K_REGISTRATION_PATH = Path("data/reports/threshold_trigger_k.json")


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
    """连亮计数 (R81 Op2 引入; R85 Op2 修 max 语义; R100 Op1 扩 0.60 锚): 两族字段语义 —

    ``condition_*_streak`` / ``conjunction_streak`` / ``conjunction_060_streak`` =
    **最新锚定**连亮 (从最新记录向前数, 未点亮/未判定断链 — 保守: 未知不
    延长连亮); ``max_conjunction_streak`` / ``max_conjunction_060_streak`` =
    **全历史**最大连续武装段 (独立正向扫描, 断链不吞历史 — R85 Op2 修复:
    旧实现把 max 收敛进最新锚定循环, 该值恒等于当前连亮, 与字段名/MD 披露
    『历史最多』不符)。

    0.60 锚 (R100 Op1 预注册 2026-09-02): 条件③ = 0.60-0.70 桶 CI>0,
    060 合取 = ③∧② (②与 0.70 锚共享, 耦合成文)。R100 前的旧记录无
    condition_3/conjunction_060_armed 键 → 按**未点亮**处理 (断链, 保守:
    未知不延长连亮 — 与『未知不驱动参数变更』同纪律)。
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
        "condition_3_streak": 0,
        "condition_3_last_lit": None,
        "conjunction_streak": 0,
        "conjunction_last_armed": None,
        "conjunction_060_streak": 0,
        "conjunction_060_last_armed": None,
        "max_conjunction_streak": 0,
        "max_conjunction_060_streak": 0,
    }
    if not records:
        return out
    latest = records[-1]
    c1, c2 = latest.get("condition_1") or {}, latest.get("condition_2") or {}
    c3 = latest.get("condition_3") or {}
    out["condition_1_last_lit"] = c1.get("lit")
    out["condition_2_last_lit"] = c2.get("lit")
    out["condition_3_last_lit"] = c3.get("lit")
    out["conjunction_last_armed"] = latest.get("conjunction_armed")
    out["conjunction_060_last_armed"] = latest.get("conjunction_060_armed")
    run_c1 = run_c2 = run_c3 = run_and = run_and060 = True
    for rec in reversed(records):
        r1 = rec.get("condition_1") or {}
        r2 = rec.get("condition_2") or {}
        r3 = rec.get("condition_3") or {}
        lit1 = r1.get("lit") is True
        lit2 = r2.get("lit") is True
        lit3 = r3.get("lit") is True
        armed = rec.get("conjunction_armed") is True
        armed060 = rec.get("conjunction_060_armed") is True
        if run_c1 and lit1:
            out["condition_1_streak"] = int(out["condition_1_streak"]) + 1
        else:
            run_c1 = False
        if run_c2 and lit2:
            out["condition_2_streak"] = int(out["condition_2_streak"]) + 1
        else:
            run_c2 = False
        if run_c3 and lit3:
            out["condition_3_streak"] = int(out["condition_3_streak"]) + 1
        else:
            run_c3 = False
        if run_and and armed:
            out["conjunction_streak"] = int(out["conjunction_streak"]) + 1
        else:
            run_and = False
        if run_and060 and armed060:
            out["conjunction_060_streak"] = int(out["conjunction_060_streak"]) + 1
        else:
            run_and060 = False
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
    historical_max_060 = 0
    current_run = 0
    for rec in records:
        if rec.get("conjunction_060_armed") is True:
            current_run += 1
            historical_max_060 = max(historical_max_060, current_run)
        else:
            current_run = 0
    out["max_conjunction_060_streak"] = historical_max_060
    return out


_K_DEFAULT_LINE = "稳定阈值 K 未预注册（连亮达标数属 owner 预注册动作）"
_K_MALFORMED_LINE = (
    "稳定阈值 K 预注册文件损坏（不可判定 — owner 修正 "
    "data/reports/threshold_trigger_k.json 后生效）"
)


def _is_pos_int(value: object) -> bool:
    """≥1 的整数; bool 是 int 子类, 显式排除 (True 当 K=1 是形状欺骗)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def load_k_registration(
    path: Path | str | None = None,
) -> tuple[str, dict[str, object] | None]:
    """owner 预注册 K 读取面 (R112): 三态 (state, payload)。

    - ``("unregistered", None)``: 文件缺失 — 现默认态, 行为与 R111 前逐字一致;
    - ``("malformed", None)``: 文件存在但 JSON 损坏/形状不符 — owner 可见的
      异常态, 明语披露, 不假装未注册也不猜部分字段;
    - ``("registered", dict)``: 形状契约全过 — ``anchor`` 非空 str、
      ``registered_date`` 八位数字 str、``k_070`` ≥1 int、可选 ``k_060`` 同型
      (缺失归一为 None)、可选 ``owner_ref`` str。

    形状校验是判定的前提: K 参与的是「正式评估资格」语义, 形状存疑一律
    malformed (fail-open 于渲染行整体存在性, fail-closed 于资格判定)。
    """
    file_path = _resolve(path) if path is not None else K_REGISTRATION_PATH
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return ("unregistered", None)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ("malformed", None)
    if not isinstance(data, dict):
        return ("malformed", None)
    anchor = data.get("anchor")
    registered_date = data.get("registered_date")
    owner_ref = data.get("owner_ref")
    if not isinstance(anchor, str) or not anchor:
        return ("malformed", None)
    if not isinstance(registered_date, str) or not registered_date.isdigit()             or len(registered_date) != 8:
        return ("malformed", None)
    if not _is_pos_int(data.get("k_070")):
        return ("malformed", None)
    k_060 = data.get("k_060")
    if k_060 is not None and not _is_pos_int(k_060):
        return ("malformed", None)
    if owner_ref is not None and not isinstance(owner_ref, str):
        return ("malformed", None)
    reg: dict[str, object] = {
        "anchor": anchor,
        "registered_date": registered_date,
        "k_070": data["k_070"],
        "k_060": k_060 if k_060 is not None else None,
    }
    if owner_ref is not None:
        reg["owner_ref"] = owner_ref
    return ("registered", reg)


def trigger_qualification(
    records: list[dict], registration: dict[str, object]
) -> dict[str, object]:
    """反前瞻资格连亮 (R112): 只数 ``date >= registered_date`` 且 anchor 匹配
    的记录之尾部合取连亮。

    与 ``trigger_stability`` 的连亮语义同源 (反向走, 断于未武装/缺键), 差异
    仅在窗口: 注册日前的记录不参与 — K 注册晚于连亮起点时**不追溯计旧亮**
    (K 必须先于它资格化的亮存在, 事后选参的前瞻偏差机械封死)。

    - ``q_070``/``qualified_070``: 0.70 锚合取 vs ``k_070``;
    - ``q_060``/``qualified_060``: 0.60 锚合取 vs ``k_060``; ``k_060`` 缺失
      → 两者 None (该锚未预注册, 绝不借 0.70 的 K)。

    日期比较用与账本排序同一字符串空间 (YYYYMMDD); 畸形日期记录由排序/
    比较的保守断链语义兜底, 不在此重复校验 (读取面 advisory 家族纪律)。
    """
    k_070 = registration["k_070"]
    k_060 = registration.get("k_060")
    reg_date = str(registration["registered_date"])
    anchor = str(registration["anchor"])
    suffix = [
        rec for rec in records
        if str(rec.get("anchor")) == anchor and str(rec.get("date")) >= reg_date
    ]
    q_070 = 0
    for rec in reversed(suffix):
        if rec.get("conjunction_armed") is True:
            q_070 += 1
        else:
            break
    out: dict[str, object] = {
        "q_070": q_070,
        "qualified_070": q_070 >= int(k_070),  # type: ignore[arg-type]
        "q_060": None,
        "qualified_060": None,
    }
    if isinstance(k_060, int) and not isinstance(k_060, bool):
        q_060 = 0
        for rec in reversed(suffix):
            if rec.get("conjunction_060_armed") is True:
                q_060 += 1
            else:
                break
        out["q_060"] = q_060
        out["qualified_060"] = q_060 >= k_060
    return out


def k_qualification_disclosure(
    records: list[dict],
    registration: tuple[str, dict[str, object] | None] | None = None,
) -> dict[str, object]:
    """K 子句单一事实源 (R112): ``--daily-action`` 渲染行与分解报告 MD 的
    稳定计数行都从这里取 K 披露文本 — 两处消费面不许各自措辞漂移 (R109
    Op2 单一实现纪律)。

    返回 JSON 可序列化 dict (分解报告把它存进 payload["threshold_k"]):
    ``state`` / ``line_070`` (0.70 锚 K 披露句) / ``line_060`` (0.60 锚句,
    未预注册时 None) / ``qualified_070`` / ``qualified_060``。
    ``registration`` 省略时从 ``K_REGISTRATION_PATH`` 现读 (渲染面路径)。
    """
    state, reg = registration if registration is not None else load_k_registration()
    if state == "registered" and reg is not None:
        qual = trigger_qualification(records, reg)
        k_070 = int(reg["k_070"])  # type: ignore[arg-type]
        q_070 = int(qual["q_070"])  # type: ignore[arg-type]
        line_070 = (
            f"预注册 K={k_070}（自 {reg['registered_date']} 起计资格连亮 "
            f"{q_070}/{k_070}）"
        )
        if qual["qualified_070"]:
            line_070 += " → 正式评估资格达成（owner 预注册动作）"
        line_060: str | None = None
        if qual["q_060"] is not None:
            k_060 = int(reg["k_060"])  # type: ignore[arg-type]
            q_060 = int(qual["q_060"])  # type: ignore[arg-type]
            line_060 = f"预注册 K={k_060}（资格连亮 {q_060}/{k_060}）"
            if qual["qualified_060"]:
                line_060 += " → 0.50→0.60 上调评估资格达成（owner 预注册动作）"
        return {
            "state": "registered",
            "line_070": line_070,
            "line_060": line_060,
            "qualified_070": bool(qual["qualified_070"]),
            "qualified_060": (
                None if qual["qualified_060"] is None
                else bool(qual["qualified_060"])
            ),
        }
    if state == "malformed":
        return {
            "state": "malformed",
            "line_070": _K_MALFORMED_LINE,
            "line_060": None,
            "qualified_070": False,
            "qualified_060": None,
        }
    return {
        "state": "unregistered",
        "line_070": _K_DEFAULT_LINE,
        "line_060": None,
        "qualified_070": False,
        "qualified_060": None,
    }


__all__ = [
    "LEDGER_PATH",
    "K_REGISTRATION_PATH",
    "load_trigger_ledger",
    "trigger_stability",
    "load_k_registration",
    "trigger_qualification",
    "k_qualification_disclosure",
]
