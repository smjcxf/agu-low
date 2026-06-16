#!/usr/bin/env python3
"""
fetch_etf_subscription.py
抓取上交所 ETF 份额数据，通过日环比计算申购赎回
输出: data/etf_subscription.json
"""
import akshare as ak
import json
import os
from datetime import datetime, timedelta
import time

DATA_DIR = 'data'
os.makedirs(DATA_DIR, exist_ok=True)

def get_recent_trade_dates(n=60):
    dates = []
    d = datetime.now()
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.strftime('%Y%m%d'))
        d -= timedelta(days=1)
    return list(reversed(dates))

def main():
    dates = get_recent_trade_dates(60)
    print('🔵 抓取上交所 ETF 份额数据（' + str(len(dates)) + ' 个交易日）...')
    result = {'sh': [], 'update_time': ''}
    prev_total = None

    for d in dates:
        try:
            df = ak.fund_etf_scale_sse(date=d)
            if df is None or len(df) == 0:
                continue
            total_shares = df['基金份额'].sum()
            total_bil = round(total_shares / 1e8, 2)
            dt_fmt = str(int(d[4:6])) + '/' + str(int(d[6:8]))
            dt_raw = d[:4] + '-' + d[4:6] + '-' + d[6:]

            entry = {
                'date': dt_fmt,
                'date_raw': dt_raw,
                'total_shares_bil': total_bil,
                'net_subscribe_bil': 0.0
            }

            if prev_total is not None:
                net = round((total_shares - prev_total) / 1e8, 2)
                entry['net_subscribe_bil'] = net
            else:
                entry['net_subscribe_bil'] = 0.0

            result['sh'].append(entry)
            prev_total = total_shares
            print('  ' + dt_fmt + '：总份额 ' + str(total_bil) + ' 亿份，净申购 ' + str(entry['net_subscribe_bil']) + ' 亿份')
        except Exception as e:
            pass
        time.sleep(0.3)

    result['update_time'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    out = os.path.join(DATA_DIR, 'etf_subscription.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print('  ✅ 已保存：' + out + '（' + str(len(result['sh'])) + ' 条）')

if __name__ == '__main__':
    main()
