"""
数据快照功能手动测试脚本

测试项:
1. SnapshotConfig 环境变量读取
2. export_prices — 价格数据导出 + JSON/Markdown 生成
3. export_financial_metrics — 财务指标导出
4. export_line_items — 财务报表导出
5. 增量更新（幂等性）— 相同数据不重复写入
6. 索引管理 — index.json 追加/更新
7. summary.md 渲染正确性
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

# 必须在 import snapshot 之前设置环境变量
_tmp_dir = tempfile.mkdtemp(prefix="snapshot_test_")
os.environ["DATA_SNAPSHOT_ENABLED"] = "true"
os.environ["DATA_SNAPSHOT_PATH"] = _tmp_dir

# 重置单例以便测试使用新配置
from src.data.snapshot import DataSnapshotExporter

DataSnapshotExporter._instance = None  # type: ignore[attr-defined]

from src.data.models import FinancialMetrics, LineItem, Price
from src.data.snapshot import get_snapshot_exporter


def make_prices(n: int = 5) -> list[Price]:
    """生成测试价格数据"""
    return [
        Price(
            open=100.0 + i,
            close=101.0 + i,
            high=102.0 + i,
            low=99.0 + i,
            volume=1000000 + i * 100000,
            time=f"2025-01-{10 + i:02d}",
        )
        for i in range(n)
    ]


def make_metrics(n: int = 3) -> list[FinancialMetrics]:
    """生成测试财务指标"""
    return [
        FinancialMetrics(
            ticker="TEST",
            report_period=f"2024-{12 - i * 3:02d}-31",
            period="ttm",
            currency="USD",
            market_cap=1e10 + i * 1e9,
            enterprise_value=1.2e10 + i * 1e9,
            price_to_earnings_ratio=25.0 + i,
            price_to_book_ratio=3.5 + i * 0.1,
            price_to_sales_ratio=5.0,
            enterprise_value_to_ebitda_ratio=15.0,
            enterprise_value_to_revenue_ratio=6.0,
            free_cash_flow_yield=0.04,
            peg_ratio=1.2,
            gross_margin=0.45,
            operating_margin=0.25,
            net_margin=0.18,
            return_on_equity=0.22,
            return_on_assets=0.10,
            return_on_invested_capital=0.15,
            asset_turnover=0.8,
            inventory_turnover=6.0,
            receivables_turnover=8.0,
            days_sales_outstanding=45.0,
            operating_cycle=90.0,
            working_capital_turnover=4.0,
            current_ratio=2.0,
            quick_ratio=1.5,
            cash_ratio=0.8,
            operating_cash_flow_ratio=0.3,
            debt_to_equity=0.5,
            debt_to_assets=0.3,
            interest_coverage=10.0,
            revenue_growth=0.15 + i * 0.01,
            earnings_growth=0.20,
            book_value_growth=0.10,
            earnings_per_share_growth=0.18,
            free_cash_flow_growth=0.12,
            operating_income_growth=0.16,
            ebitda_growth=0.14,
            payout_ratio=0.30,
            earnings_per_share=4.5 + i * 0.2,
            book_value_per_share=30.0,
            free_cash_flow_per_share=3.0,
        )
        for i in range(n)
    ]


def make_line_items(n: int = 3) -> list[LineItem]:
    """生成测试财务报表"""
    return [
        LineItem(
            ticker="TEST",
            report_period=f"2024-{12 - i * 3:02d}-31",
            period="ttm",
            currency="USD",
            revenue=5e9 + i * 1e8,
            net_income=9e8 + i * 1e7,
            gross_profit=2.2e9,
            total_assets=2e10,
            total_liabilities=1e10,
            shareholders_equity=1e10,
            outstanding_shares=5e8,
            free_cash_flow=1.5e9,
            capital_expenditure=5e8,
            depreciation_and_amortization=3e8,
        )
        for i in range(n)
    ]


def test_config():
    """测试 1: SnapshotConfig 正确读取环境变量"""
    exporter = get_snapshot_exporter()
    assert exporter.config.enabled is True, "❌ enabled 应为 True"
    assert str(exporter.config.base_path) == _tmp_dir, f"❌ base_path 应为 {_tmp_dir}"
    assert exporter.config.mode == "sync", "❌ mode 默认应为 sync"
    print("✅ 测试 1: SnapshotConfig 环境变量读取正确")


def test_export_prices():
    """测试 2: 价格数据导出"""
    exporter = get_snapshot_exporter()
    prices = make_prices(5)
    exporter.export_prices("TEST", "2025-01-15", prices, "test_source")

    snapshot_dir = Path(_tmp_dir) / "TEST" / "2025-01-15"
    prices_file = snapshot_dir / "prices.json"
    summary_file = snapshot_dir / "summary.md"

    assert snapshot_dir.exists(), "❌ 快照目录未创建"
    assert prices_file.exists(), "❌ prices.json 未生成"
    assert summary_file.exists(), "❌ summary.md 未生成"

    data = json.loads(prices_file.read_text(encoding="utf-8"))
    assert len(data) == 5, f"❌ 价格数据条数不对: {len(data)} != 5"
    assert data[0]["open"] == 100.0, "❌ 第一条价格数据 open 不正确"

    md = summary_file.read_text(encoding="utf-8")
    assert "TEST 数据快照" in md, "❌ summary.md 标题缺失"
    assert "价格数据（OHLCV）" in md, "❌ summary.md 缺少价格区"
    assert "test_source" in md, "❌ summary.md 缺少数据源"

    print("✅ 测试 2: 价格数据导出正确 (JSON + Markdown)")


def test_export_financial_metrics():
    """测试 3: 财务指标导出"""
    exporter = get_snapshot_exporter()
    metrics = make_metrics(3)
    exporter.export_financial_metrics("TEST", "2025-01-15", metrics, "test_source")

    snapshot_dir = Path(_tmp_dir) / "TEST" / "2025-01-15"
    financials_file = snapshot_dir / "financials.json"

    assert financials_file.exists(), "❌ financials.json 未生成"

    data = json.loads(financials_file.read_text(encoding="utf-8"))
    assert len(data["financial_metrics"]) == 3, f"❌ 财务指标条数不对: {len(data['financial_metrics'])} != 3"
    assert data["financial_metrics"][0]["ticker"] == "TEST", "❌ ticker 不正确"

    md = (snapshot_dir / "summary.md").read_text(encoding="utf-8")
    assert "财务指标" in md, "❌ summary.md 缺少财务指标区"
    assert "PE" in md or "市值" in md, "❌ summary.md 缺少财务指标列标签"

    print("✅ 测试 3: 财务指标导出正确")


def test_export_line_items():
    """测试 4: 财务报表导出"""
    exporter = get_snapshot_exporter()
    items = make_line_items(3)
    exporter.export_line_items("TEST", "2025-01-15", items, "test_source")

    snapshot_dir = Path(_tmp_dir) / "TEST" / "2025-01-15"
    financials_file = snapshot_dir / "financials.json"

    data = json.loads(financials_file.read_text(encoding="utf-8"))
    assert len(data["line_items"]) == 3, f"❌ 报表数据条数不对: {len(data['line_items'])} != 3"
    assert data["line_items"][0]["revenue"] == 5e9, "❌ revenue 不正确"

    md = (snapshot_dir / "summary.md").read_text(encoding="utf-8")
    assert "财务报表数据" in md, "❌ summary.md 缺少财务报表区"

    print("✅ 测试 4: 财务报表导出正确")


def test_idempotency():
    """测试 5: 幂等性 — 相同数据不重复写入"""
    exporter = get_snapshot_exporter()
    prices = make_prices(5)

    # 第一次导出
    exporter.export_prices("IDEM", "2025-02-01", prices, "test")
    snapshot_dir = Path(_tmp_dir) / "IDEM" / "2025-02-01"
    mtime1 = (snapshot_dir / "prices.json").stat().st_mtime

    # 相同数据再次导出
    import time
    time.sleep(0.1)  # 确保 mtime 有差异
    exporter.export_prices("IDEM", "2025-02-01", prices, "test")
    mtime2 = (snapshot_dir / "prices.json").stat().st_mtime

    assert mtime1 == mtime2, "❌ 相同数据应跳过写入（幂等性失败）"
    print("✅ 测试 5: 幂等性验证通过（相同数据未重复写入）")


def test_index_management():
    """测试 6: index.json 索引管理"""
    index_path = Path(_tmp_dir) / "index.json"
    assert index_path.exists(), "❌ index.json 未生成"

    index = json.loads(index_path.read_text(encoding="utf-8"))
    tickers_in_index = [e["ticker"] for e in index]

    assert "TEST" in tickers_in_index, "❌ TEST 不在索引中"
    assert "IDEM" in tickers_in_index, "❌ IDEM 不在索引中"

    # 检查无重复条目（同 ticker+date 应只有一条）
    test_entries = [e for e in index if e["ticker"] == "TEST" and e["date"] == "2025-01-15"]
    assert len(test_entries) == 1, f"❌ TEST/2025-01-15 索引条目重复: {len(test_entries)}"

    print("✅ 测试 6: index.json 索引管理正确")


def test_disabled_mode():
    """测试 7: 禁用模式不导出任何数据"""
    exporter = get_snapshot_exporter()
    exporter.config.enabled = False

    exporter.export_prices("DISABLED", "2025-03-01", make_prices(3), "test")

    disabled_dir = Path(_tmp_dir) / "DISABLED"
    assert not disabled_dir.exists(), "❌ 禁用模式下不应创建目录"

    exporter.config.enabled = True  # 恢复
    print("✅ 测试 7: 禁用模式验证通过")


def test_empty_data():
    """测试 8: 空数据不导出"""
    exporter = get_snapshot_exporter()
    exporter.export_prices("EMPTY", "2025-03-01", [], "test")
    exporter.export_financial_metrics("EMPTY", "2025-03-01", [], "test")
    exporter.export_line_items("EMPTY", "2025-03-01", [], "test")

    empty_dir = Path(_tmp_dir) / "EMPTY"
    assert not empty_dir.exists(), "❌ 空数据不应创建目录"
    print("✅ 测试 8: 空数据处理正确（未创建任何文件）")


def test_large_volume_format():
    """测试 9: 大数值格式化（亿/万）"""
    exporter = get_snapshot_exporter()
    prices = [
        Price(open=100.0, close=101.0, high=102.0, low=99.0, volume=350_000_000, time="2025-01-20"),
        Price(open=100.0, close=101.0, high=102.0, low=99.0, volume=85_000, time="2025-01-21"),
    ]
    exporter.export_prices("FORMAT", "2025-01-21", prices, "test")

    md = (Path(_tmp_dir) / "FORMAT" / "2025-01-21" / "summary.md").read_text(encoding="utf-8")
    assert "亿" in md, "❌ 大成交量应格式化为亿"
    assert "万" in md, "❌ 中等成交量应格式化为万"
    print("✅ 测试 9: 大数值格式化正确（亿/万）")


def test_summary_price_truncation():
    """测试 10: 价格数据超过 30 条时截断展示"""
    exporter = get_snapshot_exporter()
    prices = make_prices(50)
    exporter.export_prices("TRUNC", "2025-03-01", prices, "test")

    md = (Path(_tmp_dir) / "TRUNC" / "2025-03-01" / "summary.md").read_text(encoding="utf-8")
    assert "仅展示最近 30 个交易日" in md, "❌ 超过30条应有截断提示"
    assert "完整数据共 50 条" in md, "❌ 应标注完整数据条数"
    print("✅ 测试 10: 价格数据截断展示正确")


def cleanup():
    """清理临时目录"""
    shutil.rmtree(_tmp_dir, ignore_errors=True)
    # 重置单例
    DataSnapshotExporter._instance = None  # type: ignore[attr-defined]
    print(f"\n🧹 临时目录已清理: {_tmp_dir}")


if __name__ == "__main__":
    print(f"📁 临时快照目录: {_tmp_dir}\n")

    tests = [
        test_config,
        test_export_prices,
        test_export_financial_metrics,
        test_export_line_items,
        test_idempotency,
        test_index_management,
        test_disabled_mode,
        test_empty_data,
        test_large_volume_format,
        test_summary_price_truncation,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__} 异常: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"结果: {passed} 通过, {failed} 失败 / 共 {len(tests)} 项")

    cleanup()
