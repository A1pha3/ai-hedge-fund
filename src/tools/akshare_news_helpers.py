from typing import List

import pandas as pd

from src.data.models import CompanyNews


def normalize_news_symbol(ticker: str) -> str:
    symbol = ticker.strip().lower()
    if symbol.startswith(("sh", "sz", "bj")):
        symbol = symbol[2:]
    return symbol


def sort_news_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    try:
        sorted_df = df.copy()
        sorted_df["_pub_dt"] = pd.to_datetime(sorted_df["发布时间"], errors="coerce")
        return sorted_df.sort_values("_pub_dt", ascending=False).reset_index(drop=True)
    except Exception:
        return df


def build_company_news_entry(ticker: str, row, sentiment: str) -> CompanyNews:
    content = str(row.get("新闻内容", ""))
    source = str(row.get("文章来源", ""))
    return CompanyNews(
        ticker=ticker,
        title=str(row.get("新闻标题", "")),
        author=source,
        source=source,
        date=str(row.get("发布时间", "")),
        url=str(row.get("新闻链接", "")),
        sentiment=sentiment,
        content=content[:200] if content else None,
    )


def news_date_in_range(pub_time: str, start_date: str | None, end_date: str | None) -> bool:
    try:
        news_date = pub_time[:10]
        if end_date and news_date > end_date:
            return False
        if start_date and news_date < start_date:
            return False
    except (ValueError, IndexError):
        return True
    return True


def resolve_stock_name(get_stock_name, ticker: str) -> str:
    try:
        stock_name = get_stock_name(ticker)
        return "" if stock_name == ticker else stock_name
    except Exception:
        return ""
