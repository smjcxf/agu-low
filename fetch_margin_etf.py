#!/usr/bin/env python3
"""
fetch_margin_etf.py
抓取两融（融资融券）日数据和 ETF 申购赎回数据，保存为 JSON
用法：python fetch_margin_etf.py
"""
import akshare as ak
import json
import os
from datetime import datetime, timedelta
import time

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)


def get_recent_trade_dates(n=90):
    """生成最近 n 个交易日日期列表（简单跳过周末）"""
    dates = []
    d = datetime.now()
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.strftime('%Y%m%d'))
        d -= timedelta(days=1)
    return list(reversed(dates))


# ============================================================
# 1. 两融数据（上交所，深交所单独补）
# ============================================================
def fetch_margin_data(days=90):
    """抓取上交所两融汇总数据（深交所接口有bug，暂时跳过）"""
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
    result = {'sh': [], 'sz': [], 'update_time': ''}

    # 上交所：支持日期范围
    try:
        df_sh = ak.stock_margin_sse(start_date=start, end_date=end)
        for _, row in df_sh.iterrows():
            dt = str(row['信用交易日期'])
            try:
                d_obj = datetime.strptime(dt, '%Y%m%d')
                dt_fmt = str(d_obj.month) + '/' + str(d_obj.day)
            except Exception:
                dt_fmt = dt
            result['sh'].append({
                'date': dt_fmt,
                'date_raw': dt,
                'rz_balance': round(float(row['融资余额']) / 1e8),
                'rz_buy': round(float(row['融资买入额']) / 1e8),
                'rq_balance_amt': round(float(row['融券余量金额']) / 1e8),
                'total': round(float(row['融资融券余额']) / 1e8),
            })
        # 按日期升序排列（旧→新），确保图表X轴正确
        result['sh'].sort(key=lambda x: x['date_raw'])
        print('  ✅ 上交所两融：%d 条' % len(result['sh']))
    except Exception as e:
        print('  ❌ 上交所两融失败:', e)

    result['update_time'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    return result


# ============================================================
# 2. ETF 申购赎回数据（通过份额变化计算）
# ============================================================
def fetch_etf_subscription(days=60):
    """
    抓取上交所 ETF 份额数据，通过日环比计算申购赎回
    份额增加 = 净申购；份额减少 = 净赎回
    """
    dates = get_recent_trade_dates(days)
    result = {'sh': [], 'update_time': ''}

    prev_total = None
    for d in dates:
        try:
            df = ak.fund_etf_scale_sse(date=d)
            if df is None or len(df) == 0:
                continue
            total_shares = df['基金份额'].sum()
            total_bil = round(total_shares / 1e8, 2)
            dt_fmt = d[:4] + '-' + d[4:6] + '-' + d[6:]
            dt_short = str(int(d[4:6])) + '/' + str(int(d[6:8]))

            entry = {'date': dt_short, 'date_raw': dt_fmt, 'total_shares_bil': total_bil}

            if prev_total is not None:
                net = round((total_shares - prev_total) / 1e8, 2)
                entry['net_subscribe_bil'] = net
            else:
                entry['net_subscribe_bil'] = 0.0

            result['sh'].append(entry)
            prev_total = total_shares
        except Exception as e:
            pass
        time.sleep(0.3)

    print('  ✅ 上交所ETF数据：%d 条' % len(result['sh']))
    result['update_time'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    return result


def main():
    # ⚠️ 两融数据由 fetch_margin.py 独立维护，此处仅采集 ETF 申购赎回
    print('🔵 开始抓取 ETF 申购赎回数据...')
    etf_data = fetch_etf_subscription(60)
    etf_path = os.path.join(DATA_DIR, 'etf_subscription.json')
    with open(etf_path, 'w', encoding='utf-8') as f:
        json.dump(etf_data, f, ensure_ascii=False, indent=2)
    print('  💾 已保存：%s' % etf_path)

    print('✅ 全部完成！')


if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise

