#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
龙虎榜机游共振分析 v6
- 新浪 jgmx_sina：机构席位买卖金额（真实，单位万）
- 东方财富 stock_lhb_stock_detail_em：逐笔席位明细
- 游资识别：精确匹配 lhb_seats.json 知名游资席位（不再用非机构席位一锅端）
- 分类：机构净买>8000万 + 游资净买>8000万 = 纯共振
"""
import akshare as ak
import json
import time
import datetime
import os
import sys
import re

OUT = "data/lhb_result.json"
THRESHOLD = 8000  # 强买阈值：净买入 > 8000万
SEATS_PATH = os.path.join(os.path.dirname(__file__), "data", "lhb_seats.json")

def log(msg):
    print(f"  {msg}", flush=True)

def _load_lhb_seats():
    """加载游资席位知识库"""
    if not os.path.exists(SEATS_PATH):
        log(f"[WARN] lhb_seats.json 不存在，回退到非机构席位统计算法")
        return {"seats": [], "patterns": {}}
    with open(SEATS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _classify_seat(seat_name, seats_db):
    """对某个席位名称进行分类
    返回 (type, alias) 如 ('游资', '章盟主'), ('机构', ''), ('量化', ''), ('北向', '')
    """
    if not seat_name:
        return ('未知', '')
    # 1. 机构专用 → 机构
    if '机构专用' in seat_name:
        return ('机构', '')
    # 2. 北向资金通道
    if '深股通' in seat_name or '沪股通' in seat_name:
        return ('北向', '')
    # 3. 精确匹配已知席位
    for s in seats_db.get("seats", []):
        if s["name"] == seat_name:
            return (s["type"], s.get("alias", ""))
    # 4. 模糊匹配已知游资模式
    for p in seats_db.get("patterns", {}).get("游资", []):
        if p in seat_name:
            return ('游资', '')
    for p in seats_db.get("patterns", {}).get("量化", []):
        if p in seat_name:
            return ('量化', '')
    # 5. 未知 → 归类为游资（包含所有非机构席位）
    return ('游资', '')

def get_date_str(target_date=None):
    """返回 YYYYMMDD 格式日期字符串。
    target_date: datetime.date 对象，为 None 时用今天逻辑。
    """
    if target_date is None:
        target_date = datetime.date.today()
    weekday = target_date.weekday()
    if weekday == 0:  # 周一
        friday = target_date - datetime.timedelta(days=3)
        return friday.strftime("%Y%m%d")
    elif weekday >= 5:  # 周六/周日
        days_back = weekday - 4
        friday = target_date - datetime.timedelta(days=days_back)
        return friday.strftime("%Y%m%d")
    else:
        return target_date.strftime("%Y%m%d")

def fetch_lhb_list(date_str):
    try:
        df = ak.stock_lhb_detail_em(start_date=date_str, end_date=date_str)
        if df is None or len(df) == 0:
            log(f"龙虎榜：暂无{date_str}数据")
            return []
        stocks = []
        seen = set()
        for _, row in df.iterrows():
            code = str(row.get('代码', '')).zfill(6)
            if code and code not in seen:
                seen.add(code)
                stocks.append({
                    'code': code,
                    'name': str(row.get('名称', '')),
                    'price': float(row.get('最新价', 0) or 0),
                    'pct': float(row.get('涨跌幅', 0) or 0),
                    'amount': float(row.get('龙虎榜净买额', 0) or 0),
                    'reason': str(row.get('上榜原因', '')),
                })
        log(f"龙虎榜：{len(stocks)} 只")
        return stocks
    except Exception as e:
        log(f"获取龙虎榜失败: {e}")
        return []

def fetch_inst_map():
    """新浪机构席位买卖金额，单位：万"""
    inst_map = {}
    try:
        df = ak.stock_lhb_jgmx_sina()
        for _, row in df.iterrows():
            code = str(row.get('股票代码', '')).zfill(6)
            buy = float(row.get('机构席位买入额', 0) or 0)
            sell = float(row.get('机构席位卖出额', 0) or 0)
            if code not in inst_map:
                inst_map[code] = {'buy': 0, 'sell': 0}
            inst_map[code]['buy'] += buy
            inst_map[code]['sell'] += sell
        log(f"机构数据：{len(inst_map)} 只")
    except Exception as e:
        log(f"新浪接口失败: {e}")
    return inst_map

def fetch_yz_map(stocks, date_str, limit=40):
    """东方财富逐笔席位明细，仅统计知名游资席位买卖金额，单位：万"""
    yz_map = {}
    seats_db = _load_lhb_seats()
    priority = sorted(stocks, key=lambda s: abs(inst_map.get(s['code'], {}).get('buy', 0) - inst_map.get(s['code'], {}).get('sell', 0)), reverse=True) if 'inst_map' in dir() else stocks
    codes = list(set(s['code'] for s in priority[:limit]))
    yz_seat_count = 0  # 统计命中的游资席位数

    for code in codes:
        for flag in ['买入', '卖出']:
            try:
                detail_df = ak.stock_lhb_stock_detail_em(symbol=code, date=date_str, flag=flag)
                if detail_df is not None and not detail_df.empty:
                    col = '买入金额' if flag == '买入' else '卖出金额'
                    for _, drow in detail_df.iterrows():
                        seat = str(drow.get('交易营业部名称', ''))
                        stype, _ = _classify_seat(seat, seats_db)
                        # 只统计游资/量化席位，跳过机构、北向、未知
                        if stype not in ('游资', '量化'):
                            continue
                        yz_seat_count += 1
                        amt = float(drow.get(col, 0) or 0) / 10000  # 元→万
                        if code not in yz_map:
                            yz_map[code] = {'buy': 0, 'sell': 0}
                        if flag == '买入':
                            yz_map[code]['buy'] += amt
                        else:
                            yz_map[code]['sell'] += amt
                time.sleep(0.3)
            except Exception:
                pass
    log(f"游资席位命中：{yz_seat_count} 次，覆盖 {len(yz_map)} 只股票")
    return yz_map

def classify(inst_buy, inst_sell, yz_buy, yz_sell):
    inst_net = inst_buy - inst_sell
    yz_net = yz_buy - yz_sell
    inst_strong = inst_net > THRESHOLD
    yz_strong = yz_net > THRESHOLD
    if inst_strong and yz_strong:
        return '纯共振', inst_net, yz_net
    elif inst_strong or yz_strong:
        return '标X', inst_net, yz_net
    else:
        return '不达标', inst_net, yz_net

def format_amount(v):
    """金额格式化：万→亿，保留2位小数"""
    if abs(v) >= 10000:
        return f"{v/10000:.2f}亿"
    elif abs(v) >= 1000:
        return f"{v/10000:.2f}亿"
    else:
        return f"{v:.0f}万"

def update_lhb_history(results, fmt_date):
    """将机游共振数据写入 lhb_history.json（机游共振日历数据源）
    只写入纯共振数据。
    """
    path = "data/lhb_history.json"
    hist = {}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                hist = json.load(f)
        except Exception:
            pass

    # 只保留纯共振，简化数据格式：只保留名称和金额
    pure_simple = []
    for item in results['纯共振']:
        pure_simple.append({
            'code': item['code'],
            'name': item['name'],
            'amount': format_amount(item['inst_net_万']),
        })

    hist[fmt_date] = {
        'trading': True,
        'pure': pure_simple,
    }

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    log(f"机游共振日历更新：{fmt_date} 纯共振{len(pure_simple)} 只")

def main():
    print("=" * 50)
    date_str = get_date_str()
    print(f"龙虎榜机游共振分析 v5（日期：{date_str}，阈值：{THRESHOLD}万）")
    print("=" * 50)

    stocks = fetch_lhb_list(date_str)
    if not stocks:
        print("无龙虎榜数据")
        return

    inst_map = fetch_inst_map()
    yz_map = fetch_yz_map(stocks, date_str, limit=40)

    results = {'纯共振': [], '标X': [], '不达标': []}
    for s in stocks:
        code = s['code']
        inst = inst_map.get(code, {'buy': 0, 'sell': 0})
        yz = yz_map.get(code, {'buy': 0, 'sell': 0})
        cat, inst_net, yz_net = classify(inst['buy'], inst['sell'], yz['buy'], yz['sell'])
        results[cat].append({
            'code': code,
            'name': s['name'],
            'price': s['price'],
            'pct': s['pct'],
            'reason': s['reason'],
            'category': cat,
            'inst_buy_万': round(inst['buy'], 1),
            'inst_sell_万': round(inst['sell'], 1),
            'inst_net_万': round(inst_net, 1),
            'yz_buy_万': round(yz['buy'], 1),
            'yz_sell_万': round(yz['sell'], 1),
            'yz_net_万': round(yz_net, 1),
        })

    # 输出
    os.makedirs('data', exist_ok=True)
    output = {
        'date': date_str,
        'update_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'stocks': results['纯共振'] + results['标X'] + results['不达标'],
        'summary': {
            '纯共振': len(results['纯共振']),
            '标X': len(results['标X']),
            '不达标': len(results['不达标']),
            '总计': len(stocks),
        }
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 计算 fmt_date
    if len(date_str) == 8:
        fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    else:
        fmt_date = datetime.date.today().strftime('%Y-%m-%d')

    update_lhb_history(results, fmt_date)

    print(f"\n完成！")
    print(f"  纯共振：{len(results['纯共振'])} 只")
    for r in results['纯共振'][:5]:
        print(f"    {r['code']} {r['name']} 机构净买{r['inst_net_万']}万 游资净买{r['yz_net_万']}万")
    print(f"  标X：{len(results['标X'])} 只")
    print(f"  不达标：{len(results['不达标'])} 只")

if __name__ == '__main__':
    main()
