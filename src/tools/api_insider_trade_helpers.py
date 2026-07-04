import logging
import os

from src.data.models import InsiderTrade, InsiderTradeResponse

# BH-024 / BH-023 同族: US-equity insider trades 解析边界此前无 module logger。
# Pydantic 解析失败时静默 break 分页 → 内部交易数据缺失且无信号。debug 级
# 降级诊断让运维可定位 insider trades 拉取降级。
logger = logging.getLogger(__name__)


def build_insider_trade_cache_key(ticker: str, start_date: str | None, end_date: str, limit: int) -> str:
    return f"{ticker}_{start_date or 'none'}_{end_date}_{limit}"


def load_cached_insider_trades(cache, cache_key: str) -> list[InsiderTrade] | None:
    cached_data = cache.get_insider_trades(cache_key)
    if not cached_data:
        return None
    return [InsiderTrade(**trade) for trade in cached_data]


def cache_insider_trades(cache, cache_key: str, trades: list[InsiderTrade]) -> list[InsiderTrade]:
    cache.set_insider_trades(cache_key, [trade.model_dump() for trade in trades])
    return trades


def build_financial_datasets_headers(api_key: str | None) -> dict:
    headers = {}
    financial_api_key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY")
    if financial_api_key:
        headers["X-API-KEY"] = financial_api_key
    return headers


def fetch_remote_insider_trades(make_api_request, ticker: str, end_date: str, start_date: str | None, limit: int, headers: dict) -> list[InsiderTrade]:
    all_trades: list[InsiderTrade] = []
    current_end_date = end_date

    while True:
        url = f"https://api.financialdatasets.ai/insider-trades/?ticker={ticker}&filing_date_lte={current_end_date}"
        if start_date:
            url += f"&filing_date_gte={start_date}"
        url += f"&limit={limit}"

        response = make_api_request(url, headers)
        if response is None or response.status_code != 200:
            break

        try:
            insider_trades = InsiderTradeResponse(**response.json()).insider_trades
        except Exception as exc:
            # BH-024 / BH-023 同族: insider trades 响应解析失败时静默 break
            # 分页 → 内部交易数据缺失且无信号。发降级诊断。
            logger.debug(
                "insider_trades response parse degraded (break pagination) for %s: %s",
                ticker,
                exc,
            )
            break

        if not insider_trades:
            break

        all_trades.extend(insider_trades)
        if not start_date or len(insider_trades) < limit:
            break

        dates = [trade.filing_date for trade in insider_trades if trade.filing_date]
        if not dates:
            break
        current_end_date = min(dates).split("T")[0]
        if current_end_date <= start_date:
            break

    return all_trades
