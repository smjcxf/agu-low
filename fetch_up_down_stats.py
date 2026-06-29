#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
涨跌家数统计抓取脚本
收盘后拉取全A股行情，统计涨/跌/平家数，追加到 sh_sz_history.json
v2: 主数据源akshare，失败时自动fallback到新浪API
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DATA_FILE = os.path.join(DATA_DIR, "sh_sz_history.json")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def fetch_via_akshare():
    """主数据源：akshare"""
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    up = int(len(df[df['涨跌幅'] > 0]))
    down = int(len(df[df['涨跌幅'] < 0]))
    flat = int(len(df[df['涨跌幅'] == 0]))
    return up, down, flat

def fetch_via_sina():
    """备用数据源：新浪API分页抓取全A股"""
    log("fallback: 新浪API分页抓取...")
    up = 0
    down = 0
    flat = 0
    page = 1
    per_page = 80
    max_pages = 80  # 最多6400只
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': 'https://finance.sina.com.cn/'
    }
    
    while page <= max_pages:
        url = (
            'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
            'Market_Center.getHQNodeData?page={page}&num={num}&sort=code&asc=1'
            '&node=hs_a&symbol=&_s_r_a=auto'
        ).format(page=page, num=per_page)
        
        try:
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=15)
            text = resp.read().decode('gbk', errors='replace')
            stocks = json.loads(text)
            
            if not stocks:
                break
            
            for s in stocks:
                chg = float(s.get('changepercent', 0) or 0)
                if chg > 0:
                    up += 1
                elif chg < 0:
                    down += 1
                else:
                    flat += 1
            
            if len(stocks) < per_page:
                break
            
            page += 1
            time.sleep(0.3)  # 避免请求过快
            
        except Exception as e:
            log(f"  第{page}页失败: {e}")
            break
    
    total = up + down + flat
    log(f"  新浪统计: {total}只, 涨{up} 跌{down} 平{flat}")
    return up, down, flat if total > 100 else (0, 0, 0)

def fetch_up_down_stats():
    """获取涨跌家数统计（带 fallback）"""
    # 方式1: akshare (3次重试)
    for attempt in range(3):
        try:
            log(f"akshare第{attempt+1}次尝试...")
            up, down, flat = fetch_via_akshare()
            log(f"  akshare: 涨{up} 跌{down} 平{flat}")
            return up, down, flat
        except Exception as e:
            log(f"  失败: {e}")
            if attempt < 2:
                time.sleep(5)
    
    # 方式2: 新浪API fallback
    try:
        up, down, flat = fetch_via_sina()
        if up + down + flat > 100:
            return up, down, flat
    except Exception as e:
        log(f"新浪fallback也失败: {e}")
    
    return None, None, None

def update_data_file(up, down, flat):
    """更新数据文件"""
    if up is None:
        return False
    
    today = datetime.now()
    date_str = f"{today.month}/{today.day}"
    stats = {"date": date_str, "up": up, "down": down, "flat": flat}
    log(f"今日 {date_str}: 涨{up} 跌{down} 平{flat}")
    
    data = {"update_time": "", "amount_history": [], "daily_stats": []}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            log(f"读取现有数据失败: {e}")
    
    daily_stats = data.get("daily_stats", [])
    
    existing_idx = None
    for i, d in enumerate(daily_stats):
        if d.get("date") == date_str:
            existing_idx = i
            break
    
    if existing_idx is not None:
        daily_stats[existing_idx] = stats
        log(f"更新今日数据: {date_str}")
    else:
        daily_stats.append(stats)
        log(f"追加新数据: {date_str}")
    
    if len(daily_stats) > 60:
        daily_stats = daily_stats[-60:]
    
    data["daily_stats"] = daily_stats
    data["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    log(f"已保存: {DATA_FILE}")
    return True

def main():
    log("=" * 40)
    log("涨跌家数统计抓取开始")
    log("=" * 40)
    
    up, down, flat = fetch_up_down_stats()
    if up is not None:
        update_data_file(up, down, flat)
        log("✅ 完成")
    else:
        log("❌ 失败（所有数据源均不可用）")
        sys.exit(1)

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
