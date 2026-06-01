from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from scripts.analyze_btst_early_runner_v1 import analyze_btst_early_runner_v1
from scripts.btst_strategy_thresholds import (
    DEFAULT_STRATEGY_THRESHOLDS_PROFILE,
    resolve_strategy_thresholds,
    resolve_strategy_thresholds_config_path,
)
from scripts.generate_btst_early_runner_daily_tables import generate_btst_early_runner_daily_tables
from src.paper_trading.btst_decision_enrichment import (
    attach_execution_semantics,
    build_historical_reliability_metrics,
    build_decision_card,
    build_execution_semantics,
    build_premarket_control_tower,
    build_report_mode,
    build_review_ledger_rows,
    build_veto_owner,
    enrich_btst_row,
    estimate_execution_cost_cap,
)
from src.paper_trading.btst_reporting_utils import _format_rollout_value

REPORTS_DIR = Path("data/reports")
OUTPUTS_DIR = Path("outputs")


def _normalize_signal_date(value: str) -> tuple[str, str]:
    """Normalize a signal date into compact and ISO formats."""
    raw = str(value or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return raw, f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        compact = raw.replace("-", "")
        if compact.isdigit():
            return compact, raw
    raise ValueError(f"unsupported signal date: {value!r}")


def _read_json(path: Path) -> dict[str, Any]:
    """Read one JSON file into a dict."""
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _write_text(path: Path, content: str) -> None:
    """Write UTF-8 text and create parent directories when needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _safe_rows(value: Any) -> list[dict[str, Any]]:
    """Convert mixed JSON payloads into a list of row dicts."""
    return [dict(item or {}) for item in list(value or [])]


def _tag_rows(rows: list[dict[str, Any]], table_key: str) -> list[dict[str, Any]]:
    """Attach one stable table key to rows so downstream docs can keep four-layer semantics."""
    tagged_rows = []
    for row in rows:
        tagged = dict(row)
        tagged.setdefault("table_key", table_key)
        tagged_rows.append(tagged)
    return tagged_rows


def _fmt_pct(value: Any, digits: int = 2) -> str:
    """Render mixed numeric values into percentage text."""
    try:
        if value is None or value == "":
            return "n/a"
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_num(value: Any, digits: int = 4) -> str:
    """Render mixed numeric values into decimal text."""
    try:
        if value is None or value == "":
            return "n/a"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _resolve_thresholds_config_path(
    config_path: str | Path | None = None,
    *,
    profile: str | None = None,
) -> str:
    """Return the visible BTST strategy-threshold config path for generated docs."""
    return resolve_strategy_thresholds_config_path(config_path, profile=profile).as_posix()


def _stock_label(entry: dict[str, Any]) -> str:
    """Format one stock as code plus name when the name is available."""
    ticker = str(entry.get("ticker") or "").strip()
    name = str(entry.get("name") or "").strip()
    return f"{ticker} {name}".strip()


def _enriched_stock_label(row: dict[str, Any]) -> str:
    ticker = str(row.get("ticker") or "").strip()
    name = str(row.get("name") or "").strip()
    return f"{ticker} {name}".strip()


def _stock_name_suffix(entry: dict[str, Any]) -> str:
    """Return a short Chinese-name suffix for compact code-first fields."""
    name = str(entry.get("name") or "").strip()
    return f"（{name}）" if name else ""


def _stock_labels(rows: list[dict[str, Any]], *, limit: int | None = None) -> list[str]:
    """Return display labels for compact list fields."""
    selected = rows if limit is None else rows[:limit]
    return [_stock_label(row) for row in selected if _stock_label(row)]


def _stock_labels_text(rows: list[dict[str, Any]], *, limit: int | None = None) -> str:
    """Return a human-readable compact stock-label list."""
    labels = _stock_labels(rows, limit=limit)
    return "、".join(labels) if labels else "无"


_STOCK_NAME_EVENT_PREFIXES = ("*ST", "ST", "XD", "XR", "DR", "N", "C")


def _strip_stock_name_event_prefix(name: str) -> str:
    """Remove exchange event prefixes from display names without guessing missing characters."""
    text = str(name or "").strip()
    changed = True
    while changed:
        changed = False
        for prefix in _STOCK_NAME_EVENT_PREFIXES:
            if text.startswith(prefix) and len(text) > len(prefix):
                text = text[len(prefix) :].strip()
                changed = True
                break
    return text


def _stock_name_has_event_prefix(name: str) -> bool:
    text = str(name or "").strip()
    return any(text.startswith(prefix) and len(text) > len(prefix) for prefix in _STOCK_NAME_EVENT_PREFIXES)


def _stock_name_quality(name: str) -> tuple[int, int]:
    text = str(name or "").strip()
    if not text:
        return (0, 0)
    canonical = _strip_stock_name_event_prefix(text)
    return (0 if _stock_name_has_event_prefix(text) else 1, len(canonical))


def _prefer_stock_name(current: str | None, candidate: str | None) -> str:
    """Pick the cleaner stock name when multiple local artifacts disagree."""
    current_text = str(current or "").strip()
    candidate_text = str(candidate or "").strip()
    if not candidate_text:
        return current_text
    normalized_candidate = _strip_stock_name_event_prefix(candidate_text)
    if not current_text:
        return normalized_candidate
    if _stock_name_quality(candidate_text) > _stock_name_quality(current_text):
        return normalized_candidate
    return _strip_stock_name_event_prefix(current_text)


def _collect_tickers_from_payload(value: Any, tickers: set[str]) -> None:
    """Collect ticker symbols from nested artifacts."""
    if isinstance(value, dict):
        ticker = str(value.get("ticker") or "").strip()
        if ticker:
            tickers.add(ticker)
        for child in value.values():
            _collect_tickers_from_payload(child, tickers)
        return
    if isinstance(value, list):
        for item in value:
            _collect_tickers_from_payload(item, tickers)


def _collect_stock_names_from_payload(value: Any, names: dict[str, str]) -> None:
    """Collect ticker-name pairs already present in nested artifacts."""
    if isinstance(value, dict):
        ticker = str(value.get("ticker") or "").strip()
        name = str(value.get("name") or "").strip()
        if ticker and name:
            names[ticker] = _prefer_stock_name(names.get(ticker), name)
        for child in value.values():
            _collect_stock_names_from_payload(child, names)
        return
    if isinstance(value, list):
        for item in value:
            _collect_stock_names_from_payload(item, names)


def _extract_stock_name_from_snapshot_summary(text: str, ticker: str) -> str:
    """Extract one stock name from a local data snapshot summary."""
    for pattern in (
        r"- \*\*股票名称\*\*：([^\n]+)",
        rf"#\s*{re.escape(ticker)}[（(]([^）)]+)[）)]数据快照",
    ):
        match = re.search(pattern, text)
        if match:
            return str(match.group(1)).strip()
    return ""


def _collect_stock_names_from_snapshots(report_dir: Path) -> dict[str, str]:
    """Read local data snapshot summaries and return ticker-name pairs."""
    snapshot_root = report_dir / "data_snapshots"
    if not snapshot_root.exists():
        return {}
    names: dict[str, str] = {}
    for summary_path in snapshot_root.glob("*/*/summary.md"):
        ticker = summary_path.parent.parent.name
        try:
            name = _extract_stock_name_from_snapshot_summary(
                summary_path.read_text(encoding="utf-8"),
                ticker,
            )
        except OSError:
            continue
        if ticker and name:
            names[ticker] = _prefer_stock_name(names.get(ticker), name)
    return names


def _collect_stock_names_from_sibling_snapshots(reports_root: Path, tickers: set[str]) -> dict[str, str]:
    """Find cleaner historical names for requested tickers from sibling report snapshots."""
    names: dict[str, str] = {}
    if not reports_root.exists():
        return names
    for ticker in sorted(tickers):
        for summary_path in reports_root.glob(f"*/data_snapshots/{ticker}/*/summary.md"):
            try:
                name = _extract_stock_name_from_snapshot_summary(
                    summary_path.read_text(encoding="utf-8"),
                    ticker,
                )
            except OSError:
                continue
            if name:
                names[ticker] = _prefer_stock_name(names.get(ticker), name)
    return names


def _apply_stock_names_to_payload(value: Any, names: dict[str, str]) -> None:
    """Fill missing names in nested artifact payloads without overwriting existing names."""
    if isinstance(value, dict):
        ticker = str(value.get("ticker") or "").strip()
        current_name = str(value.get("name") or "").strip()
        if ticker and names.get(ticker):
            value["name"] = _prefer_stock_name(current_name, names[ticker])
        for child in value.values():
            _apply_stock_names_to_payload(child, names)
        return
    if isinstance(value, list):
        for item in value:
            _apply_stock_names_to_payload(item, names)


def _enrich_missing_stock_names(
    *,
    reports_root: Path,
    report_dir: Path,
    rule_report: dict[str, Any],
    brief: dict[str, Any],
    priority_board: dict[str, Any],
    early_runner: dict[str, Any],
) -> dict[str, str]:
    """Build a local name map and apply it to current BTST artifacts."""
    names: dict[str, str] = {}
    tickers: set[str] = set()
    for payload in (rule_report, brief, priority_board, early_runner):
        _collect_tickers_from_payload(payload, tickers)
        _collect_stock_names_from_payload(payload, names)
    names.update(_collect_stock_names_from_snapshots(report_dir))
    for ticker, name in _collect_stock_names_from_sibling_snapshots(reports_root, tickers).items():
        names[ticker] = _prefer_stock_name(names.get(ticker), name)
    for payload in (rule_report, brief, priority_board, early_runner):
        _apply_stock_names_to_payload(payload, names)
    return names


def _enrich_formal_rows(rows: list[dict[str, Any]], *, role: str, early_runner_status: str) -> list[dict[str, Any]]:
    return [enrich_btst_row(row, role=role, early_runner_status=early_runner_status) for row in rows]


def _enrich_early_runner_rows(
    rows: list[dict[str, Any]],
    *,
    role: str,
    early_runner_status: str,
) -> list[dict[str, Any]]:
    return [enrich_btst_row(row, role=role, early_runner_status=early_runner_status) for row in rows]


def _render_decision_card(card: dict[str, Any]) -> list[str]:
    primary = {
        "ticker": str(card.get("primary_ticker") or "").strip(),
        "name": str(card.get("primary_name") or "").strip(),
    }
    return [
        "## 30 秒决策卡",
        "",
        f"- 交易倾向：`{card.get('trade_bias')}`。",
        f"- 主票：`{card.get('primary_ticker') or 'n/a'}`{_stock_name_suffix(primary)}。",
        f"- 证据等级：`{card.get('evidence_grade')}`；数据质量：`{card.get('data_quality')}`；风险姿态：`{card.get('risk_posture')}`。",
        f"- 必须确认：{card.get('must_confirm')}",
        f"- 失效条件：{card.get('invalidate_if')}",
        f"- early-runner 状态：`{card.get('early_runner_status')}`。",
    ]


def _attach_decision_card_primary_name(card: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach the display name of the primary ticker to a compact decision card."""
    result = dict(card)
    primary_ticker = str(result.get("primary_ticker") or "").strip()
    for row in rows:
        if str(row.get("ticker") or "").strip() == primary_ticker:
            result["primary_name"] = str(row.get("name") or "").strip()
            break
    return result


def _row_historical_metric(row: dict[str, Any], key: str) -> Any:
    """Return one historical metric from nested prior first, then from the row itself."""
    source_row = dict(row.get("source_row") or {})
    prior = dict(row.get("historical_prior") or source_row.get("historical_prior") or {})
    value = prior.get(key)
    if value not in (None, "", [], {}, ()):
        return value
    value = row.get(key)
    if value not in (None, "", [], {}, ()):
        return value
    return source_row.get(key)


def _row_field(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if value not in (None, "", [], {}, ()):
        return value
    return dict(row.get("source_row") or {}).get(key)


def _historical_reading_note(row: dict[str, Any]) -> str:
    """Explain how to read historical win-rate and payoff numbers for one stock."""
    rate = _row_historical_metric(row, "next_close_positive_rate")
    payoff = _row_historical_metric(row, "next_close_payoff_ratio")
    evaluable = _row_historical_metric(row, "evaluable_count")
    try:
        rate_value = None if rate in (None, "") else float(rate)
    except (TypeError, ValueError):
        rate_value = None
    try:
        payoff_value = None if payoff in (None, "") else float(payoff)
    except (TypeError, ValueError):
        payoff_value = None
    note_parts: list[str] = []
    if rate_value is None and payoff_value is None:
        note = "胜率和盈亏比暂缺，只能先把它当成轻量历史先验。"
    else:
        if rate_value is None:
            note_parts.append("胜率暂缺")
        elif rate_value >= 0.70:
            note_parts.append("胜率高")
        elif rate_value >= 0.55:
            note_parts.append("胜率中性偏强")
        elif rate_value >= 0.45:
            note_parts.append("胜率中性")
        else:
            note_parts.append("胜率偏弱")
        if payoff_value is None:
            note_parts.append("盈亏比暂缺，通常表示历史正负样本拆分不足")
        elif payoff_value >= 2.0:
            note_parts.append("盈亏比优秀，赚钱时通常能明显覆盖亏损")
        elif payoff_value >= 1.0:
            note_parts.append("盈亏比站上 1.00，赚钱时大体能覆盖亏损")
        else:
            note_parts.append("盈亏比低于 1.00，更像靠命中率吃小胜")
        note = "，".join(note_parts) + "。"
    try:
        evaluable_count = None if evaluable in (None, "") else int(evaluable)
    except (TypeError, ValueError):
        evaluable_count = None
    if evaluable_count is not None and evaluable_count < 5:
        note = note[:-1] + "；样本偏少，只能作弱参考。"
    elif evaluable_count is not None and evaluable_count < 10:
        note = note[:-1] + "；样本不大，宜配合盘中确认。"
    return note


def _render_historical_metric_guide() -> list[str]:
    """Render one shared guide that explains historical win-rate and payoff metrics."""
    return [
        "## 指标怎么读",
        "",
        "- `收盘胜率` 看的是历史上次日收盘为正的比例，越高代表历史命中率越好。",
        "- `盈亏比` 大于 `1.00` 才说明平均赚幅大体能覆盖平均亏幅；低于 `1.00` 往往更依赖命中率。",
        "- 如果文档写 `n/a`，通常表示历史正负样本拆分不足，先验只能轻量参考，不能把空字段误读成强信号。",
    ]


def _is_intraday_only(row: dict[str, Any]) -> bool:
    """Return whether a selected row should be treated as intraday-only."""
    mode = str(row.get("preferred_entry_mode") or "")
    payoff = _row_historical_metric(row, "next_close_payoff_ratio")
    try:
        payoff_value = None if payoff in (None, "") else float(payoff)
    except (TypeError, ValueError):
        payoff_value = None
    return mode == "intraday_confirmation_only" or (payoff_value is not None and payoff_value < 1.0)


def _render_win_rate_payoff_decision(rows: list[dict[str, Any]]) -> list[str]:
    """Render the execution priority through the win-rate/payoff lens."""
    lines = ["## 胜率/赔率优先决策", ""]
    if not rows:
        lines.append("- 当前没有正式执行票，胜率/赔率闸门不放行。")
        return lines
    hold_candidates = [row for row in rows if not _is_intraday_only(row)]
    intraday_only = [row for row in rows if _is_intraday_only(row)]
    if hold_candidates:
        first = hold_candidates[0]
        lines.append(f"- 第一优先：`{_stock_label(first)}`，收盘胜率 `{_fmt_pct(_row_historical_metric(first, 'next_close_positive_rate'))}`，" f"盈亏比 `{_fmt_num(_row_historical_metric(first, 'next_close_payoff_ratio'), 2)}`，先等盘中确认，不做开盘无确认追价。")
        for row in hold_candidates[1:3]:
            lines.append(f"- 备选确认：`{_stock_label(row)}`，收盘胜率 `{_fmt_pct(_row_historical_metric(row, 'next_close_positive_rate'))}`，" f"盈亏比 `{_fmt_num(_row_historical_metric(row, 'next_close_payoff_ratio'), 2)}`，确认强度不足时只观察。")
    else:
        lines.append("- 没有胜率和赔率同时站稳的隔夜延续候选，正式票也只按盘中确认处理。")
    for row in intraday_only[:3]:
        lines.append(f"- 只做盘中机会：`{_stock_label(row)}`，收盘胜率 `{_fmt_pct(_row_historical_metric(row, 'next_close_positive_rate'))}`，" f"盈亏比 `{_fmt_num(_row_historical_metric(row, 'next_close_payoff_ratio'), 2)}`，不预设隔夜持有。")
    return lines


def _render_win_rate_payoff_gate(rows: list[dict[str, Any]]) -> list[str]:
    """Render checklist items for the win-rate/payoff gate."""
    lines = ["## 胜率/赔率闸门", ""]
    decision_lines = _render_win_rate_payoff_decision(rows)[2:]
    for line in decision_lines:
        if line.startswith("- "):
            lines.append("- [ ] " + line[2:])
    return lines or ["## 胜率/赔率闸门", "", "- [ ] 当前没有正式执行票。"]


def _render_alpha_reliability_lines(rows: list[dict[str, Any]]) -> list[str]:
    """Render sample-size, Wilson interval and label decomposition for Alpha review."""
    lines = ["## Alpha 样本稳健性与标签拆解", ""]
    if not rows:
        lines.append("- 当前没有正式执行票，无法形成样本稳健性卡片。")
        return lines
    for row in rows[:5]:
        reliability = build_historical_reliability_metrics(row)
        positive_count = reliability.get("positive_count")
        negative_count = reliability.get("negative_count")
        evaluable_count = reliability.get("evaluable_count") or reliability.get("sample_count")
        count_text = f"样本 `{evaluable_count}`（正 `{positive_count}` / 负 `{negative_count}`）" if evaluable_count is not None else "样本 `n/a`"
        wilson_low = reliability.get("win_rate_wilson_low")
        wilson_high = reliability.get("win_rate_wilson_high")
        wilson_text = f"{_fmt_pct(wilson_low)}~{_fmt_pct(wilson_high)}" if wilson_low is not None and wilson_high is not None else "n/a"
        lines.append(
            f"- `{_stock_label(row)}`：{count_text}，原始胜率 `{_fmt_pct(reliability.get('raw_win_rate'))}`，"
            f"Wilson 区间 `{wilson_text}`，收缩胜率 `{_fmt_pct(reliability.get('shrunk_win_rate'))}`，"
            f"可靠性 `{reliability.get('reliability_label')}`；标签拆解："
            f"开盘均值 `{_fmt_pct(_row_historical_metric(row, 'next_open_return_mean'))}`，"
            f"最高命中 `{_fmt_pct(_row_historical_metric(row, 'next_high_hit_rate_at_threshold'))}`，"
            f"收盘均值 `{_fmt_pct(_row_historical_metric(row, 'next_close_return_mean'))}`，"
            f"开盘到收盘 `{_fmt_pct(_row_historical_metric(row, 'next_open_to_close_return_mean'))}`。"
        )
    return lines


def _compact_code_items(items: Any, *, limit: int = 4) -> str:
    values = [str(item).strip() for item in list(items or []) if str(item).strip()]
    if not values:
        return "`无`"
    return "、".join(f"`{item}`" for item in values[:limit])


def _gate_status_text(row: dict[str, Any]) -> str:
    gate_status = dict(_row_field(row, "gate_status") or {})
    if not gate_status:
        return "`n/a`"
    return "，".join(f"{key}={value}" for key, value in gate_status.items())


def _render_alpha_factor_cards(rows: list[dict[str, Any]]) -> list[str]:
    """Render compact factor attribution cards from artifact evidence fields."""
    lines = ["## Alpha 因子证据卡", ""]
    if not rows:
        lines.append("- 当前没有正式执行票。")
        return lines
    for row in rows[:5]:
        positive = list(_row_field(row, "positive_tags") or _row_field(row, "top_reasons") or [])
        why_now = _row_field(row, "why_now")
        if not positive and why_now:
            positive = [item.strip() for item in str(why_now).split(",") if item.strip()]
        negative = list(
            _first_non_empty(
                _row_field(row, "negative_tags"),
                _row_field(row, "blockers"),
                _row_field(row, "execution_blocked_flags"),
                [],
            )
            or []
        )
        if not negative:
            negative = list(_row_field(row, "candidate_reason_codes") or [])[:2]
        lines.append(
            f"- `{_stock_label(row)}`：正向证据：{_compact_code_items(positive)}；"
            f"风险/负项：{_compact_code_items(negative)}；gate：{_gate_status_text(row)}。"
        )
    return lines


def _render_beta_execution_controls(rows: list[dict[str, Any]]) -> list[str]:
    """Render execution, microstructure and cost controls for Beta review."""
    lines = [
        "## Beta 执行硬条件与成本闸门",
        "",
        "| 股票 | 触发条件 | 取消条件 | 成本闸门 | 成交约束 |",
        "| --- | --- | --- | --- | --- |",
    ]
    if not rows:
        lines.append("| 无 | 无正式执行票 | 保持空仓观察 | n/a | n/a |")
        return lines
    for row in rows[:5]:
        preferred_entry_mode = str(row.get("preferred_entry_mode") or "next_day_breakout_confirmation")
        cost_cap = estimate_execution_cost_cap(row)
        lines.append(
            f"| {_markdown_table_cell(_stock_label(row))} | "
            f"{_markdown_table_cell('09:25 后等待 VWAP/开盘价承接与量价延续确认；' + ('只做盘中机会' if preferred_entry_mode == 'intraday_confirmation_only' else '确认后才允许 BTST 持有'))} | "
            f"{_markdown_table_cell('高开过大后快速跌回开盘价/VWAP、竞价缩量或盘口撤单异常时取消')} | "
            f"{_markdown_table_cell('滑点+冲击成本 <= `' + _fmt_pct(cost_cap) + '`')} | "
            f"{_markdown_table_cell('单票参与率 <= 5%；盘口价差异常或涨停排队不主动追单')} |"
        )
    return lines


def _render_post_trade_review_loop() -> list[str]:
    """Render the post-trade feedback fields expected by the review ledger."""
    return [
        "## 盘后复盘闭环",
        "",
        "- 收盘后回填 `realized_entry_price`、`realized_exit_price`、`realized_slippage`、`mae`、`mfe`、`post_close_review_state`、`post_close_review_transition` 与 `execution_review_label`。",
        "- 次日复盘时同时标注是否触发买点、是否触发取消条件、真实滑点是否超过成本闸门。",
        "- 回填结果进入 review ledger，用于下一轮样本稳健性、执行质量和风险预算校准。",
    ]


def _buy_order_label(order: dict[str, Any], rows_by_ticker: dict[str, dict[str, Any]]) -> str:
    ticker = str(order.get("ticker") or "").strip()
    row = dict(rows_by_ticker.get(ticker) or {"ticker": ticker})
    return _stock_label(row)


def _render_gamma_market_gate_lines(selection_snapshot: dict[str, Any], selected_rows: list[dict[str, Any]]) -> list[str]:
    """Render market gate, risk budget and portfolio guardrails for Gamma review."""
    lines = ["## Gamma 市场门控与风险预算", ""]
    if not selection_snapshot:
        lines.append("- selection_snapshot 未找到；本节只保留人工复核入口，不能把市场门控状态写成已验证。")
        return lines
    market_state = dict(selection_snapshot.get("market_state") or {})
    funnel_diagnostics = dict(selection_snapshot.get("funnel_diagnostics") or {})
    gate_enforcement = dict(funnel_diagnostics.get("btst_regime_gate_enforcement") or {})
    reasons = list(market_state.get("regime_gate_reasons") or [])
    lines.append(
        f"- 市场状态：regime_gate_level：`{market_state.get('regime_gate_level') or 'n/a'}`；"
        f"breadth_ratio：`{_fmt_pct(market_state.get('breadth_ratio'))}`；"
        f"daily_return：`{_fmt_pct(market_state.get('daily_return'))}`；"
        f"涨跌停：`{market_state.get('limit_up_count', 'n/a')}` / `{market_state.get('limit_down_count', 'n/a')}`；"
        f"position_scale：`{_fmt_pct(market_state.get('position_scale'))}`。"
    )
    if reasons:
        lines.append(f"- 门控原因：{_compact_code_items(reasons, limit=6)}。")
    if gate_enforcement:
        lines.append(
            f"- regime gate enforcement：gate：`{gate_enforcement.get('gate') or 'n/a'}`；"
            f"mode：`{gate_enforcement.get('mode') or 'n/a'}`；enforced：`{gate_enforcement.get('enforced')}`；"
            f"buy_orders_cleared：`{gate_enforcement.get('buy_orders_cleared')}`"
            f"（count `{gate_enforcement.get('buy_orders_cleared_count', 'n/a')}`）。"
        )
        promoted = gate_enforcement.get("shadow_promotion_tickers")
        if promoted:
            lines.append(f"- shadow promotion tickers：{_compact_code_items(promoted, limit=8)}。")
    rows_by_ticker = {str(row.get("ticker") or "").strip(): row for row in selected_rows}
    buy_orders = _safe_rows(selection_snapshot.get("buy_orders"))
    if buy_orders:
        lines.append("- 风险预算上限：")
        for order in buy_orders[:5]:
            lines.append(
                f"  - `{_buy_order_label(order, rows_by_ticker)}`：shares `{order.get('shares', 'n/a')}`，"
                f"amount `{_fmt_num(order.get('amount'), 2)}`，risk_budget_ratio `{_fmt_num(order.get('risk_budget_ratio'), 2)}`，"
                f"gate `{order.get('risk_budget_gate') or 'n/a'}`，contract `{order.get('execution_contract_bucket') or 'n/a'}`，"
                f"constraint `{order.get('constraint_binding') or 'n/a'}`。"
            )
    else:
        lines.append("- 当前 selection_snapshot 没有 buy_orders 风险预算明细。")
    lines.append("- 组合约束：同主题候选不叠加加仓，市场门控为 `halt/risk_off/crisis` 时只允许确认后小仓复核或放弃。")
    return lines


def _build_premarket_control_tower(
    decision_card: dict[str, Any],
    selection_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Combine model trade bias with market gate state into one effective execution state."""
    return build_premarket_control_tower(decision_card, selection_snapshot)


def _render_premarket_control_tower(control_tower: dict[str, Any]) -> list[str]:
    """Render the effective premarket status above detailed execution sections."""
    return [
        "## 盘前控制塔",
        "",
        f"- 模型原始倾向：`{control_tower.get('raw_trade_bias') or 'n/a'}`；门控后有效状态：`{control_tower.get('effective_trade_bias') or 'n/a'}`。",
        f"- 市场门控：regime_gate_level `{control_tower.get('regime_gate_level') or 'n/a'}`，gate `{control_tower.get('gate') or 'n/a'}`，buy_orders_cleared `{control_tower.get('buy_orders_cleared')}`。",
        f"- 风险姿态：证据 `{control_tower.get('evidence_grade') or 'n/a'}`，数据 `{control_tower.get('data_quality') or 'n/a'}`，仓位缩放 `{_fmt_pct(control_tower.get('position_scale'))}`。",
        f"- 原因码：{_compact_code_items(control_tower.get('reason_codes'), limit=6)}。",
        f"- 执行动作：{control_tower.get('action') or 'n/a'}",
    ]


def _render_opening_timeline_lines(primary_label: str) -> list[str]:
    """Render next-morning time windows required by the final document spec."""
    focus = primary_label or "主票"
    return [
        "## 早盘时间轴",
        "",
        f"- 09:20-09:25：只看竞价强弱和封单/撤单质量，`{focus}` 没有稳定承接就不提前预设买点。",
        "- 09:25-09:35：等待开盘后第一段延续确认；高开后快速回落时直接降级观察。",
        "- 09:35-10:00：只复审仍在原始触发逻辑内的票，不因低位反抽自动升级。",
        "- 10:00 后：没有形成延续确认的正式票退出执行队列，只保留观察记录和复盘标签。",
    ]


def _stock_bullets(rows: list[dict[str, Any]], *, limit: int, include_payoff: bool = False) -> list[str]:
    """Render compact stock bullets for document sections."""
    lines: list[str] = []
    for row in rows[:limit]:
        rate = _row_historical_metric(row, "next_close_positive_rate")
        payoff = _row_historical_metric(row, "next_close_payoff_ratio")
        base = f"- `{_stock_label(row)}`：层级 `{row.get('action_tier') or row.get('lane') or row.get('table_key') or row.get('entry_status') or 'n/a'}`，模式 `{row.get('preferred_entry_mode') or 'n/a'}`，分数 `{_fmt_num(row.get('score_target', row.get('pre_score')), 4)}`"
        if include_payoff:
            base += f"，收盘胜率 `{_fmt_pct(rate)}`，盈亏比 `{_fmt_num(payoff, 2)}`，说明：{_historical_reading_note(row)}"
            lines.append(base)
            continue
        lines.append(base + "。")
    return lines or ["- 无。"]


def _render_enriched_stock_bullets(rows: list[dict[str, Any]], *, limit: int) -> list[str]:
    lines: list[str] = []
    for row in rows[:limit]:
        metrics = dict(row.get("metrics") or {})
        quality_notes = list(row.get("quality_notes") or [])
        note_suffix = f"质量提示：{'；'.join(str(note) for note in quality_notes)}。" if quality_notes else ""
        source_row = dict(row.get("source_row") or {})
        reading_note = _historical_reading_note(source_row or row).rstrip("。")
        lines.append(
            f"- `{_enriched_stock_label(row)}`：模式 `{row.get('preferred_entry_mode')}`，"
            f"分数 `{_fmt_num(row.get('score_target'), 4)}`，"
            f"证据 `{row.get('evidence_grade')}`，数据 `{row.get('data_quality')}`，"
            f"倾向 `{row.get('trade_bias')}`，风险 `{row.get('risk_posture')}`，"
            f"收盘胜率 `{_fmt_pct(metrics.get('win_rate'))}`，"
            f"盈亏比 `{_fmt_num(metrics.get('payoff_ratio'), 2)}`，"
            f"说明：{reading_note}。{note_suffix}"
        )
    return lines or ["- 无。"]


def _markdown_table_cell(value: Any) -> str:
    text = str(value or "")
    return text.replace("|", "\\|").replace("\n", "<br>")


def _render_action_matrix_sections(
    rows: list[dict[str, Any]],
    *,
    report_mode: str = "formal_execution",
    limit: int = 3,
) -> list[str]:
    section_labels = _build_section_labels(report_mode)
    action_matrix_title = str(section_labels.get("action_matrix_title") or "正式执行动作矩阵")
    action_item_label = str(section_labels.get("checklist_execution_item_label") or "正式执行")
    lines = [f"## {action_matrix_title}", ""]
    if not rows:
        lines.append(f"- 当前没有{action_item_label}票。")
        return lines
    for row in rows[:limit]:
        lines.extend(
            [
                f"### {_enriched_stock_label(row)}",
                "",
                "| 场景 | 动作 |",
                "| --- | --- |",
            ]
        )
        for item in list(row.get("action_matrix") or []):
            scenario = _markdown_table_cell(item.get("scenario"))
            action = _markdown_table_cell(item.get("action"))
            lines.append(f"| {scenario} | {action} |")
        lines.append("")
    return lines


def _build_section_labels(report_mode: str) -> dict[str, str]:
    if str(report_mode or "").strip() == "formal_execution":
        return {
            "llm_execution_title": "正式执行层",
            "checklist_execution_title": "正式执行顺序",
            "checklist_execution_item_label": "正式执行",
            "action_matrix_title": "正式执行动作矩阵",
            "execution_state_table_title": "当日执行状态",
        }
    return {
        "llm_execution_title": "确认复核队列",
        "checklist_execution_title": "确认复核顺序",
        "checklist_execution_item_label": "确认复核",
        "action_matrix_title": "确认复核动作矩阵",
        "execution_state_table_title": "当日执行状态",
    }


_ALLOWED_SECTION_ORDER = (
    "formal_queue",
    "review_queue",
    "watch_queue",
    "blocked_only",
)


def _normalized_allowed_sections(value: Any) -> list[str]:
    if value in (None, "", [], (), set(), frozenset()):
        return []
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw_values = list(value)
    else:
        raw_values = [value]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        text = str(item or "").strip()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return normalized


def _group_rows_by_allowed_sections(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped_rows: dict[str, list[dict[str, Any]]] = {
        section: [] for section in _ALLOWED_SECTION_ORDER
    }
    for row in rows:
        for section in _normalized_allowed_sections(row.get("allowed_sections")):
            if section in grouped_rows:
                grouped_rows[section].append(row)
    return grouped_rows


def _flatten_grouped_rows(
    grouped_rows: dict[str, list[dict[str, Any]]],
    *,
    order: tuple[str, ...] = _ALLOWED_SECTION_ORDER,
) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    seen_row_ids: set[int] = set()
    for section in order:
        for row in grouped_rows.get(section, []):
            row_id = id(row)
            if row_id in seen_row_ids:
                continue
            flattened.append(row)
            seen_row_ids.add(row_id)
    return flattened


def _primary_execution_section(report_mode: str) -> str:
    if str(report_mode or "").strip() == "formal_execution":
        return "formal_queue"
    return "review_queue"


def _attach_execution_semantics_rows(
    rows: list[dict[str, Any]],
    *,
    report_mode: str,
    control_tower: dict[str, Any],
    veto_owner: str,
) -> list[dict[str, Any]]:
    return [
        attach_execution_semantics(
            row,
            report_mode=report_mode,
            control_tower=control_tower,
            veto_owner=veto_owner,
        )
        for row in rows
    ]


def _fmt_bool(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "n/a"


def _render_execution_state_table(rows: list[dict[str, Any]], *, title: str) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| 股票 | trade_bias | execution_state | max_allowed_state_today | formal_buy_allowed | allowed_sections | veto_owner | state_reason_codes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not rows:
        lines.append("| 无 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
        return lines
    for row in rows[:5]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_table_cell(_enriched_stock_label(row)),
                    _markdown_table_cell(str(row.get("trade_bias") or "n/a")),
                    _markdown_table_cell(str(row.get("execution_state") or "n/a")),
                    _markdown_table_cell(str(row.get("max_allowed_state_today") or "n/a")),
                    _markdown_table_cell(_fmt_bool(row.get("formal_buy_allowed"))),
                    _markdown_table_cell("/".join(str(item) for item in list(row.get("allowed_sections") or [])) or "n/a"),
                    _markdown_table_cell(str(row.get("veto_owner") or "n/a")),
                    _markdown_table_cell("/".join(str(item) for item in list(row.get("state_reason_codes") or [])) or "n/a"),
                ]
            )
            + " |"
        )
    return lines


def _build_semantic_conflicts(*, report_mode: str, rows: list[dict[str, Any]]) -> list[str]:
    def _format_expected(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, tuple, set, frozenset)):
            normalized = _normalized_allowed_sections(value)
            return "/".join(normalized) if normalized else "none"
        text = str(value or "").strip()
        return text or "n/a"

    conflicts: list[str] = []
    for row in rows:
        ticker_label = _enriched_stock_label(row) or str(row.get("ticker") or "unknown")
        row_report_mode = str(row.get("report_mode") or "").strip()
        role = str(row.get("role") or "").strip()
        trade_bias = str(row.get("trade_bias") or "").strip()
        if row_report_mode and row_report_mode != report_mode:
            conflicts.append(f"{ticker_label}:report_mode={row_report_mode}")
        expected_semantics = build_execution_semantics(
            report_mode=report_mode,
            role=role,
            trade_bias=trade_bias,
        )
        if str(row.get("execution_state") or "").strip() != str(expected_semantics.get("execution_state") or "").strip():
            conflicts.append(
                f"{ticker_label}:expected_execution_state={_format_expected(expected_semantics.get('execution_state'))}"
            )
        if str(row.get("max_allowed_state_today") or "").strip() != str(expected_semantics.get("max_allowed_state_today") or "").strip():
            conflicts.append(
                f"{ticker_label}:expected_max_allowed_state_today={_format_expected(expected_semantics.get('max_allowed_state_today'))}"
            )
        if row.get("formal_buy_allowed") is not expected_semantics.get("formal_buy_allowed"):
            conflicts.append(
                f"{ticker_label}:expected_formal_buy_allowed={_format_expected(expected_semantics.get('formal_buy_allowed'))}"
            )
        if _normalized_allowed_sections(row.get("allowed_sections")) != _normalized_allowed_sections(expected_semantics.get("allowed_sections")):
            conflicts.append(
                f"{ticker_label}:expected_allowed_sections={_format_expected(expected_semantics.get('allowed_sections'))}"
            )
    return conflicts


def _build_forbidden_semantics_hits(
    *,
    signal_date_compact: str,
    docs: dict[str, str],
    report_mode: str,
) -> list[str]:
    llm_doc_name = f"BTST-LLM-{signal_date_compact}.md"
    checklist_doc_name = f"BTST-{signal_date_compact}-EXEC-CHECKLIST.md"
    plain_doc_name = f"{signal_date_compact}-两套交易计划通俗说明.md"
    forum_doc_name = f"{signal_date_compact}-两套交易计划论坛短版.md"
    forbidden_by_doc = (
        {
            llm_doc_name: [
                "## 正式执行层",
                "正式执行层先决定主顺序",
                "正式 BTST 决定主执行顺序",
            ],
            checklist_doc_name: [
                "## 正式执行顺序",
                "## 正式执行动作矩阵",
                "- [ ] 正式执行：",
            ],
            plain_doc_name: [
                "正式 BTST 仍以",
                "正式 BTST 决定主执行顺序",
            ],
            forum_doc_name: [
                "明日 BTST 主线还是",
                "正式 BTST 决定主票",
            ],
        }
        if report_mode == "confirmation_review_only"
        else {
            llm_doc_name: ["## 确认复核队列"],
            checklist_doc_name: [
                "## 确认复核顺序",
                "## 确认复核动作矩阵",
                "- [ ] 确认复核：",
            ],
            plain_doc_name: ["确认复核主线"],
            forum_doc_name: ["明日确认复核主线还是"],
        }
    )
    hits: list[str] = []
    for file_name, phrases in forbidden_by_doc.items():
        content = docs.get(file_name, "")
        for phrase in phrases:
            if phrase in content:
                hits.append(f"{file_name}:{phrase}")
    return hits


def _build_source_of_truth_snapshot(
    *,
    signal_date_compact: str,
    report_mode: str,
    veto_owner: str,
    section_labels: dict[str, str],
    control_tower: dict[str, Any],
    early_runner: dict[str, Any],
    selection_snapshot: dict[str, Any],
    semantic_rows: list[dict[str, Any]],
    forbidden_semantics_hits: list[str],
) -> dict[str, Any]:
    grouped_rows = _group_rows_by_allowed_sections(semantic_rows)
    return {
        "signal_date": signal_date_compact,
        "report_mode": report_mode,
        "veto_owner": veto_owner,
        "section_labels": dict(section_labels),
        "early_runner_status": early_runner.get("status"),
        "control_tower_effective_trade_bias": control_tower.get("effective_trade_bias"),
        "control_tower_reason_codes": list(control_tower.get("reason_codes") or []),
        "selection_snapshot_loaded": bool(selection_snapshot),
        "selection_snapshot_source_path": selection_snapshot.get("_source_path"),
        "selection_snapshot_gate": {
            "regime_gate_level": control_tower.get("regime_gate_level"),
            "gate": control_tower.get("gate"),
            "buy_orders_cleared": control_tower.get("buy_orders_cleared"),
        },
        "formal_rows": [
            {
                "ticker": str(row.get("ticker") or ""),
                "execution_state": row.get("execution_state"),
                "max_allowed_state_today": row.get("max_allowed_state_today"),
                "allowed_sections": _normalized_allowed_sections(row.get("allowed_sections")),
                "formal_buy_allowed": row.get("formal_buy_allowed"),
                "release_authority": row.get("release_authority"),
            }
            for row in semantic_rows
            if str(row.get("role") or "").strip() == "formal_selected"
        ],
        "render_groups": {
            section: [str(row.get("ticker") or "") for row in grouped_rows.get(section, [])]
            for section in _ALLOWED_SECTION_ORDER
        },
        "forbidden_semantics_hits": list(forbidden_semantics_hits),
    }


def _rule_stock_bullets(rows: list[dict[str, Any]], *, limit: int) -> list[str]:
    """Render rule-report high-confidence rows from their native score fields."""
    lines: list[str] = []
    for row in rows[:limit]:
        details = [
            f"规则分数 `{_fmt_num(_first_non_empty(row.get('score'), row.get('score_target')), 4)}`",
        ]
        if row.get("pct_chg") not in (None, ""):
            details.append(f"当日涨幅 `{_fmt_num(row.get('pct_chg'), 2)}%`")
        if row.get("close_strength") not in (None, ""):
            details.append(f"close_strength `{_fmt_num(row.get('close_strength'), 4)}`")
        if row.get("catalyst_freshness") not in (None, ""):
            details.append(f"catalyst_freshness `{_fmt_num(row.get('catalyst_freshness'), 4)}`")
        if row.get("candidate_source") not in (None, ""):
            details.append(f"来源 `{row.get('candidate_source')}`")
        lines.append(f"- `{_stock_label(row)}`：" + "，".join(details) + "。")
    return lines or ["- 无。"]


def _first_non_empty(*values: Any) -> Any:
    """Return the first non-empty value from a list of candidates."""
    for value in values:
        if value not in (None, "", [], {}, ()):
            return value
    return None


def _discover_report_dir(reports_root: Path, signal_date_iso: str, explicit_report_dir: str | Path | None) -> Path:
    """Discover the short-trade report directory for the requested signal date."""
    if explicit_report_dir:
        return Path(explicit_report_dir).expanduser().resolve()
    signal_date_compact = signal_date_iso.replace("-", "")
    candidates: list[Path] = []
    for child in reports_root.iterdir():
        if not child.is_dir():
            continue
        session_summary_path = child / "session_summary.json"
        if not session_summary_path.exists():
            continue
        try:
            session_summary = _read_json(session_summary_path)
        except Exception:
            continue
        btst_followup = dict(session_summary.get("btst_followup") or {})
        trade_date = str(
            _first_non_empty(
                session_summary.get("trade_date"),
                btst_followup.get("trade_date"),
                session_summary.get("start_date"),
                session_summary.get("end_date"),
            )
            or ""
        )
        selection_target = str(_first_non_empty(session_summary.get("selection_target"), dict(session_summary.get("plan_generation") or {}).get("selection_target")) or "")
        normalized_trade_date = trade_date.replace("-", "")
        if normalized_trade_date == signal_date_compact and selection_target == "short_trade_only":
            candidates.append(child)
    if not candidates:
        raise FileNotFoundError(f"unable to find short_trade_only report dir for {signal_date_iso}")
    return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)[0]


def _refresh_early_runner_artifacts(reports_root: Path) -> dict[str, Any]:
    """Refresh early-runner analysis and daily tables before document generation."""
    analysis = analyze_btst_early_runner_v1(reports_root)
    tables = generate_btst_early_runner_daily_tables(reports_root)
    return {
        "analysis": analysis,
        "tables": tables,
    }


def _resolve_existing_json_path(raw_path: Any, report_dir: Path) -> Path | None:
    """Resolve a JSON path from artifacts without assuming it is absolute."""
    if not raw_path:
        return None
    candidate = Path(str(raw_path)).expanduser()
    candidates = [candidate]
    if not candidate.is_absolute():
        candidates.append(report_dir / candidate)
    for item in candidates:
        if item.exists():
            return item.resolve()
    return None


def _load_selection_snapshot(
    *,
    report_dir: Path,
    signal_date_iso: str,
    brief: dict[str, Any],
    priority_board: dict[str, Any],
) -> dict[str, Any]:
    """Load selection_snapshot when current artifacts expose it."""
    source_paths = dict(priority_board.get("source_paths") or {})
    candidate_paths = [
        brief.get("snapshot_path"),
        source_paths.get("snapshot_path"),
        report_dir / "selection_artifacts" / signal_date_iso / "selection_snapshot.json",
    ]
    for raw_path in candidate_paths:
        path = _resolve_existing_json_path(raw_path, report_dir)
        if path is None:
            continue
        try:
            payload = _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        payload["_source_path"] = path.as_posix()
        return payload
    return {}


def _load_early_runner_context(reports_root: Path, signal_date_iso: str, *, refresh: bool) -> dict[str, Any]:
    """Load the exact-date early-runner board or the latest available fallback board."""
    if refresh:
        refreshed = _refresh_early_runner_artifacts(reports_root)
        analysis = dict(refreshed["analysis"])
        tables_refresh = dict(refreshed["tables"])
    else:
        analysis = _read_json(reports_root / "btst_early_runner_v1_latest.json")
        tables_refresh = {}
    boards = _safe_rows(analysis.get("daily_boards"))
    exact_board = next((row for row in boards if str(row.get("trade_date") or "") == signal_date_iso), {})
    latest_board = max(boards, key=lambda row: str(row.get("trade_date") or ""), default={})
    selected_board = dict(exact_board or latest_board or {})
    status = "exact"
    if not selected_board:
        status = "unavailable"
    elif not exact_board:
        status = "stale_fallback"
    return {
        "analysis": analysis,
        "tables_refresh": tables_refresh,
        "status": status,
        "requested_trade_date": signal_date_iso,
        "board": selected_board,
        "latest_trade_date": str(latest_board.get("trade_date") or "") or None,
        "watchlist": _tag_rows(_safe_rows(selected_board.get("early_runner_watchlist")), "early_runner_watchlist"),
        "priority": _tag_rows(_safe_rows(selected_board.get("early_runner_priority")), "early_runner_priority"),
        "second_entry": _tag_rows(_safe_rows(selected_board.get("second_entry_reentry")), "second_entry_reentry"),
        "research_confirmation": _tag_rows(_safe_rows(selected_board.get("full_report_confirmation")), "full_report_confirmation"),
    }


def _overlap_tickers(formal_rows: list[dict[str, Any]], early_runner_rows: list[dict[str, Any]]) -> list[str]:
    """Compute de-duplicated ticker overlaps between formal BTST rows and early-runner rows."""
    formal_tickers = {str(row.get("ticker") or "").strip() for row in formal_rows if str(row.get("ticker") or "").strip()}
    overlap = []
    for row in early_runner_rows:
        ticker = str(row.get("ticker") or "").strip()
        if ticker and ticker in formal_tickers and ticker not in overlap:
            overlap.append(ticker)
    return overlap


def _find_row_by_ticker(rows: list[dict[str, Any]], ticker: str) -> dict[str, Any]:
    """Find one row by ticker and return an empty dict when it is missing."""
    normalized = str(ticker or "").strip()
    for row in rows:
        if str(row.get("ticker") or "").strip() == normalized:
            return row
    return {}


def _build_intersection_summary(context: dict[str, Any], formal_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build four-layer early-runner groups without mixing second-entry into first-entry overlap logic."""
    watchlist = _safe_rows(context.get("watchlist"))
    priority = _safe_rows(context.get("priority"))
    second_entry = _safe_rows(context.get("second_entry"))
    first_entry_rows = [*priority, *watchlist]
    overlap_tickers = _overlap_tickers(formal_rows, first_entry_rows)
    formal_tickers = {str(row.get("ticker") or "").strip() for row in formal_rows}
    overlap_rows = []
    for ticker in overlap_tickers:
        formal_row = _find_row_by_ticker(formal_rows, ticker)
        early_row = _first_non_empty(_find_row_by_ticker(priority, ticker), _find_row_by_ticker(watchlist, ticker), {}) or {}
        overlap_rows.append(
            {
                "ticker": ticker,
                "formal_row": dict(formal_row or {}),
                "early_row": dict(early_row or {}),
                "highlight_state": "intersection_priority" if str(context.get("status") or "") == "exact" else "reference_only_intersection",
            }
        )
    only_early_runner_rows = []
    seen_only = set()
    for row in first_entry_rows:
        ticker = str(row.get("ticker") or "").strip()
        if ticker and ticker not in formal_tickers and ticker not in seen_only:
            seen_only.add(ticker)
            only_early_runner_rows.append(dict(row))
    return {
        "status": str(context.get("status") or "unavailable"),
        "priority_rows": priority,
        "watchlist_rows": watchlist,
        "second_entry_rows": second_entry,
        "overlap_tickers": overlap_tickers,
        "overlap_rows": overlap_rows,
        "only_early_runner_rows": only_early_runner_rows,
    }


def _render_intersection_highlights(intersection_summary: dict[str, Any]) -> list[str]:
    """Render middle-stage overlap highlights with exact-vs-fallback wording."""
    status = str(intersection_summary.get("status") or "unavailable")
    overlap_rows = _safe_rows(intersection_summary.get("overlap_rows"))
    lines = ["## 交集票高亮", ""]
    if overlap_rows:
        if status == "exact":
            lines.append("- 当日 early-runner 与正式 BTST 同时命中的票如下，这些票进入“交集优先复审”层。")
        else:
            lines.append("- 当前交集来自回退板或非当日板，只能作为参考高亮，不能直接当成当日交集优先。")
        for row in overlap_rows:
            formal_row = dict(row.get("formal_row") or {})
            early_row = dict(row.get("early_row") or {})
            lines.append(
                f"- `{_stock_label(formal_row or early_row)}`：正式层级 `{formal_row.get('action_tier') or formal_row.get('lane') or 'n/a'}`，"
                f"early-runner 层级 `{early_row.get('entry_status') or early_row.get('table_key') or 'priority/watchlist'}`，"
                f"正式模式 `{formal_row.get('preferred_entry_mode') or 'n/a'}`，"
                f"early-runner pre/confirm `{_fmt_num(early_row.get('pre_score'), 4)}` / `{_fmt_num(early_row.get('confirm_score'), 4)}`。"
            )
    else:
        lines.append("- 当前没有可高亮的交集票。")
    return lines


def _resolve_selected_rows(brief: dict[str, Any], priority_board: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve formal selected rows from the brief first, then from the priority board."""
    selected_rows = _safe_rows(_first_non_empty(brief.get("selected_actions"), brief.get("selected_entries")))
    if selected_rows:
        return selected_rows
    rows = []
    for row in _safe_rows(priority_board.get("priority_rows")):
        lane = str(row.get("lane") or "")
        if lane in {"primary_entry", "selected_backup"}:
            rows.append(row)
    return rows


def _resolve_watch_rows(brief: dict[str, Any], priority_board: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve watch-only rows from the brief first, then from the priority board."""
    watch_rows = _safe_rows(brief.get("watch_actions"))
    if watch_rows:
        return watch_rows
    rows = []
    for row in _safe_rows(priority_board.get("priority_rows")):
        lane = str(row.get("lane") or "")
        actionability = str(row.get("actionability") or "")
        if actionability == "watch_only" or "near_miss" in lane:
            rows.append(row)
    return rows


def _resolve_opportunity_rows(brief: dict[str, Any], priority_board: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve opportunity rows from the brief first, then from the priority board."""
    opportunity_rows = _safe_rows(brief.get("opportunity_actions"))
    if opportunity_rows:
        return opportunity_rows
    rows = []
    for row in _safe_rows(priority_board.get("priority_rows")):
        lane = str(row.get("lane") or "")
        if lane == "opportunity_pool":
            rows.append(row)
    return rows


def _resolve_primary_action(brief: dict[str, Any], priority_board: dict[str, Any]) -> dict[str, Any]:
    """Resolve the primary trade idea from multiple artifact variants."""
    selected_rows = _resolve_selected_rows(brief, priority_board)
    return dict(_first_non_empty(brief.get("primary_action"), brief.get("primary_entry"), selected_rows[0] if selected_rows else {}) or {})


def _resolve_primary_semantic_action(rows: list[dict[str, Any]], *, report_mode: str) -> dict[str, Any]:
    grouped_rows = _group_rows_by_allowed_sections(rows)
    for section in (
        _primary_execution_section(report_mode),
        "watch_queue",
        "blocked_only",
    ):
        section_rows = grouped_rows.get(section, [])
        if section_rows:
            return dict(section_rows[0])
    return dict(rows[0] if rows else {})


def _render_primary_contract_lines(primary_action: dict[str, Any], *, report_mode: str) -> list[str]:
    if not primary_action:
        return [
            "## 当日状态与放行权",
            "",
            "- 当前没有可用主线，因此放行权保持 `none`，维持空仓观察。",
        ]
    lines = [
        "## 当日状态与放行权",
        "",
        f"- 主线当前状态是 `{primary_action.get('execution_state') or 'n/a'}`，当日上限是 `{primary_action.get('max_allowed_state_today') or 'n/a'}`。",
        f"- 放行权归 `{primary_action.get('release_authority') or 'none'}`。",
    ]
    if report_mode == "confirmation_review_only":
        lines.append("- 当前只允许先确认，不允许把这份文档当成正式下单单。")
    else:
        lines.append("- 当前主线已经进入正式执行语义，但盘中仍需服从失效条件和成本闸门。")
    return lines


def _render_contract_mirror_lines(
    primary_action: dict[str, Any],
    *,
    report_mode: str,
    control_tower: dict[str, Any] | None = None,
    title: str | None,
) -> list[str]:
    lines: list[str] = []
    if title:
        lines.extend([title, ""])
    if not primary_action:
        lines.append("- 当前没有 formal 主线，对应 contract 保持空仓观察，release_authority `none`。")
        return lines
    lines.append(
        f"- 当前状态 `{primary_action.get('execution_state') or 'n/a'}`；当日上限 `{primary_action.get('max_allowed_state_today') or 'n/a'}`；放行权 `{primary_action.get('release_authority') or 'none'}`；release_authority `{primary_action.get('release_authority') or 'none'}`。"
    )
    if control_tower:
        lines.append(
            f"- effective_trade_bias `{control_tower.get('effective_trade_bias') or 'n/a'}`；reason_codes { _compact_code_items(control_tower.get('reason_codes'), limit=6) }。"
        )
    if report_mode == "confirmation_review_only":
        lines.append("- 这里只镜像主执行 contract，不自动等价成正式下单许可。")
    else:
        lines.append("- 这里与正式执行 contract 对齐，但盘中仍需服从确认与失效条件。")
    return lines


def _render_early_runner_status(context: dict[str, Any]) -> list[str]:
    """Render human-readable early-runner availability lines."""
    board = dict(context.get("board") or {})
    research_confirmation = _safe_rows(context.get("research_confirmation"))
    status = str(context.get("status") or "unavailable")
    requested = str(context.get("requested_trade_date") or "")
    latest = str(context.get("latest_trade_date") or "")
    lines = [f"- 请求 trade_date：`{requested}`。"]
    if status == "exact":
        lines.append(f"- early-runner 命中当日板：`{requested}`，`deployment_mode={board.get('deployment_mode')}`，`gate_action={board.get('gate_action')}`。")
    elif status == "stale_fallback":
        lines.append(f"- 当日 early-runner 板缺失，回退到最近可用板：`{latest}`，`deployment_mode={board.get('deployment_mode')}`，`gate_action={board.get('gate_action')}`。")
    else:
        lines.append("- 当前没有可用 early-runner 板，本轮文档只记录缺失状态，不编造观察票。")
    if research_confirmation:
        lines.append(f"- 当前板保留 `full_report_confirmation={len(research_confirmation)}` 条研究确认票；它们只用于研究确认，不自动进入 priority/watchlist/second-entry。")
        lines.append(f"- 研究确认前排：`{_stock_labels_text(research_confirmation, limit=5)}`。")
    return lines


def _render_early_runner_overlay(context: dict[str, Any], formal_rows: list[dict[str, Any]]) -> list[str]:
    """Render the overlay section that compares early-runner with formal BTST rows."""
    watchlist = _safe_rows(context.get("watchlist"))
    priority = _safe_rows(context.get("priority"))
    second_entry = _safe_rows(context.get("second_entry"))
    research_confirmation = _safe_rows(context.get("research_confirmation"))
    intersection_summary = _build_intersection_summary(context, formal_rows)
    lines = []
    lines.extend(_render_early_runner_status(context))
    lines.append(f"- watchlist 数量：`{len(watchlist)}`；priority 数量：`{len(priority)}`；second_entry 数量：`{len(second_entry)}`。")
    if research_confirmation:
        lines.append(f"- research-only 确认池数量：`{len(research_confirmation)}`。")
    overlap_labels = _stock_labels_text([dict(row.get("formal_row") or row.get("early_row") or {}) for row in _safe_rows(intersection_summary.get("overlap_rows"))])
    lines.append(f"- 与正式 BTST 的重合票：`{overlap_labels}`。")
    only_rows = _safe_rows(intersection_summary.get("only_early_runner_rows"))
    second_entry_rows = _safe_rows(intersection_summary.get("second_entry_rows"))
    if str(intersection_summary.get("status") or "") == "stale_fallback":
        lines.append(f"- 仅 early-runner 命中的补充票：`{len(only_rows)} 只，非当日板，仅作历史参考`。")
        lines.append(f"- 回补机会层：`{len(second_entry_rows)} 只，非当日板，仅作历史参考`。")
    else:
        lines.append(f"- 仅 early-runner 命中的补充票：`{_stock_labels_text(only_rows)}`。")
        lines.append(f"- 回补机会层：`{_stock_labels_text(second_entry_rows)}`。")
    return lines


def _render_strategy_threshold_lines(
    strategy_thresholds: dict[str, Any],
    strategy_thresholds_config_path: str,
    strategy_thresholds_profile: str,
) -> list[str]:
    """Render the shared BTST strategy-threshold baseline into generated documents."""
    return [
        "## 当前策略阈值基线",
        "",
        f"- 阈值 profile：`{strategy_thresholds_profile}`；配置文件：`{strategy_thresholds_config_path}`。",
        f"- exact 连续门槛：`{strategy_thresholds.get('min_recent_exact_streak')}`；交集出现天数门槛：`{strategy_thresholds.get('min_intersection_positive_days')}`。",
        f"- 交集层 uplift 门槛：胜率差 `+{_fmt_pct(strategy_thresholds.get('intersection_uplift_rate_threshold'))}`；均值差 `+{_fmt_num(strategy_thresholds.get('intersection_uplift_mean_return_threshold'), 2)}`。",
        f"- 补充层最大容忍正收益率：`{_fmt_pct(strategy_thresholds.get('only_early_runner_max_positive_rate'))}`；回补层 T+2 优势门槛：`+{_fmt_num(strategy_thresholds.get('second_entry_t2_advantage_threshold'), 3)}`。",
    ]


def _render_rule_doc(
    signal_date_compact: str,
    rule_report: dict[str, Any],
    brief: dict[str, Any],
    priority_board: dict[str, Any],
    early_runner: dict[str, Any],
    rule_report_path: Path,
    report_dir: Path,
    strategy_thresholds: dict[str, Any],
    strategy_thresholds_config_path: str,
    strategy_thresholds_profile: str,
) -> str:
    """Render the rule-based document and append early-runner status as an overlay section."""
    high_confidence = _safe_rows(rule_report.get("high_confidence"))
    selected_actions = _resolve_selected_rows(brief, priority_board)
    formal_rows = selected_actions + _resolve_watch_rows(brief, priority_board)
    intersection_summary = _build_intersection_summary(early_runner, formal_rows)
    early_status = str(early_runner.get("status") or "unavailable")
    enriched_only_early_runner = _enrich_early_runner_rows(
        _safe_rows(intersection_summary.get("only_early_runner_rows")),
        role="early_runner_only",
        early_runner_status=early_status,
    )
    enriched_second_entry = _enrich_early_runner_rows(
        _safe_rows(intersection_summary.get("second_entry_rows")),
        role="early_runner_second_entry",
        early_runner_status=early_status,
    )
    lines = [
        f"# BTST 规则版详细计划（{signal_date_compact}）",
        "",
        "## 核心结论",
        "",
        f"- 信号日：`{signal_date_compact}`；目标交易日：`{rule_report.get('next_date') or brief.get('next_trade_date') or 'n/a'}`。",
        f"- 规则池：`pool_size={rule_report.get('pool_size')}`，`selected_count={rule_report.get('selected_count')}`，`near_miss_count={rule_report.get('near_miss_count')}`。",
        f"- 规则报告来源：`{rule_report_path}`。",
        f"- 多智能体运行目录：`{report_dir}`。",
        "",
    ]
    lines.extend(_render_strategy_threshold_lines(strategy_thresholds, strategy_thresholds_config_path, strategy_thresholds_profile))
    lines.extend([""])
    lines.extend(_render_historical_metric_guide())
    lines.extend(["", "## 规则前排", ""])
    lines.extend(_rule_stock_bullets(high_confidence, limit=8))
    lines.append("- 规则前排这里先看规则分数；若要看 BTST 股票的历史胜率和盈亏比，请以下面的多智能体详细计划与预警文档为准。")
    lines.extend(
        [
            "",
            "## Early Runner Overlay",
            "",
        ]
    )
    lines.extend(_render_early_runner_overlay(early_runner, formal_rows))
    lines.extend([""])
    lines.extend(_render_intersection_highlights(intersection_summary))
    if _safe_rows(intersection_summary.get("only_early_runner_rows")):
        lines.extend(["", "### 补充复审层", ""])
        lines.extend(_render_enriched_stock_bullets(enriched_only_early_runner, limit=5))
    if _safe_rows(intersection_summary.get("second_entry_rows")):
        lines.extend(["", "### 回补机会层", ""])
        lines.extend(_render_enriched_stock_bullets(enriched_second_entry, limit=5))
    return "\n".join(lines) + "\n"


def _render_rollout_validation_lines(brief: dict[str, Any]) -> list[str]:
    rollout_validation = {
        "status": "unavailable",
        **dict(brief.get("rollout_validation") or {}),
    }
    lines = [
        "## Governed Rollout 观察",
        "",
        f"- status: `{rollout_validation.get('status') or 'unavailable'}`",
        f"- primary_lane: `{rollout_validation.get('primary_lane') or 'n/a'}`",
        f"- summary: {rollout_validation.get('summary') or 'n/a'}",
        f"- selected_hit_rate_15pct: `{_format_rollout_value(rollout_validation.get('selected_hit_rate_15pct'), 4)}` -> `{_format_rollout_value(rollout_validation.get('shadow_hit_rate_15pct'), 4)}`",
        f"- selected_count_delta: `{_format_rollout_value(rollout_validation.get('selected_count_delta'))}`",
        f"- execution_eligible_delta: `{_format_rollout_value(rollout_validation.get('execution_eligible_delta'))}`",
        f"- buy_order_delta: `{_format_rollout_value(rollout_validation.get('buy_order_delta'))}`",
    ]
    if rollout_validation.get("source_json_path"):
        lines.append(f"- rollout_source_json: `{rollout_validation.get('source_json_path')}`")
    return lines


def _render_llm_doc(
    signal_date_compact: str,
    brief: dict[str, Any],
    priority_board: dict[str, Any],
    session_summary: dict[str, Any],
    semantic_selected: list[dict[str, Any]],
    semantic_watch: list[dict[str, Any]],
    early_runner: dict[str, Any],
    selection_snapshot: dict[str, Any],
    control_tower: dict[str, Any],
    report_mode: str,
    veto_owner: str,
    section_labels: dict[str, str],
    report_dir: Path,
    strategy_thresholds: dict[str, Any],
    strategy_thresholds_config_path: str,
    strategy_thresholds_profile: str,
) -> str:
    """Render the multi-agent document and add early-runner overlaps plus watch-only context."""
    selected_actions = semantic_selected
    watch_actions = semantic_watch
    grouped_semantic_rows = _group_rows_by_allowed_sections([*semantic_selected, *semantic_watch])
    primary_execution_rows = grouped_semantic_rows[_primary_execution_section(report_mode)]
    watch_queue_rows = grouped_semantic_rows["watch_queue"]
    blocked_rows = grouped_semantic_rows["blocked_only"]
    opportunity_actions = _resolve_opportunity_rows(brief, priority_board)
    formal_rows = [*selected_actions, *watch_actions, *opportunity_actions]
    intersection_summary = _build_intersection_summary(early_runner, formal_rows)
    profile_name = _first_non_empty(dict(session_summary.get("optimization_profile_resolution") or {}).get("profile_name"), session_summary.get("short_trade_target_profile_name"))
    early_status = str(early_runner.get("status") or "unavailable")
    enriched_only_early_runner = _enrich_early_runner_rows(
        _safe_rows(intersection_summary.get("only_early_runner_rows")),
        role="early_runner_watchlist",
        early_runner_status=early_status,
    )
    enriched_second_entry = _enrich_early_runner_rows(
        _safe_rows(intersection_summary.get("second_entry_rows")),
        role="early_runner_second_entry",
        early_runner_status=early_status,
    )
    decision_card = build_decision_card(
        selected_rows=semantic_selected,
        early_runner_status=early_status,
        signal_date=str(brief.get("trade_date") or ""),
        next_trade_date=str(brief.get("next_trade_date") or ""),
    )
    decision_card = _attach_decision_card_primary_name(decision_card, semantic_selected)
    lines = [
        f"# BTST 多智能体详细计划（{signal_date_compact}）",
        "",
        "## 核心结论",
        "",
        f"- 信号日：`{brief.get('trade_date')}`；目标交易日：`{brief.get('next_trade_date')}`。",
        f"- 运行目录：`{report_dir}`。",
        f"- 选股模式：`{brief.get('selection_target')}`；LLM 选股 profile：`{profile_name or 'n/a'}`。",
        f"- selected 数量：`{len(selected_actions)}`；watch 数量：`{len(watch_actions)}`；机会池数量：`{len(opportunity_actions)}`。",
        "",
    ]
    lines.extend(_render_decision_card(decision_card))
    lines.extend([""])
    lines.extend(_render_premarket_control_tower(control_tower))
    lines.extend([""])
    lines.extend(_render_win_rate_payoff_decision(selected_actions))
    lines.extend([""])
    lines.extend(_render_alpha_reliability_lines(selected_actions))
    lines.extend([""])
    lines.extend(_render_alpha_factor_cards(selected_actions))
    lines.extend([""])
    lines.extend(_render_gamma_market_gate_lines(selection_snapshot, selected_actions))
    lines.extend([""])
    lines.extend(_render_beta_execution_controls(selected_actions))
    lines.extend([""])
    lines.extend(_render_strategy_threshold_lines(strategy_thresholds, strategy_thresholds_config_path, strategy_thresholds_profile))
    lines.extend([""])
    lines.extend(_render_historical_metric_guide())
    rollout_lines = _render_rollout_validation_lines(brief)
    if rollout_lines:
        lines.extend([""])
        lines.extend(rollout_lines)
    lines.extend(["", f"## {section_labels['llm_execution_title']}", ""])
    lines.extend(_render_enriched_stock_bullets(primary_execution_rows, limit=5))
    lines.extend(["", "## 观察层", ""])
    lines.extend(_render_enriched_stock_bullets(watch_queue_rows, limit=8))
    if blocked_rows:
        lines.extend(["", "## 阻断层", ""])
        lines.extend(_render_enriched_stock_bullets(blocked_rows, limit=8))
    if opportunity_actions:
        lines.extend(["", "## 机会池", ""])
        lines.extend(_stock_bullets(opportunity_actions, limit=5, include_payoff=True))
    lines.extend(["", "## Early Runner 章节", ""])
    lines.extend(_render_early_runner_overlay(early_runner, formal_rows))
    lines.extend([""])
    lines.extend(_render_intersection_highlights(intersection_summary))
    lines.extend(["", "### 四层使用顺序", ""])
    if str(intersection_summary.get("status") or "") == "exact":
        if report_mode == "formal_execution":
            lines.append("- 正式执行层先决定主顺序，交集票只做优先复审，不做无条件升级。")
        else:
            lines.append("- 确认复核队列先决定主复核顺序，交集票只做优先复审，不做无条件升级。")
    else:
        lines.append("- 当前只有回退板或旧板可用，因此交集只做参考高亮，不升级为当日交集优先。")
    lines.append("- only early-runner 票只进入补充复审层，不自动升级为正式主票。")
    lines.append("- second-entry / reentry 单独归入回补机会层，不和普通补充票混用。")
    if _safe_rows(intersection_summary.get("only_early_runner_rows")):
        lines.extend(["", "### 补充复审层", ""])
        lines.extend(_render_enriched_stock_bullets(enriched_only_early_runner, limit=5))
    if _safe_rows(intersection_summary.get("second_entry_rows")):
        lines.extend(["", "### 回补机会层", ""])
        lines.extend(_render_enriched_stock_bullets(enriched_second_entry, limit=5))
    return "\n".join(lines) + "\n"


def _render_plain_language_doc(
    signal_date_compact: str,
    brief: dict[str, Any],
    semantic_selected: list[dict[str, Any]],
    semantic_watch: list[dict[str, Any]],
    early_runner: dict[str, Any],
    report_mode: str,
) -> str:
    """Render the plain-language explanation and explain why early-runner is watch-only now."""
    selected_actions = semantic_selected
    watch_actions = semantic_watch
    primary_action = _resolve_primary_semantic_action([*selected_actions, *watch_actions], report_mode=report_mode)
    intersection_summary = _build_intersection_summary(early_runner, [*selected_actions, *watch_actions])
    early_status = str(early_runner.get("status") or "unavailable")
    board = dict(early_runner.get("board") or {})
    status_note = {
        "exact": ("这次文档里已经拿到了当日 early-runner 板，但它当前仍是 `research_only`，只保留研究确认池，不生成可执行观察票。" if str(board.get("gate_action") or "") == "research_only" else "这次文档里已经拿到了当日 early-runner 板，所以它可以作为正式 BTST 旁边的第二观察层使用。"),
        "stale_fallback": "这次文档没有拿到当日 early-runner 板，只能回退到最近可用板，所以它只能作为参考线索，不能当成当天正式观察单。",
        "unavailable": "这次文档没有拿到可用 early-runner 板，所以只能显式记录缺失状态，不能拿它补出不存在的观察票。",
    }.get(early_status, "当前 early-runner 状态不明确，只能保守处理。")
    lines = [
        f"# {signal_date_compact}-两套交易计划通俗说明",
        "",
        f"信号日：`{brief.get('trade_date')}`；目标交易日：`{brief.get('next_trade_date')}`。",
        "",
        "## 先说结论",
        "",
        (
            f"确认复核主线仍以 `{_stock_label(primary_action)}` 这条主线为准，early-runner 不是替代品，而是补充观察层。{status_note}"
            if report_mode == "confirmation_review_only"
            else f"正式 BTST 仍以 `{_stock_label(primary_action)}` 这条主线为准，early-runner 不是替代品，而是补充观察层。{status_note}"
        ),
        "",
    ]
    lines.extend(_render_primary_contract_lines(primary_action, report_mode=report_mode))
    lines.extend([
        "",
        "## 这次为什么要把 Early Runner 写进来",
        "",
        "- 正式 BTST 更适合做最终执行排序。",
        "- early-runner 更适合做更早的补充观察和盘中复审。",
        "- 两边都同时命中的票，比只出现在单边的票更值得优先盯。",
        "",
        "## 正式 BTST 在看什么",
        "",
        f"- 主票是 `{_stock_label(primary_action)}`，执行模式是 `{primary_action.get('preferred_entry_mode') or 'n/a'}`。",
        f"- 正式 selected 数量是 `{len(selected_actions)}`，watch 数量是 `{len(watch_actions)}`。",
        "",
        "## Early Runner 在看什么",
        "",
    ])
    lines.extend(_render_early_runner_overlay(early_runner, [*selected_actions, *watch_actions]))
    lines.extend(
        [
            "",
            "## 交集票怎么处理",
            "",
        ]
    )
    if _safe_rows(intersection_summary.get("overlap_rows")):
        if early_status == "exact":
            lines.append("- 当日交集票会被高亮成“交集优先复审”，意思是先看这些票，再看普通观察票。")
        else:
            lines.append("- 当前看到的交集来自回退板，只能帮助你理解历史重合关系，不能当成明天一早的强优先级。")
        for row in _safe_rows(intersection_summary.get("overlap_rows"))[:5]:
            lines.append(f"- 交集票：`{_stock_label(dict(row.get('formal_row') or row.get('early_row') or {}))}`。")
    else:
        lines.append("- 这次没有交集票，所以仍按正式 BTST 主线和普通观察层执行。")
    lines.extend(
        [
            "",
            "## 怎么使用这两条线",
            "",
            ("- 确认复核主线决定先看谁，不能直接下单。" if report_mode == "confirmation_review_only" else "- 正式 BTST 决定主执行顺序。"),
            "- early-runner 负责提示更早的观察票和 second-entry 线索。",
            "- 只出现在 early-runner 的票默认不进正式执行清单，只放入盘中复审。",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_forum_doc(
    signal_date_compact: str,
    brief: dict[str, Any],
    semantic_selected: list[dict[str, Any]],
    semantic_watch: list[dict[str, Any]],
    early_runner: dict[str, Any],
    report_mode: str,
) -> str:
    """Render the short forum-ready version with a compact early-runner status note."""
    selected_actions = semantic_selected
    watch_actions = semantic_watch
    primary_action = _resolve_primary_semantic_action([*selected_actions, *watch_actions], report_mode=report_mode)
    intersection_summary = _build_intersection_summary(early_runner, [*selected_actions, *watch_actions])
    priority = _safe_rows(early_runner.get("priority"))
    watchlist = _safe_rows(early_runner.get("watchlist"))
    research_confirmation = _safe_rows(early_runner.get("research_confirmation"))
    extra_rows = priority[:2] or watchlist[:2]
    extra_label = "补充观察票优先看"
    if not extra_rows and research_confirmation:
        extra_rows = research_confirmation[:2]
        extra_label = "research-only 确认前排"
    extra = _stock_labels_text(extra_rows, limit=2)
    overlap = _stock_labels_text([dict(row.get("formal_row") or row.get("early_row") or {}) for row in _safe_rows(intersection_summary.get("overlap_rows"))[:3]])
    lines = [
        f"# {signal_date_compact}-两套交易计划论坛短版",
        "",
        f"信号日：`{brief.get('trade_date')}`；目标交易日：`{brief.get('next_trade_date')}`。",
        "",
        (
            f"明日确认复核主线还是 `{_stock_label(primary_action)}`，当前状态 `{primary_action.get('execution_state') or 'n/a'}` / 当日上限 `{primary_action.get('max_allowed_state_today') or 'n/a'}`，放行权 `{primary_action.get('release_authority') or 'none'}`，先确认再决定，不做开盘无脑追价。"
            if report_mode == "confirmation_review_only"
            else f"明日 BTST 主线还是 `{_stock_label(primary_action)}`，执行模式 `{primary_action.get('preferred_entry_mode') or 'n/a'}`，放行权 `{primary_action.get('release_authority') or 'none'}`，先确认再决定，不做开盘无脑追价。"
        ),
        "",
        f"这次 early-runner 状态：`{early_runner.get('status')}`；交集高亮 `{overlap}`；{extra_label} `{extra}`。",
        "",
        (
            "使用顺序：确认复核主线决定先看谁，early-runner 只做交集优先和补充复审，不替代正式执行单。"
            if report_mode == "confirmation_review_only"
            else "使用顺序：正式 BTST 决定主票，early-runner 只做交集优先和补充复审，不替代正式执行单。"
        ),
    ]
    return "\n".join(lines) + "\n"


def _render_checklist_doc(
    signal_date_compact: str,
    brief: dict[str, Any],
    priority_board: dict[str, Any],
    semantic_selected: list[dict[str, Any]],
    semantic_watch: list[dict[str, Any]],
    early_runner: dict[str, Any],
    selection_snapshot: dict[str, Any],
    control_tower: dict[str, Any],
    report_mode: str,
    veto_owner: str,
    section_labels: dict[str, str],
    strategy_thresholds: dict[str, Any],
    strategy_thresholds_config_path: str,
    strategy_thresholds_profile: str,
) -> str:
    """Render the next-morning checklist and append early-runner watch-only checkpoints."""
    selected_actions = semantic_selected
    watch_actions = semantic_watch
    grouped_semantic_rows = _group_rows_by_allowed_sections([*semantic_selected, *semantic_watch])
    primary_execution_rows = grouped_semantic_rows[_primary_execution_section(report_mode)]
    watch_queue_rows = grouped_semantic_rows["watch_queue"]
    blocked_rows = grouped_semantic_rows["blocked_only"]
    execution_state_rows = _flatten_grouped_rows(grouped_semantic_rows)
    intersection_summary = _build_intersection_summary(early_runner, [*selected_actions, *watch_actions])
    early_status = str(early_runner.get("status") or "unavailable")
    decision_card = build_decision_card(
        selected_rows=semantic_selected,
        early_runner_status=early_status,
        signal_date=str(brief.get("trade_date") or ""),
        next_trade_date=str(brief.get("next_trade_date") or ""),
    )
    decision_card = _attach_decision_card_primary_name(decision_card, semantic_selected)
    lines = [
        f"# BTST-{signal_date_compact}-EXEC-CHECKLIST",
        "",
        f"信号日：`{brief.get('trade_date')}`；目标交易日：`{brief.get('next_trade_date')}`。",
        "",
    ]
    lines.extend(_render_decision_card(decision_card))
    lines.extend([""])
    lines.extend(_render_premarket_control_tower(control_tower))
    lines.extend([""])
    lines.extend(_render_opening_timeline_lines(_stock_label(selected_actions[0]) if selected_actions else ""))
    lines.extend([""])
    lines.extend(_render_win_rate_payoff_gate(selected_actions))
    lines.extend([""])
    lines.extend(_render_gamma_market_gate_lines(selection_snapshot, selected_actions))
    lines.extend([""])
    lines.extend(_render_beta_execution_controls(selected_actions))
    lines.extend([""])
    lines.extend(_render_strategy_threshold_lines(strategy_thresholds, strategy_thresholds_config_path, strategy_thresholds_profile))
    lines.extend([""])
    lines.extend(_render_historical_metric_guide())
    rollout_lines = _render_rollout_validation_lines(brief)
    if rollout_lines:
        lines.extend([""])
        lines.extend(rollout_lines)
    lines.extend([""])
    lines.extend(_render_execution_state_table(execution_state_rows, title=section_labels["execution_state_table_title"]))
    lines.extend(["", f"## {section_labels['checklist_execution_title']}", ""])
    for row in primary_execution_rows[:3]:
        lines.append(f"- [ ] {section_labels['checklist_execution_item_label']}：`{_stock_label(row)}`，模式 `{row.get('preferred_entry_mode') or 'n/a'}`，" f"收盘胜率 `{_fmt_pct(_row_historical_metric(row, 'next_close_positive_rate'))}`，" f"盈亏比 `{_fmt_num(_row_historical_metric(row, 'next_close_payoff_ratio'), 2)}`，" f"说明：{_historical_reading_note(row)}")
    lines.extend([""])
    lines.extend(_render_action_matrix_sections(primary_execution_rows, report_mode=report_mode, limit=3))
    lines.extend(["", "## 正式观察顺序", ""])
    for row in watch_queue_rows[:6]:
        lines.append(f"- [ ] 正式观察：`{_stock_label(row)}`，层级 `{row.get('action_tier') or 'watch_only'}`，必要时盘中再确认。")
    if not watch_queue_rows:
        lines.append("- [ ] 当前没有进入 watch_queue 的观察票。")
    if blocked_rows:
        lines.extend(["", "## 阻断观察", ""])
        for row in blocked_rows[:6]:
            lines.append(
                f"- [ ] 阻断观察：`{_stock_label(row)}`，当前 execution_state `{row.get('execution_state') or 'blocked'}`，只做 blocker 复核，不进入当日执行/观察清单。"
            )
    lines.extend(["", "## 交集优先复审", ""])
    if _safe_rows(intersection_summary.get("overlap_rows")):
        for row in _safe_rows(intersection_summary.get("overlap_rows"))[:5]:
            merged = dict(row.get("formal_row") or row.get("early_row") or {})
            if str(intersection_summary.get("status") or "") == "exact":
                lines.append(f"- [ ] 交集优先：`{_stock_label(merged)}`，先于普通观察票复审。")
            else:
                lines.append(f"- [ ] 历史交集参考：`{_stock_label(merged)}`，仅做参考，不当作当日优先升级。")
    else:
        lines.append("- [ ] 当前没有交集票。")
    lines.extend(["", "## Early Runner 补充观察", ""])
    lines.extend(_render_early_runner_status(early_runner))
    only_early_runner_rows = _safe_rows(intersection_summary.get("only_early_runner_rows"))
    if only_early_runner_rows:
        for row in only_early_runner_rows[:5]:
            lines.append(f"- [ ] Early Runner 补充复审：`{_stock_label(row)}`，来源 `{row.get('table_key') or 'early_runner'}`，`pre_score={_fmt_num(row.get('pre_score'), 4)}`，`confirm_score={_fmt_num(row.get('confirm_score'), 4)}`，仅做补充复审。")
    else:
        lines.append("- [ ] 当前没有可直接使用的 only early-runner 补充票。")
    lines.extend(["", "## 回补机会层", ""])
    second_entry_rows = _safe_rows(intersection_summary.get("second_entry_rows"))
    if second_entry_rows:
        for row in second_entry_rows[:5]:
            lines.append(f"- [ ] Second Entry / Reentry：`{_stock_label(row)}`，`pre_score={_fmt_num(row.get('pre_score'), 4)}`，`confirm_score={_fmt_num(row.get('confirm_score'), 4)}`，等二次确认后再决定是否跟进。")
    else:
        lines.append("- [ ] 当前没有 second-entry / reentry 回补机会票。")
    lines.extend([""])
    lines.extend(_render_post_trade_review_loop())
    return "\n".join(lines) + "\n"


def _render_early_warning_doc(
    signal_date_compact: str,
    signal_date_iso: str,
    next_trade_date: str,
    early_runner: dict[str, Any],
    formal_rows: list[dict[str, Any]],
    semantic_selected: list[dict[str, Any]],
    control_tower: dict[str, Any],
    report_mode: str,
    strategy_thresholds: dict[str, Any],
    strategy_thresholds_config_path: str,
    strategy_thresholds_profile: str,
) -> str:
    """Render the dedicated early-warning document from early-runner watchlists and second-entry rows."""
    intersection_summary = _build_intersection_summary(early_runner, formal_rows)
    research_confirmation = _safe_rows(early_runner.get("research_confirmation"))
    early_status = str(early_runner.get("status") or "unavailable")
    enriched_priority = _enrich_early_runner_rows(
        _safe_rows(early_runner.get("priority")),
        role="early_runner_priority",
        early_runner_status=early_status,
    )
    enriched_watchlist = _enrich_early_runner_rows(
        _safe_rows(early_runner.get("watchlist")),
        role="early_runner_watchlist",
        early_runner_status=early_status,
    )
    enriched_second_entry = _enrich_early_runner_rows(
        _safe_rows(early_runner.get("second_entry")),
        role="early_runner_second_entry",
        early_runner_status=early_status,
    )
    enriched_research = _enrich_early_runner_rows(
        research_confirmation,
        role="early_runner_research",
        early_runner_status=early_status,
    )
    primary_action = _resolve_primary_semantic_action(
        semantic_selected,
        report_mode=report_mode,
    )
    lines = [
        f"# BTST 提前预警池（{signal_date_compact}）",
        "",
        f"信号日：`{signal_date_iso}`；目标交易日：`{next_trade_date}`。",
        "",
        "## 定位",
        "",
        "这份文档专门承接方案 A 的 early-runner 观察层，不替代正式 BTST 主计划。",
        "",
    ]
    lines.extend(_render_strategy_threshold_lines(strategy_thresholds, strategy_thresholds_config_path, strategy_thresholds_profile))
    lines.extend([""])
    lines.extend(_render_historical_metric_guide())
    lines.extend(
        [
            "",
            "## 状态",
            "",
        ]
    )
    lines.extend(_render_early_runner_status(early_runner))
    lines.extend(
        [
            "",
        ]
    )
    lines.extend(
        _render_contract_mirror_lines(
            primary_action,
            report_mode=report_mode,
            control_tower=control_tower,
            title="## 与主执行层对齐的当日 contract",
        )
    )
    lines.extend([""])
    lines.extend(_render_intersection_highlights(intersection_summary))
    lines.extend(["", "## Priority", ""])
    lines.extend(_render_enriched_stock_bullets(enriched_priority, limit=6))
    lines.extend(["", "## Watchlist", ""])
    lines.extend(_render_enriched_stock_bullets(enriched_watchlist, limit=8))
    lines.extend(["", "## Second Entry / Reentry", ""])
    lines.extend(_render_enriched_stock_bullets(enriched_second_entry, limit=8))
    if research_confirmation:
        lines.extend(["", "## Research Only 确认池", ""])
        lines.append("- 当前是 research_only 板，以下确认票只保留为研究确认，不自动升级为可执行 early-runner 观察票。")
        lines.extend(_render_enriched_stock_bullets(enriched_research, limit=8))
    lines.extend(["", "## 使用原则", ""])
    lines.extend(
        [
            "- 只把它当作补充观察，不把它自动升级成正式交易单。",
            "- 交集票优先看，only early-runner 票只做盘中复审。",
            "- second-entry / reentry 单独管理，不能和普通补充票混成一层。",
            "- 如果 early-runner 板不是当日板，只能参考，不做强结论。",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_early_warning_card_doc(
    signal_date_compact: str,
    signal_date_iso: str,
    next_trade_date: str,
    early_runner: dict[str, Any],
    formal_rows: list[dict[str, Any]],
    semantic_selected: list[dict[str, Any]],
    control_tower: dict[str, Any],
    report_mode: str,
) -> str:
    """Render the compact early-warning card for quick reading."""
    intersection_summary = _build_intersection_summary(early_runner, formal_rows)
    priority = _safe_rows(early_runner.get("priority"))
    watchlist = _safe_rows(early_runner.get("watchlist"))
    second_entry = _safe_rows(early_runner.get("second_entry"))
    research_confirmation = _safe_rows(early_runner.get("research_confirmation"))
    primary_action = _resolve_primary_semantic_action(
        semantic_selected,
        report_mode=report_mode,
    )
    lines = [
        f"# BTST 提前预警卡（{signal_date_compact}）",
        "",
        f"- 信号日：`{signal_date_iso}`；目标交易日：`{next_trade_date}`。",
        f"- early-runner 状态：`{early_runner.get('status')}`。",
        f"- 交集高亮：`{_stock_labels_text([dict(row.get('formal_row') or row.get('early_row') or {}) for row in _safe_rows(intersection_summary.get('overlap_rows'))[:5]])}`。",
        f"- priority：`{_stock_labels_text(priority, limit=5)}`。",
        f"- watchlist：`{_stock_labels_text(watchlist, limit=5)}`。",
        f"- second_entry：`{_stock_labels_text(second_entry, limit=5)}`。",
        "- 使用顺序：先看正式 BTST，再看交集优先复审，only early-runner 做补充复审，second-entry 单独看回补机会。",
    ]
    lines[4:4] = _render_contract_mirror_lines(
        primary_action,
        report_mode=report_mode,
        control_tower=control_tower,
        title=None,
    )
    if research_confirmation:
        lines.insert(
            8,
            f"- research_only 确认池：`{_stock_labels_text(research_confirmation, limit=5)}`。",
        )
    return "\n".join(lines) + "\n"


def _build_report_quality_summary(
    *,
    signal_date_compact: str,
    docs: dict[str, str],
    report_mode: str,
    veto_owner: str,
    section_labels: dict[str, str],
    semantic_rows: list[dict[str, Any]],
    control_tower: dict[str, Any],
    early_runner: dict[str, Any],
    selection_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Build a machine-readable QA summary for the generated report bundle."""
    forbidden_hits = _build_forbidden_semantics_hits(
        signal_date_compact=signal_date_compact,
        docs=docs,
        report_mode=report_mode,
    )
    required_sections = {
        f"BTST-LLM-{signal_date_compact}.md": [
            "## 30 秒决策卡",
            "## 盘前控制塔",
            "## Alpha 样本稳健性与标签拆解",
            "## Alpha 因子证据卡",
            "## Gamma 市场门控与风险预算",
            "## Beta 执行硬条件与成本闸门",
            "## Governed Rollout 观察",
            f"## {section_labels['llm_execution_title']}",
        ],
        f"BTST-{signal_date_compact}-EXEC-CHECKLIST.md": [
            "## 30 秒决策卡",
            "## 盘前控制塔",
            "## 早盘时间轴",
            "## 胜率/赔率闸门",
            "## Gamma 市场门控与风险预算",
            "## Beta 执行硬条件与成本闸门",
            f"## {section_labels['execution_state_table_title']}",
            f"## {section_labels['checklist_execution_title']}",
            "## 盘后复盘闭环",
        ],
        f"{signal_date_compact}-两套交易计划通俗说明.md": [
            "## 当日状态与放行权",
        ],
    }
    missing: list[str] = []
    for file_name, sections in required_sections.items():
        content = docs.get(file_name, "")
        for section in sections:
            if section not in content:
                missing.append(f"{file_name}:{section}")
    quality_warnings = [
        code
        for code in list(control_tower.get("reason_codes") or [])
        if code
        in {
            "market_gate_downgraded_raw_trade_allowed",
            "market_gate_requires_confirmation",
            "selection_snapshot_missing",
        }
    ]
    return {
        "signal_date": signal_date_compact,
        "report_mode": report_mode,
        "veto_owner": veto_owner,
        "section_labels": dict(section_labels),
        "control_tower": control_tower,
        "early_runner_status": early_runner.get("status"),
        "selection_snapshot_loaded": bool(selection_snapshot),
        "required_sections_missing": missing,
        "quality_warnings": quality_warnings,
        "semantic_conflicts": _build_semantic_conflicts(report_mode=report_mode, rows=semantic_rows),
        "forbidden_semantics_hits": forbidden_hits,
        "source_of_truth_snapshot": _build_source_of_truth_snapshot(
            signal_date_compact=signal_date_compact,
            report_mode=report_mode,
            veto_owner=veto_owner,
            section_labels=section_labels,
            control_tower=control_tower,
            early_runner=early_runner,
            selection_snapshot=selection_snapshot,
            semantic_rows=semantic_rows,
            forbidden_semantics_hits=forbidden_hits,
        ),
    }


def generate_btst_doc_bundle(
    signal_date: str,
    *,
    reports_root: str | Path = REPORTS_DIR,
    output_dir: str | Path | None = None,
    report_dir: str | Path | None = None,
    refresh_early_runner: bool = True,
    include_extra_warning_docs: bool = True,
    strategy_thresholds_config_path: str | Path | None = None,
    strategy_thresholds_profile: str = DEFAULT_STRATEGY_THRESHOLDS_PROFILE,
    write_review_ledger: bool = False,
) -> dict[str, Any]:
    """Generate the final BTST reading bundle and append scheme-A early-runner sections."""
    signal_date_compact, signal_date_iso = _normalize_signal_date(signal_date)
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_report_dir = _discover_report_dir(resolved_reports_root, signal_date_iso, report_dir)
    session_summary = _read_json(resolved_report_dir / "session_summary.json")
    followup_paths = dict(session_summary.get("btst_followup") or {})
    brief = _read_json(Path(followup_paths["brief_json"]))
    priority_board = _read_json(Path(followup_paths["priority_board_json"])) if followup_paths.get("priority_board_json") else {}
    rule_report_path = resolved_reports_root / f"btst_full_report_{signal_date_compact}.json"
    rule_report = _read_json(rule_report_path)
    early_runner = _load_early_runner_context(resolved_reports_root, signal_date_iso, refresh=refresh_early_runner)
    _enrich_missing_stock_names(
        reports_root=resolved_reports_root,
        report_dir=resolved_report_dir,
        rule_report=rule_report,
        brief=brief,
        priority_board=priority_board,
        early_runner=early_runner,
    )
    selection_snapshot = _load_selection_snapshot(
        report_dir=resolved_report_dir,
        signal_date_iso=signal_date_iso,
        brief=brief,
        priority_board=priority_board,
    )
    resolved_strategy_thresholds = resolve_strategy_thresholds(
        config_path=strategy_thresholds_config_path,
        profile=strategy_thresholds_profile,
    )
    resolved_strategy_thresholds_config_path = _resolve_thresholds_config_path(
        strategy_thresholds_config_path,
        profile=strategy_thresholds_profile,
    )
    selected_rows = _resolve_selected_rows(brief, priority_board)
    watch_rows = _resolve_watch_rows(brief, priority_board)
    opportunity_rows = _resolve_opportunity_rows(brief, priority_board)
    formal_rows = [*selected_rows, *watch_rows, *opportunity_rows]
    intersection_summary = _build_intersection_summary(early_runner, formal_rows)
    target_output_dir = Path(output_dir).expanduser().resolve() if output_dir else (OUTPUTS_DIR / signal_date_compact[:6] / brief.get("next_trade_date", signal_date_iso).replace("-", "")).resolve()
    early_status = str(early_runner.get("status") or "unavailable")
    control_selected = _enrich_formal_rows(
        selected_rows,
        role="formal_selected",
        early_runner_status=early_status,
    )
    control_watch = _enrich_formal_rows(
        watch_rows,
        role="formal_watch",
        early_runner_status=early_status,
    )
    control_decision_card = build_decision_card(
        selected_rows=control_selected,
        early_runner_status=early_status,
        signal_date=str(brief.get("trade_date") or signal_date_iso),
        next_trade_date=str(brief.get("next_trade_date") or ""),
    )
    control_tower = _build_premarket_control_tower(control_decision_card, selection_snapshot)
    report_mode = build_report_mode(control_tower)
    veto_owner = build_veto_owner(control_tower)
    section_labels = _build_section_labels(report_mode)
    control_tower = {
        **control_tower,
        "report_mode": report_mode,
        "veto_owner": veto_owner,
    }
    semantic_selected = _attach_execution_semantics_rows(
        control_selected,
        report_mode=report_mode,
        control_tower=control_tower,
        veto_owner=veto_owner,
    )
    semantic_watch = _attach_execution_semantics_rows(
        control_watch,
        report_mode=report_mode,
        control_tower=control_tower,
        veto_owner=veto_owner,
    )
    docs = {
        f"BTST-{signal_date_compact}.md": _render_rule_doc(signal_date_compact, rule_report, brief, priority_board, early_runner, rule_report_path, resolved_report_dir, resolved_strategy_thresholds, resolved_strategy_thresholds_config_path, strategy_thresholds_profile),
        f"BTST-LLM-{signal_date_compact}.md": _render_llm_doc(signal_date_compact, brief, priority_board, session_summary, semantic_selected, semantic_watch, early_runner, selection_snapshot, control_tower, report_mode, veto_owner, section_labels, resolved_report_dir, resolved_strategy_thresholds, resolved_strategy_thresholds_config_path, strategy_thresholds_profile),
        f"{signal_date_compact}-两套交易计划通俗说明.md": _render_plain_language_doc(signal_date_compact, brief, semantic_selected, semantic_watch, early_runner, report_mode),
        f"{signal_date_compact}-两套交易计划论坛短版.md": _render_forum_doc(signal_date_compact, brief, semantic_selected, semantic_watch, early_runner, report_mode),
        f"BTST-{signal_date_compact}-EXEC-CHECKLIST.md": _render_checklist_doc(signal_date_compact, brief, priority_board, semantic_selected, semantic_watch, early_runner, selection_snapshot, control_tower, report_mode, veto_owner, section_labels, resolved_strategy_thresholds, resolved_strategy_thresholds_config_path, strategy_thresholds_profile),
    }
    if include_extra_warning_docs:
        docs[f"BTST-{signal_date_compact}-EARLY-WARNING.md"] = _render_early_warning_doc(signal_date_compact, signal_date_iso, str(brief.get("next_trade_date") or ""), early_runner, formal_rows, semantic_selected, control_tower, report_mode, resolved_strategy_thresholds, resolved_strategy_thresholds_config_path, strategy_thresholds_profile)
        docs[f"BTST-{signal_date_compact}-EARLY-WARNING-CARD.md"] = _render_early_warning_card_doc(signal_date_compact, signal_date_iso, str(brief.get("next_trade_date") or ""), early_runner, formal_rows, semantic_selected, control_tower, report_mode)
    quality_summary = _build_report_quality_summary(
        signal_date_compact=signal_date_compact,
        docs=docs,
        report_mode=report_mode,
        veto_owner=veto_owner,
        section_labels=section_labels,
        semantic_rows=[*semantic_selected, *semantic_watch],
        control_tower=control_tower,
        early_runner=early_runner,
        selection_snapshot=selection_snapshot,
    )
    quality_summary_json_path = target_output_dir / f"{signal_date_compact}-btst-report-quality-summary.json"
    written_files = []
    for name, content in docs.items():
        target_path = target_output_dir / name
        _write_text(target_path, content)
        written_files.append(target_path.as_posix())
    _write_text(quality_summary_json_path, json.dumps(quality_summary, ensure_ascii=False, indent=2) + "\n")
    review_ledger_json_path = None
    if write_review_ledger:
        ledger_rows = build_review_ledger_rows(
            signal_date=str(brief.get("trade_date") or signal_date_iso),
            next_trade_date=str(brief.get("next_trade_date") or ""),
                rows=[*semantic_selected, *semantic_watch],
            report_mode=report_mode,
            control_tower=control_tower,
        )
        review_ledger_json_path = target_output_dir / f"{signal_date_compact}-btst-decision-review-ledger.json"
        _write_text(
            review_ledger_json_path,
            json.dumps(
                {
                    "signal_date": str(brief.get("trade_date") or signal_date_iso),
                    "next_trade_date": str(brief.get("next_trade_date") or ""),
                    "rows": ledger_rows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        written_files.append(review_ledger_json_path.as_posix())
    return {
        "status": "generated",
        "signal_date": signal_date_compact,
        "signal_date_iso": signal_date_iso,
        "report_dir": resolved_report_dir.as_posix(),
        "output_dir": target_output_dir.as_posix(),
        "written_files": written_files,
        "early_runner_status": early_runner.get("status"),
        "early_runner_latest_trade_date": early_runner.get("latest_trade_date"),
        "early_runner_intersection_count": len(_safe_rows(intersection_summary.get("overlap_rows"))),
        "early_runner_only_count": len(_safe_rows(intersection_summary.get("only_early_runner_rows"))),
        "early_runner_second_entry_count": len(_safe_rows(intersection_summary.get("second_entry_rows"))),
        "strategy_thresholds_config_path": resolved_strategy_thresholds_config_path,
        "strategy_thresholds_profile": strategy_thresholds_profile,
        "strategy_thresholds": resolved_strategy_thresholds,
        "control_tower": control_tower,
        "report_mode": report_mode,
        "veto_owner": veto_owner,
        "section_labels": section_labels,
        "quality_summary_json_path": quality_summary_json_path.as_posix(),
        "review_ledger_json_path": review_ledger_json_path.as_posix() if review_ledger_json_path else None,
    }


def _build_profile_doc_bundle_comparison(profile_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare daily BTST bundle outputs across multiple threshold profiles."""
    profiles = [
        {
            "profile": profile,
            "output_dir": result.get("output_dir"),
            "written_file_count": len(list(result.get("written_files") or [])),
            "early_runner_status": result.get("early_runner_status"),
            "intersection_count": int(result.get("early_runner_intersection_count") or 0),
            "only_early_runner_count": int(result.get("early_runner_only_count") or 0),
            "second_entry_count": int(result.get("early_runner_second_entry_count") or 0),
        }
        for profile, result in profile_results.items()
    ]
    ranked_profiles = sorted(
        profiles,
        key=lambda item: (
            int(item.get("intersection_count") or 0),
            -int(item.get("only_early_runner_count") or 0),
            -int(item.get("second_entry_count") or 0),
            1 if item.get("profile") == "conservative" else 0,
        ),
        reverse=True,
    )
    recommended_profile = ranked_profiles[0]["profile"] if ranked_profiles else None
    reasons: list[str] = []
    if len(ranked_profiles) >= 2:
        top = ranked_profiles[0]
        runner_up = ranked_profiles[1]
        if top["intersection_count"] == runner_up["intersection_count"] and top["only_early_runner_count"] == runner_up["only_early_runner_count"] and top["second_entry_count"] == runner_up["second_entry_count"]:
            reasons.append("两套 profile 的交集票、only early-runner 与 second-entry 完全持平；没有形成有效 profile 差异，默认采用 conservative 做风控基线。")
        else:
            if top["intersection_count"] > runner_up["intersection_count"]:
                reasons.append(f"`{top['profile']}` 的交集票更多：`{top['intersection_count']}` vs `{runner_up['intersection_count']}`。")
            if top["only_early_runner_count"] < runner_up["only_early_runner_count"]:
                reasons.append(f"`{top['profile']}` 的 only early-runner 更少：`{top['only_early_runner_count']}` vs `{runner_up['only_early_runner_count']}`。")
            if top["second_entry_count"] < runner_up["second_entry_count"]:
                reasons.append(f"`{top['profile']}` 的 second-entry 干扰更少：`{top['second_entry_count']}` vs `{runner_up['second_entry_count']}`。")
    return {
        "profiles": sorted(profiles, key=lambda item: str(item["profile"])),
        "recommended_profile": recommended_profile,
        "recommendation_reasons": reasons,
    }


def _render_profile_doc_bundle_comparison_markdown(signal_date_compact: str, comparison: dict[str, Any]) -> str:
    """Render one markdown summary for daily BTST bundle profile comparison."""
    lines = [
        f"# BTST {signal_date_compact} Profile 文档包对照",
        "",
        f"- 推荐 profile：`{comparison.get('recommended_profile') or 'n/a'}`",
        "",
        "## 总览",
        "",
        "| profile | early_runner_status | intersection_count | only_early_runner_count | second_entry_count | written_file_count | output_dir |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in list(comparison.get("profiles") or []):
        lines.append(f"| {item['profile']} | {item.get('early_runner_status')} | {item.get('intersection_count')} | {item.get('only_early_runner_count')} | {item.get('second_entry_count')} | {item.get('written_file_count')} | {item.get('output_dir')} |")
    lines.extend(["", "## 推荐理由", ""])
    if list(comparison.get("recommendation_reasons") or []):
        for reason in list(comparison.get("recommendation_reasons") or []):
            lines.append(f"- {reason}")
    else:
        lines.append("- 当前样本不足，尚未形成明显 profile 差异。")
    return "\n".join(lines) + "\n"


def _build_profile_doc_bundle_decision_card(comparison: dict[str, Any]) -> dict[str, Any]:
    """Build one compact pre-trade decision card from the daily profile comparison."""
    profiles = list(comparison.get("profiles") or [])
    recommended_profile = comparison.get("recommended_profile")
    recommended = next(
        (item for item in profiles if item.get("profile") == recommended_profile),
        None,
    )
    alternatives = [item for item in profiles if item.get("profile") != recommended_profile]
    challenger = alternatives[0] if alternatives else None
    action_bias = "偏保守执行" if recommended_profile == "conservative" else "偏激进执行"
    return {
        "recommended_profile": recommended_profile,
        "action_bias": action_bias,
        "early_runner_status": recommended.get("early_runner_status") if recommended else None,
        "intersection_count": int(recommended.get("intersection_count") or 0) if recommended else 0,
        "only_early_runner_count": int(recommended.get("only_early_runner_count") or 0) if recommended else 0,
        "second_entry_count": int(recommended.get("second_entry_count") or 0) if recommended else 0,
        "intersection_delta_vs_runner_up": (int(recommended.get("intersection_count") or 0) - int(challenger.get("intersection_count") or 0) if recommended and challenger else 0),
        "only_early_runner_delta_vs_runner_up": (int(recommended.get("only_early_runner_count") or 0) - int(challenger.get("only_early_runner_count") or 0) if recommended and challenger else 0),
        "second_entry_delta_vs_runner_up": (int(recommended.get("second_entry_count") or 0) - int(challenger.get("second_entry_count") or 0) if recommended and challenger else 0),
        "recommendation_reasons": list(comparison.get("recommendation_reasons") or []),
    }


def _render_profile_doc_bundle_decision_card_markdown(signal_date_compact: str, decision_card: dict[str, Any]) -> str:
    """Render one compact pre-trade decision card for fast profile selection."""
    lines = [
        f"# BTST {signal_date_compact} 交易前决策卡",
        "",
        f"- 推荐 profile：`{decision_card.get('recommended_profile') or 'n/a'}`",
        f"- 执行倾向：`{decision_card.get('action_bias') or 'n/a'}`",
        f"- early-runner 状态：`{decision_card.get('early_runner_status') or 'n/a'}`",
        f"- 交集票：`{decision_card.get('intersection_count')}`；相对次优差值：`{decision_card.get('intersection_delta_vs_runner_up'):+d}`",
        f"- only early-runner：`{decision_card.get('only_early_runner_count')}`；相对次优差值：`{decision_card.get('only_early_runner_delta_vs_runner_up'):+d}`",
        f"- second-entry：`{decision_card.get('second_entry_count')}`；相对次优差值：`{decision_card.get('second_entry_delta_vs_runner_up'):+d}`",
        "",
        "## 快速判断",
        "",
    ]
    if list(decision_card.get("recommendation_reasons") or []):
        for reason in list(decision_card.get("recommendation_reasons") or []):
            lines.append(f"- {reason}")
    else:
        lines.append("- 当前样本不足，暂不偏向单一 profile。")
    return "\n".join(lines) + "\n"


def _render_profile_decision_bridge_lines(decision_card: dict[str, Any]) -> list[str]:
    """Render one shared conclusion block that can be injected into final BTST docs."""
    return [
        "## 今日执行倾向",
        "",
        f"- 今日更偏：`{decision_card.get('recommended_profile') or 'n/a'}`，执行倾向：`{decision_card.get('action_bias') or 'n/a'}`。",
        f"- 交集票：`{decision_card.get('intersection_count')}`；相对次优差值：`{int(decision_card.get('intersection_delta_vs_runner_up') or 0):+d}`。",
        f"- only early-runner：`{decision_card.get('only_early_runner_count')}`；相对次优差值：`{int(decision_card.get('only_early_runner_delta_vs_runner_up') or 0):+d}`。",
        f"- second-entry：`{decision_card.get('second_entry_count')}`；相对次优差值：`{int(decision_card.get('second_entry_delta_vs_runner_up') or 0):+d}`。",
    ] + [f"- {reason}" for reason in list(decision_card.get("recommendation_reasons") or [])]


def _append_profile_decision_bridge(
    output_dir: Path,
    signal_date_compact: str,
    decision_card: dict[str, Any],
) -> list[str]:
    """Append one shared profile-decision bridge section into the main BTST docs."""
    bridge = "\n" + "\n".join(_render_profile_decision_bridge_lines(decision_card)) + "\n"
    updated_files: list[str] = []
    for file_name in (
        f"BTST-{signal_date_compact}.md",
        f"BTST-LLM-{signal_date_compact}.md",
    ):
        target_path = output_dir / file_name
        if not target_path.exists():
            continue
        original = target_path.read_text(encoding="utf-8")
        if "## 今日执行倾向" in original:
            continue
        target_path.write_text(original.rstrip() + bridge, encoding="utf-8")
        updated_files.append(target_path.as_posix())
    return updated_files


def compare_btst_doc_bundle_profiles(
    signal_date: str,
    *,
    profiles: list[str] | tuple[str, ...],
    reports_root: str | Path = REPORTS_DIR,
    output_dir: str | Path | None = None,
    report_dir: str | Path | None = None,
    refresh_early_runner: bool = True,
    include_extra_warning_docs: bool = True,
) -> dict[str, Any]:
    """Generate daily BTST bundles for multiple profiles and write one comparison report."""
    signal_date_compact, _ = _normalize_signal_date(signal_date)
    resolved_output_dir = Path(output_dir).expanduser().resolve() if output_dir else (OUTPUTS_DIR / signal_date_compact[:6] / f"{signal_date_compact}_profile_compare").resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    profile_results: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        profile_output_dir = resolved_output_dir / str(profile)
        profile_results[str(profile)] = generate_btst_doc_bundle(
            signal_date_compact,
            reports_root=reports_root,
            output_dir=profile_output_dir,
            report_dir=report_dir,
            refresh_early_runner=refresh_early_runner,
            include_extra_warning_docs=include_extra_warning_docs,
            strategy_thresholds_profile=str(profile),
        )
    comparison = _build_profile_doc_bundle_comparison(profile_results)
    decision_card = _build_profile_doc_bundle_decision_card(comparison)
    bridge_updated_files: list[str] = []
    for profile, result in profile_results.items():
        bridge_updated_files.extend(
            _append_profile_decision_bridge(
                Path(result["output_dir"]),
                signal_date_compact,
                decision_card,
            )
        )
    json_path = resolved_output_dir / f"{signal_date_compact}-btst-doc-bundle-profile-comparison.json"
    md_path = resolved_output_dir / f"{signal_date_compact}-btst-doc-bundle-profile-comparison.md"
    card_json_path = resolved_output_dir / f"{signal_date_compact}-btst-pretrade-decision-card.json"
    card_md_path = resolved_output_dir / f"{signal_date_compact}-btst-pretrade-decision-card.md"
    payload = {
        "signal_date": signal_date_compact,
        "profiles": list(profiles),
        "comparison": comparison,
        "decision_card": decision_card,
        "bridge_updated_files": bridge_updated_files,
        "profile_results": profile_results,
    }
    _write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    _write_text(md_path, _render_profile_doc_bundle_comparison_markdown(signal_date_compact, comparison))
    _write_text(card_json_path, json.dumps(decision_card, ensure_ascii=False, indent=2) + "\n")
    _write_text(card_md_path, _render_profile_doc_bundle_decision_card_markdown(signal_date_compact, decision_card))
    return {
        "status": "compared",
        "signal_date": signal_date_compact,
        "output_dir": resolved_output_dir.as_posix(),
        "json_path": json_path.as_posix(),
        "md_path": md_path.as_posix(),
        "decision_card_json_path": card_json_path.as_posix(),
        "decision_card_md_path": card_md_path.as_posix(),
        "comparison": comparison,
        "decision_card": decision_card,
        "bridge_updated_files": bridge_updated_files,
        "profile_results": profile_results,
    }


def main() -> None:
    """CLI entrypoint for generating the BTST reading bundle."""
    parser = argparse.ArgumentParser(description="Generate BTST reading docs with scheme-A early-runner sections.")
    parser.add_argument("--signal-date", required=True, help="Signal date in YYYYMMDD or YYYY-MM-DD format.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--no-refresh-early-runner", action="store_true")
    parser.add_argument("--core-only", action="store_true", help="Generate only the 5 canonical BTST docs.")
    parser.add_argument("--strategy-thresholds-config", default="")
    parser.add_argument("--strategy-thresholds-profile", default=DEFAULT_STRATEGY_THRESHOLDS_PROFILE)
    parser.add_argument("--compare-profiles", nargs="*", default=[])
    parser.add_argument("--write-review-ledger", action="store_true")
    args = parser.parse_args()
    if list(args.compare_profiles):
        result = compare_btst_doc_bundle_profiles(
            args.signal_date,
            profiles=list(args.compare_profiles),
            reports_root=args.reports_root,
            output_dir=args.output_dir or None,
            report_dir=args.report_dir or None,
            refresh_early_runner=not args.no_refresh_early_runner,
            include_extra_warning_docs=not args.core_only,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    result = generate_btst_doc_bundle(
        args.signal_date,
        reports_root=args.reports_root,
        output_dir=args.output_dir or None,
        report_dir=args.report_dir or None,
        refresh_early_runner=not args.no_refresh_early_runner,
        include_extra_warning_docs=not args.core_only,
        strategy_thresholds_config_path=args.strategy_thresholds_config or None,
        strategy_thresholds_profile=args.strategy_thresholds_profile,
        write_review_ledger=args.write_review_ledger,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
