#!/usr/bin/env python3
"""
诊断 AKShare 网络连接问题
"""

import sys
import os
sys.path.insert(0, '/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork')

import requests
import urllib3


def check_proxy_settings():
    """检查代理设置"""
    print("=" * 70)
    print("1. 检查系统代理设置")
    print("=" * 70)
    
    print("\n环境变量中的代理设置:")
    proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']
    for var in proxy_vars:
        value = os.environ.get(var)
        if value:
            print(f"  {var}: {value}")
        else:
            print(f"  {var}: (未设置)")
    
    print("\nurllib3 代理设置:")
    try:
        import urllib.request
        print(f"  urllib.request.getproxies(): {urllib.request.getproxies()}")
    except Exception as e:
        print(f"  (获取代理信息失败: {e})")


def test_direct_connection():
    """测试直接连接（禁用代理）"""
    print("\n" + "=" * 70)
    print("2. 测试直接连接（禁用代理）")
    print("=" * 70)
    
    test_urls = [
        "https://www.baidu.com",
        "https://push2his.eastmoney.com",
        "https://82.push2.eastmoney.com",
    ]
    
    session = requests.Session()
    session.trust_env = False
    
    for url in test_urls:
        try:
            print(f"\n测试连接: {url}")
            response = session.get(url, timeout=10, verify=False)
            print(f"  ✓ 连接成功! 状态码: {response.status_code}")
        except Exception as e:
            print(f"  ✗ 连接失败: {e}")


def test_without_proxy():
    """测试不使用代理连接东方财富接口"""
    print("\n" + "=" * 70)
    print("3. 测试 AKShare 接口（禁用代理）")
    print("=" * 70)
    
    try:
        import akshare as ak
        print("✓ AKShare 已安装")
    except ImportError:
        print("✗ AKShare 未安装")
        return
    
    try:
        print("\n尝试获取股票历史数据（禁用代理）...")
        
        import requests
        original_get = requests.get
        
        def patched_get(*args, **kwargs):
            kwargs['proxies'] = {'http': None, 'https': None}
            return original_get(*args, **kwargs)
        
        requests.get = patched_get
        
        df = ak.stock_zh_a_hist(
            symbol="000001",
            period="daily",
            start_date="20250101",
            end_date="20250201",
            adjust="qfq"
        )
        
        if not df.empty:
            print(f"✓ 成功获取数据!")
            print(f"  数据行数: {len(df)}")
            print(f"  列名: {list(df.columns)}")
            print("\n前 5 行数据:")
            print(df.head())
        else:
            print("✗ 获取的数据为空")
            
    except Exception as e:
        print(f"✗ 获取数据失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        requests.get = original_get


def test_modified_akshare_api():
    """测试我们自己的 akshare_api 模块"""
    print("\n" + "=" * 70)
    print("4. 测试 akshare_api 模块（使用模拟数据）")
    print("=" * 70)
    
    from src.tools.akshare_api import get_prices, get_mock_prices, AShareDataError
    
    ticker = "000001"
    start_date = "2025-01-01"
    end_date = "2025-02-01"
    
    print(f"\n尝试获取模拟数据:")
    prices = get_mock_prices(ticker, start_date, end_date)
    print(f"✓ 成功获取 {len(prices)} 条模拟数据")
    
    print(f"\n尝试获取真实数据（应该会失败，但会优雅处理）:")
    try:
        prices = get_prices(ticker, start_date, end_date)
    except AShareDataError as e:
        print(f"  预期的错误: {e}")
        print("  ✓ 错误处理正常工作正常")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("AKShare 网络连接诊断")
    print("=" * 70)
    
    check_proxy_settings()
    test_direct_connection()
    test_without_proxy()
    test_modified_akshare_api()
    
    print("\n" + "=" * 70)
    print("诊断完成")
    print("=" * 70)
    print("\n建议:")
    print("  1. 如果问题是代理导致的，可以:")
    print("     - 禁用系统代理")
    print("     - 或使用模拟数据进行开发")
    print("  2. 检查防火墙是否阻止了东方财富的连接")
