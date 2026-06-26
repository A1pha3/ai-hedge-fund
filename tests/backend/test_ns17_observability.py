"""NS-17 切片 2: 打分可观测性 — graph.py + hedge_fund_streaming.py print→logger drain.

NS-17 描述: "parse_hedge_fund_response 返 None → 无面包屑" + "SSE cancel + LLM
JSON-parse 失败用 print() 不入 logs"。本测试守卫两个文件不再用 print() 吞错误,
改用 module logger 让运维可从结构化日志定位"为何某 ticker 缺 strategy signal"
以及"为何某次 hedge fund run / backtest 中途断流"。

graph.py parse_hedge_fund_response 是 LLM 打分链路的关键一环:
LLM 返回 JSON → parse_hedge_fund_response 解析 → strategy signal → signal_fusion
融合 → score_b。parse 失败会导致 strategy signal 缺失, 影响 score_b, 属 must-win
workflow 的可观测性缺口。
"""

from __future__ import annotations

import logging

from app.backend.routes import hedge_fund_streaming
from app.backend.services import graph


class TestParseHedgeFundResponseObservability:
    """NS-17: parse_hedge_fund_response 失败时发 logger.warning 而非 print()。"""

    def test_json_decode_error_logs_warning_and_returns_none(self, caplog) -> None:
        """malformed JSON 必须发 warning + 返回 None, 不再静默 print。"""
        with caplog.at_level(logging.WARNING, logger="app.backend.services.graph"):
            result = graph.parse_hedge_fund_response("{not valid json")

        assert result is None
        assert any(
            "JSONDecodeError" in record.getMessage()
            and "parse_hedge_fund_response" in record.getMessage()
            for record in caplog.records
        ), "JSONDecodeError 必须发 logger.warning 含 parse_hedge_fund_response 标记"

    def test_type_error_logs_warning_and_returns_none(self, caplog) -> None:
        """非字符串输入 (如 int) 必须发 warning + 返回 None。"""
        with caplog.at_level(logging.WARNING, logger="app.backend.services.graph"):
            result = graph.parse_hedge_fund_response(42)

        assert result is None
        assert any(
            "TypeError" in record.getMessage()
            and "parse_hedge_fund_response" in record.getMessage()
            for record in caplog.records
        ), "TypeError 必须发 logger.warning 含 parse_hedge_fund_response 标记"

    def test_valid_json_returns_dict_without_warning(self, caplog) -> None:
        """合法 JSON 正常解析, 不发 warning。"""
        with caplog.at_level(logging.WARNING, logger="app.backend.services.graph"):
            result = graph.parse_hedge_fund_response('{"action": "buy", "score": 0.85}')

        assert result == {"action": "buy", "score": 0.85}
        assert not any(
            "parse_hedge_fund_response" in record.getMessage()
            for record in caplog.records
        ), "合法 JSON 不应发 warning"


class TestHedgeFundStreamingModuleLogger:
    """NS-17: hedge_fund_streaming 模块有 logger, SSE cancel 不再用 print()。"""

    def test_module_logger_exists(self) -> None:
        """模块必须有 logger (此前无 logging, SSE cancel 用 print 不入 logs)。"""
        assert hasattr(hedge_fund_streaming, "logger"), (
            "hedge_fund_streaming 必须有 module logger (NS-17 可观测性要求)"
        )
        assert isinstance(hedge_fund_streaming.logger, logging.Logger)
        assert hedge_fund_streaming.logger.name == "app.backend.routes.hedge_fund_streaming"

    def test_no_print_calls_remain(self) -> None:
        """模块源码不再含裸 print() 调用 (注释除外)。"""
        import inspect

        source = inspect.getsource(hedge_fund_streaming)
        # 统计非注释行的 print( 调用
        code_lines = [
            line
            for line in source.splitlines()
            if line.lstrip().startswith(("print(", "                print(", "            print("))
            and not line.lstrip().startswith("#")
        ]
        assert not code_lines, (
            f"hedge_fund_streaming 不应再有裸 print() 调用, 发现: {code_lines}"
        )


class TestGraphModuleLogger:
    """NS-17: graph 模块有 logger, parse 失败不再用 print()。"""

    def test_module_logger_exists(self) -> None:
        """模块必须有 logger (此前无 logging, parse 失败用 print 不入 logs)。"""
        assert hasattr(graph, "logger"), (
            "graph 必须有 module logger (NS-17 可观测性要求)"
        )
        assert isinstance(graph.logger, logging.Logger)
        assert graph.logger.name == "app.backend.services.graph"

    def test_no_print_calls_remain(self) -> None:
        """模块源码不再含裸 print() 调用 (注释除外)。"""
        import inspect

        source = inspect.getsource(graph)
        code_lines = [
            line
            for line in source.splitlines()
            if line.lstrip().startswith("print(")
            and not line.lstrip().startswith("#")
        ]
        assert not code_lines, (
            f"graph 不应再有裸 print() 调用, 发现: {code_lines}"
        )
