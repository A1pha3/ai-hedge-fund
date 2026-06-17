import logging
from datetime import datetime

from src.data.models import CompanyNews, CompanyNewsResponse

# BH-024 / BH-023 同族: US-equity news 解析边界此前无 module logger。Pydantic
# 解析失败时静默 break 分页 → news agents 拿到部分新闻做 sentiment 分析，
# 偏差且无信号。debug 级降级诊断让运维可定位 news 拉取降级。
logger = logging.getLogger(__name__)


def build_company_news_cache_key(ticker: str, start_date: str | None, end_date: str, limit: int, *, ashare: bool = False) -> str:
    suffix = "_ashare" if ashare else ""
    return f"{ticker}_{start_date or 'none'}_{end_date}_{limit}{suffix}"


def load_cached_company_news(cache, cache_key: str) -> list[CompanyNews] | None:
    cached_data = cache.get_company_news(cache_key)
    if not cached_data:
        return None
    return [CompanyNews(**news) for news in cached_data]


def resolve_company_news_cache_ttl(start_date: str | None, end_date: str) -> int:
    reference_date = str(end_date or start_date or "").replace("-", "")
    today = datetime.now().strftime("%Y%m%d")
    is_historical = bool(reference_date) and reference_date < today
    return 30 * 86400 if is_historical else 10800


def cache_company_news(cache, cache_key: str, news_items: list[CompanyNews], *, ttl: int | None = None) -> list[CompanyNews]:
    payload = [item.model_dump() for item in news_items]
    if ttl is None:
        cache.set_company_news(cache_key, payload)
        return news_items
    try:
        cache.set_company_news(cache_key, payload, ttl=ttl)
    except TypeError:
        cache.set_company_news(cache_key, payload)
    return news_items


def fetch_remote_company_news(make_api_request, ticker: str, end_date: str, start_date: str | None, limit: int, headers: dict) -> list[CompanyNews]:
    all_news: list[CompanyNews] = []
    current_end_date = end_date

    while True:
        url = f"https://api.financialdatasets.ai/news/?ticker={ticker}&end_date={current_end_date}"
        if start_date:
            url += f"&start_date={start_date}"
        url += f"&limit={limit}"

        response = make_api_request(url, headers)
        if response is None or response.status_code != 200:
            break

        try:
            company_news = CompanyNewsResponse(**response.json()).news
        except Exception as exc:
            # BH-024 / BH-023 同族: news 响应解析失败时静默 break 分页 → news
            # agents 拿到部分新闻做 sentiment 分析，偏差且无信号。发降级诊断。
            logger.debug(
                "company_news response parse degraded (break pagination) for %s: %s",
                ticker, exc,
            )
            break

        if not company_news:
            break

        all_news.extend(company_news)
        if not start_date or len(company_news) < limit:
            break

        dates = [news.date for news in company_news if news.date]
        if not dates:
            break
        current_end_date = min(dates).split("T")[0]
        if current_end_date <= start_date:
            break

    all_news.sort(key=lambda news: news.date, reverse=True)
    return all_news
