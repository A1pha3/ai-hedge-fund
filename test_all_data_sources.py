#!/usr/bin/env python3
"""
测试所有A股数据源
"""

import sys
from datetime import datetime, timedelta

sys.path.insert(0, '/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork')


def test_tushare():
    """测试 Tushare 数据源"""
    print("\n" + "="*80)
    print("测试 Tushare 数据源")
    print("="*80)
    
    try:
        from src.tools.ashare_data_sources import TushareDataSource
        
        if not TushareDataSource.available and not TushareDataSource._init_tushare():
            print("  ⚠️  Tushare 不可用（需要设置 TUSHARE_TOKEN）")
            return False
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        prices = TushareDataSource.get_prices("600519", start_date, end_date)
        
        print(f"  ✓ 成功获取 {len(prices)} 条数据")
        if prices:
            print(f"    最新日期: {prices[-1].time}")
            print(f"    最新收盘价: {prices[-1].close}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def test_baostock():
    """测试 BaoStock 数据源"""
    print("\n" + "="*80)
    print("测试 BaoStock 数据源")
    print("="*80)
    
    try:
        from src.tools.ashare_data_sources import BaoStockDataSource
        
        if not BaoStockDataSource.available and not BaoStockDataSource._init_baostock():
            print("  ⚠️  BaoStock 不可用（需要安装 baostock）")
            return False
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        prices = BaoStockDataSource.get_prices("600519", start_date, end_date)
        
        print(f"  ✓ 成功获取 {len(prices)} 条数据")
        if prices:
            print(f"    最新日期: {prices[-1].time}")
            print(f"    最新收盘价: {prices[-1].close}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def test_sina_data_source():
    """测试新浪财经数据源"""
    print("\n" + "="*80)
    print("测试新浪财经数据源")
    print("="*80)
    
    try:
        from src.tools.ashare_data_sources import SinaDataSource
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        prices = SinaDataSource.get_prices("600519", start_date, end_date)
        
        print(f"  ✓ 成功获取 {len(prices)} 条数据")
        if prices:
            print(f"    最新日期: {prices[-1].time}")
            print(f"    最新收盘价: {prices[-1].close}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def test_mock_data_source():
    """测试模拟数据源"""
    print("\n" + "="*80)
    print("测试模拟数据源")
    print("="*80)
    
    try:
        from src.tools.ashare_data_sources import MockDataSource
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        prices = MockDataSource.get_prices("600519", start_date, end_date)
        
        print(f"  ✓ 成功获取 {len(prices)} 条数据")
        if prices:
            print(f"    最新日期: {prices[-1].time}")
            print(f"    最新收盘价: {prices[-1].close}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def test_multi_source():
    """测试多数据源自动容错"""
    print("\n" + "="*80)
    print("测试多数据源自动容错")
    print("="*80)
    
    try:
        from src.tools.ashare_data_sources import get_prices_multi_source
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        prices = get_prices_multi_source("600519", start_date, end_date)
        
        print(f"  ✓ 成功获取 {len(prices)} 条数据")
        if prices:
            print(f"    最新日期: {prices[-1].time}")
            print(f"    最新收盘价: {prices[-1].close}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def test_robust_prices():
    """测试稳健数据获取"""
    print("\n" + "="*80)
    print("测试稳健数据获取 (get_prices_robust)")
    print("="*80)
    
    try:
        from src.tools.akshare_api import get_prices_robust
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        prices = get_prices_robust("600519", start_date, end_date)
        
        print(f"  ✓ 成功获取 {len(prices)} 条数据")
        if prices:
            print(f"    最新日期: {prices[-1].time}")
            print(f"    最新收盘价: {prices[-1].close}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def test_sina_realtime_quote():
    """测试新浪实时行情"""
    print("\n" + "="*80)
    print("测试新浪实时行情")
    print("="*80)
    
    try:
        from src.tools.akshare_api import get_realtime_quote_sina
        
        quote = get_realtime_quote_sina("600519")
        
        print(f"  ✓ 成功获取实时行情")
        print(f"    股票名称: {quote['name']}")
        print(f"    最新价格: {quote['current']}")
        if quote['close'] > 0:
            change_pct = (quote['current'] - quote['close']) / quote['close'] * 100
            print(f"    涨跌幅: {change_pct:.2f}%")
        
        return True
        
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def main():
    """主测试函数"""
    print("="*80)
    print("A股多数据源测试套件")
    print("="*80)
    
    results = {}
    
    results["Tushare"] = test_tushare()
    results["BaoStock"] = test_baostock()
    results["新浪财经"] = test_sina_data_source()
    results["模拟数据"] = test_mock_data_source()
    results["多数据源容错"] = test_multi_source()
    results["稳健数据获取"] = test_robust_prices()
    results["新浪实时行情"] = test_sina_realtime_quote()
    
    print("\n" + "="*80)
    print("测试结果汇总")
    print("="*80)
    
    for name, success in results.items():
        status = "✓ 通过" if success else "✗ 失败"
        print(f"  {name}: {status}")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"\n总计: {passed}/{total} 测试通过")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
