"""P1-13 条件单模板券商格式导出 — 将 ConditionalOrderAdvice 转换为
华泰 / 国泰君安 / 同花顺 三家券商条件单导入格式。

设计原则:
  - **纯函数**: 不读写文件, 不发网络, 便于单测。
  - **字段映射**: 同一语义在不同券商格式下字段名不同, 通过 ``broker_field_map`` 统一。
  - **ConditionalOrderAdvice 字段说明**:
      - ``suggested_buy_zone`` → ``(low, high)`` 建议买入区间
      - ``suggested_stop_loss`` → 止损价
      - ``suggested_take_profit`` → 止盈价
      - ``current_price`` → 当前价 (作为触发价参考)
      - ``ticker`` → 标的代码
      - ``name`` → 标的名称
    缺失字段: ``valid_until`` (有效期) / ``quantity`` (委托数量) — 不在
    ConditionalOrderAdvice 中, 导出时用合理默认值:
      - ``valid_until`` = today + 3 营业日
      - ``quantity`` = 100 (A股最小单位 1 手)
  - **CSV 编码**: utf-8-sig (加 BOM), Excel 直接打开不乱码。

主入口:
  - :func:`export_conditional_orders`  统一导出入口, 根据 broker 选择 adapter
  - :func:`huatai_adapter`  华泰条件单 CSV
  - :func:`gtja_adapter`    国泰君安条件单 CSV
  - :func:`ths_adapter`     同花顺条件单 JSON

字段映射参考:
  - 华泰: 字段顺序参考 华泰证券「条件单导入模板」v2024 — 股票代码/买卖方向/触发价/委托价/有效期/委托数量/触发条件
  - 国泰君安: 字段顺序参考 国泰君安「智能条件单批量导入」v2024 — 证券代码/委托类别/触发价格/报价/委托数量/有效日期
  - 同花顺: 字段顺序参考 同花顺「条件单批量导入」v2024 — code/direction/price/triggerPrice/condition/validDays
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Sequence

from src.screening.conditional_order_advisor import ConditionalOrderAdvice

# R151: 降级 (数据不足) advice 被 advisor 自标为 "建议仅作参考, 请补充数据"
# (confidence=0.0)。将降级 advice 作为真实券商条件单导出会与该标记矛盾, 且
# 新上市 (<MIN_PRICE_SESSIONS 日) 标的用占位 ATR (current×0.005) 生成极紧止损
# (≈1%), 正常波动下近必然触发; corrupted feed 则产生 0 价条件单。降级 advice
# 仅在展示表 (带 "降级" 标签) 中可见, 不应进入券商导入。debug 级别避免噪音。
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_BROKERS = ("huatai", "gtja", "ths")

#: 默认有效期 (today + N 营业日, 简化为 today + N 日)
DEFAULT_VALID_DAYS = 3

#: A 股最小委托数量 (1 手 = 100 股)
DEFAULT_QUANTITY = 100

#: 1 手的股数 (LOT_SIZE = DEFAULT_QUANTITY = 100, A 股最小委托单位)
LOT_SIZE = DEFAULT_QUANTITY


# ---------------------------------------------------------------------------
# Helper: 营业日计算 (trade_cal 优先, weekday fallback)
# ---------------------------------------------------------------------------


def _next_business_day(start: date, n_days: int = DEFAULT_VALID_DAYS) -> str:
    """计算从 start 起第 n_days 个交易日后的日期。

    优先使用 tushare ``trade_cal`` (``get_open_trade_dates``) 获取真实 A 股
    交易日, 排除周末和节假日 (春节/国庆等)。无 token / 网络失败 / 空结果时
    fallback 到 weekday-only 近似 (跳过周六周日, 不排除节假日)。

    NS-15(1) 修复: 旧实现用 ``start + timedelta(days=n_days)`` 纯自然日,
    周四+3=周日, broker 收到周末到期单被拒/静默失效。

    Args:
        start: 基准日期 (不含在 n_days 内, 即返回 start 之后第 n_days 个交易日)
        n_days: 交易日天数 (默认 3)

    Returns:
        ``YYYYMMDD`` 格式字符串
    """
    start_str = start.strftime("%Y%m%d")

    # 1. 优先用 trade_cal (拉取足够窗口: n_days 个交易日 + 21 天节假日缓冲)
    try:
        from src.tools.tushare_api import get_open_trade_dates  # local import: keep startup light

        fetch_end = start + timedelta(days=n_days + 21)
        open_dates = get_open_trade_dates(start_str, fetch_end.strftime("%Y%m%d"))
    except Exception as exc:  # pragma: no cover — defensive: never block export on calendar fetch
        logger.debug("_next_business_day: trade_cal fetch failed: %s", exc)
        open_dates = []

    if open_dates:
        # 过滤掉 start 及之前的日期, 取第 n_days 个交易日 (1-indexed)
        future_dates = [d for d in sorted(open_dates) if d > start_str]
        if len(future_dates) >= n_days:
            return future_dates[n_days - 1]
        # 不足 n_days (理论上不会发生, 因窗口有 21 天缓冲), 保守 fallback

    # 2. Fallback: weekday-only 近似 (Mon-Fri, 不排除节假日)
    target = start
    count = 0
    while count < n_days:
        target = target + timedelta(days=1)
        if target.weekday() < 5:  # Mon=0..Fri=4, Sat=5, Sun=6
            count += 1
    return target.strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class BrokerConditionalOrder:
    """券商条件单 (单标的) — 承载同一语义在不同券商格式下的字段映射。

    Attributes:
        ticker: 标的代码 (6 位 A 股)
        name: 标的名称
        side: 买卖方向 ("买入" / "卖出")
        entry_price: 委托价格 (建议买入区间中值)
        stop_loss_price: 止损价
        take_profit_price: 止盈价
        trigger_price: 触发价格 (当前价 / 买入区间高值)
        valid_until: 有效截止日期 (YYYYMMDD)
        quantity: 委托数量 (股)
        trigger_condition: 触发条件 (">=" / "<=")
    """

    ticker: str
    name: str
    side: str
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    trigger_price: float
    valid_until: str
    quantity: int
    trigger_condition: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "side": self.side,
            "entry_price": self.entry_price,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "trigger_price": self.trigger_price,
            "valid_until": self.valid_until,
            "quantity": self.quantity,
            "trigger_condition": self.trigger_condition,
        }


# ---------------------------------------------------------------------------
# Conversion: ConditionalOrderAdvice → BrokerConditionalOrder
# ---------------------------------------------------------------------------


def advice_to_broker_order(
    advice: ConditionalOrderAdvice,
    *,
    valid_days: int = DEFAULT_VALID_DAYS,
    quantity: int = DEFAULT_QUANTITY,
    today: date | None = None,
) -> BrokerConditionalOrder:
    """将 ConditionalOrderAdvice 转换为 BrokerConditionalOrder。

    字段映射:
      - entry_price = buy_zone 中值 = (low + high) / 2
      - stop_loss_price = suggested_stop_loss
      - take_profit_price = suggested_take_profit
      - trigger_price = current_price (当现价跌破买入区间时触发买入)
      - trigger_condition = "<=" (价格跌到触发价以下时买入)
      - side = "买入" (条件单默认为买入条件单)
      - valid_until = today + valid_days

    Args:
        advice: ConditionalOrderAdvice 实例
        valid_days: 有效天数 (默认 3)
        quantity: 委托数量 (默认 100)
        today: 基准日期 (默认 date.today())

    Returns:
        BrokerConditionalOrder 实例
    """
    base_date = today or date.today()
    low, high = advice.suggested_buy_zone
    entry = (low + high) / 2.0
    trigger = advice.current_price

    return BrokerConditionalOrder(
        ticker=advice.ticker,
        name=advice.name,
        side="买入",
        entry_price=round(entry, 2),
        stop_loss_price=round(advice.suggested_stop_loss, 2),
        take_profit_price=round(advice.suggested_take_profit, 2),
        trigger_price=round(trigger, 2),
        valid_until=_next_business_day(base_date, valid_days),
        quantity=quantity,
        trigger_condition="<=",
    )


# ---------------------------------------------------------------------------
# Broker adapters
# ---------------------------------------------------------------------------


def huatai_adapter(
    orders: list[BrokerConditionalOrder],
    *,
    broker_name: str = "huatai",
) -> str:
    """华泰证券条件单 CSV 导出。

    字段顺序参考 华泰证券「条件单导入模板」v2024:
      股票代码, 买卖方向, 触发价, 委托价, 有效期, 委托数量, 触发条件(>=/< =)

    Args:
        orders: BrokerConditionalOrder 列表
        broker_name: 券商标识 (保留参数, 便于统一调用签名)

    Returns:
        CSV 字符串 (utf-8-sig 编码, 含 BOM)
    """
    header = ["股票代码", "买卖方向", "触发价", "委托价", "有效期", "委托数量", "触发条件"]

    buf = io.StringIO()
    # 写入 UTF-8 BOM 以便 Excel 正确识别中文
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(header)

    for o in orders:
        writer.writerow([
            o.ticker,
            o.side,
            f"{o.trigger_price:.2f}",
            f"{o.entry_price:.2f}",
            o.valid_until,
            str(o.quantity),
            o.trigger_condition,
        ])

    return buf.getvalue()


def gtja_adapter(
    orders: list[BrokerConditionalOrder],
    *,
    broker_name: str = "gtja",
) -> str:
    """国泰君安条件单 CSV 导出。

    字段顺序参考 国泰君安「智能条件单批量导入」v2024:
      证券代码, 委托类别(0买1卖), 触发价格, 报价, 委托数量, 有效日期(YYYYMMDD)

    注意: 委托类别 0=买入, 1=卖出 (国泰君安专用编码)

    Args:
        orders: BrokerConditionalOrder 列表
        broker_name: 券商标识 (保留参数)

    Returns:
        CSV 字符串 (utf-8-sig 编码, 含 BOM)
    """
    header = ["证券代码", "委托类别", "触发价格", "报价", "委托数量", "有效日期"]

    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(header)

    for o in orders:
        side_code = 0 if o.side == "买入" else 1
        writer.writerow([
            o.ticker,
            str(side_code),
            f"{o.trigger_price:.2f}",
            f"{o.entry_price:.2f}",
            str(o.quantity),
            o.valid_until,
        ])

    return buf.getvalue()


def ths_adapter(
    orders: list[BrokerConditionalOrder],
    *,
    broker_name: str = "ths",
) -> str:
    """同花顺条件单 JSON 导出。

    字段顺序参考 同花顺「条件单批量导入」v2024:
      code, direction, price, triggerPrice, condition, validDays

    Args:
        orders: BrokerConditionalOrder 列表
        broker_name: 券商标识 (保留参数)

    Returns:
        JSON 数组字符串 (格式化, utf-8)
    """
    items: list[dict[str, Any]] = []
    for o in orders:
        items.append({
            "code": o.ticker,
            "direction": o.side,
            "price": o.entry_price,
            "triggerPrice": o.trigger_price,
            "condition": o.trigger_condition,
            "validDays": DEFAULT_VALID_DAYS,
        })
    return json.dumps(items, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Unified export
# ---------------------------------------------------------------------------

_ADAPTER_MAP = {
    "huatai": huatai_adapter,
    "gtja": gtja_adapter,
    "ths": ths_adapter,
}


def export_conditional_orders(
    advices: Sequence[ConditionalOrderAdvice],
    broker: str,
    *,
    valid_days: int = DEFAULT_VALID_DAYS,
    quantity: int = DEFAULT_QUANTITY,
    today: date | None = None,
    quantity_map: dict[str, int] | None = None,
) -> str:
    """统一导出入口: ConditionalOrderAdvice 列表 → 券商格式文本。

    Args:
        advices: ConditionalOrderAdvice 序列
        broker: 券商标识 ("huatai" / "gtja" / "ths")
        valid_days: 有效天数 (默认 3)
        quantity: 委托数量 (默认 100)
        today: 基准日期 (默认 date.today())

    Returns:
        券商格式文本 (CSV 或 JSON)

    Raises:
        ValueError: broker 不在支持列表中
    """
    if broker not in SUPPORTED_BROKERS:
        raise ValueError(
            f"不支持的券商: {broker!r}, 支持: {', '.join(SUPPORTED_BROKERS)}"
        )

    # R151: 过滤降级 (数据不足) advice — 不导出为真实券商条件单 (见模块 logger 注释)。
    viable = [a for a in advices if not getattr(a, "degraded", False)]
    skipped = len(advices) - len(viable)
    if skipped > 0:
        logger.warning(
            "conditional_order_export: 跳过 %d 条降级 (数据不足) advice, "
            "仅导出 %d 条有效条件单 (降级 advice 自标 '建议仅作参考', 不应进入券商导入)",
            skipped,
            len(viable),
        )

    # NS-15(2): quantity_map 提供时按 ticker 取数量, 0 数量票被跳过 (不导出无效条件单)。
    # quantity_map=None 时所有票用 ``quantity`` 参数 (向后兼容)。
    orders: list[BrokerConditionalOrder] = []
    for a in viable:
        if quantity_map is not None:
            q = quantity_map.get(a.ticker, 0)
            if q <= 0:
                continue
        else:
            q = quantity
        orders.append(
            advice_to_broker_order(a, valid_days=valid_days, quantity=q, today=today)
        )

    adapter = _ADAPTER_MAP[broker]
    return adapter(orders, broker_name=broker)


def export_from_dicts(
    dicts: Sequence[dict[str, Any]],
    broker: str,
    *,
    valid_days: int = DEFAULT_VALID_DAYS,
    quantity: int = DEFAULT_QUANTITY,
    today: date | None = None,
    quantity_map: dict[str, int] | None = None,
) -> str:
    """从 ConditionalOrderAdvice.to_dict() 字典列表导出。

    与 ``export_conditional_orders`` 功能相同, 但接受已序列化的 dict 列表
    (从 auto_screening JSON 报告中读取)。

    Args:
        dicts: ConditionalOrderAdvice.to_dict() 字典列表
        broker: 券商标识
        valid_days: 有效天数
        quantity: 委托数量
        today: 基准日期

    Returns:
        券商格式文本

    Raises:
        ValueError: broker 不在支持列表中
    """
    advices: list[ConditionalOrderAdvice] = []
    for d in dicts:
        buy_zone = d.get("suggested_buy_zone", [0.0, 0.0])
        if isinstance(buy_zone, (list, tuple)) and len(buy_zone) >= 2:
            zone_tuple = (float(buy_zone[0]), float(buy_zone[1]))
        else:
            low = float(d.get("suggested_buy_zone_low", 0.0) or 0.0)
            high = float(d.get("suggested_buy_zone_high", 0.0) or 0.0)
            zone_tuple = (low, high)

        advice = ConditionalOrderAdvice(
            ticker=str(d.get("ticker", "")),
            name=str(d.get("name", "")),
            current_price=float(d.get("current_price") or 0.0),
            atr=float(d.get("atr") or 0.0),
            suggested_buy_zone=zone_tuple,
            suggested_stop_loss=float(d.get("suggested_stop_loss") or 0.0),
            suggested_take_profit=float(d.get("suggested_take_profit") or 0.0),
            confidence=float(d.get("confidence") or 0.0),
            reasoning=str(d.get("reasoning", "")),
            historical_hit_rate=float(d.get("historical_hit_rate") or 0.0),
            risk_reward_ratio=float(d.get("risk_reward_ratio") or 0.0),
            n_sessions=int(d.get("n_sessions") or 0),
            degraded=bool(d.get("degraded", False)),
            atr_period=int(d.get("atr_period") or 14),
            params=d.get("params") or {},
        )
        advices.append(advice)

    return export_conditional_orders(
        advices, broker, valid_days=valid_days, quantity=quantity, today=today,
        quantity_map=quantity_map,
    )


# ---------------------------------------------------------------------------
# NS-15(2): 等权仓位分配 (NAV-based equal-weight position sizing)
# ---------------------------------------------------------------------------


def compute_equal_weight_quantities(
    advices: Sequence[ConditionalOrderAdvice],
    nav: float,
    *,
    lot_size: int = LOT_SIZE,
) -> dict[str, int]:
    """根据总资产 NAV 等权分配各标的的委托手数。

    NS-15(2) design_decision_packet (engineering-owned):
      - 公式: ``allocation_per_pick = nav / len(viable)``, 每票等权
      - 入口价: ``entry = (buy_zone_low + buy_zone_high) / 2.0`` (用建议区间中点)
      - 手数: ``lots = floor(allocation_per_pick / entry / lot_size)``,
        ``quantity = lots * lot_size`` (向下取整到 1 手 = 100 股)
      - 降级 (degraded=True) advice 不参与等权分配
      - nav <= 0 或 viable 为空 → 空 dict
      - 单票买不起 1 手 → 该票 quantity = 0

    Args:
        advices: ConditionalOrderAdvice 序列
        nav: 总资产 (Net Asset Value, 元)
        lot_size: 1 手的股数 (默认 100, A 股最小委托单位)

    Returns:
        ``{ticker: quantity}`` 字典; 已过滤 degraded, 未在 dict 中的 degraded 票
        不出现在结果中
    """
    viable = [a for a in advices if not getattr(a, "degraded", False)]
    if not viable or nav <= 0:
        return {}
    allocation_per_pick = nav / len(viable)
    result: dict[str, int] = {}
    for a in viable:
        low, high = a.suggested_buy_zone
        entry = (low + high) / 2.0
        if entry <= 0:
            result[a.ticker] = 0
            continue
        raw_shares = allocation_per_pick / entry
        lots = int(raw_shares // lot_size)
        result[a.ticker] = lots * lot_size
    return result


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_export_conditional_orders_cli(
    broker: str = "huatai",
    *,
    nav: float | None = None,
) -> int:
    """CLI 入口 — 读取最新 auto_screening 报告, 导出条件单券商格式。

    Args:
        broker: 券商标识 (默认 "huatai")

    Returns:
        退出码 (0=成功, 1=无报告/无条件单, 2=broker 不支持)
    """
    import glob

    from colorama import Fore, Style

    if broker not in SUPPORTED_BROKERS:
        print(
            f"{Fore.RED}[Export] 不支持的券商: {broker!r}, "
            f"支持: {', '.join(SUPPORTED_BROKERS)}{Style.RESET_ALL}"
        )
        return 2

    # 1. 查找最新 auto_screening 报告
    reports_dir = "data/reports"
    pattern = f"{reports_dir}/auto_screening_*.json"
    files = sorted(glob.glob(pattern))
    if not files:
        print(
            f"{Fore.YELLOW}[Export] 未找到 auto_screening 报告, "
            f"请先运行 --conditional-orders 或 --auto{Style.RESET_ALL}"
        )
        return 1

    latest_file = files[-1]

    # 2. 加载报告
    import json as _json

    try:
        with open(latest_file, encoding="utf-8") as f:
            payload = _json.load(f)
    except Exception as e:
        print(f"{Fore.RED}[Export] 读取报告失败: {e}{Style.RESET_ALL}")
        return 1

    conditional_orders = payload.get("conditional_orders") or []

    # 3. 如果没有 conditional_orders, 尝试从 recommendations 生成
    if not conditional_orders:
        recs = payload.get("recommendations") or []
        if recs:
            from src.screening.conditional_order_advisor import (
                attach_conditional_orders_to_payload,
            )

            conditional_orders = attach_conditional_orders_to_payload(payload, top_n=20)

    if not conditional_orders:
        print(
            f"{Fore.YELLOW}[Export] 报告中无条件单数据, "
            f"请先运行 --conditional-orders 或 --auto{Style.RESET_ALL}"
        )
        return 1

    # 4. 导出
    ext = "json" if broker == "ths" else "csv"
    today_str = date.today().strftime("%Y%m%d")
    output_path = f"{reports_dir}/conditional_orders_{broker}_{today_str}.{ext}"

    # R151: 统计降级 advice 数 (export_from_dicts 内部会过滤); 让用户知晓跳过。
    degraded_count = sum(1 for d in conditional_orders if isinstance(d, dict) and d.get("degraded"))

    # NS-15(2): nav 提供时按等权公式计算每票委托手数; 否则 None 用默认 quantity。
    quantity_map: dict[str, int] | None = None
    if nav is not None:
        advice_objs: list[ConditionalOrderAdvice] = []
        for d in conditional_orders:
            if not isinstance(d, dict) or d.get("degraded"):
                continue
            buy_zone = d.get("suggested_buy_zone", [0.0, 0.0])
            if isinstance(buy_zone, (list, tuple)) and len(buy_zone) >= 2:
                zone_tuple = (float(buy_zone[0]), float(buy_zone[1]))
            else:
                low = float(d.get("suggested_buy_zone_low", 0.0) or 0.0)
                high = float(d.get("suggested_buy_zone_high", 0.0) or 0.0)
                zone_tuple = (low, high)
            advice_objs.append(ConditionalOrderAdvice(
                ticker=str(d.get("ticker", "")),
                name=str(d.get("name", "")),
                current_price=float(d.get("current_price") or 0.0),
                atr=float(d.get("atr") or 0.0),
                suggested_buy_zone=zone_tuple,
                suggested_stop_loss=float(d.get("suggested_stop_loss") or 0.0),
                suggested_take_profit=float(d.get("suggested_take_profit") or 0.0),
                confidence=float(d.get("confidence") or 0.0),
                reasoning=str(d.get("reasoning", "")),
                historical_hit_rate=float(d.get("historical_hit_rate") or 0.0),
                risk_reward_ratio=float(d.get("risk_reward_ratio") or 0.0),
                n_sessions=int(d.get("n_sessions") or 0),
                degraded=False,
                atr_period=int(d.get("atr_period") or 14),
                params=d.get("params") or {},
            ))
        quantity_map = compute_equal_weight_quantities(advice_objs, nav=nav)

    content = export_from_dicts(conditional_orders, broker, quantity_map=quantity_map)

    # 5. 写入文件 (CSV 用 utf-8-sig 写入, JSON 用 utf-8)
    encoding = "utf-8-sig" if ext == "csv" else "utf-8"
    with open(output_path, "w", encoding=encoding) as f:
        f.write(content)

    # 6. 输出预览
    viable_count = len(conditional_orders) - degraded_count
    print(f"\n{Fore.CYAN}{Style.BRIGHT}{'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[P1-13] 条件单导出 · {broker.upper()}{Style.RESET_ALL}")
    print(f"  来源: {latest_file}")
    print(f"  数量: {viable_count} 条有效" + (
        f" (跳过 {degraded_count} 条降级建议 — 数据不足, 不导出)" if degraded_count else ""
    ))
    print(f"  输出: {output_path}")
    print(f"{Fore.CYAN}{Style.BRIGHT}{'=' * 60}{Style.RESET_ALL}\n")

    # 预览前 3 行
    lines = content.strip().split("\n")
    preview_count = min(4, len(lines))  # header + 3 data rows
    if ext == "csv":
        print(f"{Fore.GREEN}预览 (前 {max(0, preview_count - 1)} 行):{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}预览:{Style.RESET_ALL}")
    for line in lines[:preview_count]:
        print(f"  {line}")
    if len(lines) > preview_count:
        print(f"  ... (共 {len(lines)} 行)")

    print(f"\n{Fore.GREEN}文件已写入: {output_path}{Style.RESET_ALL}")
    return 0


__all__ = [
    "SUPPORTED_BROKERS",
    "DEFAULT_VALID_DAYS",
    "DEFAULT_QUANTITY",
    "LOT_SIZE",
    "compute_equal_weight_quantities",
    "BrokerConditionalOrder",
    "advice_to_broker_order",
    "huatai_adapter",
    "gtja_adapter",
    "ths_adapter",
    "export_conditional_orders",
    "export_from_dicts",
    "run_export_conditional_orders_cli",
]
