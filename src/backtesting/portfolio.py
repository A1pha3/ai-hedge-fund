from __future__ import annotations

from types import MappingProxyType
from typing import Dict, Mapping

from .types import PortfolioSnapshot, PositionState, TickerRealizedGains


class Portfolio:
    """Portfolio state management for backtesting operations.

    Encapsulates cash, positions, and margin tracking.
    Supports both long and short positions with proper cost basis tracking
    and realized gains/losses calculation.
    """

    def __init__(
        self,
        *,
        tickers: list[str],
        initial_cash: float,
        margin_requirement: float,
    ) -> None:
        self._portfolio: PortfolioSnapshot = {
            "cash": float(initial_cash),
            "margin_used": 0.0,
            "margin_requirement": float(margin_requirement),
            "positions": {
                ticker: {
                    "long": 0,
                    "short": 0,
                    "long_cost_basis": 0.0,
                    "short_cost_basis": 0.0,
                    "short_margin_used": 0.0,
                    "entry_date": "",
                    "holding_days": 0,
                    "max_unrealized_pnl_pct": 0.0,
                    "profit_take_stage": 0,
                    "entry_score": 0.0,
                    "is_fundamental_driven": False,
                    "industry_sw": "",
                }
                for ticker in tickers
            },
            "realized_gains": {ticker: {"long": 0.0, "short": 0.0} for ticker in tickers},
        }

    def get_snapshot(self) -> PortfolioSnapshot:
        positions_copy: Dict[str, PositionState] = {
            t: {
                "long": p["long"],
                "short": p["short"],
                "long_cost_basis": p["long_cost_basis"],
                "short_cost_basis": p["short_cost_basis"],
                "short_margin_used": p["short_margin_used"],
                "entry_date": str(p.get("entry_date", "")),
                "last_trade_date": str(p.get("last_trade_date", "")),
                "holding_days": int(p.get("holding_days", 0)),
                "max_unrealized_pnl_pct": float(p.get("max_unrealized_pnl_pct", 0.0)),
                "profit_take_stage": int(p.get("profit_take_stage", 0)),
                "entry_score": float(p.get("entry_score", 0.0)),
                "is_fundamental_driven": bool(p.get("is_fundamental_driven", False)),
                "industry_sw": str(p.get("industry_sw", "")),
            }
            for t, p in self._portfolio["positions"].items()
        }
        gains_copy: Dict[str, TickerRealizedGains] = {t: {"long": g["long"], "short": g["short"]} for t, g in self._portfolio["realized_gains"].items()}
        return {
            "cash": float(self._portfolio["cash"]),
            "margin_used": float(self._portfolio["margin_used"]),
            "margin_requirement": float(self._portfolio["margin_requirement"]),
            "positions": positions_copy,
            "realized_gains": gains_copy,
        }

    def load_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        self._portfolio = {
            "cash": float(snapshot["cash"]),
            "margin_used": float(snapshot["margin_used"]),
            "margin_requirement": float(snapshot["margin_requirement"]),
            "positions": {
                ticker: {
                    "long": int(position["long"]),
                    "short": int(position["short"]),
                    "long_cost_basis": float(position["long_cost_basis"]),
                    "short_cost_basis": float(position["short_cost_basis"]),
                    "short_margin_used": float(position["short_margin_used"]),
                    "entry_date": str(position.get("entry_date", "")),
                    "last_trade_date": str(position.get("last_trade_date", "")),
                    "holding_days": int(position.get("holding_days", 0)),
                    "max_unrealized_pnl_pct": float(position.get("max_unrealized_pnl_pct", 0.0)),
                    "profit_take_stage": int(position.get("profit_take_stage", 0)),
                    "entry_score": float(position.get("entry_score", 0.0)),
                    "is_fundamental_driven": bool(position.get("is_fundamental_driven", False)),
                    "industry_sw": str(position.get("industry_sw", "")),
                }
                for ticker, position in snapshot["positions"].items()
            },
            "realized_gains": {
                ticker: {"long": float(gains["long"]), "short": float(gains["short"])} for ticker, gains in snapshot["realized_gains"].items()
            },
        }

    def get_cash(self) -> float:
        return float(self._portfolio["cash"])

    def get_margin_used(self) -> float:
        return float(self._portfolio["margin_used"])

    def get_margin_requirement(self) -> float:
        return float(self._portfolio["margin_requirement"])

    def get_positions(self) -> Mapping[str, PositionState]:
        return MappingProxyType(self._portfolio["positions"])  # type: ignore[arg-type]

    def get_realized_gains(self) -> Mapping[str, TickerRealizedGains]:
        return MappingProxyType(self._portfolio["realized_gains"])  # type: ignore[arg-type]

    def ensure_ticker(self, ticker: str) -> None:
        if ticker in self._portfolio["positions"]:
            return
        self._portfolio["positions"][ticker] = {
            "long": 0,
            "short": 0,
            "long_cost_basis": 0.0,
            "short_cost_basis": 0.0,
            "short_margin_used": 0.0,
            "entry_date": "",
            "last_trade_date": "",
            "holding_days": 0,
            "max_unrealized_pnl_pct": 0.0,
            "profit_take_stage": 0,
            "entry_score": 0.0,
            "is_fundamental_driven": False,
            "industry_sw": "",
        }
        self._portfolio["realized_gains"][ticker] = {"long": 0.0, "short": 0.0}

    def record_long_entry(
        self,
        ticker: str,
        trade_date: str,
        *,
        reset: bool,
        entry_score: float = 0.0,
        is_fundamental_driven: bool = False,
        industry_sw: str = "",
    ) -> None:
        self.ensure_ticker(ticker)
        position = self._portfolio["positions"][ticker]
        if reset:
            position["entry_date"] = trade_date
            position["last_trade_date"] = trade_date
            position["holding_days"] = 0
            position["max_unrealized_pnl_pct"] = 0.0
            position["profit_take_stage"] = 0
            position["entry_score"] = float(entry_score)
            position["is_fundamental_driven"] = bool(is_fundamental_driven)
            position["industry_sw"] = industry_sw

    def record_long_exit(self, ticker: str, trigger_reason: str = "") -> None:
        self.ensure_ticker(ticker)
        position = self._portfolio["positions"][ticker]
        if position["long"] <= 0:
            position["entry_date"] = ""
            position["last_trade_date"] = ""
            position["holding_days"] = 0
            position["max_unrealized_pnl_pct"] = 0.0
            position["profit_take_stage"] = 0
            position["entry_score"] = 0.0
            position["is_fundamental_driven"] = False
            position["industry_sw"] = ""
            return
        if trigger_reason == "profit_take_stage_1":
            position["profit_take_stage"] = max(int(position.get("profit_take_stage", 0)), 1)
        elif trigger_reason == "profit_take_stage_2":
            position["profit_take_stage"] = max(int(position.get("profit_take_stage", 0)), 2)

    def refresh_position_lifecycle(self, current_prices: Mapping[str, float], trade_date: str) -> None:
        for ticker, position in self._portfolio["positions"].items():
            if position["long"] <= 0:
                continue
            entry_date = str(position.get("entry_date") or "")
            if not entry_date:
                entry_date = trade_date
                position["entry_date"] = trade_date
            current_price = float(current_prices.get(ticker, 0.0))
            cost_basis = float(position.get("long_cost_basis", 0.0))
            if current_price > 0 and cost_basis > 0:
                pnl_pct = (current_price - cost_basis) / cost_basis
                position["max_unrealized_pnl_pct"] = max(float(position.get("max_unrealized_pnl_pct", 0.0)), pnl_pct)
            last_trade_date = str(position.get("last_trade_date") or "")
            if not last_trade_date:
                if trade_date > entry_date:
                    position["holding_days"] = max(0, int(position.get("holding_days", 0))) + 1
                position["last_trade_date"] = trade_date
                continue
            if trade_date > last_trade_date:
                if trade_date > entry_date:
                    position["holding_days"] = max(0, int(position.get("holding_days", 0))) + 1
                position["last_trade_date"] = trade_date

    def adjust_cash(self, delta: float) -> None:
        self._portfolio["cash"] += float(delta)

    def apply_long_buy(self, ticker: str, quantity: int, price: float) -> int:
        if quantity <= 0:
            return 0
        quantity = int(quantity)
        position = self._portfolio["positions"][ticker]
        cost = quantity * price
        if cost <= self._portfolio["cash"]:
            old_shares = position["long"]
            old_cost_basis = position["long_cost_basis"]
            total_shares = old_shares + quantity
            if total_shares > 0:
                total_old_cost = old_cost_basis * old_shares
                total_new_cost = cost
                position["long_cost_basis"] = (total_old_cost + total_new_cost) / total_shares
            position["long"] = old_shares + quantity
            self._portfolio["cash"] -= cost
            return quantity
        max_quantity = int(self._portfolio["cash"] / price) if price > 0 else 0
        if max_quantity > 0:
            cost = max_quantity * price
            old_shares = position["long"]
            old_cost_basis = position["long_cost_basis"]
            total_shares = old_shares + max_quantity
            if total_shares > 0:
                total_old_cost = old_cost_basis * old_shares
                total_new_cost = cost
                position["long_cost_basis"] = (total_old_cost + total_new_cost) / total_shares
            position["long"] = old_shares + max_quantity
            self._portfolio["cash"] -= cost
            return max_quantity
        return 0

    def apply_long_sell(self, ticker: str, quantity: int, price: float) -> int:
        position = self._portfolio["positions"][ticker]
        quantity = min(int(quantity), position["long"]) if quantity > 0 else 0
        if quantity <= 0:
            return 0
        avg_cost = position["long_cost_basis"] if position["long"] > 0 else 0.0
        realized_gain = (price - avg_cost) * quantity
        self._portfolio["realized_gains"][ticker]["long"] += realized_gain
        position["long"] -= quantity
        self._portfolio["cash"] += quantity * price
        if position["long"] == 0:
            position["long_cost_basis"] = 0.0
        return quantity

    def apply_short_open(self, ticker: str, quantity: int, price: float) -> int:
        if quantity <= 0:
            return 0
        quantity = int(quantity)
        position = self._portfolio["positions"][ticker]
        proceeds = price * quantity
        margin_ratio = self._portfolio["margin_requirement"]
        margin_required = proceeds * margin_ratio
        if margin_required <= self._portfolio["cash"]:
            old_short_shares = position["short"]
            old_cost_basis = position["short_cost_basis"]
            total_shares = old_short_shares + quantity
            if total_shares > 0:
                total_old_cost = old_cost_basis * old_short_shares
                total_new_cost = price * quantity
                position["short_cost_basis"] = (total_old_cost + total_new_cost) / total_shares
            position["short"] = old_short_shares + quantity
            position["short_margin_used"] += margin_required
            self._portfolio["margin_used"] += margin_required
            self._portfolio["cash"] += proceeds
            self._portfolio["cash"] -= margin_required
            return quantity
        max_quantity = int(self._portfolio["cash"] / (price * margin_ratio)) if margin_ratio > 0 and price > 0 else 0
        if max_quantity > 0:
            proceeds = price * max_quantity
            margin_required = proceeds * margin_ratio
            old_short_shares = position["short"]
            old_cost_basis = position["short_cost_basis"]
            total_shares = old_short_shares + max_quantity
            if total_shares > 0:
                total_old_cost = old_cost_basis * old_short_shares
                total_new_cost = price * max_quantity
                position["short_cost_basis"] = (total_old_cost + total_new_cost) / total_shares
            position["short"] = old_short_shares + max_quantity
            position["short_margin_used"] += margin_required
            self._portfolio["margin_used"] += margin_required
            self._portfolio["cash"] += proceeds
            self._portfolio["cash"] -= margin_required
            return max_quantity
        return 0

    def apply_short_cover(self, ticker: str, quantity: int, price: float) -> int:
        position = self._portfolio["positions"][ticker]
        quantity = min(int(quantity), position["short"]) if quantity > 0 else 0
        if quantity <= 0:
            return 0
        cover_cost = quantity * price
        avg_short_price = position["short_cost_basis"] if position["short"] > 0 else 0.0
        realized_gain = (avg_short_price - price) * quantity
        if position["short"] > 0:
            portion = quantity / position["short"]
        else:
            portion = 1.0
        margin_to_release = portion * position["short_margin_used"]
        position["short"] -= quantity
        position["short_margin_used"] -= margin_to_release
        self._portfolio["margin_used"] -= margin_to_release
        self._portfolio["cash"] += margin_to_release
        self._portfolio["cash"] -= cover_cost
        self._portfolio["realized_gains"][ticker]["short"] += realized_gain
        if position["short"] == 0:
            position["short_cost_basis"] = 0.0
            position["short_margin_used"] = 0.0
        return quantity
