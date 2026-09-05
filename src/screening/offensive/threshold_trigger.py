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

import hashlib
import json
import math
import re
from pathlib import Path

LEDGER_PATH = Path("data/reports/threshold_trigger_ledger.jsonl")
K_REGISTRATION_PATH = Path("data/reports/threshold_trigger_k.json")
K_OBSERVATION_LOG_PATH = Path(
    "data/reports/threshold_trigger_k_observations.jsonl"
)
_K_DATE_RE = re.compile(r"\d{8}")


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
    except (OSError, ValueError):
        # R129 Op3: ValueError (UnicodeDecodeError) 与 OSError 同族 — 非 UTF-8
        # 损坏文件此前裸逃逸炸穿无守卫的渲染行 (R115 纪律违例 PoC 实锤);
        # 损坏账本 → advisory 空态 (整行省略), 与逐行损坏 advisory 跳过同语义。
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


def condition_dict(rec: dict, key: str) -> dict | None:
    """行内条件值形状守卫 (R128 Op1, R127 Op2 condition_lit 的基元提升):
    条件值必须恰为 dict — truthy 非 dict 形态 (手编账本/损坏写入/形态
    演化; `or {}` 只兜 falsy 不兜 truthy) 与缺键同语义返回 None, 绝不让
    毒化行以裸 AttributeError 炸掉消费面 (R115 Op1 家族纪律: 证据面损坏
    不得阻断披露/生产面)。调用方 `condition_dict(...) or {}` 对 None 与
    空 dict 均安全收敛为空判定。"""
    cond = rec.get(key)
    return cond if isinstance(cond, dict) else None


def condition_lit(rec: dict, key: str) -> bool | None:
    """行内条件 lit 读数 (condition_dict 单一守卫的 lit 投影):
    条件值非 dict → None (断链); dict → cond.get("lit")。"""
    cond = condition_dict(rec, key)
    return None if cond is None else cond.get("lit")


def court_content_digest(court: object) -> str | None:
    """从 court 绑定读取数据状态摘要 (R130 Op1)。

    恰 dict 且 ``content_digest`` 为非空 str 才返回, 其余 (非 dict/缺键/
    None 值/空串) 一律 None — 守卫纪律同 ``condition_dict`` 家族: 形状
    未知不合并、不比较、不假装。
    """
    if not isinstance(court, dict):
        return None
    digest = court.get("content_digest")
    return digest if isinstance(digest, str) and digest else None


def court_data_state_equal(left: object, right: object) -> bool:
    """两份 court 绑定是否同一**数据状态** (R130 Op1)。

    数据前进门的身份语义: 判定是 (数据状态, 规则) 的确定性纯函数, 同一份
    事件表反复判定不产生新证据。绑定中的 ``window_start``/``window_end``
    是**请求态** (本次 build 的请求窗), 不是数据内容 — 非交易日重建只推
    进请求窗而内容不变, 整字典比较会把请求窗漂移误判为数据前进, 在账本
    写下『新日期旧数据』重复判定记录 (2026-09-05 周六休市实录: 0905 与
    0904 绑定唯一差异 window_end, content_digest/rows/fingerprint 全同,
    条件①连亮被重复观测膨胀)。故身份只认 ``content_digest``: 双方均为
    非空 str 且相等 → 同一数据状态。任一侧缺失/畸形/None → 不等 (保守
    方向 = 宁多记不漏记: 旧形态无 digest 记录与 manifest 损坏 degrade
    形态保持既有门放行行为; corrupt-manifest 双 None digest 角落维持
    现行为, 已知边界成文)。
    """
    left_digest = court_content_digest(left)
    right_digest = court_content_digest(right)
    if left_digest is None or right_digest is None:
        return False
    return left_digest == right_digest


def collapse_adjacent_same_court_state(records: list[dict]) -> list[dict]:
    """折叠账本中**相邻**同数据状态的重复判定记录 (R130 Op1)。

    每段相邻同 ``content_digest`` 运行只保留**首次**判定 — 重复观测不是
    新证据 (2026-09-05 非交易日重复判定形态), 且保首与资格判定的反前瞻
    语义一致: 注册日前首现的数据状态不因周末重复观测变成注册后证据。
    仅相邻折叠 — A→B→A 数据回退再判定不被合并 (回归再判定是真判定);
    缺/畸形 digest 的记录永不折叠 (未知不合并)。
    """
    folded: list[dict] = []
    for rec in records:
        if folded and court_data_state_equal(
            folded[-1].get("court"), rec.get("court")
        ):
            continue
        folded.append(rec)
    return folded


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

    R127 Op2 形状守卫: 行内条件值经 ``condition_lit`` 单一实现读取 —
    truthy 非 dict 形态与缺键同语义 (断链 + last_lit None, advisory 不
    假装), 不再以裸 AttributeError 炸消费面 (R126 Op2 日层族同族修复的
    单一实现提升)。

    R130 Op1 连亮语义: 计数前对相邻同数据状态 (content_digest) 的重复
    判定记录折叠 — 同一份数据反复判定不产生新证据, 非交易日重建的重复
    观测不膨胀连亮 (保首语义见 ``collapse_adjacent_same_court_state``)。
    ``records``/``first_date``/``last_date`` 保持**原始账本事实** (文件
    有几行/首末日期), 连亮字段按**不同数据状态**计数 — 两者是不同侧面,
    都如实。
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
    out["condition_1_last_lit"] = condition_lit(latest, "condition_1")
    out["condition_2_last_lit"] = condition_lit(latest, "condition_2")
    out["condition_3_last_lit"] = condition_lit(latest, "condition_3")
    out["conjunction_last_armed"] = latest.get("conjunction_armed")
    out["conjunction_060_last_armed"] = latest.get("conjunction_060_armed")
    # R130 Op1: 连亮扫描走折叠视图 (重复观测不膨胀); latest 取原始末条 —
    # 同状态重复记录判定值恒等 (判定是数据状态的确定性纯函数), 末条即
    # 折叠末条语义。
    scan_records = collapse_adjacent_same_court_state(records)
    run_c1 = run_c2 = run_c3 = run_and = run_and060 = True
    for rec in reversed(scan_records):
        lit1 = condition_lit(rec, "condition_1") is True
        lit2 = condition_lit(rec, "condition_2") is True
        lit3 = condition_lit(rec, "condition_3") is True
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
    # 全历史最大武装段: 独立正向扫描, 与最新锚定循环解耦 (R130 Op1 起走
    # 折叠视图 — 重复观测不虚增历史最大段)
    historical_max = 0
    current_run = 0
    for rec in scan_records:
        if rec.get("conjunction_armed") is True:
            current_run += 1
            historical_max = max(historical_max, current_run)
        else:
            current_run = 0
    out["max_conjunction_streak"] = historical_max
    historical_max_060 = 0
    current_run = 0
    for rec in scan_records:
        if rec.get("conjunction_060_armed") is True:
            current_run += 1
            historical_max_060 = max(historical_max_060, current_run)
        else:
            current_run = 0
    out["max_conjunction_060_streak"] = historical_max_060
    return out


ALL_STRENGTH_BUCKETS: tuple[str, ...] = ("<0.50", "0.50-0.60", "0.60-0.70", "≥0.70", "unknown")


def strength_bucket(strength: float | None) -> str:
    """强度分桶 (R114 Op3 自分解脚本逐字上移 — 单一实现): 0.50/0.60/0.70
    左闭右开 (与 panel_signal_decomposition 同侧)。court 分组与操作员渲染
    行共用本函数, 两侧口径不可漂移 (R109 Op2 纪律)。"""
    if strength is None or (isinstance(strength, float) and math.isnan(strength)):
        return "unknown"
    if strength < 0.50:
        return "<0.50"
    if strength < 0.60:
        return "0.50-0.60"
    if strength < 0.70:
        return "0.60-0.70"
    return "≥0.70"


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
    except UnicodeDecodeError:
        # R129 Op3: 文件存在但非 UTF-8 → 损坏态 (malformed 明语句), 不是
        # 未注册 — UnicodeDecodeError 是 ValueError 非 OSError, 此前从读段
        # 裸逃逸炸穿无守卫渲染行 (PoC 实锤)。
        return ("malformed", None)
    try:
        data = json.loads(text)
    except ValueError:
        # JSONDecodeError + UnicodeDecodeError 同收 — 非 UTF-8 损坏文件此前
        # 裸逃逸 (UnicodeDecodeError 不是 JSONDecodeError), PoC 实锤炸穿
        # 无 try 守卫的强度渲染行 (R129 Op3); 损坏 → owner 可见 malformed 态。
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

    形状防御 (R113 Op2): 本函数在 ``__all__`` 导出, 直接调用者的
    registration 不经 load 形状校验 — float K 经 ``int()`` 截断可使
    2/2.5 判达标, bool K 是 int 子类可伪装; 形状复验 fail-closed
    (ValueError), 绝不静默截断。日期窗口只认 YYYYMMDD 形状记录 —
    畸形日期 (如 ``2026-9-1``) 字典序可比但形状非法, 不参与资格
    (保守断链, 读取面 advisory 家族纪律)。

    R130 Op1: 窗口过滤前先折叠相邻同数据状态记录 (保首) — 注册日前
    首现的状态不因周末重复观测变成注册后证据 (反前瞻语义的重复观测
    延伸); 窗内重复观测也只计一次 (同一数据状态只资格化一次)。
    """
    _validate_registration_shape(registration)
    k_070 = registration["k_070"]
    k_060 = registration.get("k_060")
    reg_date = str(registration["registered_date"])
    anchor = str(registration["anchor"])
    suffix = [
        rec for rec in collapse_adjacent_same_court_state(records)
        if str(rec.get("anchor")) == anchor
        and _K_DATE_RE.fullmatch(str(rec.get("date") or ""))
        and str(rec.get("date")) >= reg_date
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


def k_registration_hash(registration: dict[str, object]) -> str:
    """注册内容身份 (canonical JSON 的 sha256): 回溯改写声明日期/数值即新
    内容 → 新哈希 → 旧观测不约束新内容, 新观测重开起算窗口。"""
    canonical = json.dumps(
        registration, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def observe_k_registration(
    registration: dict[str, object],
    observed_date: str,
    path: Path | str | None = None,
) -> dict[str, object]:
    """K 注册观测日志 (R113 Op2): 夜刷 build 单写者把「何时首次见到这份
    声明」落进 append-only JSONL — registered_date 从此有观测凭证, 回溯
    改写声明日期会被 ``effective_k_registration`` 交叉出并以观测日起算。

    幂等: 同内容同日重放不重复追加; 日志自身损坏行 advisory 跳过
    (诊断面家族纪律)。调用方 (分解报告 build) 失败 advisory 不阻断。
    """
    log_path = Path(path) if path is not None else K_OBSERVATION_LOG_PATH
    k_hash = k_registration_hash(registration)
    existing = load_k_observations(log_path)
    for rec in existing:
        if rec.get("k_hash") == k_hash and rec.get("observed_date") == observed_date:
            return rec
    record = {
        "observed_date": observed_date,
        "k_hash": k_hash,
        "declared_registered_date": str(registration["registered_date"]),
        "anchor": str(registration["anchor"]),
        "k_070": registration.get("k_070"),
        "k_060": registration.get("k_060"),
    }
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return record


def load_k_observations(path: Path | str | None = None) -> list[dict]:
    """读观测日志, 按观测日升序; 缺失/损坏行 advisory 跳过 (账本同族)。

    R115 Op1 形状守卫: ``observed_date`` 必须是 YYYYMMDD 字符串 — 只查键
    存在时, 畸形观测日 (9 位 ``202609011``) 曾经 ``effective_k_registration``
    流入资格窗口起算日, 再经 ``trigger_qualification`` 形状复验 ValueError
    裸逃逸炸掉 ``--daily-action`` 渲染与夜刷 build 双面 (fail-open 家族纪律:
    证据面损坏不得阻断披露/生产面)。畸形行 advisory 跳过, 不假装有观测。
    """
    log_path = Path(path) if path is not None else K_OBSERVATION_LOG_PATH
    try:
        text = log_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        # R129 Op3: 非 UTF-8 损坏观测日志 → advisory 空态 (同 load_trigger_ledger)
        return []
    records: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        observed = rec.get("observed_date") if isinstance(rec, dict) else None
        if (
            isinstance(observed, str)
            and _K_DATE_RE.fullmatch(observed)
            and rec.get("k_hash")
        ):
            records.append(rec)
    return sorted(records, key=lambda r: str(r["observed_date"]))


def effective_k_registration(
    registration: dict[str, object],
    observations: list[dict],
) -> tuple[str, bool]:
    """反回溯有效起算日 (R113 Op2): ``max(声明日, 该内容哈希首次观测日)``。

    返回 ``(effective_registered_date, backdated)``。无观测记录 (文件刚落,
    夜刷未跑) → 声明日暂态生效, 最迟当晚修正; 声明日早于首次观测 →
    backdated=True (回溯注册实锤), 以观测日起算 — Op1 的「K 必须先于它
    资格化的亮存在」从诚实声明升级为观测凭证。

    R115 Op2 加固: 「首次」= **最早**匹配观测 (``min``, 顺序无关 — 修复前
    ``next()`` 取调用方列表首条, 乱序注入返回不同起算日, PoC 实锤); 畸形
    ``observed_date`` 记录不构成观测证据 (R113 P3 同族纪律: 只认 YYYYMMDD,
    不参与 — 对直接调用者也不信输入形状)。
    """
    _validate_registration_shape(registration)
    k_hash = k_registration_hash(registration)
    declared = str(registration["registered_date"])
    first_observed = min(
        (
            rec["observed_date"]
            for rec in observations
            if isinstance(rec, dict)
            and rec.get("k_hash") == k_hash
            and isinstance(rec.get("observed_date"), str)
            and _K_DATE_RE.fullmatch(rec["observed_date"])
        ),
        default=None,
    )
    if first_observed is None or first_observed <= declared:
        return (declared, False)
    return (first_observed, True)


def _validate_registration_shape(registration: object) -> None:
    if not isinstance(registration, dict):
        raise ValueError("registration must be a dict")
    anchor = registration.get("anchor")
    if not isinstance(anchor, str) or not anchor:
        raise ValueError("registration.anchor must be a non-empty str")
    registered_date = registration.get("registered_date")
    if not isinstance(registered_date, str) or not _K_DATE_RE.fullmatch(registered_date):
        raise ValueError("registration.registered_date must be YYYYMMDD str")
    if not _is_pos_int(registration.get("k_070")):
        raise ValueError("registration.k_070 must be an int >= 1")
    k_060 = registration.get("k_060")
    if k_060 is not None and not _is_pos_int(k_060):
        raise ValueError("registration.k_060 must be None or an int >= 1")


def k_qualification_disclosure(
    records: list[dict],
    registration: tuple[str, dict[str, object] | None] | None = None,
    observation_log: list[dict] | None = None,
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
        # 反回溯窗口 (R113 Op2): 起算日 = max(声明, 首次观测); 观测日志显式
        # 注入 (script build 已观测后传入) 或从默认路径现读 (渲染面).
        log_records = (
            observation_log if observation_log is not None
            else load_k_observations()
        )
        effective_date, backdated = effective_k_registration(reg, log_records)
        reg_effective = {**reg, "registered_date": effective_date}
        qual = trigger_qualification(records, reg_effective)
        k_070 = int(reg["k_070"])  # type: ignore[arg-type]
        q_070 = int(qual["q_070"])  # type: ignore[arg-type]
        line_070 = (
            f"预注册 K={k_070}（自 {effective_date} 起计资格连亮 "
            f"{q_070}/{k_070}）"
        )
        if backdated:
            line_070 += (
                f"— 声明日期 {reg['registered_date']} 早于首次观测，"
                "以观测日起算"
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
            "effective_registered_date": effective_date,
            "backdated": bool(backdated),
        }
    if state == "malformed":
        return {
            "state": "malformed",
            "line_070": _K_MALFORMED_LINE,
            "line_060": None,
            "qualified_070": False,
            "qualified_060": None,
            "effective_registered_date": None,
            "backdated": False,
        }
    return {
        "state": "unregistered",
        "line_070": _K_DEFAULT_LINE,
        "line_060": None,
        "qualified_070": False,
        "qualified_060": None,
        "effective_registered_date": None,
        "backdated": False,
    }


__all__ = [
    "LEDGER_PATH",
    "K_REGISTRATION_PATH",
    "K_OBSERVATION_LOG_PATH",
    "load_trigger_ledger",
    "condition_dict",
    "condition_lit",
    "court_content_digest",
    "court_data_state_equal",
    "collapse_adjacent_same_court_state",
    "trigger_stability",
    "load_k_registration",
    "trigger_qualification",
    "k_qualification_disclosure",
    "k_registration_hash",
    "observe_k_registration",
    "load_k_observations",
    "effective_k_registration",
    "ALL_STRENGTH_BUCKETS",
    "strength_bucket",
]
