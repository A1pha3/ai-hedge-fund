"""
测试 A 股数据获取功能
"""

import sys
sys.path.insert(0, '/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork')

from src.tools.akshare_api import (
    get_prices,
    get_financial_metrics,
    get_stock_info,
    search_stocks,
    is_ashare,
    AShareTicker,
)


def test_ashare_detection():
    """测试 A 股代码识别"""
    print("=" * 60)
    print("测试 A 股代码识别")
    print("=" * 60)
    
    test_cases = [
        ("600000", True, "浦发银行"),
        ("000001", True, "平安银行"),
        ("300001", True, "特锐德"),
        ("sh600000", True, "上交所格式"),
        ("sz000001", True, "深交所格式"),
        ("AAPL", False, "美股代码"),
        ("MSFT", False, "美股代码"),
    ]
    
    for ticker, expected, desc in test_cases:
        result = is_ashare(ticker)
        status = "✓" if result == expected else "✗"
        print(f"{status} {ticker:12} -> {result:5} ({desc})")
    
    print()


def test_ticker_parsing():
    """测试股票代码解析"""
    print("=" * 60)
    print("测试股票代码解析")
    print("=" * 60)
    
    test_cases = ["600000", "000001", "300001", "sh600000", "sz000001"]
    
    for symbol in test_cases:
        ticker = AShareTicker.from_symbol(symbol)
        print(f"输入: {symbol:12} -> 代码: {ticker.symbol:6} 交易所: {ticker.exchange:2} 完整代码: {ticker.full_code}")
    
    print()


def test_stock_search():
    """测试股票搜索"""
    print("=" * 60)
    print("测试股票搜索 (搜索'茅台')")
    print("=" * 60)
    
    results = search_stocks("茅台")
    for stock in results[:5]:
        print(f"代码: {stock['symbol']:6} 名称: {stock['name']:10} 价格: {stock['price']:8.2f} 涨跌: {stock['change']:+.2f}%")
    
    print()


def test_stock_info():
    """测试获取股票信息"""
    print("=" * 60)
    print("测试获取股票信息 (600519 贵州茅台)")
    print("=" * 60)
    
    info = get_stock_info("600519")
    if info:
        for key, value in list(info.items())[:10]:
            print(f"{key:20}: {value}")
    else:
        print("未能获取股票信息")
    
    print()


def test_price_data():
    """测试获取价格数据"""
    print("=" * 60)
    print("测试获取价格数据 (000001 平安银行)")
    print("=" * 60)
    
    prices = get_prices("000001", "2025-01-01", "2025-02-01")
    if prices:
        print(f"获取到 {len(prices)} 条价格数据")
        print("\n最近5天数据:")
        for price in prices[-5:]:
            print(f"日期: {price.date} 开盘: {price.open:8.2f} 收盘: {price.close:8.2f} 最高: {price.high:8.2f} 最低: {price.low:8.2f} 成交量: {price.volume}")
    else:
        print("未能获取价格数据")
    
    print()


def test_financial_metrics():
    """测试获取财务指标"""
    print("=" * 60)
    print("测试获取财务指标 (000001 平安银行)")
    print("=" * 60)
    
    metrics = get_financial_metrics("000001", "2025-02-01", limit=5)
    if metrics:
        print(f"获取到 {len(metrics)} 条财务指标")
        for metric in metrics[:3]:
            print(f"\n报告期: {metric.report_period}")
            print(f"  收入: {metric.revenue}")
            print(f"  净利润: {metric.net_income}")
            print(f"  EPS: {metric.eps}")
            print(f"  ROE: {metric.roe}")
            print(f"  负债率: {metric.debt_to_equity}")
    else:
        print("未能获取财务指标")
    
    print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("A 股数据接口测试")
    print("=" * 60 + "\n")
    
    try:
        test_ashare_detection()
        test_ticker_parsing()
        test_stock_search()
        test_stock_info()
        test_price_data()
        test_financial_metrics()
        
        print("=" * 60)
        print("测试完成！")
        print("=" * 60)
    except Exception as e:
        print(f"\n测试出错: {e}")
        import traceback
        traceback.print_exc()
