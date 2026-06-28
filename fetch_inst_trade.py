#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机构买卖统计抓取 — 龙虎榜机构净买卖排名
输出: data/inst_trade.json
"""
import json, os, sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DATA_FILE = os.path.join(DATA_DIR, "inst_trade.json")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def main():
    log("=" * 40)
    log("机构买卖统计抓取")
    log("=" * 40)
    
    today = datetime.now().strftime('%Y%m%d')
    
    try:
        import akshare as ak
        df = ak.stock_lhb_jgmmtj_em(start_date=today, end_date=today)
    except Exception as e:
        log(f"akshare失败: {e}")
        sys.exit(1)
    
    if len(df) == 0:
        log("今日无龙虎榜机构数据（非交易日或尚未公布）")
        sys.exit(0)
    
    # Deduplicate by code (keep max net buy)
    deduped = {}
    for _, r in df.iterrows():
        code = str(r['代码'])
        amt = float(r['机构买入净额'])
        if code not in deduped or abs(amt) > abs(deduped[code]['net_amt']):
            deduped[code] = {
                'code': code,
                'name': r['名称'],
                'close': float(r['收盘价']),
                'pct': float(r['涨跌幅']),
                'buy_inst': int(r['买方机构数']),
                'sell_inst': int(r['卖方机构数']),
                'buy_amt': float(r['机构买入总额']),
                'sell_amt': float(r['机构卖出总额']),
                'net_amt': amt,
                'total_amt': float(r['市场总成交额']),
                'net_ratio': float(r['机构净买额占总成交额比']),
                'turnover': float(r['换手率']),
                'reason': r['上榜原因'][:80],
            }
    
    stocks = sorted(deduped.values(), key=lambda x: x['net_amt'], reverse=True)
    
    # Stats
    total_net = sum(s['net_amt'] for s in stocks)
    buy_count = sum(1 for s in stocks if s['net_amt'] > 0)
    sell_count = sum(1 for s in stocks if s['net_amt'] < 0)
    
    # Top 10
    top_buy = [s for s in stocks if s['net_amt'] > 0][:10]
    top_sell = sorted([s for s in stocks if s['net_amt'] < 0], key=lambda x: x['net_amt'])[:5]
    
    output = {
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'date': today,
        'total_net': round(total_net / 100000000, 2),  # 元 → 亿
        'buy_count': buy_count,
        'sell_count': sell_count,
        'total_count': len(stocks),
        'top_buy': top_buy,
        'top_sell': top_sell,
        'all': stocks,
    }
    
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    total_net_yi = round(total_net / 100000000, 2)
    log(f"✅ {len(stocks)}只股票, 机构净{('买' if total_net > 0 else '卖')}{abs(total_net_yi):.1f}亿")
    log(f"   净买{buy_count}只, 净卖{sell_count}只")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise

