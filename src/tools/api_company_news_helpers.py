from src.data.models import CompanyNews, CompanyNewsResponse


def build_company_news_cache_key(ticker: str, start_date: str | None, end_date: str, limit: int, *, ashare: bool = False) -> str:
    suffix = "_ashare" if ashare else ""
    return f"{ticker}_{start_date or 'none'}_{end_date}_{limit}{suffix}"


def load_cached_company_news(cache, cache_key: str) -> list[CompanyNews] | None:
    cached_data = cache.get_company_news(cache_key)
    if not cached_data:
        return None
    return [CompanyNews(**news) for news in cached_data]


def cache_company_news(cache, cache_key: str, news_items: list[CompanyNews]) -> list[CompanyNews]:
    cache.set_company_news(cache_key, [item.model_dump() for item in news_items])
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
        if response.status_code != 200:
            break

        try:
            company_news = CompanyNewsResponse(**response.json()).news
        except Exception:
            break

        if not company_news:
            break

        all_news.extend(company_news)
        if not start_date or len(company_news) < limit:
            break

        current_end_date = min(news.date for news in company_news).split("T")[0]
        if current_end_date <= start_date:
            break

    all_news.sort(key=lambda news: news.date, reverse=True)
    return all_news
