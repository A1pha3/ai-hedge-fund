#!/usr/bin/env python3
"""
测试获取股票历史数据功能
"""

import sys
import os
sys.path.insert(0, '/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork')

from src.tools.akshare_api import (
    get_prices,
    get_mock_prices,
    AShareDataError,
    AShareTicker,
    get_realtime_quote_sina,
)


def test_mock_data():
    """测试模拟数据获取"""
    print("=" * 70)
    print("测试 1: 获取模拟历史数据")
    print("=" * 70)
    
    try:
        ticker = "600519"
        start_date = "2025-01-01"
        end_date = "2025-02-24"
        
        prices = get_mock_prices(ticker, start_date, end_date)
        
        print(f"✓ 成功获取 {len(prices)} 条模拟数据")
        print(f"✓ 数据区间: {prices[0].time} 至 {prices[-1].time}")
        print()
        print("最近 5 条数据:")
        print(f"{'日期':<12} {'开盘':<10} {'收盘':<10} {'最高':<10} {'最低':<10} {'成交量':<15}")
        print("-" * 70)
        for p in prices[-5:]:
            print(f"{p.time:<12} {p.open:<10.2f} {p.close:<10.2f} {p.high:<10.2f} {p.low:<10.2f} {p.volume:<15,}")
        
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_sina_realtime_quote():
    """测试新浪财经实时行情"""
    print("\n" + "=" * 70)
    print("测试 2: 获取新浪财经实时行情")
    print("=" * 70)
    
    try:
        ticker = "600519"
        quote = get_realtime_quote_sina(ticker)
        
        print(f"✓ 成功获取股票: {quote['name']}")
        print(f"✓ 当前价格: {quote['current']:.2f}")
        print(f"✓ 今日开盘: {quote['open']:.2f}")
        print(f"✓ 昨日收盘: {quote['close']:.2f}")
        print(f"✓ 最高价: {quote['high']:.2f}")
        print(f"✓ 最低价: {quote['low']:.2f}")
        print(f"✓ 成交量: {quote['volume']:,} 股")
        print(f"✓ 成交金额: {quote['amount']:,.2f} 元")
        print(f"✓ 更新时间: {quote['date']} {quote['time']}")
        
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        print("提示: 可能是网络问题或代理配置问题")
        return False


def test_real_data_with_fallback():
    """测试真实数据获取，失败时使用模拟数据"""
    print("\n" + "=" * 70)
    print("测试 3: 获取真实历史数据 (带模拟数据回退)")
    print("=" * 70)
    
    ticker = "000001"
    start_date = "2025-01-01"
    end_date = "2025-02-24"
    
    try:
        print(f"尝试获取 {ticker} 的真实数据...")
        prices = get_prices(ticker, start_date, end_date)
        
        print(f"✓ 成功获取 {len(prices)} 条真实数据")
        print(f"✓ 数据区间: {prices[0].time} 至 {prices[-1].time}")
        print()
        print("最近 5 条数据:")
        print(f"{'日期':<12} {'开盘':<10} {'收盘':<10} {'最高':<10} {'最低':<10} {'成交量':<15}")
        print("-" * 70)
        for p in prices[-5:]:
            print(f"{p.time:<12} {p.open:<10.2f} {p.close:<10.2f} {p.high:<10.2f} {p.low:<10.2f} {p.volume:<15,}")
        
        return True
    except AShareDataError as e:
        print(f"⚠ 无法获取真实数据: {e}")
        print("使用模拟数据进行演示...")
        
        prices = get_mock_prices(ticker, start_date, end_date)
        
        print(f"✓ 使用模拟数据，获取 {len(prices)} 条数据")
        print(f"✓ 数据区间: {prices[0].time} 至 {prices[-1].time}")
        print()
        print("最近 5 条数据:")
        print(f"{'日期':<12} {'开盘':<10} {'收盘':<10} {'最高':<10} {'最低':<10} {'成交量':<15}")
        print("-" * 70)
        for p in prices[-5:]:
            print(f"{p.time:<12} {p.open:<10.2f} {p.close:<10.2f} {p.high:<10.2f} {p.low:<10.2f} {p.volume:<15,}")
        
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ticker_parsing():
    """测试股票代码解析"""
    print("\n" + "=" * 70)
    print("测试 4: 股票代码解析")
    print("=" * 70)
    
    test_cases = [
        "600519",
        "000001", 
        "300001",
        "sh600000",
        "sz000001",
    ]
    
    all_passed = True
    for symbol in test_cases:
        try:
            ticker = AShareTicker.from_symbol(symbol)
            print(f"✓ {symbol:12} -> 代码: {ticker.symbol:6} 交易所: {ticker.exchange:2} 完整代码: {ticker.full_code}")
        except Exception as e:
            print(f"✗ {symbol:12} -> 解析失败: {e}")
            all_passed = False
    
    return all_passed


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("股票历史数据获取功能测试")
    print("=" * 70 + "\n")
    
    results = []
    
    results.append(("模拟数据获取", test_mock_data()))
    results.append(("新浪实时行情", test_sina_realtime_quote()))
    results.append(("真实/模拟数据回退", test_real_data_with_fallback()))
    results.append(("股票代码解析", test_ticker_parsing()))
    
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)
    
    passed = 0
    total = len(results)
    
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{name:25} {status}")
        if result:
            passed += 1
    
    print()
    print(f"总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("✓ 所有测试通过！")
    else:
        print("⚠ 部分测试失败，请检查网络连接或代理配置")
