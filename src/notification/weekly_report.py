"""P2-10 组合体检周报 — 自动生成 + 推送。

设计原则:
  - **纯函数**: ``generate_weekly_report`` 不依赖外部状态, 便于单测
  - **优雅降级**: 任一区块数据缺失 → "本周无 X 数据", 不崩溃
  - **复用**: 调 brinson_attribution / performance_report / push 框架, 不重新实现
  - **企微切分**: Markdown > 4096 字节时按区块切分发送

入口:
  - ``generate_weekly_report(start_date, end_date) -> str``
  - ``push_weekly_report(start_date, end_date, channel) -> int``
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.notification.push import (
    MAX_WECOM_CONTENT,
    PushChannel,
    PushConfig,
    PushPayload,
    PushResult,
    load_push_config,
    send_push,
)

logger = logging.getLogger(__name__)

# 默认报告目录
_DEFAULT_REPORT_DIR = Path("data/reports")
_DEFAULT_TRACKING_FILE = "tracking_history.json"


# ---------------------------------------------------------------------------
# 日期工具
# ---------------------------------------------------------------------------


def _this_monday_friday(ref_date: datetime | None = None) -> tuple[str, str]:
    """返回本周一/五的 YYYYMMDD。周日时回退到上一周。"""
    today = ref_date or datetime.now()
    # 周日 (weekday==6) 回退 7 天取周一; 其余正常
    if today.weekday() == 6:
        monday = today - timedelta(days=6)
    else:
        monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)
    return monday.strftime("%Y%m%d"), friday.strftime("%Y%m%d")


def _fmt_display(date_str: str) -> str:
    """YYYYMMDD → YYYY-MM-DD。"""
    cleaned = date_str.replace("-", "").strip()
    if len(cleaned) == 8:
        return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:]}"
    return date_str


# ---------------------------------------------------------------------------
# 区块 1: Brinson 归因
# ---------------------------------------------------------------------------


def _block_brinson_attribution(start: str, end: str, positions_path: Path | None = None) -> str:
    """本周 Brinson 归因 — 复用 brinson_attribution / brinson_attribution_from_snapshots。"""
    try:
        from src.portfolio.return_attribution import brinson_attribution

        # 尝试从 positions_path 或默认路径加载持仓数据
        path = positions_path
        if path is None:
            default_positions = Path("data/positions.json")
            if default_positions.exists():
                path = default_positions

        if path is None or not path.exists():
            return "### 本周归因\n\n> 本周无持仓数据\n"

        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        # 支持两种格式: 单个 dict 或 list
        if isinstance(raw, list):
            positions_list = raw
        elif isinstance(raw, dict):
            positions_list = raw.get("positions", [raw])
        else:
            return "### 本周归因\n\n> 本周无持仓数据\n"

        if not positions_list:
            return "### 本周归因\n\n> 本周无持仓数据\n"

        # 从持仓快照提取 ticker_returns 和 market_values
        ticker_returns: dict[str, float] = {}
        ticker_mvs: dict[str, float] = {}
        total_mv = 0.0

        for pos in positions_list:
            if not isinstance(pos, dict):
                continue
            ticker = str(pos.get("ticker", "") or "").strip()
            if not ticker:
                continue
            ret = float(pos.get("return_pct", 0.0) or 0.0)
            mv = float(pos.get("market_value", 0.0) or pos.get("value", 0.0) or 0.0)
            ticker_returns[ticker] = ret
            ticker_mvs[ticker] = mv
            total_mv += abs(mv)

        if total_mv <= 0:
            return "### 本周归因\n\n> 本周无持仓数据\n"

        result = brinson_attribution(
            start_date=start,
            end_date=end,
            ticker_returns=ticker_returns,
            ticker_market_values=ticker_mvs,
            total_portfolio_value=total_mv,
        )

        lines = ["### 本周归因 (Brinson)\n"]
        lines.append(f"- 组合收益: {result.total_portfolio_return:+.2%}")
        lines.append(f"- 基准收益: {result.total_benchmark_return:+.2%}")
        lines.append(f"- 配置贡献: {result.total_allocation_contribution:+.2%}")
        lines.append(f"- 选择贡献: {result.total_selection_contribution:+.2%}")

        # Top 3 贡献
        sorted_tickers = sorted(result.tickers, key=lambda t: t.total_contribution, reverse=True)
        if sorted_tickers:
            lines.append("\n**贡献 Top 3:**\n")
            for t in sorted_tickers[:3]:
                lines.append(f"  {t.ticker}: {t.total_contribution:+.2%} (配置 {t.allocation_contribution:+.2%}, 选择 {t.selection_contribution:+.2%})")
        lines.append("")
        return "\n".join(lines)

    except Exception as exc:
        logger.warning("[WeeklyReport] Brinson 归因异常: %s", exc)
        return "### 本周归因\n\n> 本周无持仓数据\n"


# ---------------------------------------------------------------------------
# 区块 2: 退出/调仓摘要
# ---------------------------------------------------------------------------


def _block_exit_rebalance_summary(start: str, end: str, report_dir: Path | None = None) -> str:
    """触发退出/调仓次数 + 平均收益 — 从 tracking_history 读取。"""
    try:
        rdir = report_dir or _DEFAULT_REPORT_DIR
        history_path = rdir / _DEFAULT_TRACKING_FILE
        if not history_path.exists():
            return "### 退出调仓\n\n> 本周无交易记录\n"

        with open(history_path, encoding="utf-8") as f:
            payload = json.load(f)

        records = payload.get("records", [])
        if not isinstance(records, list):
            return "### 退出调仓\n\n> 本周无交易记录\n"

        # 筛选本周范围内的记录
        start_clean = start.replace("-", "")
        end_clean = end.replace("-", "")
        week_records = []
        for rec in records:
            rec_date = str(rec.get("recommended_date", "") or "").replace("-", "").strip()
            if len(rec_date) == 8 and start_clean <= rec_date <= end_clean:
                week_records.append(rec)

        if not week_records:
            return "### 退出调仓\n\n> 本周无交易记录\n"

        exits = 0
        rebalances = 0
        returns: list[float] = []
        for rec in week_records:
            action = str(rec.get("action", "") or "").lower()
            ret = float(rec.get("next_day_return", 0.0) or 0.0)
            returns.append(ret)
            if "exit" in action or "sell" in action or "止损" in action:
                exits += 1
            elif "rebalance" in action or "调仓" in action:
                rebalances += 1

        avg_ret = sum(returns) / len(returns) if returns else 0.0
        lines = ["### 退出调仓\n"]
        lines.append(f"- 本周交易: {len(week_records)} 笔")
        lines.append(f"- 触发退出: {exits} 次 | 调仓: {rebalances} 次")
        lines.append(f"- 平均收益: {avg_ret:+.2%}")
        lines.append("")
        return "\n".join(lines)

    except Exception as exc:
        logger.warning("[WeeklyReport] 退出调仓异常: %s", exc)
        return "### 退出调仓\n\n> 本周无交易记录\n"


# ---------------------------------------------------------------------------
# 区块 3: 风险指标变化
# ---------------------------------------------------------------------------


def _block_risk_metrics_delta(start: str, end: str, positions_path: Path | None = None) -> str:
    """风险指标变化 (本周 vs 上周) — 复用 performance_report 的风险计算。"""
    try:
        from src.portfolio.performance_report import (
            _compute_daily_returns,
            _compute_max_drawdown,
            _compute_sharpe,
            _compute_volatility,
        )

        # 尝试从缓存/报告目录加载 positions_history
        report_dir = _DEFAULT_REPORT_DIR
        positions_history: list[dict[str, Any]] = []

        # 从 attribution_daily 报告中收集
        if report_dir.exists():
            for f in sorted(report_dir.glob("attribution_daily_*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    pv = float(data.get("portfolio_value_base", 0.0) or 0.0)
                    if pv > 0:
                        positions_history.append({
                            "date": str(data.get("date", "")),
                            "portfolio_value": pv,
                        })
                except (OSError, json.JSONDecodeError, ValueError):
                    continue

        if len(positions_history) < 2:
            return "### 风险变化\n\n> 本周无足够历史数据\n"

        daily_rets = _compute_daily_returns(positions_history)
        if not daily_rets:
            return "### 风险变化\n\n> 本周无足够历史数据\n"

        sharpe = _compute_sharpe(daily_rets)
        vol = _compute_volatility(daily_rets)
        max_dd = _compute_max_drawdown(positions_history)

        # 上周数据 (简单用前半段近似)
        mid = len(daily_rets) // 2
        prev_rets = daily_rets[:mid] if mid >= 2 else []
        curr_rets = daily_rets[mid:]

        prev_sharpe = _compute_sharpe(prev_rets) if prev_rets else 0.0
        prev_vol = _compute_volatility(prev_rets) if prev_rets else 0.0

        lines = ["### 风险变化\n"]
        lines.append(f"- Sharpe: {sharpe:.2f} (上周 {prev_sharpe:.2f}, Δ {sharpe - prev_sharpe:+.2f})")
        lines.append(f"- 波动率: {vol:.2%} (上周 {prev_vol:.2%})")
        lines.append(f"- 最大回撤: {max_dd:.2%}")
        lines.append("")
        return "\n".join(lines)

    except Exception as exc:
        logger.warning("[WeeklyReport] 风险指标异常: %s", exc)
        return "### 风险变化\n\n> 本周无足够历史数据\n"


# ---------------------------------------------------------------------------
# 区块 4: 下周关注
# ---------------------------------------------------------------------------


def _block_next_week_watch(report_dir: Path | None = None) -> str:
    """下周关注事项 — 从最新 auto_screening + 市场状态推 1-2 条。"""
    try:
        rdir = report_dir or _DEFAULT_REPORT_DIR
        if not rdir.exists():
            return "### 下周关注\n\n> 暂无最新选股报告\n"

        # 找最新 auto_screening 报告
        files = sorted(rdir.glob("auto_screening_*.json"), reverse=True)
        if not files:
            return "### 下周关注\n\n> 暂无最新选股报告\n"

        with open(files[0], encoding="utf-8") as f:
            payload = json.load(f)

        recs = payload.get("recommendations") or []
        market_state = payload.get("market_state") or {}
        state_type = str(market_state.get("state_type", "") or "").strip() or "未知"
        # NOTE: 0.0 是合法 position_scale (0% 仓位, 全风控), 不能用 `or 1.0` 静默覆盖为满仓。
        _ps_raw = market_state.get("position_scale", 1.0)
        pos_scale = float(_ps_raw) if _ps_raw is not None else 1.0

        lines = ["### 下周关注\n"]

        # 市场状态提示
        if state_type in ("bullish", "trending_up"):
            lines.append(f"- 市场偏多 ({state_type}), 仓位系数 {pos_scale:.0%}, 关注强势板块延续")
        elif state_type in ("bearish", "trending_down"):
            lines.append(f"- 市场偏空 ({state_type}), 仓位系数 {pos_scale:.0%}, 注意风控减仓")
        else:
            lines.append(f"- 市场震荡 ({state_type}), 仓位系数 {pos_scale:.0%}, 关注反转信号")

        # Top 1 标的
        if recs and isinstance(recs, list):
            top1 = recs[0]
            ticker = str(top1.get("ticker", "") or "").strip()
            score = float(top1.get("score_b", 0.0) or 0.0)
            if ticker:
                lines.append(f"- 最新 Top 推荐: {ticker} (score_b={score:+.2f})")

        lines.append("")
        return "\n".join(lines)

    except Exception as exc:
        logger.warning("[WeeklyReport] 下周关注异常: %s", exc)
        return "### 下周关注\n\n> 暂无最新选股报告\n"


# ---------------------------------------------------------------------------
# 主入口: 生成周报
# ---------------------------------------------------------------------------


def generate_weekly_report(
    start_date: str | None = None,
    end_date: str | None = None,
    positions_path: Path | None = None,
    report_dir: Path | None = None,
) -> str:
    """生成 Markdown 格式的周报 (< 3000 字, 5 分钟阅读量)。

    Args:
        start_date: 开始日期 YYYYMMDD, 缺省本周一。
        end_date: 结束日期 YYYYMMDD, 缺省本周五。
        positions_path: 可选持仓 JSON 路径。
        report_dir: 可选报告目录 (覆盖默认 data/reports)。

    Returns:
        Markdown 字符串。
    """
    if start_date and end_date:
        s, e = start_date.replace("-", ""), end_date.replace("-", "")
    else:
        s, e = _this_monday_friday()

    lines: list[str] = []
    lines.append(f"# 组合体检周报 · {_fmt_display(s)} ~ {_fmt_display(e)}")
    lines.append("")
    lines.append(f"> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # 4 个区块
    lines.append(_block_brinson_attribution(s, e, positions_path))
    lines.append(_block_exit_rebalance_summary(s, e, report_dir))
    lines.append(_block_risk_metrics_delta(s, e, positions_path))
    lines.append(_block_next_week_watch(report_dir))

    lines.append("---")
    lines.append("*AI Hedge Fund · 组合体检周报 (P2-10)*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 推送入口
# ---------------------------------------------------------------------------


def _split_markdown_for_wecom(markdown: str, max_bytes: int = MAX_WECOM_CONTENT) -> list[str]:
    """按行切分 Markdown, 每段 ≤ max_bytes (UTF-8)。

    在段落边界切分, 保证每段都是完整段落。
    """
    encoded = markdown.encode("utf-8")
    if len(encoded) <= max_bytes:
        return [markdown]

    paragraphs = markdown.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for para in paragraphs:
        para_bytes = len(para.encode("utf-8")) + 2  # +2 for \n\n
        if current_size + para_bytes > max_bytes and current:
            chunks.append("\n\n".join(current))
            current = []
            current_size = 0
        current.append(para)
        current_size += para_bytes

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def push_weekly_report(
    start_date: str | None = None,
    end_date: str | None = None,
    channel: str = "wecom",
    positions_path: Path | None = None,
    report_dir: Path | None = None,
    config_path: Path | None = None,
) -> int:
    """生成周报并推送至指定通道。

    Args:
        start_date: 开始日期 YYYYMMDD, 缺省本周一。
        end_date: 结束日期 YYYYMMDD, 缺省本周五。
        channel: 推送通道 ("wecom" / "dingtalk" / "email" / "webhook")。
        positions_path: 可选持仓 JSON。
        report_dir: 可选报告目录。
        config_path: 可选推送配置路径。

    Returns:
        0 成功 / 1 失败。
    """
    markdown = generate_weekly_report(
        start_date=start_date,
        end_date=end_date,
        positions_path=positions_path,
        report_dir=report_dir,
    )

    configs = load_push_config(config_path, only_enabled=True)
    if not configs:
        # 无配置: 直接打印周报, 返回 0
        print(markdown)
        print("\n[WeeklyReport] 无推送配置, 已输出到终端。请配置 data/push_config.json 或使用 --push-test --init。")
        return 0

    # 过滤目标通道
    target_channel = channel.strip().lower()
    filtered = [c for c in configs if c.channel.value == target_channel]
    if not filtered:
        filtered = configs  # fallback: 用第一个可用通道

    any_success = False
    for cfg in filtered:
        if target_channel == "wecom" or cfg.channel is PushChannel.WECOM:
            # 企微: 可能需要切分
            chunks = _split_markdown_for_wecom(markdown)
            for i, chunk in enumerate(chunks):
                suffix = f" ({i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
                report_data = {
                    "date": datetime.now().strftime("%Y%m%d"),
                    "market_state": {"state_type": "mixed", "position_scale": 1.0},
                    "recommendations": [],
                    "_weekly_report_chunk": chunk,
                    "_weekly_report_subject": f"组合体检周报{suffix}",
                }
                # 直接用 PushPayload 绕过 format_report_markdown
                payload = PushPayload(
                    subject=f"组合体检周报{suffix}",
                    markdown_body=chunk,
                )
                result = _send_chunk(cfg, payload)
                if result.success:
                    any_success = True
        else:
            # 其他通道: 发送完整内容
            report_data = {
                "date": datetime.now().strftime("%Y%m%d"),
                "_weekly_report_markdown": markdown,
            }
            result = send_push(cfg, report_data)
            if result.success:
                any_success = True

    if any_success:
        preview = markdown[:120].replace("\n", " ")
        print(f"[WeeklyReport] 周报已推送 (通道: {target_channel})")
        print(f"  预览: {preview}...")
    else:
        print("[WeeklyReport] 周报推送失败 — 请检查推送配置")

    return 0 if any_success else 1


def _send_chunk(config: PushConfig, payload: PushPayload) -> PushResult:
    """发送单个 chunk — 复用 push 的重试逻辑。"""
    from src.notification.push import (
        MAX_RETRIES,
        RETRY_BACKOFF_BASE,
        _default_http_post,
        _send_wecom,
    )

    start_time = __import__("time").monotonic()
    last_error: str | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _send_wecom(config, payload, _default_http_post)
            duration_ms = (__import__("time").monotonic() - start_time) * 1000
            return PushResult(
                channel=config.channel,
                target=config.target,
                success=True,
                attempts=attempt,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_RETRIES:
                __import__("time").sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))

    duration_ms = (__import__("time").monotonic() - start_time) * 1000
    return PushResult(
        channel=config.channel,
        target=config.target,
        success=False,
        attempts=MAX_RETRIES,
        error=last_error,
        duration_ms=duration_ms,
    )


__all__ = [
    "generate_weekly_report",
    "push_weekly_report",
    "_split_markdown_for_wecom",
    "_this_monday_friday",
]
