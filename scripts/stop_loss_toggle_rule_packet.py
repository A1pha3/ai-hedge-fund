"""止损开关规则 packet CLI (R195 Op1) — preview / status / --write。

镜像 ``threshold_trigger_k_packet.py`` (R129) 的操作面纪律:

- 默认 preview 对文件系统**零写入** (测试钉死); 假想注册的资格判定明确
  标注未注册;
- ``--write`` 是 **owner 亲自执行** 的预注册动作 (预注册参数属产品方向
  决策, agent 会话绝不代写); 已存在的注册文件**拒绝覆写** — 改写注册 =
  静默替换, 正是反回溯机器要封死的回溯向量;
- ``status``: 注册 tri-state + 当日武装判定 (regime 史 + 夜刷
  exit_anatomy 当期方向 + 执行模式), 读数缺失具名不猜测。

启用判定输入: crisis streak (``daily_action._crisis_streak`` 单一实现)、
当期方向 Δ (``stop_loss_enablement_pack.stop_direction_reading`` 单一
实现, 夜刷 exit_anatomy)、连续非 crisis (``stop_loss_toggle_rule``)。
**武装 ≠ 启用**: 启用判定属 owner (清单项 5), 亲自设
DAILY_ACTION_EXECUTION_STOP (配置不是权限); 纯披露零策略语义变更
(宪法 #2)。

用法::

    uv run python scripts/stop_loss_toggle_rule_packet.py preview
        [--k 5] [--n 5] [--require-delta | --no-require-delta] [--as-of YYYYMMDD]
    uv run python scripts/stop_loss_toggle_rule_packet.py status
    uv run python scripts/stop_loss_toggle_rule_packet.py --write --k 5 --n 5 \
        --require-delta --note "..."
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.screening.offensive import stop_loss_toggle_rule as _rule  # noqa: E402
from src.screening.offensive.daily_action import (  # noqa: E402
    _crisis_streak,
    _current_cn_datetime,
    _load_regime_history,
)
from src.screening.offensive.gap_disclosure import (  # noqa: E402
    latest_exit_anatomy_report,
    report_filename_date,
)
from src.screening.offensive.paper_tracker import _execution_stop_mode  # noqa: E402

DEFAULT_RULE_PATH = Path("data/reports/stop_loss_toggle_rule.json")
PREVIEW_WINDOW_SESSIONS = 30


def _current_direction_delta(reports_dir: Path, label: str | None) -> tuple[float | None, str | None]:
    """当期方向 Δ (最佳止损档 delta_vs_base); 读数缺失 → (None, reason)。"""
    if not label:
        return None, "regime_label_missing"
    from scripts.stop_loss_enablement_pack import stop_direction_reading

    found = latest_exit_anatomy_report(reports_dir)
    if found is None:
        return None, "exit_anatomy_missing"
    report_path, payload = found
    reading = stop_direction_reading(payload, label, report_filename_date(report_path) or "")
    if reading is None:
        return None, "stop_direction_unavailable"
    return reading["best_delta"], None


def _would_have_armed_dates(history: dict[str, str], as_of, k: int) -> list[str]:
    """过去 N 个有标签会话中『当日 crisis streak ≥ k』的日期 (假想推演)。"""
    labeled = sorted(
        (datetime.strptime(str(key), "%Y%m%d").date(), str(label))
        for key, label in history.items()
        if _parseable(key) and datetime.strptime(str(key), "%Y%m%d").date() <= as_of
    )
    window = labeled[-PREVIEW_WINDOW_SESSIONS:]
    armed: list[str] = []
    for day, label in window:
        if label != "crisis":
            continue
        streak = 0
        for prev_day, prev_label in reversed(window):
            if prev_day > day:
                continue
            if prev_label != "crisis":
                break
            streak += 1
        if streak >= k:
            armed.append(day.strftime("%Y%m%d"))
    return armed


def _parseable(key: object) -> bool:
    try:
        datetime.strptime(str(key), "%Y%m%d")
        return True
    except (TypeError, ValueError):
        return False


def _preview(args: argparse.Namespace) -> int:
    as_of = _parse_as_of(args.as_of)
    history = _load_regime_history()
    streak, _anchor = _crisis_streak(history, as_of)
    k, n = args.k, args.n
    print("止损开关规则 packet (preview, 零写入; 假想注册未生效)")
    print(f"  假想规则: k_crisis_sessions={k} · n_normal_to_disable={n} · "
          f"require_delta_positive={args.require_delta}")
    print(f"  当前 (as-of {as_of.strftime('%Y%m%d')}): 连续 crisis {streak} 日 · "
          f"连续非 crisis {_rule.consecutive_non_crisis(history, as_of)} 日 · "
          f"执行模式 {_execution_stop_mode()}")
    hypothetical = _rule.arming_reading(
        {"k_crisis_sessions": k, "n_normal_sessions_to_disable": n,
         "require_delta_positive": args.require_delta},
        crisis_streak=streak, current_delta=None,
        consecutive_non_crisis=_rule.consecutive_non_crisis(history, as_of),
        stop_mode=_execution_stop_mode(),
    )
    print(f"  假想 enable_armed (不含 Δ 条件读数): {hypothetical['enable_armed']}")
    armed_dates = _would_have_armed_dates(history, as_of, k)
    print(f"  过去 {PREVIEW_WINDOW_SESSIONS} 会话 would-have-armed (假想): "
          f"{len(armed_dates)} 日{' · ' + ','.join(armed_dates[-5:]) if armed_dates else ''}")
    print("  --write 是 owner 亲为的预注册动作; 注册后 status 提供机械武装判定")
    return 0


def _status(args: argparse.Namespace) -> int:
    as_of = _parse_as_of(args.as_of)
    rule, reason = _rule.load_rule(Path(args.rule_path))
    if rule is None:
        if reason is None:
            print("status: 未注册 (连亮达标判定属 owner 预注册动作)")
        else:
            print(f"status: 注册损坏 fail-closed — {reason}", file=sys.stderr)
        return 2 if reason else 0
    history = _load_regime_history()
    streak, _anchor = _crisis_streak(history, as_of)
    label = history.get(as_of.strftime("%Y%m%d"))
    delta, missing = _current_direction_delta(Path(args.reports_dir), label)
    non_crisis = _rule.consecutive_non_crisis(history, as_of)
    reading = _rule.arming_reading(
        rule, crisis_streak=streak, current_delta=delta,
        consecutive_non_crisis=non_crisis, stop_mode=_execution_stop_mode(),
    )
    print(json.dumps(
        {"as_of": as_of.strftime("%Y%m%d"), "crisis_streak": streak,
         "consecutive_non_crisis": non_crisis, "current_delta": delta,
         "current_delta_missing_reason": missing, **reading},
        ensure_ascii=False, indent=1,
    ))
    return 0


def _write(args: argparse.Namespace) -> int:
    path = Path(args.rule_path)
    if path.exists():
        print("refuse: 注册文件已存在 (改写注册 = 回溯向量; owner 手动移除后才可重写)",
              file=sys.stderr)
        return 2
    if not args.note or not args.note.strip():
        print("refuse: --note 必填 (注册语义记录)", file=sys.stderr)
        return 2
    rule, errors = _rule.validate_rule({
        "schema": _rule.RULE_SCHEMA,
        "registered_date": (args.registered_date
                            or _current_cn_datetime().strftime("%Y%m%d")),
        "k_crisis_sessions": args.k,
        "n_normal_sessions_to_disable": args.n,
        "require_delta_positive": args.require_delta,
        "note": args.note,
    })
    if rule is None or errors:
        print(f"refuse: 规则校验失败 — {errors}", file=sys.stderr)
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rule, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    print(f"registered: {path}")
    return 0


def _parse_as_of(value: str | None):
    if value:
        return datetime.strptime(value, "%Y%m%d").date()
    return _current_cn_datetime().date()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", default="preview",
                        choices=("preview", "status"))
    parser.add_argument("--write", action="store_true",
                        help="owner 亲为的预注册动作 (预览默认零写入)")
    parser.add_argument("--k", type=int, default=5, help="crisis 连续会话数阈值")
    parser.add_argument("--n", type=int, default=5, help="连续非 crisis 会话数关闭阈值")
    parser.add_argument("--require-delta", dest="require_delta",
                        action="store_true", default=True)
    parser.add_argument("--no-require-delta", dest="require_delta",
                        action="store_false")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--rule-path", default=str(DEFAULT_RULE_PATH))
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--registered-date", default=None)
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    if args.write:
        return _write(args)
    if args.command == "status":
        return _status(args)
    return _preview(args)


if __name__ == "__main__":
    raise SystemExit(main())
