"""
A股多数据源模块
支持多种数据源：Tushare、BaoStock、新浪财经、AKShare、模拟数据
"""

import logging
import os

import pandas as pd

from src.data.models import FinancialMetrics, Price
from src.tools.ashare_board_utils import to_baostock_code, to_tushare_code

# NS-17 / BH-017 family sibling drain: 本模块此前无 logger, 7 处 print() 在 cron /
# 长跑 pipeline 上下文里不入结构化日志, Tushare/BaoStock 初始化静默失败或多源回退
# 链退化时, 运维失去根因定位能力。本模块是 north-star P&L backfill
# (recommendation_tracker._default_price_fetcher R164 fallback) + 多源价格路径
# (akshare_api.get_prices → get_prices_multi_source) 的生产基础设施。
logger = logging.getLogger(__name__)


class DataSourceError(Exception):
    """数据源错误"""


class BaseDataSource:
    """数据源基类"""

    name: str = "base"
    available: bool = False

    @classmethod
    def get_prices(cls, ticker: str, start_date: str, end_date: str, period: str = "daily") -> list[Price]:
        """获取价格数据"""
        raise NotImplementedError

    @classmethod
    def get_financial_metrics(cls, ticker: str, end_date: str, limit: int = 10) -> list[FinancialMetrics]:
        """获取财务指标"""
        raise NotImplementedError


class TushareDataSource(BaseDataSource):
    """Tushare 数据源"""

    name: str = "tushare"
    available: bool = False
    _pro = None

    @classmethod
    def _init_tushare(cls):
        """初始化 Tushare"""
        if cls._pro is not None:
            return True

        try:
            import tushare as ts

            token = os.environ.get("TUSHARE_TOKEN")
            if token:
                ts.set_token(token)
                _ts_timeout = int(os.environ.get("TUSHARE_TIMEOUT", "120"))
                cls._pro = ts.pro_api(timeout=_ts_timeout)
                cls.available = True
                return True
            logger.warning("Tushare 不可用: TUSHARE_TOKEN 环境变量未设置")
            return False
        except ImportError:
            logger.warning("Tushare 不可用: tushare 模块未安装")
            return False
        except Exception as e:
            logger.warning("Tushare 初始化失败: %s", e, exc_info=True)
            return False

    @classmethod
    def get_prices(cls, ticker: str, start_date: str, end_date: str, period: str = "daily") -> list[Price]:
        """
        通过 Tushare 获取价格数据

        Args:
            ticker: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 周期

        Returns:
            List[Price]: 价格数据列表
        """
        if not cls._init_tushare():
            raise DataSourceError("Tushare 不可用，请设置 TUSHARE_TOKEN 环境变量")

        try:
            from src.tools.tushare_api import (
                _apply_qfq_adjustment,
                _cached_tushare_dataframe_call,
            )

            ts_code = to_tushare_code(ticker)
            start_date_fmt = start_date.replace("-", "")
            end_date_fmt = end_date.replace("-", "")

            df = _cached_tushare_dataframe_call(
                cls._pro,
                "daily",
                ts_code=ts_code,
                start_date=start_date_fmt,
                end_date=end_date_fmt,
            )

            if df is None or df.empty:
                raise DataSourceError(f"Tushare 返回空数据: {ticker}")

            # NS-9: apply forward-adjustment (前复权 qfq) to remove ex-dividend
            # gaps. Mirrors R37 _fetch_tushare_ashare_prices_df in
            # src/tools/tushare_api.py. Without qfq, raw close gaps down across
            # any ex-dividend day (送股/分红/配股), fabricating phantom losses
            # that corrupt return/ATR/stop-loss/drawdown downstream. If
            # adj_factor fetch fails, fall back to raw daily (degrade, don't
            # block — a backtest with unadjusted prices is still runnable,
            # just less accurate on ex-div days).
            try:
                adj_df = _cached_tushare_dataframe_call(
                    cls._pro,
                    "adj_factor",
                    ts_code=ts_code,
                    start_date=start_date_fmt,
                    end_date=end_date_fmt,
                )
            except Exception as e:
                # NS-17 / BH-017 family sibling: 与 src/data/providers/tushare_provider.py
                # get_prices adj_factor 路径同族残留 (NS-9/R37 复权 drain)。adj_factor
                # 抓取失败时降级到未复权价格是有意为之 (backtest 仍可跑, 仅在 ex-div
                # 日有 phantom loss), 但之前完全静默 — 运维无法感知 backtest 结果被
                # 未复权价格污染。surface 到 logger.warning 让 operators 能检测到此
                # 降级触发, 并与下游 return/ATR/stop-loss/drawdown 异常关联定位。
                logger.warning(
                    "adj_factor 抓取失败 ts_code=%s, 降级到未复权价格 (ex-div 日将产生 phantom loss): %s",
                    ts_code,
                    e,
                    exc_info=True,
                )
                adj_df = None

            if adj_df is not None and not adj_df.empty:
                df = _apply_qfq_adjustment(df, adj_df)

            prices = []
            for _, row in df.iterrows():
                # R133 (R83/R132 same-class drain): skip rows with NaN/None in any
                # OHLC/vol cell. Tushare daily yields NaN vol on halted/illiquid
                # days; bare ``int(row["vol"])`` raises ValueError, caught by the
                # outer except and re-raised as DataSourceError — dropping the
                # whole ticker's price series on one bad row. Aligns with the
                # sibling AKShareProvider (R83) / build_prices_from_dataframe (R132)
                # pd.notna skip guards.
                ohlc = (row["open"], row["high"], row["low"], row["close"], row["vol"])
                if any(not pd.notna(v) for v in ohlc):
                    continue
                date_str = row["trade_date"]
                date_formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

                price = Price(
                    time=date_formatted,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["vol"]),
                )
                prices.append(price)

            prices.reverse()
            return prices

        except DataSourceError:
            raise
        except Exception as e:
            raise DataSourceError(f"Tushare 获取数据失败: {e}") from e


class BaoStockDataSource(BaseDataSource):
    """BaoStock 数据源"""

    name: str = "baostock"
    available: bool = False

    @classmethod
    def _init_baostock(cls):
        """初始化 BaoStock"""
        try:
            import importlib.util

            if importlib.util.find_spec("baostock") is not None:
                cls.available = True
            else:
                # baostock 未安装: 此前完全静默 (available 默默保持 False, 无任何面包屑),
                # 与 BH-017 silent-degradation 家族同型。发 warning 让运维可定位回退链为何
                # 跳过 BaoStock。
                logger.warning("BaoStock 不可用: baostock 模块未安装")
            return True
        except ImportError:
            logger.warning("BaoStock 不可用: baostock 模块未安装")
            return False

    @classmethod
    def get_prices(cls, ticker: str, start_date: str, end_date: str, period: str = "daily") -> list[Price]:
        """
        通过 BaoStock 获取价格数据

        Args:
            ticker: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 周期

        Returns:
            List[Price]: 价格数据列表
        """
        if not cls._init_baostock():
            raise DataSourceError("BaoStock 不可用，请安装 baostock")

        try:
            import baostock as bs

            bs_code = to_baostock_code(ticker)

            lg = bs.login()
            if lg.error_code != "0":
                raise DataSourceError(f"BaoStock 登录失败: {lg.error_msg}")

            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,volume",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="2",
                )  # NS-9: 前复权 qfq (was "3" 不复权 → 除权除息日假跳空污染收益/ATR/止损/回撤)

                if rs.error_code != "0":
                    raise DataSourceError(f"BaoStock 查询失败: {rs.error_msg}")

                prices = []
                while (rs.error_code == "0") & rs.next():
                    row = rs.get_row_data()
                    # R134 (R83/R132/R133 same-class drain residue): BaoStock
                    # returns empty-string cells for missing OHLC/volume on
                    # halted/illiquid days. The prior guard only checked the OPEN
                    # cell (``row[1]``), so a row with a present open but an empty
                    # volume/high/low/close crashed ``int(float(row[5]))`` /
                    # ``float(row[N])`` with ValueError, dropping the whole ticker's
                    # price series. Skip a row if ANY OHLC/volume cell is empty,
                    # aligning with the sibling df→Price converters' guard.
                    if any(cell == "" or cell is None for cell in row[1:6]):
                        continue

                    price = Price(
                        time=row[0],
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=int(float(row[5])),
                    )
                    prices.append(price)

                return prices

            finally:
                bs.logout()

        except DataSourceError:
            raise
        except Exception as e:
            raise DataSourceError(f"BaoStock 获取数据失败: {e}") from e


class SinaDataSource(BaseDataSource):
    """新浪财经数据源（增强版）"""

    name: str = "sina"
    available: bool = True

    @classmethod
    def get_prices(cls, ticker: str, start_date: str, end_date: str, period: str = "daily") -> list[Price]:
        """
        通过新浪财经获取历史数据（使用模拟数据，因为真实接口暂时不可用）

        Args:
            ticker: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 周期

        Returns:
            List[Price]: 价格数据列表
        """
        try:
            from src.tools.akshare_api import get_sina_historical_data

            return get_sina_historical_data(ticker, start_date, end_date, period)
        except Exception as e:
            raise DataSourceError(f"新浪财经获取数据失败: {e}") from e


class MockDataSource(BaseDataSource):
    """模拟数据源"""

    name: str = "mock"
    available: bool = True

    @classmethod
    def get_prices(cls, ticker: str, start_date: str, end_date: str, period: str = "daily") -> list[Price]:
        """
        获取模拟价格数据

        Args:
            ticker: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 周期

        Returns:
            List[Price]: 模拟价格数据列表
        """
        from src.tools.akshare_api import get_mock_prices

        return get_mock_prices(ticker, start_date, end_date)


# 数据源列表（按优先级排序）
DATA_SOURCES = [
    TushareDataSource,
    BaoStockDataSource,
    SinaDataSource,
    MockDataSource,
]


def get_prices_multi_source(
    ticker: str,
    start_date: str,
    end_date: str,
    period: str = "daily",
    source_preference: list[str] | None = None,
) -> list[Price]:
    """
    多数据源获取价格数据（自动容错）

    Args:
        ticker: 股票代码
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        period: 周期
        source_preference: 数据源优先级列表

    Returns:
        List[Price]: 价格数据列表
    """
    sources = DATA_SOURCES

    if source_preference:
        source_map = {s.name: s for s in DATA_SOURCES}
        sources = [source_map[name] for name in source_preference if name in source_map]

    last_error = None

    for source in sources:
        try:
            logger.debug("尝试使用数据源: %s", source.name)
            prices = source.get_prices(ticker, start_date, end_date, period)
            logger.debug("✓ 数据源 %s 获取成功，共 %d 条数据", source.name, len(prices))
            return prices
        except Exception as e:
            last_error = e
            logger.warning("✗ 数据源 %s 获取失败: %s", source.name, e, exc_info=True)
            continue

    raise DataSourceError(f"所有数据源都失败，最后错误: {last_error}")
