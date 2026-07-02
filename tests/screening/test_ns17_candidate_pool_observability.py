"""NS-17/BH-017 family sibling drain: candidate_pool._resolve_batch_fetcher_for_avg_amount.

Context: ``_resolve_batch_fetcher_for_avg_amount`` 是决策链数据源 (avg_amount 用于
候选池流动性筛选) 的 lazy 单例解析器。此前两处 ``except Exception: return None``
静默吞掉 ImportError (batch_data_fetcher 模块语法错误/循环依赖/缺失依赖) 与
单例初始化失败 (DB 连接/配置错误)。

虽然有 fallback (``batch_fetcher=None`` 时走 ``_cached_tushare_dataframe_call``,
数据仍流通), 但运维无法知道 batch fetcher 不可用 — 效率降低 + batch_data_fetcher
内部 bug 被掩盖。

c274 drain: best-effort 契约保留 (return None + fallback), 但 failure path 必须
发 ``logger.warning`` (罕见 + 决策链数据源 + 决策关键)。
"""

from __future__ import annotations

import logging

from src.screening import candidate_pool


class TestResolveBatchFetcherForAvgAmountObservability:
    """NS-17 c274: _resolve_batch_fetcher_for_avg_amount 失败路径必须可观测."""

    def test_import_failure_emits_warning(self, caplog, monkeypatch) -> None:
        """batch_data_fetcher 导入失败 (ImportError) 必须发 warning + 返回 None.

        覆盖场景: 模块语法错误/循环依赖/缺失依赖 — fallback 仍可工作但效率降低,
        运维需要知道 batch fetcher 不可用。
        """
        # 注入一个会抛 ImportError 的 import 钩子
        real_import = (
            __builtins__["__import__"]
            if isinstance(__builtins__, dict)
            else __builtins__.__import__
        )

        def _import_side_effect(name, *args, **kwargs):
            if name == "src.screening.batch_data_fetcher":
                raise ImportError("simulated batch_data_fetcher import failure")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _import_side_effect)

        with caplog.at_level(logging.WARNING, logger="src.screening.candidate_pool"):
            result = candidate_pool._resolve_batch_fetcher_for_avg_amount()

        assert result is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, (
            f"expected 1 WARNING for import failure, got {warnings}"
        )
        msg = warnings[0].getMessage()
        assert "batch_data_fetcher import failed" in msg
        assert "simulated batch_data_fetcher import failure" in msg

    def test_init_failure_emits_warning(self, caplog, monkeypatch) -> None:
        """get_global_batch_data_fetcher() 单例初始化失败必须发 warning + 返回 None.

        覆盖场景: DB 连接失败/配置错误 — fallback 仍可工作但 batch_data_fetcher
        内部 bug 被掩盖, 运维需要知道。
        """
        # 注入一个假 batch_data_fetcher 模块, get_global_batch_data_fetcher 抛异常
        import sys
        from types import ModuleType

        fake_module = ModuleType("src.screening.batch_data_fetcher")

        def _boom_init():
            raise RuntimeError("simulated batch_data_fetcher init failure")

        fake_module.get_global_batch_data_fetcher = _boom_init  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "src.screening.batch_data_fetcher", fake_module)

        with caplog.at_level(logging.WARNING, logger="src.screening.candidate_pool"):
            result = candidate_pool._resolve_batch_fetcher_for_avg_amount()

        assert result is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, (
            f"expected 1 WARNING for init failure, got {warnings}"
        )
        msg = warnings[0].getMessage()
        assert "get_global_batch_data_fetcher() init failed" in msg
        assert "simulated batch_data_fetcher init failure" in msg

    def test_success_returns_fetcher_no_warning(self, caplog, monkeypatch) -> None:
        """合法 batch_data_fetcher 返回时不应发 warning (避免日志噪声)."""
        import sys
        from types import ModuleType

        fake_module = ModuleType("src.screening.batch_data_fetcher")

        class _FakeFetcher:
            pass

        fake_fetcher = _FakeFetcher()
        fake_module.get_global_batch_data_fetcher = lambda: fake_fetcher  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "src.screening.batch_data_fetcher", fake_module)

        with caplog.at_level(logging.WARNING, logger="src.screening.candidate_pool"):
            result = candidate_pool._resolve_batch_fetcher_for_avg_amount()

        assert result is fake_fetcher
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 0
