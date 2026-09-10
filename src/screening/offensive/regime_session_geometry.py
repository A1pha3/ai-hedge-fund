"""regime 会话索引算术单一实现 (R176 Op1 自 scripts 上移)。

run_geometry / BLOCKED_REGIMES / is_blocked 此前唯一实现在诊断脚本侧
(BLOCKED_REGIMES 与 _is_blocked 定义于 scripts/regime_proximity_conditioning.py,
run_geometry 定义于 scripts/regime_blocked_run_conditioning.py — R168 Op1 引入,
R170 Op1 泛化)。R176 起 --daily-action 的 d1 重入邻近度披露行需要同一算术:
操作员看到的形态必须与证据轴 (R166/R168) 的形态同源 — 同一会话索引算术,
否则披露行与夜刷报告可对不上号。上移后脚本侧委托 (import 即模块属性),
邻近度/连跑/稳健性三工具既有套件零改动全绿即零漂移证明。

regime 标签语义: BLOCKED_REGIMES = ("crisis", "risk_off") (阻断新仓的两标签;
tuple 形态与邻近度工具侧原定义逐字一致, payload 序列化 list(BLOCKED_REGIMES)
顺序零漂移)。daily_action regime gate 的 _REGIME_GATE_BLOCK_REGIMES 同值但
不同源 — 生产 gate 面零改动是本 operation 的刻意范围选择 (纯披露, 宪法 #2);
两常量等值性由本模块测试钉住, 漂移即测试失败。
"""

from __future__ import annotations

BLOCKED_REGIMES: tuple[str, ...] = ("crisis", "risk_off")


def is_blocked(label: object) -> bool:
    return label in BLOCKED_REGIMES


def run_geometry(
    signal_date: str, sessions: list[str], labels: dict[str, str]
) -> tuple[str, int, int, tuple[str, ...]]:
    """信号日 → (形态, 距离, 前导连跑长度, 连跑 label 序) 会话索引算术.

    R176 Op1 自 scripts/regime_blocked_run_conditioning.py 逐字上移
    (R168 Op1 引入, R170 Op1 原地泛化; 仅 _is_blocked → is_blocked 命名随上移,
    算术逐字保留):
    - 形态: "blocked" 自身即阻断日 / "unknown" 不在会话序 / "no_prior"
      窗口内无阻断日 / "normal" 有前导阻断日;
    - dist = 信号日索引 − 最后一个阻断日索引 (≥1; 非 normal 形态为 0);
    - run = 结束于该阻断日的连续阻断日计数 (被 normal 日打断重新计,
      更早的阻断段不延伸); run_labels 为该段自近及远的 label 序;
    - 距离/连跑 → 组名映射见 blocked_run_group (本函数不编码组名)。
    """
    index = {s: i for i, s in enumerate(sessions)}
    idx = index.get(signal_date)
    if idx is None:
        return ("unknown", 0, 0, ())
    if is_blocked(labels.get(signal_date, "")):
        return ("blocked", 0, 0, ())
    j = idx - 1
    while j >= 0 and not is_blocked(labels.get(sessions[j], "")):
        j -= 1
    if j < 0:
        return ("no_prior", 0, 0, ())
    run = 0
    k = j
    run_labels: list[str] = []
    while k >= 0 and is_blocked(labels.get(sessions[k], "")):
        run += 1
        run_labels.append(labels.get(sessions[k], ""))
        k -= 1
    return ("normal", idx - j, run, tuple(run_labels))
