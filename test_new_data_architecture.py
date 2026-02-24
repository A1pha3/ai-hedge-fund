"""
新数据架构测试脚本

测试新的数据源架构是否正常工作
"""

import asyncio
import sys
sys.path.insert(0, '/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork')

from src.data import (
    get_router,
    AKShareProvider,
    TushareProvider,
    DataValidator,
    DataCleaner,
    get_enhanced_cache,
)
from src.data.api_new import (
    get_prices,
    get_financial_metrics,
    prices_to_df,
)


async def test_providers():
    """测试数据提供商"""
    print("=" * 60)
    print("测试数据提供商")
    print("=" * 60)
    
    # 测试 AKShare
    print("\n1. 测试 AKShareProvider")
    try:
        akshare = AKShareProvider(priority=10)
        is_healthy = await akshare.health_check()
        print(f"   ✓ AKShare 健康状态: {'健康' if is_healthy else '不健康'}")
        
        if is_healthy:
            # 测试获取价格
            response = await akshare.get_prices("600519", "2024-01-01", "2024-01-10")
            print(f"   ✓ 获取价格数据: {len(response.data)} 条")
            print(f"   ✓ 延迟: {response.latency_ms:.2f} ms")
            
            # 显示第一条数据
            if response.data:
                price = response.data[0]
                print(f"   ✓ 示例数据: {price.time} 开盘:{price.open} 收盘:{price.close}")
    except Exception as e:
        print(f"   ✗ AKShare 测试失败: {e}")
    
    # 测试 Tushare
    print("\n2. 测试 TushareProvider")
    try:
        tushare = TushareProvider(priority=5)
        is_healthy = await tushare.health_check()
        print(f"   ✓ Tushare 健康状态: {'健康' if is_healthy else '不健康'}")
        
        if is_healthy:
            response = await tushare.get_prices("600519", "2024-01-01", "2024-01-10")
            print(f"   ✓ 获取价格数据: {len(response.data)} 条")
            print(f"   ✓ 延迟: {response.latency_ms:.2f} ms")
    except Exception as e:
        print(f"   ✗ Tushare 测试失败: {e}")
    
    # 关闭提供商
    await akshare.close()
    await tushare.close()


async def test_router():
    """测试数据路由器"""
    print("\n" + "=" * 60)
    print("测试数据路由器")
    print("=" * 60)
    
    router = get_router()
    
    print(f"\n1. 已注册提供商: {len(router.providers)} 个")
    for provider in router.providers:
        print(f"   - {provider.name} (优先级: {provider.priority})")
    
    print("\n2. 测试路由获取价格数据")
    try:
        response = await router.get_prices("600519", "2024-01-01", "2024-01-10")
        print(f"   ✓ 数据来源: {response.source}")
        print(f"   ✓ 数据条数: {len(response.data)}")
        print(f"   ✓ 是否缓存: {response.cached}")
        if response.latency_ms:
            print(f"   ✓ 请求延迟: {response.latency_ms:.2f} ms")
    except Exception as e:
        print(f"   ✗ 路由测试失败: {e}")
    
    print("\n3. 测试路由获取财务指标")
    try:
        response = await router.get_financial_metrics("600519", "2024-01-31", limit=5)
        print(f"   ✓ 数据来源: {response.source}")
        print(f"   ✓ 数据条数: {len(response.data)}")
    except Exception as e:
        print(f"   ✗ 财务指标测试失败: {e}")


async def test_validation():
    """测试数据验证"""
    print("\n" + "=" * 60)
    print("测试数据验证和清洗")
    print("=" * 60)
    
    from src.data.models import Price
    
    # 创建测试数据（包含一些异常值）
    test_prices = [
        Price(time="2024-01-01", open=100.0, high=105.0, low=99.0, close=102.0, volume=10000),
        Price(time="2024-01-02", open=102.0, high=106.0, low=101.0, close=105.0, volume=12000),
        Price(time="2024-01-03", open=105.0, high=103.0, low=104.0, close=104.0, volume=8000),  # 异常：high < open
        Price(time="2024-01-04", open=104.0, high=108.0, low=103.0, close=107.0, volume=15000),
        Price(time="2024-01-01", open=100.0, high=105.0, low=99.0, close=102.0, volume=10000),  # 重复
    ]
    
    print(f"\n1. 原始数据: {len(test_prices)} 条")
    
    # 验证
    valid_prices = DataValidator.validate_prices(test_prices)
    print(f"   ✓ 验证通过: {len(valid_prices)} 条")
    
    # 清洗
    cleaned_prices = DataCleaner.clean_prices(valid_prices)
    print(f"   ✓ 清洗后: {len(cleaned_prices)} 条（去重+排序）")


async def test_cache():
    """测试缓存"""
    print("\n" + "=" * 60)
    print("测试增强缓存")
    print("=" * 60)
    
    cache = get_enhanced_cache()
    
    print("\n1. 测试 LRU 缓存")
    cache.set("test_key", {"data": "test_value"})
    value = cache.get("test_key")
    print(f"   ✓ 设置并获取: {value}")
    
    print("\n2. 缓存统计")
    stats = cache.get_stats()
    print(f"   ✓ LRU 命中: {stats['lru_hits']}")
    print(f"   ✓ Redis 命中: {stats['redis_hits']}")
    print(f"   ✓ 未命中: {stats['misses']}")
    print(f"   ✓ 命中率: {stats['hit_rate']:.2%}")


async def test_api():
    """测试新 API"""
    print("\n" + "=" * 60)
    print("测试新 API 接口")
    print("=" * 60)
    
    print("\n1. 测试 get_prices")
    try:
        prices = await get_prices("600519", "2024-01-01", "2024-01-10")
        print(f"   ✓ 获取到 {len(prices)} 条价格数据")
        
        # 转换为 DataFrame
        df = prices_to_df(prices)
        print(f"   ✓ 转换为 DataFrame: {df.shape}")
        print(f"   ✓ 列: {list(df.columns)}")
    except Exception as e:
        print(f"   ✗ 测试失败: {e}")
    
    print("\n2. 测试 get_financial_metrics")
    try:
        metrics = await get_financial_metrics("600519", "2024-01-31", limit=3)
        print(f"   ✓ 获取到 {len(metrics)} 条财务指标")
        if metrics:
            m = metrics[0]
            print(f"   ✓ P/E: {m.price_to_earnings_ratio}")
            print(f"   ✓ P/B: {m.price_to_book_ratio}")
            print(f"   ✓ ROE: {m.return_on_equity}")
    except Exception as e:
        print(f"   ✗ 测试失败: {e}")


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("新数据架构测试")
    print("=" * 60)
    
    try:
        await test_providers()
    except Exception as e:
        print(f"提供商测试失败: {e}")
    
    try:
        await test_router()
    except Exception as e:
        print(f"路由器测试失败: {e}")
    
    try:
        await test_validation()
    except Exception as e:
        print(f"验证测试失败: {e}")
    
    try:
        await test_cache()
    except Exception as e:
        print(f"缓存测试失败: {e}")
    
    try:
        await test_api()
    except Exception as e:
        print(f"API 测试失败: {e}")
    
    # 关闭路由器
    try:
        router = get_router()
        await router.close()
        print("\n✓ 所有连接已关闭")
    except Exception as e:
        print(f"\n✗ 关闭连接失败: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
