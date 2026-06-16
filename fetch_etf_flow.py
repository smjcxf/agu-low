#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家队ETF资金流向获取脚本（修复版）
监控12只国家队持有的ETF，获取实时行情和资金流向
数据保存至 data/nt_data.json
"""

import akshare as ak
import json
import time
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 12只国家队ETF监控列表
ETF_LIST = [
    # 宽基ETF（8只）
    {"code": "510300", "name": "华泰柏瑞沪深300ETF", "type": "宽基"},
    {"code": "510310", "name": "易方达沪深300ETF", "type": "宽基"},
    {"code": "159919", "name": "嘉实沪深300ETF", "type": "宽基"},
    {"code": "510330", "name": "华夏沪深300ETF", "type": "宽基"},
    {"code": "510050", "name": "华夏上证50ETF", "type": "宽基"},
    {"code": "510500", "name": "南方中证500ETF", "type": "宽基"},
    {"code": "159845", "name": "华夏中证1000ETF", "type": "宽基"},
    {"code": "588000", "name": "华夏科创50ETF", "type": "宽基"},
    # 行业ETF（4只）
    {"code": "512690", "name": "酒ETF", "type": "行业"},
    {"code": "515050", "name": "5G通信ETF", "type": "行业"},
    {"code": "159995", "name": "芯片ETF", "type": "行业"},
    {"code": "512010", "name": "医药ETF", "type": "行业"},
]

def fetch_etf_realtime():
    """获取ETF实时行情（使用更可靠的接口）"""
    print("📊 获取ETF实时行情...")
    etf_data = []
    
    # 方法1：尝试使用 fund_etf_spot_em（东方财富）
    try:
        print("  尝试接口：fund_etf_spot_em...")
        df = ak.fund_etf_spot_em()
        print(f"  ✓ 成功获取 {len(df)} 只ETF数据")
        
        for etf in ETF_LIST:
            try:
                row = df[df['代码'] == etf['code']]
                
                if not row.empty:
                    info = row.iloc[0]
                    etf_data.append({
                        "code": etf['code'],
                        "name": etf['name'],
                        "type": etf['type'],
                        "price": float(info['最新价']),
                        "change_pct": float(info['涨跌幅']),
                        "volume": float(info['成交量']),
                        "amount": float(info['成交额']),
                        "amplitude": float(info['振幅']),
                    })
                    print(f"    ✓ {etf['name']}: {info['最新价']} ({info['涨跌幅']}%)")
                else:
                    print(f"    ✗ {etf['name']} ({etf['code']}): 未找到")
                
                time.sleep(0.1)
            except Exception as e:
                print(f"    ✗ {etf['name']} ({etf['code']}) 处理失败: {e}")
        
        return etf_data
    except Exception as e:
        print(f"  ✗ fund_etf_spot_em 失败: {e}")
    
    # 方法2：备用方案 - 使用 fund_etf_hist_sina 获取历史数据（最新一天作为实时）
    print("  尝试备用接口：fund_etf_hist_sina...")
    for etf in ETF_LIST:
        try:
            df = ak.fund_etf_hist_sina(symbol=etf['code'])
            
            if not df.empty:
                latest = df.iloc[-1]
                # 使用收盘价和开盘价估算涨跌幅
                change_pct = ((latest['close'] - latest['open']) / latest['open'] * 100) if latest['open'] > 0 else 0
                
                etf_data.append({
                    "code": etf['code'],
                    "name": etf['name'],
                    "type": etf['type'],
                    "price": float(latest['close']),
                    "change_pct": float(change_pct),
                    "volume": float(latest['volume']),
                    "amount": float(latest['volume'] * latest['close']),
                    "amplitude": float(((latest['high'] - latest['low']) / latest['low'] * 100) if latest['low'] > 0 else 0),
                })
                print(f"    ✓ {etf['name']}: {latest['close']} ({change_pct:.2f}%) [备用数据]")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"    ✗ {etf['name']} ({etf['code']}) 备用方案失败: {e}")
    
    return etf_data

def generate_alerts(etf_data):
    """生成异动提醒"""
    alerts = []
    
    # 1. 检查大幅涨跌
    for etf in etf_data:
        if abs(etf['change_pct']) >= 2.0:
            alert = {
                "type": "etf",
                "severity": "high" if abs(etf['change_pct']) >= 3.0 else "medium",
                "message": f"{etf['name']} {'大涨' if etf['change_pct'] > 0 else '大跌'} {abs(etf['change_pct']):.2f}%",
                "time": datetime.now().strftime("%H:%M"),
            }
            alerts.append(alert)
    
    # 2. 汇总分析
    if etf_data:
        up_count = sum(1 for etf in etf_data if etf['change_pct'] > 0)
        down_count = len(etf_data) - up_count
        
        summary_alert = {
            "type": "summary",
            "severity": "medium",
            "message": f"ETF监测中，{up_count}涨{down_count}跌",
            "time": datetime.now().strftime("%H:%M"),
        }
        alerts.insert(0, summary_alert)
    
    return alerts

def main():
    print("=" * 60)
    print("🚀 国家队ETF资金流向获取（修复版）")
    print("=" * 60)
    print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 1. 获取实时行情
    etf_data = fetch_etf_realtime()
    print(f"\n✅ 成功获取 {len(etf_data)} 只ETF实时行情")
    print()
    
    # 2. 生成异动提醒
    alerts = generate_alerts(etf_data)
    print(f"📢 生成 {len(alerts)} 条异动提醒")
    print()
    
    # 3. 汇总统计
    up_count = sum(1 for etf in etf_data if etf['change_pct'] > 0) if etf_data else 0
    down_count = len(etf_data) - up_count if etf_data else 0
    
    # 4. 重要日历事件（手动维护，每月更新）
    calendar_events = [
        {"date": "2026-06-05", "title": "美国非农", "type": "data"},
        {"date": "2026-06-08", "title": "中国5月出口", "type": "data"},
        {"date": "2026-06-09", "title": "CPI/PPI", "type": "data"},
        {"date": "2026-06-10", "title": "期权交割", "type": "option"},
        {"date": "2026-06-11", "title": "股指期货交割", "type": "futures"},
        {"date": "2026-06-12", "title": "SpaceX IPO", "type": "data"},
        {"date": "2026-06-15", "title": "MLF操作", "type": "central_bank"},
        {"date": "2026-06-17", "title": "美联储议息", "type": "fomc"},
        {"date": "2026-06-18", "title": "A50交割", "type": "a50"},
        {"date": "2026-06-19", "title": "LPR报价", "type": "central_bank"},
        {"date": "2026-06-22", "title": "中国PMI", "type": "data"},
        {"date": "2026-06-25", "title": "期权交割", "type": "option"},
        {"date": "2026-06-30", "title": "股指期货交割", "type": "futures"},
        {"date": "2026-07-02", "title": "F34窗口", "type": "data"},
        {"date": "2026-07-15", "title": "MLF操作", "type": "central_bank"},
        {"date": "2026-07-16", "title": "美联储议息", "type": "fomc"},
        {"date": "2026-07-20", "title": "LPR报价", "type": "central_bank"},
        {"date": "2026-07-31", "title": "F55窗口", "type": "data"},
    ]
    
    # 5. 保存数据
    result = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "alerts": alerts,
        "etfFlow": {
            "etfs": etf_data,
            "summary": {
                "total": len(ETF_LIST),
                "valid": len(etf_data),
                "up": up_count,
                "down": down_count,
                "alerts_count": len([a for a in alerts if a['type'] != 'summary']),
            }
        },
        "calendar": calendar_events,
    }
    
    output_file = "data/nt_data.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 数据已保存至 {output_file}")
    print(f"⏰ 结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

if __name__ == "__main__":
    main()
