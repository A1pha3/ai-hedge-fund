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
    _next_business_day,
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
        ticker="000001",
        name="测试",
        side="卖出",
        entry_price=100.0,
        stop_loss_price=96.0,
        take_profit_price=106.0,
        trigger_price=100.0,
        valid_until="20260612",
        quantity=100,
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
    csv_content = export_conditional_orders(sample_advices, "huatai", today=fixed_today)
    out_file = tmp_path / "test_huatai.csv"
    out_file.write_text(csv_content, encoding="utf-8-sig")

    # 读回验证
    raw = out_file.read_text(encoding="utf-8-sig")
    assert "000001" in raw
    assert "股票代码" in raw

    # 同花顺 JSON
    json_content = export_conditional_orders(sample_advices, "ths", today=fixed_today)
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


def test_cli_prints_front_door_verdict_disclosure(monkeypatch, capsys) -> None:
    """autodev-13 / loop 105: --export-conditional-orders must print the
    front-door verdict disclosure so the operator sees which exported orders
    are AVOID-rated BEFORE placing them with the broker (real-money path).
    Sibling of loop 104 (--conditional-orders CLI display). The export writes
    a broker CSV/JSON that cannot carry an arbitrary verdict column (broker
    format constraints), so the disclosure is a CONSOLE warning at export
    time — additive, does not touch the broker file format."""
    from src.screening import conditional_order_export as coe

    # Force the helper to return a recognizable sentinel so we can assert the
    # export wiring invokes it and prints its output. This verifies the
    # integration (helper is called on the exported tickers) without depending
    # on the specific report contents.
    monkeypatch.setattr(
        coe,
        "_format_front_door_verdict_disclosure",
        lambda recs, *, market_regime: "SENTINEL_VERDICT_DISCLOSURE",
    )
    rc = run_export_conditional_orders_cli(broker="huatai")
    out = capsys.readouterr().out
    # rc==0 means a report existed and the export ran; rc==1 means no report
    # (no disclosure possible). When the export runs, the sentinel must appear.
    if rc == 0:
        assert "SENTINEL_VERDICT_DISCLOSURE" in out, (
            "--export-conditional-orders must print the front-door verdict "
            "disclosure so the operator sees AVOID-rated picks before placing "
            "real broker orders (C-CONDITIONAL-ORDER-VERDICT-GATE export sibling)."
        )


# ===========================================================================
# 12. R151 — 降级 (数据不足) advice 不导出为券商条件单
# ===========================================================================


def _make_degraded_advice(ticker: str = "300999", name: str = "新股") -> ConditionalOrderAdvice:
    """构造一个降级 advice: 价格历史不足 MIN_PRICE_SESSIONS(5) → degraded=True。

    current_price > 0, 但 ATR 用占位值 (current×0.005), 生成极紧的无意义止损。
    """
    advice = compute_conditional_advice(
        ticker=ticker,
        name=name,
        current_price=50.0,
        price_history=[50.0, 49.5, 50.2],
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


# ===========================================================================
# 13. NS-15(1) — _next_business_day 必须用 trade_cal, 不能用纯自然日
# ===========================================================================
#
# 缺陷 (feature-proposals.md §三·6 NS-15):
#   旧实现 `_next_business_day(start, n)` = `start + timedelta(days=n)`, 纯自然日。
#   周四 2026-06-11 + 3 = 周日 2026-06-14 (周末, broker 收到周末到期单被拒/静默失效)。
#
# 修复:
#   用 get_open_trade_dates 算真实 A 股交易日 (排除周末 + 节假日);
#   无 token / 网络失败 / 空结果时 fallback 到 weekday 近似 (跳过周六周日)。
# ===========================================================================


def test_next_business_day_uses_trade_cal_not_calendar_days(monkeypatch) -> None:
    """NS-15(1): trade_cal 可用时, _next_business_day 返回第 n 个交易日 (非自然日)。

    周四 2026-06-11 + 3 自然日 = 周日 2026-06-14 (周末, broker 拒单)。
    周四 2026-06-11 + 3 交易日 = 周二 2026-06-16 (Fri/Mon/Tue, 跳过周末)。
    """
    # 模拟 trade_cal 返回 2026-06-11 ~ 2026-06-17 的真实 A 股交易日
    # (跳过周六 06-13、周日 06-14; 该区间无节假日)
    real_open_dates = [
        "20260611",  # Thu
        "20260612",  # Fri
        "20260615",  # Mon
        "20260616",  # Tue
        "20260617",  # Wed
    ]

    def mock_get_open(start: str, end: str) -> list[str]:
        return [d for d in real_open_dates if start <= d <= end]

    monkeypatch.setattr(
        "src.tools.tushare_api.get_open_trade_dates",
        mock_get_open,
    )

    # 周四 + 3 交易日 = 周二 (不是周日!)
    result = _next_business_day(date(2026, 6, 11), n_days=3)
    assert result == "20260616", f"Expected 20260616 (Tue, 3rd trading day after Thu), got {result}"
    # 关键断言: 绝不能返回周末日期
    assert result != "20260614", "Must not return Sunday — broker rejects weekend-expiring orders"
    assert result != "20260613", "Must not return Saturday — broker rejects weekend-expiring orders"


def test_next_business_day_falls_back_to_weekday_when_no_trade_cal(monkeypatch) -> None:
    """NS-15(1) fallback: trade_cal 不可用时, 用 weekday 近似 (跳过周六周日)。

    无 token / 网络失败时 get_open_trade_dates 返回空列表, 此时 fallback
    到 weekday-only 近似: 周四+3 weekdays = 周二 (跳过 Sat/Sun)。
    旧实现错误地用纯自然日, 返回周日。
    """
    # 模拟 trade_cal 不可用 (无 token / 网络失败)
    monkeypatch.setattr(
        "src.tools.tushare_api.get_open_trade_dates",
        lambda start, end: [],
    )

    # 周四 + 3 weekdays = 周二 (Fri=1, Mon=2, Tue=3)
    result = _next_business_day(date(2026, 6, 11), n_days=3)
    assert result == "20260616", f"Weekday fallback: Expected 20260616 (Tue), got {result}"
    # 绝不能是周日
    assert result != "20260614", "Weekday fallback must skip weekend — got Sunday (broker rejects)"


def test_next_business_day_friday_plus_one_not_saturday(monkeypatch) -> None:
    """NS-15(1) 边界: 周五 + 1 交易日 = 周一 (不是周六)。

    覆盖 n_days=1 的边界: 旧实现周五+1=周六 (周末), 修复后应为周一。
    """
    monkeypatch.setattr(
        "src.tools.tushare_api.get_open_trade_dates",
        lambda start, end: [],
    )

    # 周五 2026-06-12 + 1 weekday = 周一 2026-06-15
    result = _next_business_day(date(2026, 6, 12), n_days=1)
    assert result == "20260615", f"Fri+1 weekday = Mon; got {result}"


def test_next_business_day_preserves_weekday_only_behavior_when_no_weekend(monkeypatch) -> None:
    """NS-15(1) 回归: 起点为周二, +3 交易日 = 周五 (无周末跨越, 行为不变)。

    确保修复不破坏既有的 weekday-only 路径 (现有测试 test_advice_to_broker_order_mapping
    依赖 Tuesday+3=Friday)。
    """
    monkeypatch.setattr(
        "src.tools.tushare_api.get_open_trade_dates",
        lambda start, end: [],
    )

    # 周二 2026-06-09 + 3 weekdays = 周五 2026-06-12 (Tue→Wed→Thu→Fri)
    result = _next_business_day(date(2026, 6, 9), n_days=3)
    assert result == "20260612", f"Tue+3 weekdays = Fri (no weekend cross); got {result}"


def test_advice_to_broker_order_valid_until_uses_trade_cal(monkeypatch, fixed_today: date) -> None:
    """NS-15(1) 集成: advice_to_broker_order 的 valid_until 字段用 trade_cal。

    用 fixed_today=2026-06-09 (Tuesday) + 3 交易日 = 2026-06-12 (Friday)。
    既验证 trade_cal 路径集成, 又确保与现有 test_advice_to_broker_order_mapping
    的断言 `valid_until == "20260612"` 一致 (不破坏既有契约)。
    """
    real_open_dates = [
        "20260609",
        "20260610",
        "20260611",
        "20260612",  # Tue-Fri
        "20260615",
        "20260616",  # Mon-Tue next week
    ]

    def mock_get_open(start: str, end: str) -> list[str]:
        return [d for d in real_open_dates if start <= d <= end]

    monkeypatch.setattr(
        "src.tools.tushare_api.get_open_trade_dates",
        mock_get_open,
    )

    advice = _make_advice("000001", "平安银行", 100.0, 100.0)
    order = advice_to_broker_order(advice, today=fixed_today, valid_days=3)
    # Tuesday + 3 trading days = Friday (Wed/Thu/Fri)
    assert order.valid_until == "20260612"


# ===========================================================================
# NS-15(2): --nav CLI 算手数 (NAV-based equal-weight position sizing)
# ===========================================================================


def _make_explicit_advice(
    ticker: str,
    name: str,
    current_price: float,
    buy_zone: tuple[float, float],
    *,
    degraded: bool = False,
) -> ConditionalOrderAdvice:
    """直接构造 ConditionalOrderAdvice (绕过 compute_conditional_advice)。

    用于 NS-15(2) 测试: 需要精确控制 buy_zone / current_price / degraded,
    计算 equal-weight quantity 时入口价 = buy_zone 中点。
    """
    return ConditionalOrderAdvice(
        ticker=ticker,
        name=name,
        current_price=current_price,
        atr=2.0,
        suggested_buy_zone=buy_zone,
        suggested_stop_loss=current_price * 0.95,
        suggested_take_profit=current_price * 1.10,
        confidence=0.7,
        reasoning="test",
        historical_hit_rate=0.5,
        risk_reward_ratio=2.0,
        n_sessions=30,
        degraded=degraded,
        atr_period=14,
        params={},
    )


def test_compute_equal_weight_quantities_basic() -> None:
    """NS-15(2): 3 票 NAV=120000 等权 -> 每票 allocation=40000。

    入口价 = buy_zone 中点:
      - 000001 @ 100.0 -> 40000/100 = 400 shares = 4 lots
      - 600519 @ 1800.0 -> 40000/1800 = 22.2 shares -> 0 lots -> 0
      - 300750 @ 250.0 -> 40000/250 = 160 shares = 1 lot (floor 1.6->1)
    """
    from src.screening.conditional_order_export import compute_equal_weight_quantities

    advices = [
        _make_explicit_advice("000001", "平安银行", 100.0, (98.0, 102.0)),
        _make_explicit_advice("600519", "贵州茅台", 1800.0, (1790.0, 1810.0)),
        _make_explicit_advice("300750", "宁德时代", 250.0, (245.0, 255.0)),
    ]
    result = compute_equal_weight_quantities(advices, nav=120000.0)
    assert result == {"000001": 400, "600519": 0, "300750": 100}, f"expected 400/0/100, got {result}"


def test_compute_equal_weight_quantities_rounds_down_to_lot() -> None:
    """NS-15(2): 向下取整到 1 手 (100 股), 不四舍五入。"""
    from src.screening.conditional_order_export import compute_equal_weight_quantities

    advices = [_make_explicit_advice("000001", "平安银行", 100.0, (99.0, 101.0))]
    result = compute_equal_weight_quantities(advices, nav=100000.0)
    assert result == {"000001": 1000}, f"expected 1000 (10 lots), got {result}"


def test_compute_equal_weight_quantities_zero_when_cannot_afford() -> None:
    """NS-15(2): 茅台 @ 1800, NAV=1000, 1 票 -> 0 (买不起 1 手)。"""
    from src.screening.conditional_order_export import compute_equal_weight_quantities

    advices = [_make_explicit_advice("600519", "贵州茅台", 1800.0, (1790.0, 1810.0))]
    result = compute_equal_weight_quantities(advices, nav=1000.0)
    assert result == {"600519": 0}, f"expected 0 (cannot afford 1 lot), got {result}"


def test_compute_equal_weight_quantities_filters_degraded() -> None:
    """NS-15(2): degraded advice 不参与等权分配。"""
    from src.screening.conditional_order_export import compute_equal_weight_quantities

    advices = [
        _make_explicit_advice("000001", "平安银行", 100.0, (98.0, 102.0)),
        _make_explicit_advice("600519", "贵州茅台", 1800.0, (1790.0, 1810.0), degraded=True),
    ]
    result = compute_equal_weight_quantities(advices, nav=100000.0)
    assert result == {"000001": 1000}, f"degraded should be excluded; expected only 000001=1000, got {result}"


def test_compute_equal_weight_quantities_empty_or_zero_nav() -> None:
    """NS-15(2): 空 advices 或 nav<=0 -> 空 dict。"""
    from src.screening.conditional_order_export import compute_equal_weight_quantities

    assert compute_equal_weight_quantities([], nav=100000.0) == {}
    advices = [_make_explicit_advice("000001", "平安银行", 100.0, (98.0, 102.0))]
    assert compute_equal_weight_quantities(advices, nav=0.0) == {}
    assert compute_equal_weight_quantities(advices, nav=-1000.0) == {}


def test_export_with_quantity_map_uses_per_ticker(fixed_today: date) -> None:
    """NS-15(2): export_conditional_orders 接受 quantity_map, 按 ticker 用不同数量。"""
    advices = [
        _make_explicit_advice("000001", "平安银行", 100.0, (98.0, 102.0)),
        _make_explicit_advice("300750", "宁德时代", 250.0, (245.0, 255.0)),
    ]
    quantity_map = {"000001": 500, "300750": 200}
    content = export_conditional_orders(advices, "huatai", quantity_map=quantity_map, today=fixed_today)
    assert "500" in content, f"000001 quantity=500 not in output:\n{content}"
    assert "200" in content, f"300750 quantity=200 not in output:\n{content}"


def test_export_with_quantity_map_skips_zero(fixed_today: date) -> None:
    """NS-15(2): quantity_map 中 0 数量的票被跳过 (不导出无效条件单)。"""
    advices = [
        _make_explicit_advice("000001", "平安银行", 100.0, (98.0, 102.0)),
        _make_explicit_advice("600519", "贵州茅台", 1800.0, (1790.0, 1810.0)),
    ]
    quantity_map = {"000001": 300, "600519": 0}
    content = export_conditional_orders(advices, "huatai", quantity_map=quantity_map, today=fixed_today)
    assert "000001" in content, "000001 should be exported"
    assert "600519" not in content, "600519 (quantity=0) should be skipped"


def test_export_quantity_map_none_backward_compat(fixed_today: date) -> None:
    """NS-15(2): quantity_map=None (缺省) 用 quantity 参数, 向后兼容。"""
    advices = [
        _make_explicit_advice("000001", "平安银行", 100.0, (98.0, 102.0)),
    ]
    content_default = export_conditional_orders(advices, "huatai", today=fixed_today)
    content_explicit = export_conditional_orders(advices, "huatai", quantity=DEFAULT_QUANTITY, today=fixed_today)
    content_none_map = export_conditional_orders(advices, "huatai", quantity_map=None, today=fixed_today)
    assert content_default == content_explicit == content_none_map, "quantity_map=None should be backward compatible with quantity param"


def test_export_from_dicts_with_quantity_map(fixed_today: date) -> None:
    """NS-15(2): export_from_dicts 也接受 quantity_map。"""
    advices = [
        _make_explicit_advice("000001", "平安银行", 100.0, (98.0, 102.0)),
        _make_explicit_advice("300750", "宁德时代", 250.0, (245.0, 255.0)),
    ]
    dicts = [a.to_dict() for a in advices]
    quantity_map = {"000001": 400, "300750": 100}
    content = export_from_dicts(dicts, "huatai", quantity_map=quantity_map, today=fixed_today)
    assert "400" in content, f"000001 quantity=400 not in output:\n{content}"
    assert "100" in content, f"300750 quantity=100 not in output:\n{content}"
