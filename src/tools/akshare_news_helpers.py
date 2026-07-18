import logging
import re

import pandas as pd

from src.data.models import CompanyNews

# NS-17 / BH-017 family sibling drain: 新闻去重计数此前用 print, 在 cron 上下文不可见。
logger = logging.getLogger(__name__)


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
    except Exception as exc:
        # NS-17/BH-017 同族 (c278): 静默 return df 会让新闻时序错乱不可观测 —
        # 下游 event_sentiment agent 处理旧新闻先 / 新新闻后会误导情绪时序.
        # warning 级别 (温路径 per-ticker, 触及数据质量, 非纯展示).
        logger.warning(
            "sort_news_dataframe failed (rows=%d, returning unsorted): %s",
            len(df) if df is not None else 0,
            exc,
            exc_info=True,
        )
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
    except (TypeError, AttributeError):
        # pub_time is None or not a string — exclude unparseable dates
        return False
    return True


def resolve_stock_name(get_stock_name, ticker: str) -> str:
    try:
        stock_name = get_stock_name(ticker)
        return "" if stock_name == ticker else stock_name
    except Exception as exc:
        # NS-17/BH-017 同族 (c278): 静默 return "" 会让股票名解析失败不可观测.
        # debug 级别 (温路径 per-ticker, 纯展示用途, 非决策链).
        logger.debug(
            "resolve_stock_name failed (ticker=%s, fallback to empty): %s",
            ticker,
            exc,
        )
        return ""


def classify_news_sentiment(title: str, content: str = "") -> str:
    text = (title + " " + content).lower()

    if "一览" in title and len(content) < 50:
        return "neutral"

    positive_keywords = [
        "涨停",
        "大涨",
        "暴涨",
        "利好",
        "突破",
        "创新高",
        "增长",
        "盈利",
        "超预期",
        "上调",
        "买入",
        "推荐",
        "看好",
        "回购",
        "增持",
        "签约",
        "中标",
        "获批",
        "扭亏",
        "新高",
        "强势",
        "反弹",
        "爆发",
        "景气",
        "丰收",
        "提价",
        "提升",
        "改善",
        "加速",
        "翻倍",
        "分红",
        "派息",
        "上涨",
        "走强",
        "拉升",
        "领涨",
        "飘红",
        "翻红",
        "放量上攻",
        "底部放量",
        "企稳",
        "回暖",
        "复苏",
        "资金流入",
        "净买入",
        "青睐",
        "布局",
        "加仓",
        "建仓",
        "机构加仓",
        "北向资金",
        "合作",
        "订单",
        "营收",
        "净利润",
        "业绩预增",
        "预增",
        "高送转",
        "定增",
        "重组",
        "复牌",
        "龙头",
        "优质",
        "稳健",
        "战略合作",
        "产能扩张",
        "市占率",
        "竞争优势",
        "行业领先",
        "补贴",
        "收到补贴",
        "补贴资金",
        "政策支持",
        "获得补助",
        "补助",
        "政府补助",
        "分派",
        "每股派",
        "权益分派",
    ]
    negative_keywords = [
        "跌停",
        "大跌",
        "暴跌",
        "利空",
        "下调",
        "亏损",
        "减持",
        "卖出",
        "风险",
        "预警",
        "违规",
        "处罚",
        "退市",
        "爆雷",
        "债务",
        "诉讼",
        "炸板",
        "打开涨停",
        "下滑",
        "萎缩",
        "破发",
        "破位",
        "新低",
        "弱势",
        "下行",
        "缩水",
        "低于预期",
        "恶化",
        "暂停",
        "终止",
        "警告",
        "质押",
        "下跌",
        "跳水",
        "回调",
        "低迷",
        "承压",
        "拖累",
        "走低",
        "杀跌",
        "闪崩",
        "阴跌",
        "缩量下跌",
        "抛售",
        "出逃",
        "净流出",
        "资金流出",
        "主力流出",
        "清仓",
        "负增长",
        "收缩",
        "亏",
        "业绩变脸",
        "业绩不及预期",
        "利润下滑",
        "营收下降",
        "收入下降",
        "预降",
        "预减",
        "净利下降",
        "同比下降",
        "同比减少",
        "业绩下滑",
        "净利同比预降",
        "利润下降",
        "收入减少",
        "监管",
        "问询函",
        "关注函",
        "立案",
        "调查",
        "侵权",
        "裁员",
        "关停",
        "破产",
        "清算",
    ]

    pos_count = sum(1 for kw in positive_keywords if kw in text)
    neg_count = sum(1 for kw in negative_keywords if kw in text)
    # "st" (ST 股前缀) 用词边界匹配 — 子串会误伤拉丁词内部
    # (如 "SST签定战略协议" 实质利好, 曾误判 negative).
    if re.search(r"(?<![a-z])st(?![a-z])", text):
        neg_count += 1

    if pos_count > neg_count:
        return "positive"
    if neg_count > pos_count:
        return "negative"
    return "neutral"


def deduplicate_news(articles: list, similarity_threshold: float = 0.5) -> list:
    if len(articles) <= 1:
        return articles

    def _extract_key_chars(title: str) -> set[str]:
        cleaned = re.sub(r"^[\w\u4e00-\u9fff]+[：:]\s*", "", title)
        cleaned = re.sub(r"[^\u4e00-\u9fff0-9a-zA-Z%.]", "", cleaned)
        return set(cleaned)

    def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    unique_articles = []
    seen_char_sets: list[set[str]] = []
    # Bug 3 fix: track cluster sizes so the scorer can boost confidence for
    # multi-source consensus. Each kept article records how many near-duplicate
    # articles it absorbed (itself + N duplicates).
    cluster_sizes: list[int] = []

    for article in articles:
        title = getattr(article, "title", "")
        char_set = _extract_key_chars(title)

        is_duplicate = False
        for i, existing_set in enumerate(seen_char_sets):
            if _jaccard_similarity(char_set, existing_set) >= similarity_threshold:
                is_duplicate = True
                cluster_sizes[i] += 1  # increment the kept article's cluster
                break

        if not is_duplicate:
            unique_articles.append(article)
            seen_char_sets.append(char_set)
            cluster_sizes.append(1)

    # Write cluster_size onto each kept article (best-effort — works for
    # CompanyNews/pydantic models with the field).
    for article, size in zip(unique_articles, cluster_sizes):
        try:
            article.dedup_cluster_size = size
        except (AttributeError, TypeError):
            logger.debug("deduplicate_news: cannot set dedup_cluster_size on %s", type(article).__name__)

    dedup_count = len(articles) - len(unique_articles)
    if dedup_count > 0:
        logger.info("[AKShare] 新闻去重：移除 %d 篇重复报道（同一事件不同来源），保留 %d 篇", dedup_count, len(unique_articles))

    return unique_articles


def is_news_relevant_to_stock(title: str, content: str, ticker: str, stock_name: str = "") -> bool:
    if stock_name and stock_name in title:
        return True
    if ticker in title:
        return True

    generic_list_patterns = [
        "解密主力资金出逃股",
        "主力资金出逃",
        "短线防风险",
        "只个股",
        "一览",
        "榜单",
        "排行",
        "盘点",
        "连续.*净流出.*股",
        "连续.*净流入.*股",
        "只股票",
        "股名单",
    ]
    for pattern in generic_list_patterns:
        if re.search(pattern, title):
            return False

    if content:
        content_sample = content[:300]
        digit_count = sum(1 for char in content_sample if char.isdigit() or char in ".-")
        if len(content_sample) > 0 and digit_count / len(content_sample) > 0.5 and stock_name and stock_name not in content_sample[:100]:
            return False

    return True


def build_filtered_company_news(
    *,
    ticker: str,
    df: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
    limit: int,
    stock_name: str,
    is_news_relevant_to_stock_fn,
    classify_news_sentiment_fn,
    deduplicate_news_fn,
) -> tuple[list[CompanyNews], int]:
    results: list[CompanyNews] = []
    filtered_count = 0

    for _, row in df.iterrows():
        pub_time = str(row.get("发布时间", ""))
        if not news_date_in_range(pub_time, start_date, end_date):
            continue

        title = str(row.get("新闻标题", ""))
        content = str(row.get("新闻内容", ""))

        if not is_news_relevant_to_stock_fn(title, content, ticker, stock_name):
            filtered_count += 1
            continue

        sentiment = classify_news_sentiment_fn(title, content)
        results.append(build_company_news_entry(ticker, row, sentiment))

        if len(results) >= limit:
            break

    return deduplicate_news_fn(results), filtered_count


def load_company_news_results(
    *,
    ticker: str,
    end_date: str,
    start_date: str | None,
    limit: int,
    fetch_news_df_fn,
    resolve_stock_name_fn,
    sort_news_dataframe_fn,
    build_filtered_company_news_fn,
) -> tuple[list[CompanyNews], int, str]:
    df = fetch_news_df_fn()
    if df is None or df.empty:
        return [], 0, ""

    stock_name = resolve_stock_name_fn()
    sorted_df = sort_news_dataframe_fn(df)
    results, filtered_count = build_filtered_company_news_fn(
        ticker=ticker,
        df=sorted_df,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        stock_name=stock_name,
    )
    return results, filtered_count, stock_name
