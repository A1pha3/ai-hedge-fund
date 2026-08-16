"""除权免疫 shadow exit 与未实现盈亏回归测试 (autodev 2026-08-16 delivery).

price_cache 存不复权原始价: 持有窗口跨除权日时, shadow exit 重放消费的
raw close 会把分红/送转的机械跳降读成

- 跌破移动止盈线 (虚假 ``close_below_trailing_line`` 退出信号),
- 激活阈值 ``close >= entry * 1.10`` 被缺口永久压制 (永不 armed),
- ATR 的 True Range 在缺口日 spike (Wilder RMA 被污染数周)。

修复后 ``_evaluate_shadow_path`` 把重放消费的 high/low/close 复权到 entry 日
close 口径 (AGENTS.md 陷阱 15 第三轮收口): pct_change 列缺失/非有限时诚实
回退原始口径; 窗口内 pct_change 与 close 比值一致 (±0.5% 容差) 时原样返回
(无缺口, 与旧口径逐位一致)。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action_service import DailyActionService
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository


def _sessions() -> tuple[date, ...]:
    start = date(2026, 6, 22)
    return tuple(start + timedelta(days=offset) for offset in range(40))


def _gap_frame(*, split_ratio: float = 0.5) -> pd.DataFrame:
    """40 个 session 的含除权缺口 frame (10送10 型, raw 腰斩).

    真实调整后序列 adj 从 10.0 温和上涨, 第 24 行 (sessions[24]) 除权:
    raw[t] = adj[t] * split_ratio (t >= 24)。pct_change 记录真实涨幅
    (除权基准), 与 raw 比值在缺口行显著不一致 (>0.5%)。
    """
    sessions = _sessions()
    adj_closes = []
    value = 10.0
    for i in range(len(sessions)):
        if i == 0:
            adj_closes.append(10.0)
            continue
        if i <= 22:
            step = 0.45  # 温和上涨, sessions[22] adj≈13.6 (+36% > 激活阈值)
        else:
            step = 0.10  # 除权前后继续小涨
        value = value + step
        adj_closes.append(round(value, 4))
    rows = []
    for i, session in enumerate(sessions):
        adj = adj_closes[i]
        raw = adj if i < 24 else adj * split_ratio
        prev_adj = adj_closes[i - 1] if i > 0 else None
        pct = None if prev_adj is None else round((adj / prev_adj - 1.0) * 100.0, 4)
        rows.append(
            {
                "date": session,
                "high": round(raw + 0.15, 4),
                "low": round(max(raw - 0.15, 0.01), 4),
                "close": round(raw, 4),
                "pct_change": pct,
            }
        )
    return pd.DataFrame(rows)


def _late_activation_gap_frame() -> pd.DataFrame:
    """除权先于激活: entry 日 adj 10.0, 次日 10送10 (raw 腰斩 5.02),
    此后 adj 缓涨在 sessions[25] 越过 11.0 (entry*1.10) — raw 口径下
    close 永远 ≈5.6 回不到 11.0, 复权口径 adj 11.2 正常激活。"""
    sessions = _sessions()
    adj = [10.0] * 21  # i=0..20 flat (含 entry 日)
    value = 10.05  # sessions[21] 除权日, 真实 +0.5%
    adj.append(value)
    for _i in range(22, len(sessions)):
        value = round(value + 0.23, 4)
        adj.append(value)
    rows = []
    for i, session in enumerate(sessions):
        raw = adj[i] if i <= 20 else adj[i] * 0.5  # sessions[21] 起 raw 已除权
        pct = None if i == 0 else round((adj[i] / adj[i - 1] - 1.0) * 100.0, 4)
        rows.append(
            {
                "date": session,
                "high": round(raw + 0.15, 4),
                "low": round(max(raw - 0.15, 0.01), 4),
                "close": round(raw, 4),
                "pct_change": pct,
            }
        )
    return pd.DataFrame(rows)


def _service_with_history(tmp_path, frame):
    sessions = _sessions()
    entry_date = sessions[20]
    as_of = sessions[26]
    costs = ExecutionCosts(version="test", commission=5.0, other_fee=10.0)
    repository = LedgerRepository(
        tmp_path / "ledger.sqlite3", "shadow", 100_000, execution_costs=costs
    )
    repository.initialize()
    plan = repository.create_plan(
        "000777",
        "btst_breakout",
        "v2",
        sessions[19],
        entry_date,
        0.10,
        1,
    )
    repository.settle_plan_at_open(
        plan.trade_id, entry_date, 10.0, 9.0, 11.0, False, 10.2, 9.8
    )
    service = DailyActionService(
        repository,
        TradingSessionCalendar(sessions),
        lambda _symbol, _session: None,
        costs,
        enforce_manifest_gate=False,
        shadow_history=lambda _ticker: frame,
    )
    return service, as_of


def _position(service, as_of):
    return service.run(as_of, candidates=()).open_positions[0]


class TestShadowExitCorpActionImmunity:
    def test_armed_gap_does_not_fire_false_trailing_exit(self, tmp_path):
        """armed 后 10送10 除权: 真实涨幅为正, 不得触发虚假退出信号."""
        service, as_of = _service_with_history(tmp_path, _gap_frame())

        position = _position(service, as_of)

        assert position.shadow_would_exit_next_open is False
        assert position.shadow_reason != "close_below_trailing_line"

    def test_gap_does_not_permanently_suppress_activation(self, tmp_path):
        """涨幅已达激活阈值但除权腰斩 raw 价: 复权口径必须仍能 armed.

        构造: 除权发生在涨幅越过 entry*1.10 之前 — raw 口径下 close 永远
        回不到 11.0 (腰斩后 raw≈5.6), 复权口径 adj≈11.2 持续满足激活。
        """
        frame = _late_activation_gap_frame()
        service, as_of = _service_with_history(tmp_path, frame)

        position = _position(service, as_of)

        assert position.shadow_exit_line is not None

    def test_no_gap_frame_is_bitwise_identical_with_and_without_pct(self, tmp_path):
        """pct_change 与 close 一致 (无缺口) 时, 带/不带 pct 列的重放逐位一致."""
        frame = _gap_frame(split_ratio=1.0)  # 无缺口: raw == adj
        # 重算 pct_change 为 raw 比值精确值 (与 close 完全一致)
        frame["pct_change"] = frame["close"].pct_change() * 100.0

        service_a, as_of = _service_with_history(tmp_path / "a", frame)
        service_b, as_of_b = _service_with_history(
            tmp_path / "b", frame.drop(columns=["pct_change"])
        )

        pos_a = _position(service_a, as_of)
        pos_b = _position(service_b, as_of_b)

        fields_a = (pos_a.shadow_exit_line, pos_a.shadow_would_exit_next_open, pos_a.shadow_reason)
        fields_b = (pos_b.shadow_exit_line, pos_b.shadow_would_exit_next_open, pos_b.shadow_reason)
        assert fields_a == fields_b

    def test_missing_pct_change_falls_back_to_raw_semantics(self, tmp_path):
        """pct_change 列缺失 (MarketBar 测试路径): 保持旧口径, 缺口虚假退出仍在.

        这是诚实回退: 无 pct_change 时无法还原真实涨幅, 行为与修复前逐位一致。
        """
        frame = _gap_frame().drop(columns=["pct_change"])
        service, as_of = _service_with_history(tmp_path, frame)

        position = _position(service, as_of)

        # 旧行为: raw 腰斩被读成跌破止盈线 — 回退路径必须保持该语义
        assert position.shadow_would_exit_next_open is True
        assert position.shadow_reason == "close_below_trailing_line"
