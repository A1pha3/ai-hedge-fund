"""日层 cohort 触发器账本只读取面 (R126 Op1) — 强度阈值触发器
(threshold_trigger) 的日层同构族。

单一实现: 判定快照的**落账**在 ``scripts/btst_signal_day_cohort.py``
(数据增长耦合: court 重建 → 夜刷 cohort 刷新 → 账本追加, 镜像 R84 强度
族路径); 本模块提供跨消费者共享的读取面 — JSONL 装载经
``threshold_trigger.load_trigger_ledger`` 单一实现 (损坏行 advisory 跳过,
日期升序), 连亮计数为本族字段语义。两族账本文件互不混写: 强度族
``threshold_trigger_ledger.jsonl`` 键空间 (condition_1/2/3) 与日层族
``signal_day_cohort_trigger_ledger.jsonl`` 键空间 (strong_bucket /
mid_buckets) 独立演化, 读取侧互不解读对方记录。

诚实边界 (与 threshold_trigger 同纪律):
- 连亮多少次才算稳定 (阈值 K) 属 owner 预注册范围 — 本模块只计数不判定;
- 账本缺失/损坏行 advisory 跳过 (诊断面语义), 不假装有判定记录;
- 条件/合取的判定语义 (lit/armed) 由落账侧冻结, 读取侧不重推导 — 账本里
  是什么就披露什么 (与『配置不是权限』纪律一致: 披露 ≠ 任何行为改变)。
"""

from __future__ import annotations

import json
from pathlib import Path

from src.screening.offensive.threshold_trigger import (
    condition_lit,
    effective_k_registration,
    k_registration_hash,
    load_k_observations,
    load_trigger_ledger,
    observe_k_registration,
    trigger_qualification,
)

COHORT_TRIGGER_LEDGER_PATH = Path(
    "data/reports/signal_day_cohort_trigger_ledger.jsonl"
)
COHORT_K_REGISTRATION_PATH = Path("data/reports/cohort_trigger_k.json")
COHORT_K_OBSERVATION_LOG_PATH = Path(
    "data/reports/cohort_trigger_k_observations.jsonl"
)


def load_cohort_trigger_ledger(
    ledger_path: Path | str | None = None,
) -> list[dict]:
    """读日层 cohort 触发器账本 (threshold_trigger.load_trigger_ledger
    单一装载实现, 独立默认路径)。损坏行 advisory 跳过; 按日期升序。"""
    path = (
        Path(ledger_path) if ledger_path is not None
        else COHORT_TRIGGER_LEDGER_PATH
    )
    return load_trigger_ledger(path)


def cohort_trigger_stability(records: list[dict]) -> dict[str, object]:
    """日层 cohort 触发器连亮计数 (R126 Op1; 语义镜像
    threshold_trigger.trigger_stability, 字段为本族命名):

    ``strong_bucket_streak`` / ``mid_buckets_streak`` / ``conjunction_streak``
    = **最新锚定**连亮 (从最新记录向前数, 未点亮/未判定/缺键断链 — 保守:
    未知不延长连亮); ``max_conjunction_streak`` = **全历史**最大连续武装段
    (独立正向扫描, 断链不吞历史 — R85 Op2 修复语义)。

    本族账本自 R126 起积累, 无旧形态兼容负担; 记录缺键 (手工构造/未来
    字段演化) 一律按未点亮断链。R126 Op2 形状守卫: 行内条件值
    (strong_bucket/mid_buckets) 非 dict 形态 (手编账本/损坏写入/形态演化)
    与缺键同语义 — 断链 + last_lit None (advisory), 绝不让毒化行以裸
    AttributeError 炸掉消费面 (R115 Op1 家族纪律: 证据面损坏不得阻断
    披露/生产面); R127 Op2 起守卫经 ``condition_lit`` 单一实现委托。
    只计数不判定 — 『稳定』阈值属 owner。
    """
    dates = [str(r.get("date")) for r in records]
    out: dict[str, object] = {
        "records": len(records),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "strong_bucket_streak": 0,
        "strong_bucket_last_lit": None,
        "mid_buckets_streak": 0,
        "mid_buckets_last_lit": None,
        "conjunction_streak": 0,
        "conjunction_last_armed": None,
        "max_conjunction_streak": 0,
    }
    if not records:
        return out

    latest = records[-1]
    # R127 Op2: 形状守卫委托 threshold_trigger.condition_lit 单一实现
    # (R126 Op2 本模块私有 _lit 的语义逐字节保留, 双实现收敛)。
    out["strong_bucket_last_lit"] = condition_lit(latest, "strong_bucket")
    out["mid_buckets_last_lit"] = condition_lit(latest, "mid_buckets")
    out["conjunction_last_armed"] = latest.get("conjunction_armed")
    run_c1 = run_c2 = run_and = True
    for rec in reversed(records):
        lit1 = condition_lit(rec, "strong_bucket") is True
        lit2 = condition_lit(rec, "mid_buckets") is True
        armed = rec.get("conjunction_armed") is True
        if run_c1 and lit1:
            out["strong_bucket_streak"] = int(out["strong_bucket_streak"]) + 1
        else:
            run_c1 = False
        if run_c2 and lit2:
            out["mid_buckets_streak"] = int(out["mid_buckets_streak"]) + 1
        else:
            run_c2 = False
        if run_and and armed:
            out["conjunction_streak"] = int(out["conjunction_streak"]) + 1
        else:
            run_and = False
    # 全历史最大武装段: 独立正向扫描, 与最新锚定循环解耦 (R85 Op2 语义)
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


# --------------------------------------------------------------------------
# R129 Op1: 日层族 K 预注册机制 (强度族 R112-R115 机器的镜像复用)。
#
# owner 注册文件形状 (数据/词法独立于强度族): {"anchor": 非空 str,
# "registered_date": YYYYMMDD str, "k": >=1 int, "owner_ref"?: str}。
# 装载把 k 翻译进 threshold_trigger 规范形状的 k_070 槽位 — 之后 hash /
# 观测 / 反回溯起算 / 资格窗口判定全部是 threshold_trigger 单一实现
# (k_060 缺失 → 日层族天然单锚, 060 分支恒 None), 本模块零复制第二套
# 机器 (R128 开放项③复用纪律)。未注册缺席句按消费面历史措辞保留
# (渲染行/MD 两面在 K 子系统建立前已有各自的诚实缺席句, 统一措辞超出
# 本 op 冻结范围); 注册/损坏/达标三态判定文本经 cohort_k_qualification_
# disclosure 单一事实源供两面消费 (R112 同纪律)。


def load_cohort_k_registration(
    path: Path | str | None = None,
) -> tuple[str, dict[str, object] | None]:
    """日层族 K 注册 tri-state 装载 (unregistered / malformed / registered)。

    registered 返回值已是 threshold_trigger 规范形状 (k 落在 k_070 槽位),
    可直接交给 observe_k_registration / effective_k_registration /
    trigger_qualification。形状存疑一律 malformed — K 参与正式评估资格
    语义, 与强度族 load_k_registration 同纪律 (fail-open 于渲染行整体
    存在性, fail-closed 于资格判定)。
    """
    file_path = (
        Path(path) if path is not None else COHORT_K_REGISTRATION_PATH
    )
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return ("unregistered", None)
    except UnicodeDecodeError:
        # R129 Op3: 文件存在但非 UTF-8 → 损坏态 (malformed 明语句), 不是
        # 未注册 — UnicodeDecodeError 是 ValueError 非 OSError, 此前从读段
        # 裸逃逸炸穿无守卫渲染行 (PoC 实锤)。
        return ("malformed", None)
    try:
        data = json.loads(text)
    except ValueError:
        # JSONDecodeError + UnicodeDecodeError 同收 (R129 Op3 家族修复,
        # 镜像 threshold_trigger.load_k_registration 同款) — 非 UTF-8 损坏
        # 文件 → malformed 明语句, 不再裸逃逸/整行省略。
        return ("malformed", None)
    if not isinstance(data, dict):
        return ("malformed", None)
    anchor = data.get("anchor")
    registered_date = data.get("registered_date")
    k = data.get("k")
    owner_ref = data.get("owner_ref")
    if not isinstance(anchor, str) or not anchor:
        return ("malformed", None)
    if (
        not isinstance(registered_date, str)
        or not registered_date.isdigit()
        or len(registered_date) != 8
    ):
        return ("malformed", None)
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        return ("malformed", None)
    if owner_ref is not None and not isinstance(owner_ref, str):
        return ("malformed", None)
    reg: dict[str, object] = {
        "anchor": anchor,
        "registered_date": registered_date,
        "k_070": k,
    }
    if owner_ref is not None:
        reg["owner_ref"] = owner_ref
    return ("registered", reg)


def cohort_trigger_qualification(
    records: list[dict], registration: dict[str, object]
) -> dict[str, object]:
    """日层族资格连亮 — threshold_trigger.trigger_qualification 单一实现的
    单锚投影 (q_070 槽位即日层合取资格; 反前瞻窗口/anchor 过滤/日期形状
    防御全部单一实现语义, 本函数零判定逻辑)。"""
    qual = trigger_qualification(records, registration)
    return {"q": qual["q_070"], "qualified": qual["qualified_070"]}


def observe_cohort_k_registration(
    registration: dict[str, object],
    observed_date: str,
    path: Path | str | None = None,
) -> dict[str, object]:
    """日层族 K 观测落账 — threshold_trigger.observe_k_registration 单一
    实现, 独立默认日志路径 (两族观测历史互不混写)。幂等语义同源。"""
    return observe_k_registration(
        registration,
        observed_date,
        path=Path(path) if path is not None else COHORT_K_OBSERVATION_LOG_PATH,
    )


_COHORT_K_UNREGISTERED_LINE = "稳定阈值 K 属 owner 预注册；披露不是行为改变"
_COHORT_K_MALFORMED_LINE = (
    "稳定阈值 K 预注册文件损坏（不可判定 — owner 修正 "
    "data/reports/cohort_trigger_k.json 后生效）"
)


def cohort_k_qualification_disclosure(
    records: list[dict],
    registration: tuple[str, dict[str, object] | None] | None = None,
    observation_log: list[dict] | None = None,
) -> dict[str, object]:
    """日层族 K 子句单一事实源 (镜像 threshold_trigger.k_qualification_
    disclosure, 单锚无 060 分支): 渲染行与分解报告 MD 的注册/损坏/达标
    文本都从这里取。反回溯起算 (max(声明, 首次观测)) 与资格窗口判定
    全部单一实现; 未注册态缺席句为渲染行历史措辞 (逐字节 = 旧硬编码尾句,
    见上注)。返回 JSON 可序列化 dict。"""
    state, reg = (
        registration if registration is not None else load_cohort_k_registration()
    )
    if state == "registered" and reg is not None:
        log_records = (
            observation_log
            if observation_log is not None
            else load_k_observations(COHORT_K_OBSERVATION_LOG_PATH)
        )
        effective_date, backdated = effective_k_registration(reg, log_records)
        reg_effective = {**reg, "registered_date": effective_date}
        qual = cohort_trigger_qualification(records, reg_effective)
        k = int(reg["k_070"])  # type: ignore[arg-type]
        q = int(qual["q"])  # type: ignore[arg-type]
        line = f"预注册 K={k}（自 {effective_date} 起计资格连亮 {q}/{k}）"
        if backdated:
            line += (
                f"— 声明日期 {reg['registered_date']} 早于首次观测，以观测日起算"
            )
        if qual["qualified"]:
            line += " → 日层 cohort 规模条件化正式评估资格达成（owner 预注册动作）"
        return {
            "state": "registered",
            "line": line,
            "qualified": bool(qual["qualified"]),
            "effective_registered_date": effective_date,
            "backdated": bool(backdated),
        }
    if state == "malformed":
        return {
            "state": "malformed",
            "line": _COHORT_K_MALFORMED_LINE,
            "qualified": False,
            "effective_registered_date": None,
            "backdated": False,
        }
    return {
        "state": "unregistered",
        "line": _COHORT_K_UNREGISTERED_LINE,
        "qualified": False,
        "effective_registered_date": None,
        "backdated": False,
    }


__all__ = [
    "COHORT_TRIGGER_LEDGER_PATH",
    "COHORT_K_REGISTRATION_PATH",
    "COHORT_K_OBSERVATION_LOG_PATH",
    "load_cohort_trigger_ledger",
    "cohort_trigger_stability",
    "load_cohort_k_registration",
    "cohort_trigger_qualification",
    "observe_cohort_k_registration",
    "cohort_k_qualification_disclosure",
    "k_registration_hash",
]
