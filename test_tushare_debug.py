#!/usr/bin/env python3
"""调试 Tushare 连接"""

import os
import sys
sys.path.insert(0, '/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork')

token = os.environ.get('TUSHARE_TOKEN')
print(f"TUSHARE_TOKEN: {token[:20]}..." if token else "TUSHARE_TOKEN: 未设置")

try:
    import tushare as ts
    print(f"Tushare 版本: {ts.__version__}")
    
    if token:
        ts.set_token(token)
        pro = ts.pro_api()
        print("✓ Tushare Pro API 初始化成功")
        
        # 测试获取日线数据
        print("\n测试获取 600158.SH 日线数据...")
        df = pro.daily(ts_code='600158.SH', start_date='20240101', end_date='20240131')
        if df is not None and not df.empty:
            print(f"✓ 成功获取 {len(df)} 条数据")
            print(df.head())
        else:
            print("✗ 返回空数据")
            print(f"  DataFrame: {df}")
    else:
        print("✗ TUSHARE_TOKEN 未设置")
        
except ImportError:
    print("✗ tushare 未安装")
except Exception as e:
    print(f"✗ 错误: {e}")
    import traceback
    traceback.print_exc()
