#!/usr/bin/env python3
"""
华熙生物(688363)真实数据分析脚本
使用AKShare获取的真实财务数据
"""

import sys
import os
sys.path.insert(0, '/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork')

os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta


def get_huaxi_stock_info():
    """获取华熙生物基本信息"""
    info = ak.stock_individual_info_em(symbol="688363")
    info_dict = {}
    for _, row in info.iterrows():
        info_dict[row['item']] = row['value']
    return info_dict


def get_huaxi_yjbb():
    """获取业绩报表数据"""
    results = {}
    
    # 获取2024年度业绩
    try:
        yjbb_2024 = ak.stock_yjbb_em(date="20241231")
        huaxi_2024 = yjbb_2024[yjbb_2024['股票代码'] == '688363']
        if not huaxi_2024.empty:
            results['2024'] = huaxi_2024.iloc[0].to_dict()
    except Exception as e:
        print(f"获取2024业绩失败: {e}")
    
    # 获取2023年度业绩
    try:
        yjbb_2023 = ak.stock_yjbb_em(date="20231231")
        huaxi_2023 = yjbb_2023[yjbb_2023['股票代码'] == '688363']
        if not huaxi_2023.empty:
            results['2023'] = huaxi_2023.iloc[0].to_dict()
    except Exception as e:
        print(f"获取2023业绩失败: {e}")
    
    return results


def get_huaxi_income_statement():
    """获取利润表"""
    try:
        income = ak.stock_financial_report_sina(stock="688363", symbol="利润表")
        return income
    except Exception as e:
        print(f"获取利润表失败: {e}")
        return None


def get_huaxi_balance_sheet():
    """获取资产负债表"""
    try:
        balance = ak.stock_financial_report_sina(stock="688363", symbol="资产负债表")
        return balance
    except Exception as e:
        print(f"获取资产负债表失败: {e}")
        return None


def get_huaxi_cashflow():
    """获取现金流量表"""
    try:
        cashflow = ak.stock_financial_report_sina(stock="688363", symbol="现金流量表")
        return cashflow
    except Exception as e:
        print(f"获取现金流量表失败: {e}")
        return None


def get_huaxi_minute_prices():
    """获取分钟级价格数据"""
    try:
        min_data = ak.stock_zh_a_hist_min_em(symbol="688363", period="1", adjust="qfq")
        return min_data
    except Exception as e:
        print(f"获取分钟数据失败: {e}")
        return None


def print_analysis():
    """打印华熙生物分析报告"""
    
    print("=" * 70)
    print(" 华熙生物(688363) - 真实数据分析报告")
    print("=" * 70)
    
    # 1. 基本信息
    print("\n📊 股票基本信息")
    print("-" * 70)
    try:
        info = get_huaxi_stock_info()
        print(f"  股票代码: {info.get('股票代码', 'N/A')}")
        print(f"  股票名称: {info.get('股票简称', 'N/A')}")
        print(f"  所属行业: {info.get('行业', 'N/A')}")
        print(f"  最新价格: {info.get('最新', 'N/A')} 元")
        print(f"  总市值: {info.get('总市值', 'N/A')} 元")
        print(f"  流通市值: {info.get('流通市值', 'N/A')} 元")
        print(f"  总股本: {info.get('总股本', 'N/A')} 股")
        print(f"  上市时间: {info.get('上市时间', 'N/A')}")
    except Exception as e:
        print(f"获取基本信息失败: {e}")
    
    # 2. 业绩报表
    print("\n💰 业绩报表分析")
    print("-" * 70)
    try:
        yjbb = get_huaxi_yjbb()
        if yjbb:
            print(f"{'指标':<25} {'2024年度':<20} {'2023年度':<20} {'同比变化':<15}")
            print("-" * 70)
            
            if '2024' in yjbb and '2023' in yjbb:
                # 营业收入
                rev_2024 = yjbb['2024'].get('营业总收入-营业总收入', 0)
                rev_2023 = yjbb['2023'].get('营业总收入-营业总收入', 0)
                rev_change = yjbb['2024'].get('营业总收入-同比增长', 0)
                print(f"{'营业总收入(亿元)':<25} {rev_2024/1e8:<20.2f} {rev_2023/1e8:<20.2f} {rev_change:<15.2f}%")
                
                # 净利润
                profit_2024 = yjbb['2024'].get('净利润-净利润', 0)
                profit_2023 = yjbb['2023'].get('净利润-净利润', 0)
                profit_change = yjbb['2024'].get('净利润-同比增长', 0)
                print(f"{'净利润(亿元)':<25} {profit_2024/1e8:<20.2f} {profit_2023/1e8:<20.2f} {profit_change:<15.2f}%")
                
                # 每股收益
                eps_2024 = yjbb['2024'].get('每股收益', 0)
                eps_2023 = yjbb['2023'].get('每股收益', 0)
                print(f"{'每股收益(元)':<25} {eps_2024:<20.2f} {eps_2023:<20.2f}")
                
                # 净资产收益率
                roe_2024 = yjbb['2024'].get('净资产收益率', 0)
                roe_2023 = yjbb['2023'].get('净资产收益率', 0)
                print(f"{'净资产收益率(%)':<25} {roe_2024:<20.2f} {roe_2023:<20.2f}")
                
                # 销售毛利率
                margin_2024 = yjbb['2024'].get('销售毛利率', 0)
                print(f"{'销售毛利率(%)':<25} {margin_2024:<20.2f}")
        else:
            print("无法获取业绩报表")
    except Exception as e:
        print(f"获取业绩报表失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 3. 利润表数据
    print("\n� 利润表数据(最近4期)")
    print("-" * 70)
    try:
        income = get_huaxi_income_statement()
        if income is not None and not income.empty:
            # 显示关键指标
            key_items = ['营业总收入', '营业收入', '营业成本', '营业利润', '利润总额', '净利润']
            print(f"{'项目':<20}", end="")
            for col in income.columns[:4]:
                print(f"{col:<15}", end="")
            print()
            print("-" * 70)
            
            for item in key_items:
                if item in income.index:
                    print(f"{item:<20}", end="")
                    for col in income.columns[:4]:
                        val = income.loc[item, col]
                        if pd.notna(val):
                            print(f"{val/1e8:<15.2f}", end="")
                        else:
                            print(f"{'N/A':<15}", end="")
                    print()
        else:
            print("无法获取利润表")
    except Exception as e:
        print(f"获取利润表失败: {e}")
    
    # 4. 价格数据
    print("\n� 最新价格数据")
    print("-" * 70)
    try:
        min_data = get_huaxi_minute_prices()
        if min_data is not None and not min_data.empty:
            print(f"获取到 {len(min_data)} 条分钟级数据")
            print("\n最近5个交易时段:")
            print(min_data.tail(5)[['时间', '开盘', '收盘', '最高', '最低', '成交量']].to_string(index=False))
            
            # 计算今日统计
            today_data = min_data.tail(240)  # 约一个交易日的数据
            if not today_data.empty:
                print(f"\n今日统计:")
                print(f"  开盘价: {today_data['开盘'].iloc[0]:.2f} 元")
                print(f"  最新价: {today_data['收盘'].iloc[-1]:.2f} 元")
                print(f"  最高价: {today_data['最高'].max():.2f} 元")
                print(f"  最低价: {today_data['最低'].min():.2f} 元")
                print(f"  成交量: {today_data['成交量'].sum():,} 股")
        else:
            print("无法获取价格数据")
    except Exception as e:
        print(f"获取价格数据失败: {e}")
    
    # 5. 分析总结
    print("\n📋 分析总结")
    print("-" * 70)
    try:
        info = get_huaxi_stock_info()
        yjbb = get_huaxi_yjbb()
        
        print(f"【公司概况】")
        print(f"  公司名称: 华熙生物科技股份有限公司")
        print(f"  股票代码: 688363.SH (科创板)")
        print(f"  所属行业: {info.get('行业', 'N/A')}")
        print(f"  上市时间: 2019年11月6日")
        
        print(f"\n【财务状况】")
        if '2024' in yjbb and '2023' in yjbb:
            rev_2024 = yjbb['2024'].get('营业总收入-营业总收入', 0) / 1e8
            rev_2023 = yjbb['2023'].get('营业总收入-营业总收入', 0) / 1e8
            profit_2024 = yjbb['2024'].get('净利润-净利润', 0) / 1e8
            profit_2023 = yjbb['2023'].get('净利润-净利润', 0) / 1e8
            rev_change = yjbb['2024'].get('营业总收入-同比增长', 0)
            profit_change = yjbb['2024'].get('净利润-同比增长', 0)
            
            print(f"  2024年营收: {rev_2024:.2f} 亿元 (同比{rev_change:+.2f}%)")
            print(f"  2024年净利润: {profit_2024:.2f} 亿元 (同比{profit_change:+.2f}%)")
            print(f"  销售毛利率: {yjbb['2024'].get('销售毛利率', 0):.2f}%")
            print(f"  净资产收益率: {yjbb['2024'].get('净资产收益率', 0):.2f}%")
            
            print(f"\n【关键观察】")
            if rev_change < 0:
                print(f"  ⚠️ 营收同比下降 {abs(rev_change):.2f}%，需关注业务增长情况")
            else:
                print(f"  ✅ 营收同比增长 {rev_change:.2f}%")
                
            if profit_change < 0:
                print(f"  ⚠️ 净利润同比下降 {abs(profit_change):.2f}%，盈利能力承压")
            else:
                print(f"  ✅ 净利润同比增长 {profit_change:.2f}%")
        
        print(f"\n【估值信息】")
        print(f"  最新股价: {info.get('最新', 'N/A')} 元")
        print(f"  总市值: {float(info.get('总市值', 0))/1e8:.2f} 亿元")
        
    except Exception as e:
        print(f"生成分析总结失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("⚠️ 免责声明: 以上分析基于AKShare获取的公开历史数据，不构成投资建议。")
    print("   投资有风险，入市需谨慎。")
    print("=" * 70)


if __name__ == "__main__":
    print_analysis()
