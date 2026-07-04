"""BH-024 / BH-023 同族: US-equity news/insider 解析边界降级可观测性守卫。

`fetch_remote_company_news` / `fetch_remote_insider_trades` 在 Pydantic 解析
失败时静默 break 分页 → news/insider agents 拿到部分数据做分析，偏差且无信号。
服务"更高确信"目标。修复: 行为零变更（仍 break），但发 logger.debug 降级诊断。
"""

from types import SimpleNamespace


def _bad_response():
    """模拟 API 返回 200 但 body 是 Pydantic 无法解析的脏数据。"""
    return SimpleNamespace(status_code=200, json=lambda: {"not_a_valid_field": object()})


def test_fetch_remote_company_news_logs_degradation_on_parse_failure(caplog):
    """news 响应解析失败时必须发可观测日志。"""
    import logging

    from src.tools.api_company_news_helpers import fetch_remote_company_news

    def make_api_request(url, headers):
        return _bad_response()

    with caplog.at_level(logging.DEBUG, logger="src.tools.api_company_news_helpers"):
        result = fetch_remote_company_news(
            make_api_request,
            "AAPL",
            "2026-04-10",
            None,
            100,
            {},
        )

    # 行为零变更: 仍返回空列表 (解析失败 break)
    assert result == []
    # 可观测性: 必须有一条降级诊断日志
    debug_records = [r for r in caplog.records if r.levelname == "DEBUG"]
    assert debug_records, "company_news 解析静默失败时必须发 DEBUG 级降级诊断"
    joined = "\n".join(r.getMessage() for r in debug_records)
    assert "company_news" in joined, "降级日志必须命名降级的数据路径"
    assert "AAPL" in joined, "降级日志必须命名受影响的 ticker"


def test_fetch_remote_insider_trades_logs_degradation_on_parse_failure(caplog):
    """insider trades 响应解析失败时必须发可观测日志。"""
    import logging

    from src.tools.api_insider_trade_helpers import fetch_remote_insider_trades

    def make_api_request(url, headers):
        return _bad_response()

    with caplog.at_level(logging.DEBUG, logger="src.tools.api_insider_trade_helpers"):
        result = fetch_remote_insider_trades(
            make_api_request,
            "AAPL",
            "2026-04-10",
            None,
            100,
            {},
        )

    # 行为零变更: 仍返回空列表 (解析失败 break)
    assert result == []
    # 可观测性: 必须有一条降级诊断日志
    debug_records = [r for r in caplog.records if r.levelname == "DEBUG"]
    assert debug_records, "insider_trades 解析静默失败时必须发 DEBUG 级降级诊断"
    joined = "\n".join(r.getMessage() for r in debug_records)
    assert "insider_trades" in joined, "降级日志必须命名降级的数据路径"
    assert "AAPL" in joined, "降级日志必须命名受影响的 ticker"
