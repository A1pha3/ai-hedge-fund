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

import json
from pathlib import Path

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
