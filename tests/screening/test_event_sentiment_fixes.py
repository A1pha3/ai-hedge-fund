"""Phase 1 event_sentiment 反向 bug 修复回归测试。

覆盖 4 个修复：
  Bug 1: _count_event_keyword_hits 优先使用摄入层已算好的 sentiment 字段
  Bug 2: 关键词表扩充后能命中 A 股事件词（涨停/问询函 等）
  Bug 3: dedup_cluster_size 多源共识 → effective_weight 加成
  Bug 4: insider direction=0 时 completeness=0（不再仅限 confidence=0）
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.data.models import CompanyNews, InsiderTrade
from src.screening.strategy_scorer_event_sentiment_helpers import (
    _count_event_keyword_hits,
    _score_insider_conviction,
    _score_news_article,
)
from src.screening.strategy_scorer_utils import (
    NEGATIVE_NEWS_KEYWORDS,
    POSITIVE_NEWS_KEYWORDS,
)


def _news(
    title: str = "",
    date: str = "2026-03-05",
    content: str = "",
    sentiment: str | None = None,
    cluster_size: int = 1,
) -> CompanyNews:
    return CompanyNews(
        ticker="000001",
        title=title,
        author="test",
        source="test",
        date=date,
        url="https://example.com",
        content=content,
        sentiment=sentiment,
        dedup_cluster_size=cluster_size,
    )


# ---------------------------------------------------------------------------
# Bug 1: sentiment 字段优先于重复关键词计算
# ---------------------------------------------------------------------------


class TestBug1SentimentFieldUsed:
    def test_positive_sentiment_triggers_direction_without_keywords(self):
        """sentiment="positive" 但标题/正文无任何关键词命中 → direction 应为 +1。

        证明 _count_event_keyword_hits 使用了 sentiment 字段，而非仅靠 36/90 词表。
        """
        item = _news(
            title="某公司发布最新公告",  # 无任何关键词
            content="公司于今日召开股东大会，讨论了日常事项。",  # 无关键词
            sentiment="positive",
        )
        pos, neg = _count_event_keyword_hits(item)
        assert pos > 0, "sentiment=positive should yield pos_hits > 0"
        assert neg == 0
        assert pos >= neg

    def test_negative_sentiment_triggers_direction_without_keywords(self):
        item = _news(
            title="某公司日常公告",
            content="公司今日发布了例行通知。",
            sentiment="negative",
        )
        pos, neg = _count_event_keyword_hits(item)
        assert neg > 0, "sentiment=negative should yield neg_hits > 0"
        assert pos == 0

    def test_neutral_sentiment_falls_back_to_keywords(self):
        """sentiment=neutral 时走关键词兜底路径。"""
        item = _news(
            title="涨停 利好",
            content="",
            sentiment="neutral",
        )
        pos, neg = _count_event_keyword_hits(item)
        assert pos >= 2, f"expanded keywords should catch 涨停+利好, got pos={pos}"

    def test_missing_sentiment_falls_back_to_keywords(self):
        """sentiment=None（如美股 financialdatasets 数据）走关键词兜底。"""
        item = _news(title="profit growth beat", content="record upgrade", sentiment=None)
        pos, neg = _count_event_keyword_hits(item)
        assert pos >= 3


# ---------------------------------------------------------------------------
# Bug 2: 关键词表覆盖 A 股事件词
# ---------------------------------------------------------------------------


class TestBug2ExpandedKeywords:
    @pytest.mark.parametrize("keyword", ["涨停", "大涨", "暴涨", "利好", "突破", "预增", "增持", "业绩预增"])
    def test_positive_ashare_keywords_present(self, keyword):
        assert keyword in POSITIVE_NEWS_KEYWORDS, f"{keyword} should be in expanded positive keywords"

    @pytest.mark.parametrize("keyword", ["跌停", "大跌", "暴跌", "利空", "问询函", "关注函", "立案", "破发", "闪崩", "业绩变脸"])
    def test_negative_ashare_keywords_present(self, keyword):
        assert keyword in NEGATIVE_NEWS_KEYWORDS, f"{keyword} should be in expanded negative keywords"

    def test_keyword_count_substantially_expanded(self):
        """词表应从原来的 18+18 显著扩充。"""
        assert len(POSITIVE_NEWS_KEYWORDS) >= 35, f"positive table too small: {len(POSITIVE_NEWS_KEYWORDS)}"
        assert len(NEGATIVE_NEWS_KEYWORDS) >= 35, f"negative table too small: {len(NEGATIVE_NEWS_KEYWORDS)}"

    def test_original_keywords_preserved(self):
        """扩充不应删除原有词。"""
        for w in ["beat", "upgrade", "profit", "回购", "超预期"]:
            assert w in POSITIVE_NEWS_KEYWORDS
        for w in ["miss", "downgrade", "loss", "亏损", "减持"]:
            assert w in NEGATIVE_NEWS_KEYWORDS


# ---------------------------------------------------------------------------
# Bug 3: dedup_cluster_size 多源共识加成
# ---------------------------------------------------------------------------


class TestBug3ClusterConsensus:
    def test_cluster_size_boosts_effective_weight(self):
        """cluster_size > 1 的文章 effective_weight 应大于 cluster_size=1 的（同方向、同新鲜度）。"""
        trade_dt = datetime(2026, 3, 5)

        standalone = _score_news_article(
            _news(title="涨停 利好", date="2026-03-05", sentiment="positive", cluster_size=1),
            trade_dt,
        )
        consensus = _score_news_article(
            _news(title="涨停 利好", date="2026-03-05", sentiment="positive", cluster_size=3),
            trade_dt,
        )

        assert standalone["direction"] == consensus["direction"] == 1
        assert consensus["effective_weight"] > standalone["effective_weight"]

    def test_cluster_boost_capped_at_1_5x(self):
        """cluster_size 极大时加成不超过 1.5×。"""
        trade_dt = datetime(2026, 3, 5)

        base = _score_news_article(
            _news(title="涨停 利好", date="2026-03-05", sentiment="positive", cluster_size=1),
            trade_dt,
        )
        huge = _score_news_article(
            _news(title="涨停 利好", date="2026-03-05", sentiment="positive", cluster_size=100),
            trade_dt,
        )
        ratio = huge["effective_weight"] / base["effective_weight"]
        assert ratio <= 1.5 + 1e-9, f"cluster boost should be capped at 1.5×, got {ratio:.2f}×"

    def test_cluster_does_not_boost_neutral_article(self):
        """无方向（strength=0）的文章不应被 cluster 加成。"""
        trade_dt = datetime(2026, 3, 5)

        neutral_1 = _score_news_article(
            _news(title="日常公告", date="2026-03-05", sentiment="neutral", cluster_size=1),
            trade_dt,
        )
        neutral_5 = _score_news_article(
            _news(title="日常公告", date="2026-03-05", sentiment="neutral", cluster_size=5),
            trade_dt,
        )
        assert neutral_1["effective_weight"] == neutral_5["effective_weight"]


# ---------------------------------------------------------------------------
# Bug 4: insider direction=0 → completeness=0（不再仅限 confidence=0）
# ---------------------------------------------------------------------------


class TestBug4InsiderDeadZone:
    def test_neutral_score_has_zero_completeness(self):
        """direction=0 (score=0.5, 死区) 时 completeness 必须为 0.

        Bug 3 fix: 旧测试用 buy=5500/sell=9000 → net_flow_ratio≈-0.241 → score=0.2
        → direction=-1 (NOT 0!) → ``if factor.direction == 0`` 永远 False → 断言被跳过,
        测试虚假通过. 这正是 Bug 4 要防止的: 修复 completeness 逻辑但测试根本没覆盖到.

        修正: 构造确定性死区输入 (等额买卖 → ratio=0 → score=0.5 → direction=0),
        并用无条件断言 (先 assert direction==0, 再 assert completeness==0).
        """
        # buy_value == sell_value → net_flow_ratio = 0 → score = 0.5 → direction = 0
        buy = InsiderTrade(
            ticker="000001", issuer="测试", name="张三", title="高管",
            is_board_director=False, transaction_date="2026-03-01",
            transaction_shares=500.0, transaction_price_per_share=10.0,
            transaction_value=5000.0, shares_owned_before_transaction=50000.0,
            shares_owned_after_transaction=50500.0, security_title="股票", filing_date="2026-03-02",
        )
        sell = InsiderTrade(
            ticker="000001", issuer="测试", name="李四", title="高管",
            is_board_director=False, transaction_date="2026-03-01",
            transaction_shares=-500.0, transaction_price_per_share=10.0,
            transaction_value=-5000.0, shares_owned_before_transaction=50000.0,
            shares_owned_after_transaction=49500.0, security_title="股票", filing_date="2026-03-02",
        )
        factor = _score_insider_conviction([buy, sell])

        # 无条件断言: 先确认确实落在死区, 再断言 completeness
        assert factor.direction == 0, (
            f"测试前提: 等额买卖应产生 direction=0 (死区), got direction={factor.direction}"
        )
        assert factor.completeness == 0.0, (
            f"direction=0 must yield completeness=0 regardless of confidence, "
            f"got direction={factor.direction}, confidence={factor.confidence}, "
            f"completeness={factor.completeness}"
        )

    def test_directional_insider_retains_completeness(self):
        """direction≠0（score>0.6 或 <0.4）时 completeness 应为 1.0。"""
        # 强买入：buy_value=20000, sell_value=0 → ratio=1.0 → score=1.0 → direction=+1
        buy = InsiderTrade(
            ticker="000001", issuer="测试", name="张三", title="高管",
            is_board_director=False, transaction_date="2026-03-01",
            transaction_shares=2000.0, transaction_price_per_share=10.0,
            transaction_value=20000.0, shares_owned_before_transaction=50000.0,
            shares_owned_after_transaction=52000.0, security_title="股票", filing_date="2026-03-02",
        )
        factor = _score_insider_conviction([buy])
        # 无条件断言
        assert factor.direction == 1, (
            f"测试前提: 纯买入应产生 direction=+1, got direction={factor.direction}"
        )
        assert factor.completeness == 1.0
