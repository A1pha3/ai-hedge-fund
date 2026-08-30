"""BTST court 公共常量与只读加载器 (研究命名空间, 零生产写入).

三轮对抗审查收敛后的研究管道基础设施:
- 事件宇宙来自按日全市场快照 (含后来退市者, 幸存者偏差在宇宙层解决),
  不再用 price_cache 文件名集合 (2025-09-15 抽查缺 52%).
- PIT 输入: ST 来自当日 limit_list_d 的 name 字段; 行业映射用申万成员史
  (in_date/out_date); regime 用 regime_history.
- 双锚点: 合约腿 open→open 为主, panel 口径 open→close 仅作对照.
- 预注册决策规则在 views 脚本内以常量固化, 先于数据写死.

写入边界: 本模块不写任何文件.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from src.tools.ashare_board_utils import limit_up_cap_pct_for_ticker

# ---- 研究命名空间 (绝不写 data/price_cache / fund_flow_cache / ledgers) ----
RESEARCH_DIR = Path("data/research/btst_court")
RAW_DIR = RESEARCH_DIR / "raw"
TABLE_DIR = RESEARCH_DIR / "event_tables"

# ---- 窗口 ----
# 面板从 2025-01 起: detect 最长回看 20 交易日 + streak metadata, 6 个月余量.
PANEL_START = "20250101"
# Window A: fund_flow_cache 全体最早 2025-07 (147/150 文件实测), 全保真重放下界.
WINDOW_A_START = "20250701"
# 前向路径上限: fixed 最长 T+10 + 停牌顺延余量.
FORWARD_SESSIONS = 15

# ---- 执行成本 (v2.1 口径): 单边滑点 + 卖出印花税 ----
SLIPPAGE_BPS = 30.0
SELL_STAMP_BPS = 5.0
SLIPPAGE_STRESS_BPS = 60.0  # 预注册压力档

# ---- 预注册主对照 (先于数据写死; 其余 horizon 一律 exploratory) ----
PRIMARY_HORIZON_PAIR = (8, 10)
EXPLORATORY_HORIZONS = (3, 5)

# ---- 宇宙完备性断言: 单日与 limit_list_d(U) 对账缺口超过此比例即中止 ----
UNIVERSE_GAP_ABORT_RATIO = 0.05

# ---- 生产语义常量 (与 src 同源, 此处仅作研究侧声明; 改生产须同步) ----
REGIME_GATE_BLOCK = frozenset({"crisis", "risk_off"})
MIN_ENTRY_PRICE = 3.0
MIN_TRIGGER_STRENGTH = 0.50

_TRADE_CAL_PATH = Path("data/reports/trade_calendar.json")
_REGIME_PATH = Path("data/reports/regime_history.json")


def load_sessions(start: str, end: str) -> list[str]:
    """本地权威交易日历 → [start, end] 内 YYYYMMDD 会话列表 (升序)."""
    if not _TRADE_CAL_PATH.exists():
        raise SystemExit(f"trade calendar missing: {_TRADE_CAL_PATH} (先跑 --auto)")
    payload = json.loads(_TRADE_CAL_PATH.read_text(encoding="utf-8"))
    sessions = sorted({str(d).replace("-", "")[:8] for d in payload})
    window = [s for s in sessions if start <= s <= end and s.isdigit()]
    if len(window) < 30:
        raise SystemExit(f"calendar coverage too short for {start}-{end}: {len(window)} sessions")
    return window


def load_regime_history() -> dict[str, str]:
    payload = json.loads(_REGIME_PATH.read_text(encoding="utf-8"))
    return {str(k).replace("-", "")[:8]: str(v) for k, v in payload.items()}


# ---- regime 输入指纹与漂移检测 (R73; 构建与消费面共用此单一实现) ----


def regime_window_labels(
    regime: dict[str, str], sessions: list[str]
) -> dict[str, str]:
    """构建窗内实际消费的 {session: label} (缺标签会话不出现 — 与构建器剔除语义一致)."""
    return {s: regime[s] for s in sessions if s in regime}


def regime_window_fingerprint(window: dict[str, str]) -> str:
    """canonical hash (排序键 JSON, 分隔符固定): 同窗同标签恒同指纹,
    任一标签修订即变 — manifest 钉住的是「本次构建消费了什么」。"""
    canonical = json.dumps(window, sort_keys=True, ensure_ascii=True,
                           separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def regime_drift_status(
    manifest: dict, regime_history: dict[str, str]
) -> dict:
    """manifest 钉住的 regime_window vs 当前 regime_history → 漂移判定.

    manifest 无 regime_window (旧构建) → checked=False (如实未知, 不假报漂移);
    任一会话标签修订或缺失 → drift=True 附逐会话 changed 清单.
    """
    window = manifest.get("regime_window")
    if not isinstance(window, dict) or not window:
        return {"checked": False, "drift": False, "changed_sessions": []}
    changed = []
    for session in sorted(window):
        pinned = window[session]
        current = regime_history.get(session)
        if current != pinned:
            changed.append({"session": session, "manifest": pinned,
                            "current": current})
    return {"checked": True, "drift": bool(changed), "changed_sessions": changed}


def load_manifest_mapping(path: Path) -> dict | None:
    """读 manifest JSON → dict; 缺失/损坏/非 dict 形状 → None.

    单一实现 (R73 Op3): freshness (降级披露) 与 bench (typed 拒绝) 共用读取
    与形状校验, 失败处置语义由调用方决定 — 读取本身绝不裸崩。
    """
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # ValueError 覆盖 JSONDecodeError
        return None
    return payload if isinstance(payload, dict) else None


def forward_open_returns(
    by_day: dict[str, pd.DataFrame],
    sessions_cal: list[str],
    ts_code: str,
    s: str,
    signal_close: float,
    symbol: str,
    horizons: tuple[int, ...] = (5, 8, 10),
) -> dict:
    """court 执行口径前向收益 (公共函数, 题材动量计划 Task 1 提升).

    语义与 review_cond2_fund_flow_gate._forward_returns 原实现逐字同源
    (该脚本已改 import 此处, 本地副本删除 — 禁止再复制粘贴):
      - T+1 open 买入; 一字锁死 (open ≥ 涨停价-0.001) = 不可成交;
      - T+k open 卖出, 缺 bar 顺延至 FORWARD_SESSIONS 窗口内下一可用开盘;
      - 返回 {fillable, t1_unbuyable, t1_missing_bar, gap_t1_open,
              gross_ret_t{k}...} — 不可成交时不带 gross_ret 键。
    horizons 可自定义 (研究侧灵活性), 默认 (5, 8, 10)。
    """
    fwd = [d for d in sessions_cal if d > s][:FORWARD_SESSIONS]
    bars = []
    for d in fwd:
        day = by_day.get(d)
        r = None
        if day is not None:
            m = day[day["ts_code"] == ts_code]
            if not m.empty:
                r = m.iloc[0]
        bars.append(
            (float(r["open"]), float(r["close"]), float(r["pre_close"])) if r is not None else (None, None, None)
        )
    t1_open = bars[0][0] if bars else None
    t1_unbuyable = False
    if t1_open is not None and bars[0][2] and bars[0][2] > 0:
        cap = limit_up_cap_pct_for_ticker(symbol)
        limit_price = round(bars[0][2] * (1 + cap / 100), 2)
        t1_unbuyable = t1_open >= limit_price - 0.001
    fillable = t1_open is not None and not t1_unbuyable
    out: dict = {
        "fillable": fillable,
        "t1_unbuyable": t1_unbuyable,
        "t1_missing_bar": t1_open is None,
        "gap_t1_open": (t1_open / signal_close - 1) if (t1_open and signal_close > 0) else None,
    }
    if not fillable:
        return out
    entry = t1_open

    def fixed_open(k: int):
        for j in range(k - 1, min(FORWARD_SESSIONS, len(bars))):
            if bars[j][0] is not None:
                return bars[j][0]
        return None

    for k in horizons:
        ex = fixed_open(k)
        out[f"gross_ret_t{k}"] = (ex / entry - 1) if ex else None
    return out
