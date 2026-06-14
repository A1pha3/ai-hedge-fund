"""P1-9 市场温度计 — 单元测试

测试覆盖:
  1. run_market_status 成功路径 (全指标)
  2. _adx_level 强度等级映射
  3. _breadth_level 市场宽度映射
  4. detect_market_state 异常时优雅降级
  5. 空数据 (MarketState()) 时展示"数据暂不可用"
  6. _northbound_label 流入/流出/无方向
  7. position_scale 仓位系数展示
  8. regime_gate_level 三种级别展示
"""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from src.cli.market_status_helpers import (
    _adx_level,
    _atr_level,
    _breadth_level,
    _extract_market_status,
    _format_market_status_table,
    _northbound_label,
    _regime_gate_color,
    _state_type_cn,
)
from src.main import _is_finite_number, run_market_status
from src.screening.models import MarketState

# ============================================================================
# Helpers
# ============================================================================


def _build_market_state(**overrides) -> MarketState:
    """构造一个 MarketState，字段全有，调用方按需覆盖。"""
    defaults = dict(
        state_type="trend",
        adx=28.5,
        atr_price_ratio=0.018,
        breadth_ratio=0.55,
        daily_return=0.005,
        limit_up_count=45,
        limit_down_count=12,
        limit_up_down_ratio=3.75,
        total_volume=8000.0,
        northbound_flow_days=3,
        is_low_volume=False,
        style_dispersion=0.2,
        regime_flip_risk=0.1,
        regime_gate_level="normal",
        regime_gate_reasons=[],
        position_scale=0.85,
    )
    defaults.update(overrides)
    return MarketState(**defaults)


# ============================================================================
# 1. 成功路径 — 完整 MarketState → 表格包含所有指标
# ============================================================================


def test_run_market_status_success_path(capsys) -> None:
    """run_market_status: 当 detect_market_state 返回正常 MarketState 时,
    应当打印包含 趋势/波动/宽度/北向/涨跌停 的温度计并返回 0。"""
    state = _build_market_state()
    with patch("src.main.detect_market_state", return_value=state):
        rc = run_market_status("20260607")
    output = capsys.readouterr().out
    assert rc == 0
    assert "市场温度计" in output
    assert "趋势强度" in output
    assert "波动率" in output
    assert "市场宽度" in output
    assert "北向资金" in output
    assert "涨跌停" in output
    assert "综合状态" in output
    assert "仓位系数" in output
    assert "Regime Gate" in output
    assert "20260607" in output
    assert "0.85" in output  # position_scale
    assert "趋势型" in output  # state_type_cn


# ============================================================================
# 2. _adx_level 数值 → 强度等级
# ============================================================================


@pytest.mark.parametrize(
    "value,expected_label",
    [
        (30.0, "偏强"),
        (25.0, "偏强"),  # 边界
        (24.99, "正常"),
        (20.0, "正常"),  # 边界
        (19.99, "偏弱"),
        (15.0, "偏弱"),  # 边界
        (14.99, "弱势"),
        (5.0, "弱势"),
        (0.0, "弱势"),
    ],
)
def test_adx_level_mapping(value: float, expected_label: str) -> None:
    label, _color = _adx_level(value)
    assert label == expected_label


def test_adx_level_nan_returns_unknown() -> None:
    label, _color = _adx_level(float("nan"))
    assert label == "无数据"


def test_adx_level_inf_returns_unknown() -> None:
    label, _color = _adx_level(float("inf"))
    assert label == "无数据"


# ============================================================================
# 3. _breadth_level 数值 → 宽度等级
# ============================================================================


@pytest.mark.parametrize(
    "value,expected_label",
    [
        (0.80, "强势"),
        (0.60, "强势"),  # 边界
        (0.59, "均衡"),
        (0.50, "均衡"),  # 边界
        (0.49, "偏弱"),
        (0.40, "偏弱"),  # 边界
        (0.39, "弱势"),
        (0.10, "弱势"),
    ],
)
def test_breadth_level_mapping(value: float, expected_label: str) -> None:
    label, _color = _breadth_level(value)
    assert label == expected_label


def test_breadth_level_nan_returns_unknown() -> None:
    label, _color = _breadth_level(float("nan"))
    assert label == "无数据"


# ============================================================================
# 4. detect_market_state 抛异常 → 优雅降级 + 返回 1
# ============================================================================


def test_run_market_status_handles_api_failure(capsys) -> None:
    """当 detect_market_state 抛异常时, run_market_status 应捕获并返回 1。"""
    with patch("src.main.detect_market_state", side_effect=RuntimeError("network down")):
        rc = run_market_status("20260607")
    output = capsys.readouterr().out
    assert rc == 1
    assert "数据获取失败" in output


# ============================================================================
# 5. MarketState() (默认值) → 输出含"数据暂不可用"
# ============================================================================


def test_run_market_status_default_market_state_shows_unavailable(capsys) -> None:
    """默认 MarketState (adx=0, atr=0) → 指标值显示"数据暂不可用", 返回 1。"""
    state = MarketState()  # 全默认, adx=0.0, atr=0.0
    with patch("src.main.detect_market_state", return_value=state):
        rc = run_market_status("20260607")
    output = capsys.readouterr().out
    assert rc == 1  # has_index_data=False 且 has_price_data=False → 返回 1
    assert "数据暂不可用" in output


def test_format_market_status_table_with_zero_adx_uses_unavailable() -> None:
    """_format_market_status_table: adx=0 时趋势强度行显示"数据暂不可用"。"""
    data = _extract_market_state_dict_from(MarketState())
    data["date"] = "20260607"
    output = _format_market_status_table(data)
    assert "数据暂不可用" in output
    assert "0.0  " in output or "0.0" in output  # 涨跌停行还会有 0


# ============================================================================
# 6. _northbound_label 方向判断
# ============================================================================


@pytest.mark.parametrize(
    "days,expected_text",
    [
        (5, "+5日 净流入"),
        (1, "+1日 净流入"),
        (0, "无连续方向"),
        (-1, "-1日 净流出"),
        (-5, "-5日 净流出"),
    ],
)
def test_northbound_label_direction(days: int, expected_text: str) -> None:
    text, _color = _northbound_label(days)
    assert text == expected_text


# ============================================================================
# 7. 仓位系数 (position_scale) 展示
# ============================================================================


def test_format_market_status_table_shows_position_scale() -> None:
    """_format_market_status_table: position_scale 必须以 2 位小数出现在综合状态行。"""
    state = _build_market_state(position_scale=0.62)
    data = _extract_market_status(state)
    data["date"] = "20260607"
    output = _format_market_status_table(data)
    assert "仓位系数: 0.62" in output


def test_extract_market_status_preserves_position_scale() -> None:
    """_extract_market_status: 即使传 None / 0 / 1.0 等也安全保留为 float。"""
    state = MarketState(position_scale=0.45)
    data = _extract_market_status(state)
    assert data["position_scale"] == 0.45
    assert isinstance(data["position_scale"], float)


# ============================================================================
# 8. Regime Gate 三种级别展示
# ============================================================================


@pytest.mark.parametrize(
    "level,expected_text",
    [
        ("normal", "Regime Gate: normal"),
        ("risk_off", "Regime Gate: risk_off"),
        ("crisis", "Regime Gate: crisis"),
        ("unknown_value", "Regime Gate: unknown_value"),  # 未知值仍展示
    ],
)
def test_format_market_status_table_shows_regime_gate(level, expected_text) -> None:
    """Regime Gate 各级别在温度计输出中正确展示。"""
    state = _build_market_state(regime_gate_level=level)
    data = _extract_market_status(state)
    data["date"] = "20260607"
    output = _format_market_status_table(data)
    assert expected_text in output


def test_regime_gate_color_mapping() -> None:
    """_regime_gate_color: normal=green, risk_off=yellow, crisis=red, unknown=white。"""
    from colorama import Fore

    assert _regime_gate_color("normal") == Fore.GREEN
    assert _regime_gate_color("risk_off") == Fore.YELLOW
    assert _regime_gate_color("crisis") == Fore.RED
    # 未知值返回 white
    assert _regime_gate_color("foo_bar") == Fore.WHITE


# ============================================================================
# 9. 额外健壮性测试 — _is_finite_number / _extract_market_status 兜底
# ============================================================================


def test_is_finite_number_handles_nan_and_none() -> None:
    assert _is_finite_number(float("nan")) is False
    assert _is_finite_number(float("inf")) is False
    assert _is_finite_number(float("-inf")) is False
    assert _is_finite_number(None) is False
    assert _is_finite_number("foo") is False
    assert _is_finite_number(0.0) is True
    assert _is_finite_number(28.5) is True
    assert _is_finite_number(0) is True


def test_extract_market_status_handles_partial_none() -> None:
    """MarketState 字段部分为 None 时,_extract_market_status 应安全兜底为默认值。"""
    # 模拟一个 adx 是 None 的对象 (用 SimpleNamespace 替代以避免 Pydantic 验证失败)
    from types import SimpleNamespace

    fake = SimpleNamespace(
        adx=None,
        atr_price_ratio=None,
        breadth_ratio=None,
        daily_return=None,
        limit_up_count=None,
        limit_down_count=None,
        northbound_flow_days=None,
        state_type=None,
        position_scale=None,
        regime_gate_level=None,
    )
    data = _extract_market_status(fake)
    # None 被 `or 0.0` 替换
    assert data["adx"] == 0.0
    assert data["atr_ratio"] == 0.0
    assert data["breadth_ratio"] == 0.5
    assert data["daily_return"] == 0.0
    assert data["limit_up"] == 0
    assert data["limit_down"] == 0
    assert data["northbound_days"] == 0
    assert data["state_type"] == "mixed"
    assert data["position_scale"] == 1.0
    assert data["regime_gate_level"] == "normal"


def test_state_type_cn_mapping() -> None:
    """_state_type_cn: 四个枚举值都有中文映射,未知值原样返回。"""
    assert _state_type_cn("trend") == "趋势型"
    assert _state_type_cn("range") == "震荡型"
    assert _state_type_cn("mixed") == "混合型"
    assert _state_type_cn("crisis") == "危机型"
    assert _state_type_cn("custom_unknown") == "custom_unknown"
    assert _state_type_cn("") == "—"


def test_format_market_status_table_includes_index_return() -> None:
    """当 daily_return 有限时, 表格应包含指数日收益行。"""
    state = _build_market_state(daily_return=0.012)  # +1.2%
    data = _extract_market_status(state)
    data["date"] = "20260607"
    output = _format_market_status_table(data)
    assert "指数日收益" in output
    assert "+1.20%" in output


# ============================================================================
# Helpers
# ============================================================================


def _extract_market_state_dict_from(state: MarketState) -> dict:
    """与 _extract_market_status 等价的本地包装 (避免 import 循环 / 重复样板)。"""
    return _extract_market_status(state)
