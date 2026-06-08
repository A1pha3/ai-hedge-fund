"""市场温度计 展示辅助函数 — 从 src/main.py 抽取的纯 UI 辅助。

Round 20.14 抽取: 八个 ``run_market_status`` 的私有辅助函数, 约 220 行。
所有函数签名和行为与抽取前完全一致 (纯重构, 无行为变更)。
"""
from __future__ import annotations


def _adx_level(value: float) -> tuple[str, str]:
    """ADX -> 强度等级 + 颜色码（colorama 颜色常量字符串）。

    Thresholds (matches market_state_helpers regime logic):
        >= 25 : 偏强 (green)
        >= 20 : 正常 (yellow)
        >= 15 : 偏弱 (yellow)
        else  : 弱势 (red)
        NaN   : 无数据 (white)
    """
    from src.utils.numeric import is_finite_number as _is_finite_number

    from colorama import Fore

    if not _is_finite_number(value):
        return ("无数据", Fore.WHITE)
    if value >= 25:
        return ("偏强", Fore.GREEN)
    if value >= 20:
        return ("正常", Fore.YELLOW)
    if value >= 15:
        return ("偏弱", Fore.YELLOW)
    return ("弱势", Fore.RED)


def _atr_level(value: float) -> tuple[str, str]:
    """ATR 比率 -> 波动等级 + 颜色码。

    Thresholds:
        >= 3.0% : 高波动 (red)
        >= 1.8% : 偏大   (yellow)
        >= 1.0% : 正常   (green)
        else    : 低波   (cyan)
        NaN     : 无数据 (white)
    """
    from src.utils.numeric import is_finite_number as _is_finite_number

    from colorama import Fore

    if not _is_finite_number(value):
        return ("无数据", Fore.WHITE)
    if value >= 0.030:
        return ("高波动", Fore.RED)
    if value >= 0.018:
        return ("偏大", Fore.YELLOW)
    if value >= 0.010:
        return ("正常", Fore.GREEN)
    return ("低波", Fore.CYAN)


def _breadth_level(value: float) -> tuple[str, str]:
    """市场宽度 (0-1 涨跌比) -> 等级 + 颜色码。

    Thresholds:
        >= 0.60 : 强势 (green)
        >= 0.50 : 均衡 (yellow)
        >= 0.40 : 偏弱 (yellow)
        else    : 弱势 (red)
        NaN     : 无数据 (white)
    """
    from src.utils.numeric import is_finite_number as _is_finite_number

    from colorama import Fore

    if not _is_finite_number(value):
        return ("无数据", Fore.WHITE)
    if value >= 0.60:
        return ("强势", Fore.GREEN)
    if value >= 0.50:
        return ("均衡", Fore.YELLOW)
    if value >= 0.40:
        return ("偏弱", Fore.YELLOW)
    return ("弱势", Fore.RED)


def _northbound_label(days: int) -> tuple[str, str]:
    """北向资金连续天数 -> 文本 + 颜色码。"""
    from colorama import Fore

    if days > 0:
        return (f"+{days}日 净流入", Fore.GREEN)
    if days < 0:
        return (f"{days}日 净流出", Fore.RED)
    return ("无连续方向", Fore.YELLOW)


def _regime_gate_color(level: str) -> str:
    """Regime Gate 级别 -> 颜色码。"""
    from colorama import Fore

    return {
        "normal": Fore.GREEN,
        "risk_off": Fore.YELLOW,
        "crisis": Fore.RED,
    }.get(str(level or "").lower(), Fore.WHITE)


def _state_type_cn(state_type: str) -> str:
    """state_type 英文枚举 -> 中文标签。"""
    return {
        "trend": "趋势型",
        "range": "震荡型",
        "mixed": "混合型",
        "crisis": "危机型",
    }.get(str(state_type or "").lower(), str(state_type or "—"))


def _extract_market_status(market_state: object) -> dict:
    """从 MarketState 对象提取温度计所需的字段，含 NaN/None 兜底。

    所有数值字段均经过 ``_safe_float`` / ``_safe_int`` 处理, 杜绝 NaN 污染。
    """
    from src.utils.numeric import safe_float as _safe_float, safe_int as _safe_int

    return {
        "adx": _safe_float(getattr(market_state, "adx", 0.0), 0.0),
        "atr_ratio": _safe_float(getattr(market_state, "atr_price_ratio", 0.0), 0.0),
        "breadth_ratio": _safe_float(getattr(market_state, "breadth_ratio", 0.5), 0.5),
        "daily_return": _safe_float(getattr(market_state, "daily_return", 0.0), 0.0),
        "limit_up": _safe_int(getattr(market_state, "limit_up_count", 0), 0),
        "limit_down": _safe_int(getattr(market_state, "limit_down_count", 0), 0),
        "northbound_days": _safe_int(getattr(market_state, "northbound_flow_days", 0), 0),
        "state_type": str(getattr(market_state, "state_type", None) or "mixed"),
        "position_scale": _safe_float(getattr(market_state, "position_scale", 1.0), 1.0),
        "regime_gate_level": str(getattr(market_state, "regime_gate_level", None) or "normal"),
    }


def _format_market_status_table(data: dict) -> str:
    """根据提取的字段生成温度计文本 (彩色 ANSI 序列)。"""
    from src.utils.numeric import is_finite_number as _is_finite_number

    from colorama import Fore, Style

    adx = data["adx"]
    atr = data["atr_ratio"]
    breadth = data["breadth_ratio"]
    daily_return = data["daily_return"]
    limit_up = data["limit_up"]
    limit_down = data["limit_down"]
    north_days = data["northbound_days"]
    state_type = data["state_type"]
    position_scale = data["position_scale"]
    regime_gate = data["regime_gate_level"]

    has_index_data = _is_finite_number(adx) and adx > 0
    has_price_data = _is_finite_number(atr) and atr > 0

    adx_label, adx_color = _adx_level(adx)
    atr_label, atr_color = _atr_level(atr)
    breadth_label, breadth_color = _breadth_level(breadth)

    if not has_index_data:
        northbound_segment = f"{Fore.WHITE}数据暂不可用{Style.RESET_ALL}"
    else:
        nb_text, nb_color = _northbound_label(north_days)
        northbound_segment = nb_color + nb_text + Style.RESET_ALL

    regime_color = _regime_gate_color(regime_gate)
    state_type_cn = _state_type_cn(state_type)

    if _is_finite_number(breadth) and 0.0 <= breadth <= 1.0:
        total_est = 5000
        advancers = int(round(breadth * total_est))
        decliners = total_est - advancers
        breadth_detail = f"  ↓{decliners}/↑{advancers}"
    else:
        breadth_detail = ""

    def _bar(value: float, full_scale: float, width: int = 10) -> str:
        if not _is_finite_number(value) or value <= 0:
            return "░" * width
        ratio = max(0.0, min(1.0, value / full_scale))
        filled = int(round(ratio * width))
        return "█" * filled + "░" * (width - filled)

    adx_bar = _bar(adx, 50.0)
    atr_bar = _bar(atr, 0.030)

    border = "═" * 54
    lines: list[str] = []
    lines.append(Fore.CYAN + Style.BRIGHT + f"╔{border}╗" + Style.RESET_ALL)
    lines.append(Fore.CYAN + Style.BRIGHT + f"║{'市场温度计 · ' + str(data.get('date', '')):^54}║" + Style.RESET_ALL)
    lines.append(Fore.CYAN + Style.BRIGHT + f"╠{border}╣" + Style.RESET_ALL)
    lines.append(Fore.CYAN + "║" + " " * 54 + "║" + Style.RESET_ALL)

    if has_index_data:
        adx_value_str = f"{adx:.1f}"
    else:
        adx_value_str = "数据暂不可用"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + f"趋势强度 (ADX)    {adx_bar}  {adx_value_str:>10}  " + adx_color + adx_label + Style.RESET_ALL)

    if has_price_data:
        atr_value_str = f"{atr * 100:.2f}%"
    else:
        atr_value_str = "数据暂不可用"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + f"波动率 (ATR)      {atr_bar}  {atr_value_str:>10}  " + atr_color + atr_label + Style.RESET_ALL)

    breadth_value_str = f"{breadth:.2f}{breadth_detail}" if _is_finite_number(breadth) else "数据暂不可用"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + f"市场宽度 (涨跌比)  {breadth_value_str:<20}  " + breadth_color + breadth_label + Style.RESET_ALL)

    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + f"北向资金          {northbound_segment}")

    limit_str = f"涨停{Fore.GREEN}{limit_up}{Style.RESET_ALL} / 跌停{Fore.RED}{limit_down}{Style.RESET_ALL}"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + f"涨跌停            {limit_str:<40}  ")

    lines.append(Fore.CYAN + "║" + " " * 54 + "║" + Style.RESET_ALL)

    summary_line = f"综合状态: {state_type_cn}  |  仓位系数: {position_scale:.2f}"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + Fore.WHITE + Style.BRIGHT + summary_line + Style.RESET_ALL)

    regime_line = f"Regime Gate: {regime_gate}"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + regime_color + Style.BRIGHT + regime_line + Style.RESET_ALL)

    if _is_finite_number(daily_return):
        return_pct = daily_return * 100
        if return_pct > 0:
            return_color = Fore.RED if return_pct > 1 else Fore.WHITE
        else:
            return_color = Fore.GREEN if return_pct < -1 else Fore.WHITE
        return_line = f"指数日收益: {return_pct:+.2f}%"
        lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + return_color + return_line + Style.RESET_ALL)

    lines.append(Fore.CYAN + "║" + " " * 54 + "║" + Style.RESET_ALL)
    lines.append(Fore.CYAN + Style.BRIGHT + f"╚{border}╝" + Style.RESET_ALL)

    return "\n".join(lines)
