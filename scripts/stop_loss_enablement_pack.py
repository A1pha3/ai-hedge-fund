"""止损启用 (清单项 5) 两面证据决策包 CLI (R193 Op1)。

项 5 登记 (2026-08-22): 止损维持不启用; 启用条件 = regime 连续 crisis 或
组合回撤近 -15% 时, owner 判断 + 先跑 backtest_exit_strategies.py 确认
当期方向再设 DAILY_ACTION_EXECUTION_STOP。日度读数行
(``daily_action._render_stop_loss_readiness_line``, R181) 已把两面读数拆开
呈现, 但「两面齐备再设」此前没有机械装配面: 样本期方向只有手动 stdout
表格 (无机器可读/无新鲜度/无排除项持久), 两面无合取判定, owner 判定输入
要逐工具拼读。本工具把两面一次装配成一份可审计决策包:

- face A 当期方向: 夜刷 ``btst_exit_anatomy`` 的 production×regime 止损
  反事实网格 (诚实成交语义: 跳空按 open 成交) — 读数经
  ``gap_disclosure.latest_exit_anatomy_report`` (唯一读取家) +
  ``gap_disclosure.best_stop_tier`` (档位选择单一实现, 与日行渲染同源);
- face B 样本期方向: ``backtest_exit_strategies.py`` 冻结 journal 恢复
  样本 (2026-01-15→07-06) 的策略对比 — 优先消费 ``--json`` 机器可读排放
  (journal 以 sha256 绑定, 新鲜度/替换可见), 也可子进程现场生成;
- 合取判定 = 「两面读数是否齐备」的机械事实 (缺哪面具名), 不是启用建议。

使用纪律:
- 纯披露 (宪法 #2): 本工具不进入任何计划/评分/仓位/退出决策路径;
  齐备 ≠ 启用, 启用判定属 owner (清单项 5), 亲自设 DAILY_ACTION_EXECUTION_STOP。
- fail-open 家族纪律 (R85/R115/R119/R149/R181 同族): 任一面证据缺失/
  损坏/形状不符 → 该面读数 None + 缺失原因具名, 绝不猜测、不部分渲染;
  渲染面畸形输入 → 整节省略不崩溃。
- 输出确定性: 载荷无墙钟 (as-of 由 ``--as-of`` 显式声明), 同输入同字节。

用法::

    uv run python scripts/stop_loss_enablement_pack.py [--as-of YYYYMMDD]
        [--reports-dir data/reports] [--regime-history data/reports/regime_history.json]
        [--backtest-json PATH | (--journal/--cache-dir/--time-exit 子进程透传)]
        [--drawdown -0.05] [--out-dir data/reports]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.screening.offensive import gap_disclosure  # noqa: E402
from src.screening.offensive.gap_disclosure import (  # noqa: E402
    best_stop_tier,
    latest_exit_anatomy_report,
    report_filename_date,
)

# 单一实现纪律: crisis streak / regime 史读取 / CN 时钟 / 执行模式读取全部
# 复用 daily_action 与 paper_tracker 既有实现 (R137/R181 同源消费), 不在本
# 脚本重写第二套 (标签解析/毒化键跳过/连续性语义已在源内成文并有测试)。
from src.screening.offensive.daily_action import (  # noqa: E402
    _crisis_streak,
    _current_cn_datetime,
    _load_regime_history,
)
from src.screening.offensive.paper_tracker import _execution_stop_mode  # noqa: E402

PACK_SCHEMA = "stop_loss_enablement_pack_v1"
BACKTEST_SCHEMA = "backtest_exit_strategies_json_v1"

_FIXED_TIER_RE = re.compile(r"^fixed (-?\d+(?:\.\d+)?)%")
_FINITE_TIER_RE = gap_disclosure._STOP_TIER_RE
_DISCLAIMER = (
    "两面齐备只是读数齐备的机械事实, 不是启用建议; 启用判定属 owner "
    "(清单项 5), 纯披露零策略语义变更 (宪法 #2)。当期方向回答「现在这个 "
    "regime 止损是否有利」, 样本期方向回答「历史样本里止损是否降 E」——"
    "两面方向相反时由 owner 权衡。"
)


def _finite(value: object) -> bool:
    return gap_disclosure._finite_number(value)


def stop_direction_reading(
    payload: object,
    regime_label: object,
    report_date: str,
) -> dict[str, Any] | None:
    """face A 结构化读数: 与 stop_direction_clause 同守卫同选择, 不渲染。

    形状不符/样本为 0/基准非有限/无最佳档 → None (不假装有证据)。
    """
    if regime_label not in gap_disclosure._STOP_DIRECTION_REGIME_LABELS:
        return None
    if not report_date or not isinstance(report_date, str):
        return None
    if not isinstance(payload, dict):
        return None
    production = payload.get("production")
    if not isinstance(production, dict):
        return None
    by_regime = production.get("by_regime")
    if not isinstance(by_regime, dict):
        return None
    bucket = by_regime.get(regime_label)
    if not isinstance(bucket, dict):
        return None
    n_total = bucket.get("n_included")
    if not _finite(n_total) or n_total <= 0:
        return None
    base = bucket.get("base")
    base_mean = base.get("mean_net") if isinstance(base, dict) else None
    if not _finite(base_mean):
        return None
    found = best_stop_tier(bucket.get("stop_grid"))
    if found is None:
        return None
    best_tier, best_delta, best_entry = found
    reading: dict[str, Any] = {
        "as_of": report_date,
        "regime": regime_label,
        "n": int(n_total),
        "base_mean": float(base_mean),
        "best_tier": best_tier,
        "best_delta": best_delta,
    }
    if _finite(best_entry.get("mean_net")):
        reading["best_mean"] = float(best_entry["mean_net"])
    if _finite(best_entry.get("n_stopped")):
        reading["n_stopped"] = int(best_entry["n_stopped"])
    if _finite(best_entry.get("n_gap_through")):
        reading["n_gap_through"] = int(best_entry["n_gap_through"])
    return reading


def sample_direction_reading(backtest_payload: object) -> dict[str, Any] | None:
    """face B 结构化读数: 消费 backtest_exit_strategies --json 排放。

    固定档相对 no_stop 的 Δ 重新构造为网格后经 ``best_stop_tier`` 选择
    (浅档平局纪律与 face A 同一实现); 排除项计数原样透传 (样本侵蚀可
    观测)。schema/journal_sha256/no_stop 行/任一固定档缺失或形状不符 →
    None (半份证据不冒充整份)。
    """
    if not isinstance(backtest_payload, dict):
        return None
    if backtest_payload.get("schema") != BACKTEST_SCHEMA:
        return None
    journal_sha = backtest_payload.get("journal_sha256")
    if not isinstance(journal_sha, str) or not journal_sha:
        return None
    n_trades = backtest_payload.get("n_trades")
    if not _finite(n_trades) or n_trades <= 0:
        return None
    strategies = backtest_payload.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        return None
    no_stop_e: float | None = None
    tiers: dict[str, dict[str, float]] = {}
    for row in strategies:
        if not isinstance(row, dict):
            continue
        mode = row.get("stop_mode")
        n = row.get("n")
        e = row.get("E")
        if mode == "none" and _finite(n) and n > 0 and _finite(e):
            no_stop_e = float(e)
            continue
        label = row.get("label")
        if (
            mode == "fixed_pct"
            and isinstance(label, str)
            and _finite(n)
            and n > 0
            and _finite(e)
        ):
            match = _FIXED_TIER_RE.match(label)
            if match is not None:
                tiers[f"{match.group(1)}%"] = {"delta_vs_base": float(e)}
    if no_stop_e is None or not tiers:
        return None
    grid = {
        tier: {"delta_vs_base": body["delta_vs_base"] - no_stop_e}
        for tier, body in tiers.items()
    }
    found = best_stop_tier(grid)
    if found is None:
        return None
    best_tier, best_delta, _ = found
    tier_rows = [
        {"tier": tier, "delta": body["delta_vs_base"]}
        for tier, body in sorted(
            grid.items(), key=lambda kv: abs(float(kv[0].rstrip("%")))
        )
    ]
    return {
        "journal_sha256": journal_sha,
        "n_trades": int(n_trades),
        "no_stop_e": no_stop_e,
        "tiers": tier_rows,
        "best_tier": best_tier,
        "best_delta": best_delta,
    }


def assemble_pack(
    *,
    as_of: str,
    crisis_streak: tuple[int, Any] | None,
    drawdown: float | None,
    face_a: dict[str, Any] | None,
    face_b: dict[str, Any] | None,
    stop_mode: str,
    drawdown_ref: float,
) -> dict[str, Any]:
    """两面 + 上下文 + 机械合取判定装配 (无建议, 无墙钟)。"""
    missing: list[str] = []
    if face_a is None:
        missing.append("face_a_current")
    if face_b is None:
        missing.append("face_b_sample")
    payload: dict[str, Any] = {
        "schema": PACK_SCHEMA,
        "as_of": as_of,
        "faces_ready": not missing,
        "missing_faces": missing,
        "face_a_current": face_a,
        "face_b_sample": face_b,
        "stop_mode": stop_mode,
        "disclaimer": _DISCLAIMER,
    }
    if crisis_streak is not None:
        streak, anchor = crisis_streak
        body: dict[str, Any] = {"streak": int(streak)}
        if anchor is not None:
            body["anchor"] = anchor.strftime("%Y%m%d")
        payload["crisis_streak"] = body
    if _finite(drawdown):
        payload["drawdown"] = {
            "value": float(drawdown),
            "ref": float(drawdown_ref),
            "margin_pp": (float(drawdown) - float(drawdown_ref)) * 100,
        }
    return payload


def render_md(payload: object) -> str:
    """操作员面渲染 (fail-open: 畸形字段整节省略, 绝不崩溃不部分垃圾)。"""
    if not isinstance(payload, dict):
        return ""
    as_of = payload.get("as_of")
    if not isinstance(as_of, str) or not as_of:
        return ""
    lines = [f"# 止损启用两面证据决策包（as-of {as_of}）", ""]
    ready = payload.get("faces_ready")
    if ready is True:
        lines += ["结论：两面齐备 = 是", ""]
    elif ready is False:
        missing = payload.get("missing_faces")
        names = {
            "face_a_current": "当期方向",
            "face_b_sample": "样本期方向",
        }
        if isinstance(missing, list) and missing:
            zh = "、".join(names.get(m, str(m)) for m in missing if isinstance(m, str))
            lines += [f"结论：两面齐备 = 否（缺：{zh}）", ""]
        else:
            lines += ["结论：两面齐备 = 否", ""]
    else:
        return ""

    streak_body = payload.get("crisis_streak")
    if isinstance(streak_body, dict) and _finite(streak_body.get("streak")):
        anchor = streak_body.get("anchor")
        anchor_note = (
            f"（截至 {anchor[4:6]}{anchor[6:8]}）"
            if isinstance(anchor, str) and len(anchor) == 8
            else ""
        )
        lines += [
            f"Regime：连续 crisis {int(streak_body['streak'])} 日{anchor_note}",
            "",
        ]
    dd = payload.get("drawdown")
    if isinstance(dd, dict) and _finite(dd.get("value")) and _finite(dd.get("ref")):
        margin = dd.get("margin_pp")
        margin_note = (
            f"，余量 {float(margin):+.1f}pp" if _finite(margin) else ""
        )
        lines += [
            f"回撤：{float(dd['value']):.1%}（距 {float(dd['ref']):.0%} 降仓参考线{margin_note}）",
            "",
        ]
    mode = payload.get("stop_mode")
    if isinstance(mode, str) and mode:
        note = "已启用" if mode != "none" else "登记: 不启用"
        lines += [f"止损执行模式：{mode}（{note}）", ""]

    face_a = payload.get("face_a_current")
    lines += ["## 当期方向（face A）", ""]
    if (
        isinstance(face_a, dict)
        and isinstance(face_a.get("best_tier"), str)
        and _finite(face_a.get("best_delta"))
    ):

        def _pct(value: object) -> str:
            return f"{float(value) * 100:+.2f}%"

        head = (
            f"exit_anatomy {face_a.get('as_of', '?')} · "
            f"生产表/{face_a.get('regime', '?')}/全候选 · n={face_a.get('n', '?')}"
        )
        body = (
            f"基准 {_pct(face_a.get('base_mean'))} · "
            f"最佳止损档 {face_a['best_tier']}（Δ{float(face_a.get('best_delta')) * 100:+.2f}pp"
        )
        if _finite(face_a.get("best_mean")):
            body += f"，档内 {_pct(face_a.get('best_mean'))}"
        if _finite(face_a.get("n_stopped")) and _finite(face_a.get("n")):
            body += f"，触发 {int(face_a['n_stopped'])}/{int(face_a['n'])}"
        if _finite(face_a.get("n_gap_through")):
            body += f"，跳空穿越 {int(face_a['n_gap_through'])}"
        body += "）"
        lines += [head, body, "口径: 夜刷 btst_exit_anatomy production×regime 止损反事实（跳空按 open 成交）", ""]
    else:
        lines += ["缺失：当期方向证据未就绪（夜刷 exit_anatomy 报告缺失/损坏/标签不匹配）", ""]

    face_b = payload.get("face_b_sample")
    lines += ["## 样本期方向（face B）", ""]
    if (
        isinstance(face_b, dict)
        and isinstance(face_b.get("journal_sha256"), str)
        and isinstance(face_b.get("tiers"), list)
    ):
        sha = face_b["journal_sha256"]
        lines += [
            f"journal sha256: {sha[:16]}… · n_trades={face_b.get('n_trades', '?')} · "
            f"no_stop E={float(face_b.get('no_stop_e')) * 100:+.2f}%"
            if _finite(face_b.get("no_stop_e"))
            else f"journal sha256: {sha[:16]}… · n_trades={face_b.get('n_trades', '?')}",
        ]
        tier_cells = []
        for row in face_b["tiers"]:
            if isinstance(row, dict) and isinstance(row.get("tier"), str) and _finite(row.get("delta")):
                tier_cells.append(
                    f"{row['tier']} Δ{float(row['delta']) * 100:+.2f}pp"
                )
        if tier_cells:
            lines.append("固定档相对 no_stop：")
            lines.append(" · ".join(tier_cells))
        if isinstance(face_b.get("best_tier"), str) and _finite(face_b.get("best_delta")):
            lines.append(
                f"最佳固定档：{face_b['best_tier']}（Δ{float(face_b['best_delta']) * 100:+.2f}pp）"
            )
        lines += [
            "口径: backtest_exit_strategies.py 冻结 journal 恢复样本 2026-01-15→07-06（非当期），"
            "回溯复权 + 跳空按 open 成交 + 滑点 10bps/边",
            "",
        ]
    else:
        lines += ["缺失：样本期方向证据未就绪（backtest_exit_strategies --json 缺失/损坏/守卫拒绝）", ""]

    lines += ["## 纪律", "", _DISCLAIMER, ""]
    return "\n".join(lines)


def _load_backtest_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "backtest_json_unreadable"
    if sample_direction_reading(payload) is None:
        return None, "backtest_json_invalid_shape"
    return payload, None


def _generate_backtest_json(args: argparse.Namespace) -> tuple[dict[str, Any] | None, str | None]:
    tool = Path(__file__).resolve().parent / "backtest_exit_strategies.py"
    import tempfile

    command = [sys.executable, str(tool), "--time-exit", str(args.time_exit)]
    if args.journal:
        command += ["--journal", args.journal]
    if args.cache_dir:
        command += ["--cache-dir", args.cache_dir]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        tmp_path = Path(handle.name)
    try:
        proc = subprocess.run(
            [*command, "--json", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if proc.returncode != 0 or not tmp_path.exists():
            return None, f"backtest_tool_failed_rc_{proc.returncode}"
        payload, reason = _load_backtest_json(tmp_path)
        return payload, reason
    except subprocess.TimeoutExpired:
        return None, "backtest_tool_timeout"
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--as-of", default=None, help="as-of 日期 YYYYMMDD (默认 CN 今天)")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--regime-history", default="data/reports/regime_history.json")
    parser.add_argument("--backtest-json", dest="backtest_json", default=None,
                        help="已生成的 backtest --json 路径 (缺省子进程现场生成)")
    parser.add_argument("--journal", default=None, help="子进程透传: journal jsonl")
    parser.add_argument("--cache-dir", default=None, help="子进程透传: price_cache 目录")
    parser.add_argument("--time-exit", type=int, default=10, help="子进程透传: 时间退出 horizon")
    parser.add_argument("--drawdown", type=float, default=None,
                        help="组合回撤 (当日 --daily-action 台账行; 缺省该子句省略)")
    parser.add_argument("--out-dir", default="data/reports")
    parser.add_argument("--print", action="store_true", help="渲染 MD 到 stdout")
    args = parser.parse_args()

    as_of = args.as_of or _current_cn_datetime().strftime("%Y%m%d")
    as_of_date = datetime.strptime(as_of, "%Y%m%d").date()
    history = _load_regime_history()
    label = history.get(as_of)
    streak = _crisis_streak(history, as_of_date)

    face_a: dict[str, Any] | None = None
    if label:
        found = latest_exit_anatomy_report(Path(args.reports_dir))
        if found is not None:
            report_path, anatomy = found
            face_a = stop_direction_reading(
                anatomy, label, report_filename_date(report_path) or ""
            )

    if args.backtest_json:
        face_b_payload, _ = _load_backtest_json(Path(args.backtest_json))
    else:
        face_b_payload, _ = _generate_backtest_json(args)
    face_b = sample_direction_reading(face_b_payload) if face_b_payload else None

    from src.screening.offensive.daily_action import _STOP_READINESS_DRAWDOWN_REF

    payload = assemble_pack(
        as_of=as_of,
        crisis_streak=streak,
        drawdown=args.drawdown,
        face_a=face_a,
        face_b=face_b,
        stop_mode=_execution_stop_mode(),
        drawdown_ref=_STOP_READINESS_DRAWDOWN_REF,
    )

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = _PROJECT_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"stop_loss_enablement_pack_{as_of}.json"
    md_path = out_dir / f"stop_loss_enablement_pack_{as_of}.md"
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
