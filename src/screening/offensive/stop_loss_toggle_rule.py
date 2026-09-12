"""止损开关规则 (清单项 5) 的注册与武装判定纯核心 (R195 Op1)。

项 5 登记的决策 (2026-09-12 两面分析): 止损维持不启用; 启用条件预注册为
机械开关规则, 深 crisis 来临时响应是机械的而非临场判断。本模块是规则的
注册装载与武装判定的单一实现 (阈值 K 机器 R112-R129 的 D 面镜像):

- ``validate_rule``: 注册文件严格校验 (schema 精确/日期形状/int 字段 bool
  毒化与负数拒绝/多余键拒绝) — 预注册文件的任何形状漂移都拒绝, 不猜测;
- ``load_rule``: tri-state 装载 (缺失 → (None, None) / 合规 → (rule, None) /
  损坏或校验失败 → (None, reason) fail-closed, 不抛裸异常);
- ``consecutive_non_crisis``: 尾部连续非 crisis 会话数 (镜像
  ``daily_action._crisis_streak`` 的毒化键纪律: 非 YYYYMMDD 键跳过不计数;
  缺日与节假日不可区分的语义边界同 R157 成文, 不声称跨洞连续);
- ``arming_reading``: 武装判定纯函数 —
  enable_armed = crisis_streak ≥ k_crisis_sessions
                 且 (非 require_delta_positive 或 当期方向 Δ > 0, 缺失具名);
  disable_due = consecutive_non_crisis ≥ n_normal_sessions_to_disable
                且 stop_mode ≠ none。
  注册后武装判定机械化; **启用本身仍属 owner 亲设** DAILY_ACTION_EXECUTION_STOP
  (配置不是权限, 本模块不写任何 env/配置)。

纯判定 (宪法 #2): 本模块不进入任何计划/评分/仓位/退出决策路径。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

RULE_SCHEMA = "stop_loss_toggle_rule_v1"

_RULE_INT_FIELDS = ("k_crisis_sessions", "n_normal_sessions_to_disable")
_RULE_DATE_FIELDS = ("registered_date",)


def _valid_date_string(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def validate_rule(raw: object) -> tuple[dict[str, Any] | None, list[str]]:
    """注册文件严格校验; 返回 (合规 rule | None, errors)。多余键一律拒绝。"""
    if not isinstance(raw, dict):
        return None, ["rule_not_object"]
    expected = {"schema", "registered_date", "k_crisis_sessions",
                "n_normal_sessions_to_disable", "require_delta_positive", "note"}
    errors: list[str] = []
    if raw.get("schema") != RULE_SCHEMA:
        errors.append("schema_mismatch")
    unknown = set(raw) - expected
    if unknown:
        errors.append("unknown_fields:" + ",".join(sorted(unknown)))
    for field in _RULE_DATE_FIELDS:
        if not _valid_date_string(raw.get(field)):
            errors.append(f"invalid_{field}")
    for field in _RULE_INT_FIELDS:
        if not _positive_int(raw.get(field)):
            errors.append(f"invalid_{field}")
    if not isinstance(raw.get("require_delta_positive"), bool):
        errors.append("invalid_require_delta_positive")
    if not isinstance(raw.get("note"), str) or not raw["note"].strip():
        errors.append("invalid_note")
    if errors:
        return None, errors
    return dict(raw), []


def load_rule(path: str | Path) -> tuple[dict[str, Any] | None, str | None]:
    """tri-state 装载: 缺失 → (None, None); 合规 → (rule, None);
    不可读/坏 json/校验失败 → (None, reason) — 损坏注册绝不静默当作未注册
    (静默会把『注册被篡改』伪装成『还没注册』, 正是反回溯机器要封死的形态)。
    """
    path = Path(path)
    if not path.exists():
        return None, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "rule_unreadable"
    rule, errors = validate_rule(raw)
    if rule is None:
        return None, "rule_invalid:" + ",".join(errors)
    return rule, None


def consecutive_non_crisis(regimes_by_date: Any, as_of: date) -> int:
    """尾部连续非 crisis 会话数 (从 ≤ as_of 的最新有标签日向前回溯)。

    键非 YYYYMMDD 或解析失败的行跳过 (毒化键不参与计数, R150 教训镜像);
    无可用标签返回 0。regime 史缺日与节假日不可区分的语义边界同
    ``_crisis_streak`` (R157 成文), 不声称跨洞连续。
    """
    labeled: list[tuple[date, str]] = []
    if not isinstance(regimes_by_date, dict):
        return 0
    for key, label in regimes_by_date.items():
        try:
            day = datetime.strptime(str(key), "%Y%m%d").date()
        except (TypeError, ValueError):
            continue
        if day <= as_of:
            labeled.append((day, str(label)))
    if not labeled:
        return 0
    labeled.sort()
    streak = 0
    for _day, label in reversed(labeled):
        if label == "crisis":
            break
        streak += 1
    return streak


def arming_reading(
    rule: object,
    *,
    crisis_streak: int | None,
    current_delta: float | None,
    consecutive_non_crisis: int | None,
    stop_mode: str | None,
) -> dict[str, Any]:
    """武装判定纯函数 (输入缺失具名, 绝不猜测)。

    enable_armed = crisis_streak ≥ k
                   且 (非 require_delta_positive 或 current_delta > 0);
    disable_due  = consecutive_non_crisis ≥ n 且 stop_mode ≠ none (≠ 缺失)。
    """
    if not isinstance(rule, dict):
        return {"registered": False, "reason": "rule_not_loaded"}
    k = rule["k_crisis_sessions"]
    n = rule["n_normal_sessions_to_disable"]
    require_delta = rule["require_delta_positive"]
    reasons: list[str] = []
    enable_armed = True
    if crisis_streak is None:
        enable_armed = False
        reasons.append("regime_history_missing")
    elif crisis_streak < k:
        enable_armed = False
        reasons.append(f"crisis_streak {crisis_streak}/{k}")
    if enable_armed and require_delta:
        if current_delta is None:
            enable_armed = False
            reasons.append("current_delta_missing")
        elif current_delta <= 0:
            enable_armed = False
            reasons.append(f"current_delta {current_delta:+.2%} ≤ 0")
    if enable_armed:
        reasons.append(
            "enable_armed: crisis_streak "
            f"{crisis_streak}≥{k}"
            + (f" 且当期方向 Δ{current_delta:+.2%}>0" if require_delta else "")
        )
    disable_due = (
        consecutive_non_crisis is not None
        and consecutive_non_crisis >= n
        and stop_mode is not None
        and stop_mode != "none"
    )
    return {
        "registered": True,
        "enable_armed": enable_armed,
        "enable_reasons": reasons,
        "disable_due": disable_due,
        "k_crisis_sessions": k,
        "n_normal_sessions_to_disable": n,
        "require_delta_positive": require_delta,
    }


def stop_mode_note(mode: object) -> str | None:
    """清单项 5 止损执行模式子句的单一实现 (R203 Op1)。

    Observe PoC 定谳的作用域真相: ``DAILY_ACTION_EXECUTION_STOP`` 的唯一经济
    消费面是 legacy journal ``close_matured`` (journal 停写 20260813、零持仓);
    生产资本真相在 v2 台账且退出仅 T+10 强制 + 停牌 stale 了结, v2 生命周期
    零止损消费 — mode != none 时旧渲染「已启用」是对生产风险控制的虚假宣称
    (owner 按项 5 预注册程序设变量后视图翻「已启用」而生产惰性, 恰在深
    crisis 损失最大化的场景)。本函数把作用域真相收敛为单一实现, 三消费面
    (v2 渲染行 / enablement pack / toggle rule packet preview) 共用;
    毒化输入 (非 str/空/空白) 返回 None, 调用方省略子句 (fail-open 家族)。

    纯披露 (宪法 #2): 不进入任何计划/评分/仓位/退出决策路径。
    """
    if not isinstance(mode, str) or not mode.strip():
        return None
    if mode == "none":
        return "登记: 不启用 · 生产 v2 台账无止损执行面，退出仅 T+10 强制"
    return (
        "已设，仅作用 legacy journal 研究口径 · "
        "生产 v2 台账无止损执行面，退出仍仅 T+10 强制"
    )
