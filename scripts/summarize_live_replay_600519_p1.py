from __future__ import annotations

import argparse
import json
from pathlib import Path


EXPECTED_BASELINES = {
    "20260224": {
        "replay_score_final": 0.1979,
        "logged_score_final": 0.1584,
        "goal": "pass_watchlist",
    },
    "20260226": {
        "replay_score_final": 0.0791,
        "logged_score_final": 0.1580,
        "goal": "stay_edge",
    },
}


def _load_rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in (payload.get("comparisons") or []) if isinstance(row, dict)]


def _format_float(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def _status_for_row(row: dict) -> tuple[str, str]:
    trade_date = str(row.get("trade_date") or "")
    replay = row.get("replay") or {}
    replay_score_final = float(replay.get("score_final") or 0.0)
    replay_decision = str(replay.get("decision") or "")
    baseline = EXPECTED_BASELINES.get(trade_date, {})

    if trade_date == "20260224":
        if replay_decision != "avoid" and replay_score_final >= 0.20:
            return "ideal", "达到理想验收：已跨过 0.20 watchlist 门槛。"
        if replay_decision == "watch" and replay_score_final > float(baseline.get("replay_score_final") or 0.0):
            return "acceptable", "达到可接受验收：仍未正式过线，但高于旧 replay，方向一致改善。"
        return "not_met", "未达到验收：没有跨过 0.20，且也未明显优于旧 replay。"

    if trade_date == "20260226":
        if replay_score_final < 0.20:
            return "ideal", "达到理想验收：仍保持边缘不过线，没有滑向更激进的 P2 区间。"
        return "not_met", "未达到验收：score_final 已进入通过区间，说明行为比 P1 预期更激进。"

    return "unknown", "无预置验收标准。"


def _markdown_for_row(row: dict, source_path: Path) -> str:
    trade_date = str(row.get("trade_date") or "")
    ticker = str(row.get("ticker") or "")
    variant = str(row.get("variant") or "")
    logged = row.get("logged") or {}
    replay = row.get("replay") or {}
    delta = row.get("delta") or {}
    summary = (replay.get("agent_contribution_summary") or {})
    cohorts = summary.get("cohort_contributions") or {}
    status, note = _status_for_row(row)
    previous = EXPECTED_BASELINES.get(trade_date, {})

    lines = [
        f"### {trade_date} / {ticker}",
        "",
        f"- 来源文件：{source_path}",
        f"- variant：{variant}",
        f"- logged：score_final={_format_float(logged.get('score_final'))}，decision={logged.get('decision') or 'n/a'}，bc_conflict={logged.get('bc_conflict')}",
        f"- replay：score_c={_format_float(replay.get('score_c'))}，score_final={_format_float(replay.get('score_final'))}，decision={replay.get('decision') or 'n/a'}，bc_conflict={replay.get('bc_conflict')}",
        f"- delta：score_c={_format_float(delta.get('score_c'))}，score_final={_format_float(delta.get('score_final'))}",
        f"- cohort：investor={_format_float(cohorts.get('investor'))}，analyst={_format_float(cohorts.get('analyst'))}，other={_format_float(cohorts.get('other'))}",
        f"- 对照基线：旧 replay score_final={_format_float(previous.get('replay_score_final'))}，旧 logged score_final={_format_float(previous.get('logged_score_final'))}",
        f"- 验收结论：{status}",
        f"- 说明：{note}",
        "",
        "可直接贴入文档的结论：",
        "",
        f"> {trade_date} / {ticker} 的 live replay 结果为 score_c={_format_float(replay.get('score_c'))}、score_final={_format_float(replay.get('score_final'))}、decision={replay.get('decision') or 'n/a'}、bc_conflict={replay.get('bc_conflict')}。相较既有 replay，score_final 变化 {_format_float(delta.get('score_final'))}。{note}",
        "",
    ]
    return "\n".join(lines)


def build_markdown(paths: list[Path]) -> str:
    sections: list[str] = [
        "## 600519 P1 Live Replay 汇总",
        "",
        "本摘要用于快速判断 20260224 和 20260226 两个目标日期是否符合 P1 的最小业务补证预期。",
        "",
    ]
    for path in paths:
        rows = _load_rows(path)
        matched_rows = [row for row in rows if str(row.get("ticker") or "") == "600519"]
        if not matched_rows:
            sections.append(f"### {path.name}")
            sections.append("- 未找到 600519 的 comparison 行。")
            sections.append("")
            continue
        for row in sorted(matched_rows, key=lambda item: str(item.get("trade_date") or "")):
            sections.append(_markdown_for_row(row, path))
    return "\n".join(sections).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize live replay results for 600519 under P1 defaults")
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Optional replay JSON files. Defaults to the two canonical 600519 replay outputs.",
    )
    parser.add_argument("--output", help="Optional markdown output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.inputs:
        input_paths = [Path(item).resolve() for item in args.inputs]
    else:
        root_dir = Path(__file__).resolve().parents[1]
        input_paths = [
            root_dir / "data/reports/live_replay_600519_20260224_p1.json",
            root_dir / "data/reports/live_replay_600519_20260226_p1.json",
        ]

    markdown = build_markdown(input_paths)
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())