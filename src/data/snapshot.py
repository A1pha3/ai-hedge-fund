"""
数据快照模块

将 API 获取的股票数据以 Markdown + JSON 双格式保存为可读文件。
设计文档：docs/zh-cn/data-snapshot-design.md

环境变量：
    DATA_SNAPSHOT_ENABLED: 是否启用快照（默认 false）
    DATA_SNAPSHOT_PATH: 快照存储路径（默认 data/snapshots）
    DATA_SNAPSHOT_MODE: 导出模式 sync/async（默认 sync）
"""

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.data.models import FinancialMetrics, LineItem, Price
from src.tools.tushare_api import get_stock_name

logger = logging.getLogger(__name__)


class SnapshotConfig:
    """快照系统配置，从环境变量读取"""

    def __init__(self) -> None:
        self.enabled: bool = os.environ.get("DATA_SNAPSHOT_ENABLED", "false").lower() == "true"
        self.base_path: Path = Path(os.environ.get("DATA_SNAPSHOT_PATH", "data/snapshots"))
        self.mode: str = os.environ.get("DATA_SNAPSHOT_MODE", "sync")


class DataSnapshotExporter:
    """
    数据快照导出器

    在 api.py 网关层调用，将获取的数据以 Markdown + JSON 双格式保存。
    单例模式 + 线程安全。导出失败不影响主流程（失败隔离）。

    使用方式：
        exporter = get_snapshot_exporter()
        exporter.export_prices(ticker, end_date, prices, "tushare")
    """

    _instance: Optional["DataSnapshotExporter"] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "DataSnapshotExporter":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self.config = SnapshotConfig()
        self._index_lock = threading.Lock()

    # =========================================================================
    # 公开 API
    # =========================================================================

    def export_prices(self, ticker: str, end_date: str, prices: list[Price], data_source: str = "unknown") -> None:
        """导出价格数据快照"""
        if not self.config.enabled or not prices:
            return
        try:
            snapshot_dir = self._ensure_dir(ticker, end_date)
            prices_file = snapshot_dir / "prices.json"

            # 检查快照文件是否存在，或者是否需要更新
            need_update = True
            if prices_file.exists():
                # 检查文件是否为空或数据是否需要更新
                existing_data = self._read_json(prices_file, [])
                if existing_data:
                    # 基于日期范围判断是否需要更新
                    existing_dates = sorted([p["time"] for p in existing_data if p.get("time")])
                    new_dates = sorted([p.time for p in prices if p.time])

                    if existing_dates and new_dates:
                        # 检查日期范围是否一致
                        if existing_dates[0] == new_dates[0] and existing_dates[-1] == new_dates[-1]:
                            need_update = False

            if need_update:
                self._write_json(prices_file, [p.model_dump() for p in prices])
                self._regenerate_summary(ticker, end_date, snapshot_dir, data_source)
                self._update_index(ticker, end_date, snapshot_dir, data_source)
                logger.info("[Snapshot] 价格快照已导出: %s/%s, %d 条", ticker, end_date, len(prices))
        except Exception as e:
            logger.warning("[Snapshot] 价格快照导出失败: %s/%s - %s", ticker, end_date, e)

    def export_financial_metrics(self, ticker: str, end_date: str, metrics: list[FinancialMetrics], data_source: str = "unknown") -> None:
        """导出财务指标快照"""
        if not self.config.enabled or not metrics:
            return
        try:
            snapshot_dir = self._ensure_dir(ticker, end_date)
            financials_file = snapshot_dir / "financials.json"

            # 检查快照文件是否存在，或者是否需要更新
            need_update = True
            if financials_file.exists():
                # 检查文件是否为空或数据是否需要更新
                existing_data = self._read_json(financials_file, {"financial_metrics": [], "line_items": []})
                existing_metrics = existing_data.get("financial_metrics", [])
                if existing_metrics:
                    # 基于报告期判断是否需要更新
                    existing_periods = sorted([m["report_period"] for m in existing_metrics if m.get("report_period")])
                    new_periods = sorted([m.report_period for m in metrics if m.report_period])

                    if existing_periods and new_periods:
                        # 检查报告期是否一致
                        if existing_periods == new_periods:
                            need_update = False

            if need_update:
                financials: dict[str, Any] = self._read_json(financials_file, {"financial_metrics": [], "line_items": []})  # type: ignore[assignment]
                financials["financial_metrics"] = [m.model_dump() for m in metrics]
                self._write_json(financials_file, financials)
                self._regenerate_summary(ticker, end_date, snapshot_dir, data_source)
                self._update_index(ticker, end_date, snapshot_dir, data_source)
                logger.info("[Snapshot] 财务指标快照已导出: %s/%s, %d 期", ticker, end_date, len(metrics))
        except Exception as e:
            logger.warning("[Snapshot] 财务指标快照导出失败: %s/%s - %s", ticker, end_date, e)

    def export_line_items(self, ticker: str, end_date: str, line_items: list[LineItem], data_source: str = "unknown") -> None:
        """导出财务报表数据快照"""
        if not self.config.enabled or not line_items:
            return
        try:
            snapshot_dir = self._ensure_dir(ticker, end_date)
            financials_file = snapshot_dir / "financials.json"

            # 检查快照文件是否存在，或者是否需要更新
            need_update = True
            if financials_file.exists():
                # 检查文件是否为空或数据是否需要更新
                existing_data = self._read_json(financials_file, {"financial_metrics": [], "line_items": []})
                existing_items = existing_data.get("line_items", [])
                if existing_items:
                    # 基于报告期判断是否需要更新
                    existing_periods = sorted([item["report_period"] for item in existing_items if item.get("report_period")])
                    new_periods = sorted([item.report_period for item in line_items if item.report_period])

                    if existing_periods and new_periods:
                        # 检查报告期是否一致
                        if existing_periods == new_periods:
                            need_update = False

            if need_update:
                financials: dict[str, Any] = self._read_json(financials_file, {"financial_metrics": [], "line_items": []})  # type: ignore[assignment]
                financials["line_items"] = [item.model_dump() for item in line_items]
                self._write_json(financials_file, financials)
                self._regenerate_summary(ticker, end_date, snapshot_dir, data_source)
                self._update_index(ticker, end_date, snapshot_dir, data_source)
                logger.info("[Snapshot] 财务报表快照已导出: %s/%s, %d 条", ticker, end_date, len(line_items))
        except Exception as e:
            logger.warning("[Snapshot] 财务报表快照导出失败: %s/%s - %s", ticker, end_date, e)

    # =========================================================================
    # 文件 I/O
    # =========================================================================

    def _ensure_dir(self, ticker: str, date: str) -> Path:
        """创建并返回快照目录"""
        d = self.config.base_path / ticker / date
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        """写入 JSON 文件（UTF-8）"""
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def _read_json(path: Path, default: Any = None) -> Any:
        """读取 JSON 文件，失败返回默认值"""
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return default if default is not None else {}

    # =========================================================================
    # Markdown 渲染
    # =========================================================================

    def _regenerate_summary(self, ticker: str, date: str, snapshot_dir: Path, data_source: str) -> None:
        """从 JSON 文件重新生成 summary.md"""
        prices: list[dict[str, Any]] = self._read_json(snapshot_dir / "prices.json", [])
        financials: dict[str, Any] = self._read_json(snapshot_dir / "financials.json", {"financial_metrics": [], "line_items": []})
        md = self._render_markdown(ticker, date, data_source, prices, financials.get("financial_metrics", []), financials.get("line_items", []))
        (snapshot_dir / "summary.md").write_text(md, encoding="utf-8")

    def _render_markdown(self, ticker: str, date: str, data_source: str, prices: list[dict[str, Any]], metrics: list[dict[str, Any]], line_items: list[dict[str, Any]]) -> str:
        """渲染完整的 summary.md 内容"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parts: list[str] = []

        stock_name = get_stock_name(ticker)

        parts.append(f"# {ticker}（{stock_name}）数据快照 - {date}\n")
        parts.append(f"- **股票代码**：{ticker}")
        parts.append(f"- **股票名称**：{stock_name}")
        parts.append(f"- **分析日期**：{date}")
        parts.append(f"- **数据源**：{data_source}")
        if prices:
            times = [p["time"] for p in prices if p.get("time")]
            if times:
                parts.append(f"- **价格数据范围**：{min(times)} ~ {max(times)}")
        if metrics:
            parts.append(f"- **币种**：{metrics[0].get('currency', 'N/A')}")
        parts.append(f"- **快照生成时间**：{now}\n")

        # 价格区
        if prices:
            parts.append("## 价格数据（OHLCV）\n")
            display = prices[-30:] if len(prices) > 30 else prices
            parts.append("| 日期 | 开盘价 | 最高价 | 最低价 | 收盘价 | 成交量 |")
            parts.append("|------|--------|--------|--------|--------|--------|")
            for p in display:
                parts.append(f"| {p.get('time', '-')} | {_fmt_price(p.get('open'))} | {_fmt_price(p.get('high'))} | {_fmt_price(p.get('low'))} | {_fmt_price(p.get('close'))} | {_fmt_volume(p.get('volume'))} |")
            if len(prices) > 30:
                parts.append(f"\n> 仅展示最近 30 个交易日，完整数据共 {len(prices)} 条，详见 prices.json")
            parts.append("")

        # 财务指标区
        if metrics:
            parts.append("## 财务指标\n")
            parts.extend(_render_metrics_table(metrics))
            parts.append("")

        # 财务报表数据区
        if line_items:
            parts.append("## 财务报表数据\n")
            parts.extend(_render_line_items_table(line_items))
            parts.append("")

        if not prices and not metrics and not line_items:
            parts.append("> 暂无数据\n")

        return "\n".join(parts)

    # =========================================================================
    # 索引管理
    # =========================================================================

    def _update_index(self, ticker: str, date: str, snapshot_dir: Path, data_source: str) -> None:
        """更新全局索引 index.json（线程安全，追加或更新已有条目）"""
        with self._index_lock:
            index_path = self.config.base_path / "index.json"
            index: list[dict[str, Any]] = self._read_json(index_path, [])

            entry = {
                "ticker": ticker,
                "date": date,
                "snapshot_path": str(snapshot_dir),
                "created_at": datetime.now().timestamp(),
                "data_source": data_source,
            }

            # 使用 for...else 模式：找到则更新，未找到则追加
            for i, e in enumerate(index):
                if e.get("ticker") == ticker and e.get("date") == date:
                    index[i] = entry
                    break
            else:
                index.append(entry)

            index_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_json(index_path, index)


# =============================================================================
# 模块级格式化函数
# =============================================================================


def _fmt_price(val: float | None) -> str:
    """格式化价格，保留两位小数"""
    return f"{val:.2f}" if val is not None else "-"


def _fmt_volume(val: int | None) -> str:
    """格式化成交量，大数值自动转为亿/万"""
    if val is None:
        return "-"
    if val >= 100_000_000:
        return f"{val / 100_000_000:.2f}亿"
    if val >= 10_000:
        return f"{val / 10_000:.1f}万"
    return str(val)


def _fmt_number(val: float | int | None) -> str:
    """格式化通用数值（用于财务指标）"""
    if val is None:
        return "-"
    if not isinstance(val, (int, float)):
        return str(val)
    if abs(val) >= 1e8:
        return f"{val / 1e8:.2f}亿"
    return f"{val:.2f}"


def _fmt_amount(val: float | int | None) -> str:
    """格式化金额（用于财务报表，大数值自动转为亿/万）"""
    if val is None:
        return "-"
    if not isinstance(val, (int, float)):
        return str(val)
    if abs(val) >= 1e8:
        return f"{val / 1e8:.2f}亿"
    if abs(val) >= 1e4:
        return f"{val / 1e4:.1f}万"
    return f"{val:.2f}"


def _render_metrics_table(metrics: list[dict[str, Any]]) -> list[str]:
    """渲染财务指标 Markdown 表格，动态跳过全空列"""
    skip = {"ticker", "report_period", "period", "currency"}
    fields = [f for f in metrics[0] if f not in skip and any(m.get(f) is not None for m in metrics)]
    if not fields:
        return ["*所有指标均为空值*"]
    header = "| 报告期 | " + " | ".join(_FIELD_LABELS.get(f, f) for f in fields) + " |"
    sep = "|" + "|".join("--------" for _ in ["报告期"] + fields) + "|"
    rows = [header, sep]
    for m in metrics:
        cells = " | ".join(_fmt_number(m.get(f)) for f in fields)
        rows.append(f"| {m.get('report_period', '-')} | {cells} |")
    return rows


def _render_line_items_table(line_items: list[dict[str, Any]]) -> list[str]:
    """渲染财务报表 Markdown 表格，保持字段出现顺序"""
    skip = {"ticker", "report_period", "period", "currency"}
    fields: list[str] = []
    seen: set[str] = set()
    for item in line_items:
        for f in item:
            if f not in skip and f not in seen and any(it.get(f) is not None for it in line_items):
                fields.append(f)
                seen.add(f)
    if not fields:
        return ["*所有项目均为空值*"]
    header = "| 报告期 | " + " | ".join(_FIELD_LABELS.get(f, f) for f in fields) + " |"
    sep = "|" + "|".join("--------" for _ in ["报告期"] + fields) + "|"
    rows = [header, sep]
    for item in line_items:
        cells = " | ".join(_fmt_amount(item.get(f)) for f in fields)
        rows.append(f"| {item.get('report_period', '-')} | {cells} |")
    return rows


# =============================================================================
# 字段中文标签映射
# =============================================================================

_FIELD_LABELS: dict[str, str] = {
    # FinancialMetrics 字段
    "market_cap": "市值",
    "enterprise_value": "企业价值",
    "price_to_earnings_ratio": "PE",
    "price_to_book_ratio": "PB",
    "price_to_sales_ratio": "PS",
    "enterprise_value_to_ebitda_ratio": "EV/EBITDA",
    "enterprise_value_to_revenue_ratio": "EV/Revenue",
    "free_cash_flow_yield": "自由现金流收益率",
    "peg_ratio": "PEG",
    "gross_margin": "毛利率",
    "operating_margin": "营业利润率",
    "net_margin": "净利率",
    "return_on_equity": "ROE",
    "return_on_assets": "ROA",
    "return_on_invested_capital": "ROIC",
    "asset_turnover": "总资产周转率",
    "inventory_turnover": "存货周转率",
    "receivables_turnover": "应收账款周转率",
    "days_sales_outstanding": "应收账款天数",
    "operating_cycle": "营业周期",
    "working_capital_turnover": "营运资本周转率",
    "current_ratio": "流动比率",
    "quick_ratio": "速动比率",
    "cash_ratio": "现金比率",
    "operating_cash_flow_ratio": "经营现金流比率",
    "debt_to_equity": "资产负债率(D/E)",
    "debt_to_assets": "负债/总资产",
    "interest_coverage": "利息覆盖倍数",
    "revenue_growth": "营收增长率",
    "earnings_growth": "利润增长率",
    "book_value_growth": "净资产增长率",
    "earnings_per_share_growth": "EPS增长率",
    "free_cash_flow_growth": "自由现金流增长率",
    "operating_income_growth": "营业利润增长率",
    "ebitda_growth": "EBITDA增长率",
    "payout_ratio": "派息率",
    "earnings_per_share": "EPS",
    "book_value_per_share": "每股净资产",
    "free_cash_flow_per_share": "每股自由现金流",
    # LineItem 字段
    "revenue": "营业收入",
    "net_income": "净利润",
    "gross_profit": "毛利润",
    "total_assets": "总资产",
    "total_liabilities": "总负债",
    "shareholders_equity": "股东权益",
    "outstanding_shares": "流通股数",
    "free_cash_flow": "自由现金流",
    "capital_expenditure": "资本支出",
    "depreciation_and_amortization": "折旧摊销",
    "dividends_and_other_cash_distributions": "股息分配",
    "issuance_or_purchase_of_equity_shares": "股权融资/回购",
}


def get_snapshot_exporter() -> DataSnapshotExporter:
    """获取快照导出器单例"""
    return DataSnapshotExporter()
