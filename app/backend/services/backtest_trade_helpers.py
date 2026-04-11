from typing import Any


def normalize_trade_quantity(quantity: float) -> int:
    return int(quantity) if quantity > 0 else 0


def _update_weighted_cost_basis(position: dict[str, Any], field_name: str, existing_shares: int, new_shares: int, new_cost_total: float) -> None:
    total_shares = existing_shares + new_shares
    if total_shares <= 0:
        return

    total_old_cost = position[field_name] * existing_shares
    position[field_name] = (total_old_cost + new_cost_total) / total_shares


def execute_buy_trade(portfolio: dict[str, Any], ticker: str, quantity: int, current_price: float) -> int:
    position = portfolio["positions"][ticker]
    affordable_quantity = min(quantity, int(portfolio["cash"] / current_price))
    if affordable_quantity <= 0:
        return 0

    cost = affordable_quantity * current_price
    _update_weighted_cost_basis(position, "long_cost_basis", position["long"], affordable_quantity, cost)
    position["long"] += affordable_quantity
    portfolio["cash"] -= cost
    return affordable_quantity


def execute_sell_trade(portfolio: dict[str, Any], ticker: str, quantity: int, current_price: float) -> int:
    position = portfolio["positions"][ticker]
    sell_quantity = min(quantity, position["long"])
    if sell_quantity <= 0:
        return 0

    avg_cost_per_share = position["long_cost_basis"] if position["long"] > 0 else 0
    realized_gain = (current_price - avg_cost_per_share) * sell_quantity
    portfolio["realized_gains"][ticker]["long"] += realized_gain

    position["long"] -= sell_quantity
    portfolio["cash"] += sell_quantity * current_price
    if position["long"] == 0:
        position["long_cost_basis"] = 0.0

    return sell_quantity


def execute_short_trade(portfolio: dict[str, Any], ticker: str, quantity: int, current_price: float) -> int:
    margin_ratio = portfolio["margin_requirement"]
    max_quantity = quantity
    if margin_ratio > 0:
        max_quantity = min(quantity, int(portfolio["cash"] / (current_price * margin_ratio)))

    if max_quantity <= 0:
        return 0

    position = portfolio["positions"][ticker]
    proceeds = current_price * max_quantity
    margin_required = proceeds * margin_ratio

    _update_weighted_cost_basis(position, "short_cost_basis", position["short"], max_quantity, proceeds)
    position["short"] += max_quantity
    position["short_margin_used"] += margin_required
    portfolio["margin_used"] += margin_required
    portfolio["cash"] += proceeds
    portfolio["cash"] -= margin_required
    return max_quantity


def execute_cover_trade(portfolio: dict[str, Any], ticker: str, quantity: int, current_price: float) -> int:
    position = portfolio["positions"][ticker]
    cover_quantity = min(quantity, position["short"])
    if cover_quantity <= 0:
        return 0

    cover_cost = cover_quantity * current_price
    avg_short_price = position["short_cost_basis"] if position["short"] > 0 else 0
    realized_gain = (avg_short_price - current_price) * cover_quantity
    portion = cover_quantity / position["short"] if position["short"] > 0 else 1.0
    margin_to_release = portion * position["short_margin_used"]

    position["short"] -= cover_quantity
    position["short_margin_used"] -= margin_to_release
    portfolio["margin_used"] -= margin_to_release
    portfolio["cash"] += margin_to_release
    portfolio["cash"] -= cover_cost
    portfolio["realized_gains"][ticker]["short"] += realized_gain

    if position["short"] == 0:
        position["short_cost_basis"] = 0.0
        position["short_margin_used"] = 0.0

    return cover_quantity
