#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深入验证 mootdx category 参数
比较不同 category 的实际数据值，确认是否为同一份数据
"""
import sys
sys.path.insert(0, r"E:\workspace\stock-scanner")

try:
    from mootdx.quotes import Quotes
    
    client = Quotes.factory(market='std')
    
    test_symbol = "600519"  # 贵州茅台
    
    print(f"测试股票: {test_symbol}")
    print("=" * 60)
    
    # 获取不同 category 的数据
    data = {}
    for cat in [0, 4, 9]:  # 0=5分钟？, 4=日线？, 9=未知
        print(f"\n获取 category={cat}...")
        try:
            df = client.bars(symbol=test_symbol, category=cat, offset=50)
            if df is not None and len(df) > 0:
                data[cat] = df
                print(f"  成功: {len(df)} 条")
                print(f"  最新: {df.index[-1]}, close={df['close'].iloc[-1]}")
                print(f"  最旧: {df.index[0]}, close={df['close'].iloc[0]}")
            else:
                print(f"  无数据")
        except Exception as e:
            print(f"  失败: {e}")
    
    # 比较数据是否相同
    print("\n" + "=" * 60)
    print("数据比较:")
    
    if 0 in data and 4 in data:
        df0 = data[0]
        df4 = data[4]
        
        # 比较收盘价
        close0 = df0['close'].tolist()
        close4 = df4['close'].tolist()
        
        if close0 == close4:
            print("  ❌ category=0 和 category=4 的收盘价完全相同!")
            print("  ❌ mootdx 可能忽略了 category 参数")
        else:
            print("  ✅ category=0 和 category=4 的数据不同")
            print(f"  category=0 最新收盘: {close0[-1]}")
            print(f"  category=4 最新收盘: {close4[-1]}")
    
    if 4 in data and 9 in data:
        df4 = data[4]
        df9 = data[9]
        
        close4 = df4['close'].tolist()
        close9 = df9['close'].tolist()
        
        if close4 == close9:
            print("  ❌ category=4 和 category=9 的收盘价完全相同!")
            print("  ❌ category=9 返回的是日线数据（与 category=4 相同）")
        else:
            print("  ✅ category=4 和 category=9 的数据不同")
    
    # 检查数据粒度
    print("\n" + "=" * 60)
    print("数据粒度分析:")
    
    for cat in [0, 4, 9]:
        if cat in data:
            df = data[cat]
            if len(df) > 10:
                # 检查时间戳的小时部分
                hours = [idx.hour for idx in df.index[-10:]]
                minutes = [idx.minute for idx in df.index[-10:]]
                print(f"  category={cat}: 小时={set(hours)}, 分钟={set(minutes)}")
                
                # 如果小时都是 15（收盘时间），说明是日线数据
                if all(h == 15 for h in hours):
                    print(f"    → 所有时间戳都是 15:00:00，疑似日线数据")
    
    print("\n" + "=" * 60)
    print("结论:")
    print("  如果所有 category 都返回相同的数据（时间戳 15:00:00），")
    print("  则 mootdx 的 category 参数可能无效，或 TDX 服务器配置问题")
    
except ImportError as e:
    print(f"导入失败: {e}")
except Exception as e:
    print(f"未知错误: {e}")
    import traceback
    traceback.print_exc()
