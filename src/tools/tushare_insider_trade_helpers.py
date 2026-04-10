import pandas as pd

from src.data.models import InsiderTrade


def build_holdertrade_query_kwargs(ts_code: str, end_date: str, start_date: str | None) -> dict:
    kwargs = {"ts_code": ts_code, "end_date": end_date.replace("-", "")}
    if start_date:
        kwargs["start_date"] = start_date.replace("-", "")
    return kwargs


def build_insider_trade_from_row(ticker: str, row) -> InsiderTrade:
    ann_date = str(row.get("ann_date", ""))
    filing_date = f"{ann_date[:4]}-{ann_date[4:6]}-{ann_date[6:8]}" if len(ann_date) == 8 else ann_date

    in_de = str(row.get("in_de", ""))
    change_vol = row.get("change_vol")
    avg_price = row.get("avg_price")
    after_share = row.get("after_share")

    shares = None
    tx_value = None
    if change_vol is not None and not (isinstance(change_vol, float) and pd.isna(change_vol)):
        shares = float(change_vol)
        if in_de == "DE" and shares > 0:
            shares = -shares
        if avg_price is not None and not (isinstance(avg_price, float) and pd.isna(avg_price)):
            tx_value = abs(shares) * float(avg_price)

    shares_after = None
    if after_share is not None and not (isinstance(after_share, float) and pd.isna(after_share)):
        shares_after = float(after_share)

    shares_before = shares_after - shares if shares_after is not None and shares is not None else None
    tx_price = float(avg_price) if avg_price is not None and not (isinstance(avg_price, float) and pd.isna(avg_price)) else None

    return InsiderTrade(
        ticker=ticker,
        issuer=None,
        name=str(row.get("holder_name", "")),
        title=str(row.get("holder_type", "")),
        is_board_director=None,
        transaction_date=filing_date,
        transaction_shares=shares,
        transaction_price_per_share=tx_price,
        transaction_value=tx_value,
        shares_owned_before_transaction=shares_before,
        shares_owned_after_transaction=shares_after,
        security_title=None,
        filing_date=filing_date,
    )
