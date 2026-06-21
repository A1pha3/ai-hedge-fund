"""P1-13 条件单模板券商格式导出 — 单元测试。

覆盖:
  1. 华泰 CSV 格式 (字段名 + 数据行)
  2. 国泰君安 CSV 格式 (字段名 + 委托类别 0/1)
  3. 同花顺 JSON 格式 (JSON 数组, 字段名)
  4. 不支持的券商 → ValueError
  5. 空 advice 列表 → header/空数组
  6. 文件写入磁盘验证
  7. 三个 broker 字段值一致性 (同 advice → 相同价格)
  8. advice_to_broker_order 字段映射
  9. export_from_dicts round-trip
  10. CSV 中文 BOM 处理
"""

from __future__ import annotations

import csv
import io
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from src.screening.conditional_order_advisor import (
    compute_conditional_advice,
    ConditionalOrderAdvice,
)
from src.screening.conditional_order_export import (
    advice_to_broker_order,
    BrokerConditionalOrder,
    DEFAULT_QUANTITY,
    DEFAULT_VALID_DAYS,
    export_conditional_orders,
    export_from_dicts,
    gtja_adapter,
    huatai_adapter,
    run_export_conditional_orders_cli,
    ths_adapter,
)

# ===========================================================================
# Fixtures
# ===========================================================================


def _oscillating_prices(n: int = 30, base: float = 100.0, swing: float = 1.0) -> list[float]:
    out: list[float] = []
    for i in range(n):
        if i % 2 == 0:
            out.append(base + swing)
        else:
            out.append(base - swing)
    return out


def _make_advice(
    ticker: str = "000001",
    name: str = "平安银行",
    current_price: float = 100.0,
    base: float = 100.0,
) -> ConditionalOrderAdvice:
    series = _oscillating_prices(n=30, base=base, swing=1.0)
    return compute_conditional_advice(
        ticker=ticker,
        name=name,
        current_price=current_price,
        price_history=series,
    )


@pytest.fixture
def sample_advices() -> list[ConditionalOrderAdvice]:
    """3 条 ConditionalOrderAdvice fixture。"""
    return [
        _make_advice("000001", "平安银行", 100.0, 100.0),
        _make_advice("600519", "贵州茅台", 1800.0, 1800.0),
        _make_advice("300750", "宁德时代", 250.0, 250.0),
    ]


@pytest.fixture
def fixed_today() -> date:
    """固定日期 fixture, 确保测试可重复。"""
    return date(2026, 6, 9)


# ===========================================================================
# 1. 华泰 CSV 格式
# ===========================================================================


def test_huatai_csv_format(sample_advices: list[ConditionalOrderAdvice], fixed_today: date) -> None:
    """3 个 advice → CSV 含正确字段名 ('股票代码' 等) + 3 行数据。"""
    orders = [advice_to_broker_order(a, today=fixed_today) for a in sample_advices]
    csv_text = huatai_adapter(orders)

    # 可解析为 CSV
    reader = csv.reader(io.StringIO(csv_text.lstrip("﻿")))
    rows = list(reader)

    # 表头
    assert rows[0] == ["股票代码", "买卖方向", "触发价", "委托价", "有效期", "委托数量", "触发条件"]
    # 3 行数据
    assert len(rows) == 4  # 1 header + 3 data
    # 第一行数据
    assert rows[1][0] == "000001"
    assert rows[1][1] == "买入"
    assert rows[1][5] == "100"
    assert rows[1][6] == "<="


def test_huatai_csv_contains_all_tickers(sample_advices: list[ConditionalOrderAdvice], fixed_today: date) -> None:
    """华泰 CSV 包含所有 ticker。"""
    orders = [advice_to_broker_order(a, today=fixed_today) for a in sample_advices]
    csv_text = huatai_adapter(orders)
    for advice in sample_advices:
        assert advice.ticker in csv_text


# ===========================================================================
# 2. 国泰君安 CSV 格式
# ===========================================================================


def test_gtja_csv_format(sample_advices: list[ConditionalOrderAdvice], fixed_today: date) -> None:
    """字段名 ('证券代码' 等), 委托类别 0/1 正确。"""
    orders = [advice_to_broker_order(a, today=fixed_today) for a in sample_advices]
    csv_text = gtja_adapter(orders)

    reader = csv.reader(io.StringIO(csv_text.lstrip("﻿")))
    rows = list(reader)

    # 表头
    assert rows[0] == ["证券代码", "委托类别", "触发价格", "报价", "委托数量", "有效日期"]
    assert len(rows) == 4

    # 委托类别: 买入 → 0
    for i in range(1, 4):
        assert rows[i][1] == "0"  # 全部买入

    # 证券代码正确
    assert rows[1][0] == "000001"
    assert rows[2][0] == "600519"
    assert rows[3][0] == "300750"


def test_gtja_sell_side_code_1(fixed_today: date) -> None:
    """卖出方向 → 委托类别 1。"""
    sell_order = BrokerConditionalOrder(
        ticker="000001", name="测试", side="卖出",
        entry_price=100.0, stop_loss_price=96.0, take_profit_price=106.0,
        trigger_price=100.0, valid_until="20260612", quantity=100,
        trigger_condition=">=",
    )
    csv_text = gtja_adapter([sell_order])
    reader = csv.reader(io.StringIO(csv_text.lstrip("﻿")))
    rows = list(reader)
    assert rows[1][1] == "1"


# ===========================================================================
# 3. 同花顺 JSON 格式
# ===========================================================================


def test_ths_json_format(sample_advices: list[ConditionalOrderAdvice], fixed_today: date) -> None:
    """JSON 数组, 每元素有 code/direction/price/triggerPrice/condition/validDays。"""
    orders = [advice_to_broker_order(a, today=fixed_today) for a in sample_advices]
    json_text = ths_adapter(orders)

    parsed = json.loads(json_text)
    assert isinstance(parsed, list)
    assert len(parsed) == 3

    required_keys = {"code", "direction", "price", "triggerPrice", "condition", "validDays"}
    for item in parsed:
        assert required_keys.issubset(set(item.keys())), f"Missing keys: {required_keys - set(item.keys())}"

    # 验证值
    assert parsed[0]["code"] == "000001"
    assert parsed[0]["direction"] == "买入"
    assert isinstance(parsed[0]["price"], float)
    assert parsed[0]["condition"] == "<="
    assert parsed[0]["validDays"] == DEFAULT_VALID_DAYS


# ===========================================================================
# 4. 不支持的券商 → ValueError
# ===========================================================================


def test_broker_unknown_raises() -> None:
    """broker='unknown' → ValueError。"""
    advice = _make_advice()
    with pytest.raises(ValueError, match="不支持的券商"):
        export_conditional_orders([advice], "unknown")


# ===========================================================================
# 5. 空 advice 列表
# ===========================================================================


def test_empty_advice_returns_empty() -> None:
    """0 advice → CSV 只有 header; JSON 空数组。"""
    # 华泰 CSV — 只有 header
    csv_text = huatai_adapter([])
    assert "股票代码" in csv_text
    reader = csv.reader(io.StringIO(csv_text.lstrip("﻿")))
    rows = list(reader)
    assert len(rows) == 1  # header only

    # 国泰君安 CSV — 只有 header
    csv_text2 = gtja_adapter([])
    assert "证券代码" in csv_text2

    # 同花顺 JSON — 空数组
    json_text = ths_adapter([])
    assert json.loads(json_text) == []


# ===========================================================================
# 6. 文件写入磁盘验证
# ===========================================================================


def test_export_writes_file(tmp_path: Path, sample_advices: list[ConditionalOrderAdvice], fixed_today: date) -> None:
    """export_conditional_orders 输出写入磁盘后可正确读回。"""
    csv_content = export_conditional_orders(
        sample_advices, "huatai", today=fixed_today
    )
    out_file = tmp_path / "test_huatai.csv"
    out_file.write_text(csv_content, encoding="utf-8-sig")

    # 读回验证
    raw = out_file.read_text(encoding="utf-8-sig")
    assert "000001" in raw
    assert "股票代码" in raw

    # 同花顺 JSON
    json_content = export_conditional_orders(
        sample_advices, "ths", today=fixed_today
    )
    out_json = tmp_path / "test_ths.json"
    out_json.write_text(json_content, encoding="utf-8")
    parsed = json.loads(out_json.read_text(encoding="utf-8"))
    assert len(parsed) == 3


# ===========================================================================
# 7. 三个 broker 字段值一致性
# ===========================================================================


def test_field_mapping_consistency(fixed_today: date) -> None:
    """同一 advice 三个 broker 都包含 entry/stop_loss/take_profit 三个价格 (字段名不同但值相同)。"""
    advice = _make_advice("000001", "平安银行", 100.0, 100.0)
    order = advice_to_broker_order(advice, today=fixed_today)

    # 华泰 CSV
    csv_huatai = huatai_adapter([order])
    reader_h = csv.reader(io.StringIO(csv_huatai.lstrip("﻿")))
    rows_h = list(reader_h)
    huatai_entry = float(rows_h[1][3])  # 委托价

    # 国泰君安 CSV
    csv_gtja = gtja_adapter([order])
    reader_g = csv.reader(io.StringIO(csv_gtja.lstrip("﻿")))
    rows_g = list(reader_g)
    gtja_entry = float(rows_g[1][3])  # 报价

    # 同花顺 JSON
    json_ths = ths_adapter([order])
    ths_data = json.loads(json_ths)
    ths_entry = ths_data[0]["price"]

    # 三个 broker 的 entry_price 应相同
    assert math.isclose(huatai_entry, gtja_entry, abs_tol=1e-9)
    assert math.isclose(huatai_entry, ths_entry, abs_tol=1e-9)

    # 验证 entry_price = buy_zone 中值
    low, high = advice.suggested_buy_zone
    expected_entry = (low + high) / 2.0
    assert math.isclose(huatai_entry, expected_entry, abs_tol=1e-9)

    # 华泰触发价 == 同花顺 triggerPrice == current_price
    huatai_trigger = float(rows_h[1][2])
    ths_trigger = ths_data[0]["triggerPrice"]
    assert math.isclose(huatai_trigger, ths_trigger, abs_tol=1e-9)
    assert math.isclose(huatai_trigger, advice.current_price, abs_tol=1e-9)


# ===========================================================================
# 8. advice_to_broker_order 字段映射
# ===========================================================================


def test_advice_to_broker_order_mapping(fixed_today: date) -> None:
    """advice_to_broker_order 正确映射所有字段。"""
    advice = _make_advice("600519", "贵州茅台", 1800.0, 1800.0)
    order = advice_to_broker_order(advice, today=fixed_today, valid_days=3, quantity=200)

    assert order.ticker == "600519"
    assert order.name == "贵州茅台"
    assert order.side == "买入"
    assert order.quantity == 200
    assert order.trigger_condition == "<="

    # entry_price = buy_zone 中值
    low, high = advice.suggested_buy_zone
    expected_entry = round((low + high) / 2.0, 2)
    assert math.isclose(order.entry_price, expected_entry, abs_tol=1e-9)

    # stop_loss / take_profit
    assert math.isclose(order.stop_loss_price, advice.suggested_stop_loss, abs_tol=1e-9)
    assert math.isclose(order.take_profit_price, advice.suggested_take_profit, abs_tol=1e-9)

    # valid_until = today + 3
    assert order.valid_until == "20260612"

    # trigger_price = current_price
    assert math.isclose(order.trigger_price, 1800.0, abs_tol=1e-9)


# ===========================================================================
# 9. export_from_dicts round-trip
# ===========================================================================


def test_export_from_dicts_roundtrip(fixed_today: date) -> None:
    """ConditionalOrderAdvice → to_dict() → export_from_dicts() → 一致输出。"""
    advice = _make_advice("000001", "平安银行", 100.0, 100.0)
    d = advice.to_dict()

    # 直接 export
    direct = export_conditional_orders([advice], "huatai", today=fixed_today)
    # 从 dict export
    from_dict = export_from_dicts([d], "huatai", today=fixed_today)

    # 两者应包含相同的 ticker 和价格
    assert "000001" in from_dict
    assert "买入" in from_dict
    # 数据行数相同 (header + 1)
    reader_direct = list(csv.reader(io.StringIO(direct.lstrip("﻿"))))
    reader_from_dict = list(csv.reader(io.StringIO(from_dict.lstrip("﻿"))))
    assert len(reader_direct) == len(reader_from_dict)
    assert reader_direct[1][0] == reader_from_dict[1][0]  # ticker
    assert reader_direct[1][3] == reader_from_dict[1][3]  # entry_price


# ===========================================================================
# 10. CSV 中文 BOM 处理
# ===========================================================================


def test_csv_bom_for_excel(sample_advices: list[ConditionalOrderAdvice], fixed_today: date) -> None:
    """CSV 输出含 UTF-8 BOM, Excel 可正确打开中文。"""
    orders = [advice_to_broker_order(a, today=fixed_today) for a in sample_advices]

    # 华泰
    csv_h = huatai_adapter(orders)
    assert csv_h.startswith("﻿") or csv_h.startswith("﻿")  # BOM

    # 国泰君安
    csv_g = gtja_adapter(orders)
    assert csv_g.startswith("﻿") or csv_g.startswith("﻿")  # BOM


# ===========================================================================
# 11. CLI smoke test
# ===========================================================================


def test_cli_smoke_no_crash() -> None:
    """CLI smoke: 即使无数据也不应崩溃。"""
    rc = run_export_conditional_orders_cli(broker="huatai")
    assert rc in (0, 1, 2)


def test_cli_smoke_invalid_broker() -> None:
    """CLI smoke: 无效 broker 不崩溃, 返回 2。"""
    rc = run_export_conditional_orders_cli(broker="invalid_broker")
    assert rc == 2


# ===========================================================================
# 12. R151 — 降级 (数据不足) advice 不导出为券商条件单
# ===========================================================================


def _make_degraded_advice(ticker: str = "300999", name: str = "新股") -> ConditionalOrderAdvice:
    """构造一个降级 advice: 价格历史不足 MIN_PRICE_SESSIONS(5) → degraded=True。

    current_price > 0, 但 ATR 用占位值 (current×0.005), 生成极紧的无意义止损。
    """
    advice = compute_conditional_advice(
        ticker=ticker, name=name, current_price=50.0, price_history=[50.0, 49.5, 50.2],
    )
    assert advice.degraded is True  # n_sessions=3 < MIN_PRICE_SESSIONS=5
    return advice


def test_degraded_advice_excluded_from_export(fixed_today: date) -> None:
    """R151: 降级 advice 不应进入券商导出 — advisor 自标 '建议仅作参考, 请补充数据'。

    新上市 (<5 日) 标的降级 advice 用占位 ATR 生成 current×0.005×2 ≈ 1% 极紧止损,
    正常波动下近必然触发; 将其作为真实券商条件单导出与 advisor 自身降级标记矛盾。
    """
    valid = _make_advice("000001", "平安银行", 100.0, 100.0)
    degraded = _make_degraded_advice("300999", "新股")

    csv_text = export_conditional_orders([valid, degraded], "huatai", today=fixed_today)

    # 有效标的在, 降级标的被过滤
    assert "000001" in csv_text
    assert "300999" not in csv_text
    reader = csv.reader(io.StringIO(csv_text.lstrip("﻿")))
    rows = list(reader)
    assert len(rows) == 2  # header + 1 valid data row


def test_degraded_dict_excluded_from_export_from_dicts(fixed_today: date) -> None:
    """R151: export_from_dicts (从报告读回的路径) 同样过滤降级 dict。"""
    valid = _make_advice("000001", "平安银行", 100.0, 100.0)
    degraded = _make_degraded_advice("300999", "新股")

    dicts = [valid.to_dict(), degraded.to_dict()]
    assert dicts[1]["degraded"] is True

    csv_text = export_from_dicts(dicts, "huatai", today=fixed_today)

    assert "000001" in csv_text
    assert "300999" not in csv_text


def test_all_degraded_exports_header_only(fixed_today: date) -> None:
    """R151: 全部降级 → 仅 header (绝不导出垃圾/占位条件单), JSON → 空数组。"""
    degraded = _make_degraded_advice("300999", "新股")

    csv_text = export_conditional_orders([degraded], "huatai", today=fixed_today)
    reader = csv.reader(io.StringIO(csv_text.lstrip("﻿")))
    rows = list(reader)
    assert len(rows) == 1  # header only

    json_text = export_conditional_orders([degraded], "ths", today=fixed_today)
    assert json.loads(json_text) == []
