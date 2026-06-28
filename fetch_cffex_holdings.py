#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中信期货持仓数据抓取 — 从CFFEX会员持仓排名提取中信净多/净空
输出: data/cffex_holdings.json
"""
import json
import os
import sys
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DATA_FILE = os.path.join(DATA_DIR, "cffex_holdings.json")

# 四大股指期货
CONTRACTS = {
    'IF': '沪深300',
    'IC': '中证500',
    'IM': '中证1000',
    'IH': '上证50',
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def get_main_contract(contracts):
    """从合约列表中找到最近月主力合约"""
    for prefix in CONTRACTS:
        months = sorted([k for k in contracts if k.startswith(prefix)])
        if months:
            # 最近月 = 主力合约
            yield prefix, months[0]
        else:
            yield prefix, None

def fetch_cffex_data(date_str=None):
    """从akshare获取CFFEX持仓排名"""
    import akshare as ak
    
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    
    target_vars = list(CONTRACTS.keys())
    
    for attempt in range(3):
        try:
            result = ak.get_cffex_rank_table(date=date_str, vars_list=target_vars)
            if result and len(result) > 0:
                return result, date_str
            log(f"  空数据，重试...")
        except Exception as e:
            log(f"  第{attempt+1}次失败: {e}")
            if attempt < 2:
                import time; time.sleep(3)
    
    return None, date_str

def extract_positions(result):
    """从持仓排名中提取中信期货的净持仓"""
    positions = {}
    
    for prefix, main_contract in get_main_contract(result.keys()):
        if main_contract is None or main_contract not in result:
            positions[prefix] = {
                'contract': None,
                'long': 0, 'short': 0,
                'net': 0, 'name': CONTRACTS.get(prefix, prefix)
            }
            continue
        
        df = result[main_contract]
        
        # 统计中信的多头总持仓
        long_total = df[df['long_party_name'].str.contains('中信', na=False)]['long_open_interest'].sum()
        
        # 统计中信的空头总持仓
        short_total = df[df['short_party_name'].str.contains('中信', na=False)]['short_open_interest'].sum()
        
        net = int(long_total - short_total)
        
        positions[prefix] = {
            'contract': main_contract,
            'long': int(long_total),
            'short': int(short_total),
            'net': net,
            'name': CONTRACTS.get(prefix, prefix),
        }
    
    return positions

def calc_change(current, previous):
    """计算持仓变化"""
    if not previous or 'positions' not in previous:
        return None
    
    changes = {}
    prev_pos = previous['positions']
    for prefix in CONTRACTS:
        if prefix in current and prefix in prev_pos:
            cur_net = current[prefix].get('net', 0)
            prev_net = prev_pos[prefix].get('net', 0)
            changes[prefix] = cur_net - prev_net
    
    return changes

def analyze_sentiment(positions, changes, history):
    """分析多空情绪，输出判断性文字"""
    sentiments = {}
    
    for prefix in CONTRACTS:
        pos = positions.get(prefix, {})
        net = pos.get('net', 0)
        chg = (changes or {}).get(prefix, 0)
        name = pos.get('name', prefix)
        
        # 判断多空方向和强度
        if net > 3000:
            direction = '偏多'
            intensity = '🔴' if net > 8000 else '🟠'
        elif net < -3000:
            direction = '偏空'
            intensity = '🟢' if net < -8000 else '🟡'
        else:
            direction = '中性'
            intensity = '⚪'
        
        # 结合变化方向
        if chg > 500:
            trend = '净多增'
        elif chg < -500:
            trend = '净空增'
        else:
            trend = '持仓平稳'
        
        # 历史连续方向（检查最近3天）
        consecutive = ''
        if history:
            recent = history.get(prefix, [])
            if len(recent) >= 3:
                if all(n > 0 for n in recent[:3]):
                    consecutive = ' · 连续3日净多'
                elif all(n < 0 for n in recent[:3]):
                    consecutive = ' · 连续3日净空'
        
        sentiments[prefix] = {
            'name': name,
            'net': net,
            'change': chg,
            'direction': direction,
            'intensity': intensity,
            'trend': trend,
            'summary': f'{intensity} {name} {direction}（净{"多" if net >= 0 else "空"}{abs(net)}手，{trend}{chg:+d}手）{consecutive}'
        }
    
    # 整体判断
    totals = sum(s['net'] for s in sentiments.values())
    if totals > 15000:
        overall = '🔥 中信四大股指期货整体净多，机构看多意愿强烈'
    elif totals > 5000:
        overall = '📈 中信整体偏多，机构态度积极'
    elif totals < -15000:
        overall = '❄️ 中信整体净空，机构避险情绪明显'
    elif totals < -5000:
        overall = '📉 中信整体偏空，机构态度谨慎'
    else:
        overall = '⚖️ 中信整体中性，机构多空分歧'
    
    return sentiments, overall, totals

def main():
    log("=" * 40)
    log("中信期货持仓数据抓取")
    log("=" * 40)
    
    # 加载历史数据
    history = {}
    old_data = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
            history = old_data.get('history', {})
        except:
            pass
    
    # 获取最新数据
    today_str = datetime.now().strftime('%Y%m%d')
    result, actual_date = fetch_cffex_data(today_str)
    
    if not result:
        log("❌ 数据获取失败")
        sys.exit(1)
    
    # 提取中信持仓
    positions = extract_positions(result)
    
    # 计算变化
    changes = calc_change(positions, old_data)
    
    # 更新历史（保留最近7天）
    for prefix in CONTRACTS:
        if prefix not in history:
            history[prefix] = []
        net = positions.get(prefix, {}).get('net', 0)
        history[prefix] = ([net] + history.get(prefix, []))[:7]
    
    # 分析判断
    sentiments, overall, totals = analyze_sentiment(positions, changes, history)
    
    # 构建输出
    output = {
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'date': actual_date,
        'positions': positions,
        'changes': changes,
        'sentiments': sentiments,
        'overall': overall,
        'net_total': totals,  # 四大合约总净持仓
        'history': history,
    }
    
    # 保存
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    log(f"✅ 已保存: {DATA_FILE}")
    log(f"   整体判断: {overall}")
    for prefix in CONTRACTS:
        s = sentiments.get(prefix, {})
        log(f"   {s.get('name', prefix)}: {s.get('summary', '无数据')}")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise

