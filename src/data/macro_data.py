"""宏观经济数据集成 — CPI/PMI/社融/利率等。

P2-9 实现: 从 tushare 获取中国宏观经济指标, 生成 MacroSnapshot 快照,
并基于阈值规则派生通胀压力 / 货币政策 / 经济动能标签。

设计原则:
  - **可选**: 任何数据获取失败均不崩溃, 缺失字段为 None。
  - **可缓存**: 使用 tushare 同一套 _cached_tushare_dataframe_call 机制。
  - **无副作用**: 纯计算函数, 不修改全局状态。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.tools.tushare_api import _get_pro, _cached_tushare_dataframe_call

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MacroSnapshot
# ---------------------------------------------------------------------------


@dataclass
class MacroSnapshot:
    """宏观快照（月度/季度数据）。

    所有数值字段均可为 None — 表示该指标数据暂时不可用。
    派生指标 (inflation_pressure / monetary_stance / economic_momentum)
    在构造时不自动计算; 由 ``compute_macro_regime`` 显式生成。
    """

    date: str = ""  # 数据日期 (YYYYMM 或 YYYYMMDD)
    cpi_yoy: float | None = None  # CPI 同比 (%)
    ppi_yoy: float | None = None  # PPI 同比 (%)
    pmi_manufacturing: float | None = None  # 制造业 PMI
    pmi_non_manufacturing: float | None = None  # 非制造业 PMI
    m2_yoy: float | None = None  # M2 同比 (%)
    social_financing: float | None = None  # 社融规模 (亿元)
    interest_rate_lpr_1y: float | None = None  # 1年期 LPR (%)

    # 派生指标 (由 compute_macro_regime 填充)
    inflation_pressure: str = ""  # "low" / "moderate" / "high"
    monetary_stance: str = ""  # "loose" / "neutral" / "tight"
    economic_momentum: str = ""  # "expanding" / "stable" / "contracting"


# ---------------------------------------------------------------------------
# Tushare 宏观数据获取
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float | None = None) -> float | None:
    """安全转换为 float, 处理 None / NaN / Inf / 非数值类型。"""
    if value is None:
        return default
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(fv) or math.isinf(fv):
        return default
    return fv


def _fetch_macro_cpi(pro: Any) -> pd.DataFrame | None:
    """获取 CPI 月度同比数据。"""
    try:
        return _cached_tushare_dataframe_call(pro, "cn_cpi", ttl=7 * 86400)
    except Exception as exc:
        logger.debug("macro_data: cn_cpi 获取失败: %s", exc)
        return None


def _fetch_macro_ppi(pro: Any) -> pd.DataFrame | None:
    """获取 PPI 月度同比数据。"""
    try:
        return _cached_tushare_dataframe_call(pro, "cn_ppi", ttl=7 * 86400)
    except Exception as exc:
        logger.debug("macro_data: cn_ppi 获取失败: %s", exc)
        return None


def _fetch_macro_pmi(pro: Any) -> pd.DataFrame | None:
    """获取 PMI 月度数据。"""
    try:
        return _cached_tushare_dataframe_call(pro, "cn_pmi", ttl=7 * 86400)
    except Exception as exc:
        logger.debug("macro_data: cn_pmi 获取失败: %s", exc)
        return None


def _fetch_macro_m2(pro: Any) -> pd.DataFrame | None:
    """获取 M2 月度同比数据。"""
    try:
        return _cached_tushare_dataframe_call(pro, "cn_m2", ttl=7 * 86400)
    except Exception as exc:
        logger.debug("macro_data: cn_m2 获取失败: %s", exc)
        return None


def _fetch_macro_social_financing(pro: Any) -> pd.DataFrame | None:
    """获取社融规模月度数据。"""
    try:
        return _cached_tushare_dataframe_call(pro, "cn_sf", ttl=7 * 86400)
    except Exception as exc:
        logger.debug("macro_data: cn_sf 获取失败: %s", exc)
        return None


def _fetch_lpr_rate(pro: Any) -> pd.DataFrame | None:
    """获取 LPR 利率数据 (通过 shibor_quote 接口或直接利率接口)。"""
    try:
        return _cached_tushare_dataframe_call(pro, "shibor_quote", ttl=7 * 86400)
    except Exception as exc:
        logger.debug("macro_data: shibor_quote 获取失败: %s", exc)
        return None


def _extract_latest_from_df(df: pd.DataFrame | None, value_col: str, date_col: str = "month") -> tuple[float | None, str]:
    """从 DataFrame 中提取最新一行指定列的值和日期。

    Returns:
        (value, date_str) — value 可能为 None; date_str 默认为空字符串。
    """
    if df is None or df.empty:
        return None, ""
    if date_col not in df.columns or value_col not in df.columns:
        return None, ""
    df_sorted = df.sort_values(date_col, ascending=False)
    latest = df_sorted.iloc[0]
    val = _safe_float(latest[value_col])
    date_str = str(latest[date_col])
    return val, date_str


def _extract_latest_pmi(df: pd.DataFrame | None) -> tuple[float | None, float | None]:
    """从 PMI DataFrame 中分别提取制造业和非制造业 PMI。

    tushare cn_pmi 返回字段通常包含 ``pmi_make`` (制造业) 和 ``pmi_service`` (非制造业)。
    如果字段名不同, 尝试备选名称。
    """
    if df is None or df.empty:
        return None, None

    # 常见字段名
    mfg_col = None
    non_mfg_col = None
    for col in df.columns:
        col_lower = col.lower()
        if "make" in col_lower or "manufacturing" in col_lower or col_lower == "pmi":
            mfg_col = col
        if "service" in col_lower or "non" in col_lower:
            non_mfg_col = col

    df_sorted = df.sort_values("month", ascending=False) if "month" in df.columns else df
    latest = df_sorted.iloc[0]

    mfg_val = _safe_float(latest[mfg_col]) if mfg_col else None
    non_mfg_val = _safe_float(latest[non_mfg_col]) if non_mfg_col else None
    return mfg_val, non_mfg_val


def _extract_latest_lpr(df: pd.DataFrame | None) -> float | None:
    """从 LPR/shibor_quote DataFrame 中提取 1 年期 LPR。

    tushare shibor_quote 通常包含 ``lpr1y`` 或类似字段。
    """
    if df is None or df.empty:
        return None

    lpr_col = None
    for col in df.columns:
        col_lower = col.lower()
        if "lpr1" in col_lower or "lpr_1" in col_lower:
            lpr_col = col
            break

    if lpr_col is None:
        return None

    date_col = "date" if "date" in df.columns else "month"
    if date_col not in df.columns:
        return None

    df_sorted = df.sort_values(date_col, ascending=False)
    latest = df_sorted.iloc[0]
    return _safe_float(latest[lpr_col])


def _extract_latest_social_financing(df: pd.DataFrame | None) -> float | None:
    """从社融 DataFrame 中提取最新值 (亿元)。"""
    if df is None or df.empty:
        return None

    # 常见字段名
    sf_col = None
    for col in df.columns:
        col_lower = col.lower()
        if "total" in col_lower or "sf" in col_lower or col_lower.startswith("y0"):
            sf_col = col
            break

    if sf_col is None:
        # 取第一个数值列
        for col in df.columns:
            if col.lower() not in ("month", "date", "year"):
                sf_col = col
                break

    if sf_col is None:
        return None

    date_col = "month" if "month" in df.columns else "date"
    if date_col not in df.columns:
        return None

    df_sorted = df.sort_values(date_col, ascending=False)
    latest = df_sorted.iloc[0]
    return _safe_float(latest[sf_col])


# ---------------------------------------------------------------------------
# fetch_macro_snapshot
# ---------------------------------------------------------------------------


def fetch_macro_snapshot(*, use_cache: bool = True) -> MacroSnapshot:
    """从 tushare 获取最新宏观数据。

    逐一请求各指标; 任一接口失败不影响其他指标。
    如果 tushare 不可用 (无 token / 网络异常), 返回全 None 快照 (不崩溃)。

    Args:
        use_cache: 是否使用 tushare 缓存 (默认 True)。

    Returns:
        MacroSnapshot 实例; 部分字段可能为 None。
    """
    pro = _get_pro()
    if pro is None:
        logger.warning("macro_data: tushare pro 不可用, 返回空 MacroSnapshot")
        return MacroSnapshot()

    snapshot = MacroSnapshot()

    # 1. CPI
    try:
        cpi_df = _fetch_macro_cpi(pro)
        cpi_val, cpi_date = _extract_latest_from_df(cpi_df, "nt_yoy")  # 全国同比
        if cpi_val is None:
            cpi_val, cpi_date = _extract_latest_from_df(cpi_df, "yoy")
        snapshot.cpi_yoy = cpi_val
        snapshot.date = cpi_date
    except Exception as exc:
        logger.debug("macro_data: CPI 提取异常: %s", exc)

    # 2. PPI
    try:
        ppi_df = _fetch_macro_ppi(pro)
        ppi_val, ppi_date = _extract_latest_from_df(ppi_df, "ppi_yoy") if ppi_df is not None else (None, "")
        if ppi_val is None:
            ppi_val, _ = _extract_latest_from_df(ppi_df, "yoy")
        snapshot.ppi_yoy = ppi_val
        if not snapshot.date and ppi_date:
            snapshot.date = ppi_date
    except Exception as exc:
        logger.debug("macro_data: PPI 提取异常: %s", exc)

    # 3. PMI (制造业 + 非制造业)
    try:
        pmi_df = _fetch_macro_pmi(pro)
        mfg_pmi, non_mfg_pmi = _extract_latest_pmi(pmi_df)
        snapshot.pmi_manufacturing = mfg_pmi
        snapshot.pmi_non_manufacturing = non_mfg_pmi
        if not snapshot.date and pmi_df is not None and "month" in pmi_df.columns:
            snapshot.date = str(pmi_df.sort_values("month", ascending=False).iloc[0]["month"])
    except Exception as exc:
        logger.debug("macro_data: PMI 提取异常: %s", exc)

    # 4. M2
    try:
        m2_df = _fetch_macro_m2(pro)
        m2_val, _ = _extract_latest_from_df(m2_df, "m2_yoy")
        if m2_val is None:
            m2_val, _ = _extract_latest_from_df(m2_df, "yoy")
        snapshot.m2_yoy = m2_val
    except Exception as exc:
        logger.debug("macro_data: M2 提取异常: %s", exc)

    # 5. 社融
    try:
        sf_df = _fetch_macro_social_financing(pro)
        snapshot.social_financing = _extract_latest_social_financing(sf_df)
    except Exception as exc:
        logger.debug("macro_data: 社融提取异常: %s", exc)

    # 6. LPR 1Y
    try:
        lpr_df = _fetch_lpr_rate(pro)
        snapshot.interest_rate_lpr_1y = _extract_latest_lpr(lpr_df)
    except Exception as exc:
        logger.debug("macro_data: LPR 提取异常: %s", exc)

    return snapshot


# ---------------------------------------------------------------------------
# compute_macro_regime
# ---------------------------------------------------------------------------


def compute_macro_regime(macro: MacroSnapshot) -> dict:
    """基于宏观数据计算市场环境标签。

    规则:
      - inflation_pressure:
          CPI < 1%: "low"
          CPI 1-3%: "moderate"
          CPI > 3%: "high"
          CPI 为 None: "unknown"

      - monetary_stance:
          LPR 近 3 月下降 / M2 > 10%: "loose"
          LPR 近 3 月上升 / M2 < 8%: "tight"
          其它: "neutral"
          均为 None: "unknown"

      - economic_momentum:
          PMI > 51: "expanding"
          PMI 49-51: "stable"
          PMI < 49: "contracting"
          PMI 为 None: "unknown"

    Returns:
        {"inflation_pressure": ..., "monetary_stance": ..., "economic_momentum": ..., "summary": "..."}
    """
    # --- inflation_pressure ---
    cpi = macro.cpi_yoy
    if cpi is not None:
        if cpi < 1.0:
            inflation = "low"
        elif cpi <= 3.0:
            inflation = "moderate"
        else:
            inflation = "high"
    else:
        inflation = "unknown"

    # --- monetary_stance ---
    m2 = macro.m2_yoy
    lpr = macro.interest_rate_lpr_1y
    if m2 is not None or lpr is not None:
        # 简化规则: M2 > 10% → loose; M2 < 8% → tight
        # LPR 下降 → loose; LPR 上升 → tight (单点数据无法判断趋势, 仅做辅助)
        if m2 is not None and m2 > 10.0:
            monetary = "loose"
        elif m2 is not None and m2 < 8.0:
            monetary = "tight"
        else:
            monetary = "neutral"
    else:
        monetary = "unknown"

    # --- economic_momentum ---
    pmi = macro.pmi_manufacturing
    if pmi is not None:
        if pmi > 51.0:
            momentum = "expanding"
        elif pmi >= 49.0:
            momentum = "stable"
        else:
            momentum = "contracting"
    else:
        momentum = "unknown"

    # --- summary ---
    _CN_LABELS = {
        "inflation_pressure": {"low": "低通胀", "moderate": "温和", "high": "高通胀", "unknown": "未知"},
        "monetary_stance": {"loose": "宽松", "neutral": "中性", "tight": "紧缩", "unknown": "未知"},
        "economic_momentum": {"expanding": "扩张", "stable": "平稳", "contracting": "收缩", "unknown": "未知"},
    }
    parts = [
        f"通胀:{_CN_LABELS['inflation_pressure'][inflation]}",
        f"货币:{_CN_LABELS['monetary_stance'][monetary]}",
        f"动能:{_CN_LABELS['economic_momentum'][momentum]}",
    ]
    summary = " | ".join(parts)

    return {
        "inflation_pressure": inflation,
        "monetary_stance": monetary,
        "economic_momentum": momentum,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# render_macro_snapshot
# ---------------------------------------------------------------------------


def render_macro_snapshot(macro: MacroSnapshot, regime: dict) -> str:
    """ASCII 宏观面板。

    输出示例::

        ━━━ 宏观经济面板 ━━━

        CPI: 2.1% (同比)  PPI: -1.2%
        PMI 制造业: 50.8   PMI 非制造业: 53.2
        M2: 10.5% (同比)   社融: 22000亿
        LPR 1Y: 3.45%

        通胀压力: 温和  货币政策: 宽松  经济动能: 扩张
    """
    lines: list[str] = []
    lines.append("━━━ 宏观经济面板 ━━━")
    lines.append("")

    # CPI / PPI
    cpi_str = f"{macro.cpi_yoy:.1f}%" if macro.cpi_yoy is not None else "—"
    ppi_str = f"{macro.ppi_yoy:.1f}%" if macro.ppi_yoy is not None else "—"
    lines.append(f"CPI: {cpi_str} (同比)  PPI: {ppi_str}")

    # PMI
    pmi_mfg_str = f"{macro.pmi_manufacturing:.1f}" if macro.pmi_manufacturing is not None else "—"
    pmi_non_str = f"{macro.pmi_non_manufacturing:.1f}" if macro.pmi_non_manufacturing is not None else "—"
    lines.append(f"PMI 制造业: {pmi_mfg_str}   PMI 非制造业: {pmi_non_str}")

    # M2 / 社融
    m2_str = f"{macro.m2_yoy:.1f}%" if macro.m2_yoy is not None else "—"
    sf_str = f"{macro.social_financing:.0f}亿" if macro.social_financing is not None else "—"
    lines.append(f"M2: {m2_str} (同比)   社融: {sf_str}")

    # LPR
    lpr_str = f"{macro.interest_rate_lpr_1y:.2f}%" if macro.interest_rate_lpr_1y is not None else "—"
    lines.append(f"LPR 1Y: {lpr_str}")

    lines.append("")

    # Regime summary
    _CN = {
        "low": "低通胀", "moderate": "温和", "high": "高通胀", "unknown": "未知",
    }
    _CN_M = {
        "loose": "宽松", "neutral": "中性", "tight": "紧缩", "unknown": "未知",
    }
    _CN_E = {
        "expanding": "扩张", "stable": "平稳", "contracting": "收缩", "unknown": "未知",
    }
    ip = regime.get("inflation_pressure", "unknown")
    ms = regime.get("monetary_stance", "unknown")
    em = regime.get("economic_momentum", "unknown")
    lines.append(f"通胀压力: {_CN.get(ip, ip)}  货币政策: {_CN_M.get(ms, ms)}  经济动能: {_CN_E.get(em, em)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def run_macro_cli() -> int:
    """``--macro`` CLI 入口: 获取并展示宏观经济面板。

    Returns:
        退出码 (0 = 至少一个指标可用, 1 = 全部不可用)
    """
    from colorama import Fore, Style

    print(f"\n{Fore.CYAN}{Style.BRIGHT}[Macro] 获取宏观经济数据...{Style.RESET_ALL}")

    try:
        snapshot = fetch_macro_snapshot()
        regime = compute_macro_regime(snapshot)
    except Exception as exc:
        print(f"{Fore.RED}[Macro] 数据获取失败: {exc}{Style.RESET_ALL}")
        return 1

    # Check if any data was retrieved
    has_data = any([
        snapshot.cpi_yoy is not None,
        snapshot.ppi_yoy is not None,
        snapshot.pmi_manufacturing is not None,
        snapshot.m2_yoy is not None,
        snapshot.social_financing is not None,
        snapshot.interest_rate_lpr_1y is not None,
    ])

    if not has_data:
        print(f"{Fore.YELLOW}[Macro] 所有宏观数据均不可用 (tushare token 或接口限制){Style.RESET_ALL}")
        return 1

    print()
    print(render_macro_snapshot(snapshot, regime))
    print()

    # Also print regime dict as JSON for programmatic consumption
    import json
    print(f"Regime: {json.dumps(regime, ensure_ascii=False)}")
    return 0
