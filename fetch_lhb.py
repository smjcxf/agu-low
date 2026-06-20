#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
龙虎榜席位全量分析 v7
- 东方财富 stock_lhb_stock_detail_em：逐笔席位明细，全部统计
- 机构专用 / 深股通沪股通 / 游资 / 量化 / 未识别 → 全部计入
- 分类：机构净买>8000万 + 非机构净买>8000万 = 纯共振
"""
import akshare as ak
import json
import time
import datetime
import os
import sys

OUT = "data/lhb_result.json"
THRESHOLD = 8000  # 强买阈值：净买入 > 8000万
SEATS_PATH = os.path.join(os.path.dirname(__file__), "data", "lhb_seats.json")
DETAIL_LIMIT = 40  # 最多分析前40只股票的逐笔席位

def log(msg):
    print(f"  {msg}", flush=True)

def _load_lhb_seats():
    if not os.path.exists(SEATS_PATH):
        log(f"[WARN] lhb_seats.json 不存在")
        return {"seats": [], "patterns": {}}
    with open(SEATS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _classify_seat(seat_name, seats_db):
    """分类席位：机构/北向/游资/量化/未识别"""
    if not seat_name:
        return '未识别'
    if '机构专用' in seat_name:
        return '机构'
    if '深股通' in seat_name or '沪股通' in seat_name:
        return '北向'
    for s in seats_db.get("seats", []):
        if s["name"] == seat_name:
            return s.get("type", "游资")
    for p in seats_db.get("patterns", {}).get("游资", []):
        if p in seat_name:
            return '游资'
    for p in seats_db.get("patterns", {}).get("量化", []):
        if p in seat_name:
            return '量化'
    return '未识别'

def get_date_str(target_date=None):
    if target_date is None:
        target_date = datetime.date.today()
    weekday = target_date.weekday()
    if weekday == 0:
        friday = target_date - datetime.timedelta(days=3)
        return friday.strftime("%Y%m%d")
    elif weekday >= 5:
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

def fetch_seat_detail(stocks, date_str):
    """逐笔席位明细：全量统计，按类型分组汇总（单位：万）"""
    seats_db = _load_lhb_seats()
    # 按机构净买入金额排序（用新浪接口做近似），优先分析大金额股票
    inst_map = _fetch_inst_sina()
    priority = sorted(
        stocks,
        key=lambda s: abs(inst_map.get(s['code'], {}).get('buy', 0) - inst_map.get(s['code'], {}).get('sell', 0)),
        reverse=True
    )
    codes = list(set(s['code'] for s in priority[:DETAIL_LIMIT]))

    # 结果：{code: {"机构": {buy, sell}, "北向": {buy, sell}, ...}}
    detail_map = {}

    for code in codes:
        detail_map[code] = {}
        for flag in ['买入', '卖出']:
            try:
                df = ak.stock_lhb_stock_detail_em(symbol=code, date=date_str, flag=flag)
                if df is None or df.empty:
                    continue
                col = '买入金额' if flag == '买入' else '卖出金额'
                for _, drow in df.iterrows():
                    seat = str(drow.get('交易营业部名称', ''))
                    stype = _classify_seat(seat, seats_db)
                    amt = float(drow.get(col, 0) or 0) / 10000  # 元→万
                    if stype not in detail_map[code]:
                        detail_map[code][stype] = {'buy': 0, 'sell': 0}
                    if flag == '买入':
                        detail_map[code][stype]['buy'] += amt
                    else:
                        detail_map[code][stype]['sell'] += amt
                time.sleep(0.3)
            except Exception:
                pass

    # 统计
    total_seats = sum(len(v) for v in detail_map.values())
    log(f"逐笔席位：{total_seats} 种类型命中，覆盖 {len(detail_map)} 只股票")
    return detail_map

def _fetch_inst_sina():
    """新浪机构席位接口，用于排序参考"""
    inst_map = {}
    try:
        df = ak.stock_lhb_jgmx_sina()
        for _, row in df.iterrows():
            code = str(row.get('股票代码', '')).zfill(6)
            buy = float(row.get('机构席位买入额', 0) or 0)
            sell = float(row.get('机构席位卖出额', 0) or 0)
            inst_map[code] = {'buy': buy, 'sell': sell}
    except Exception as e:
        log(f"新浪接口: {e}")
    return inst_map

def classify(inst_buy, inst_sell, other_buy, other_sell):
    """机构 vs 非机构（北向+游资+量化+未识别）净买入判定"""
    inst_net = inst_buy - inst_sell
    other_net = other_buy - other_sell
    inst_strong = inst_net > THRESHOLD
    other_strong = other_net > THRESHOLD
    if inst_strong and other_strong:
        return '纯共振', inst_net, other_net
    elif inst_strong or other_strong:
        return '标X', inst_net, other_net
    else:
        return '不达标', inst_net, other_net

def main():
    print("=" * 50)
    date_str = get_date_str()
    print(f"龙虎榜席位全量分析 v7（日期：{date_str}，阈值：{THRESHOLD}万）")
    print("=" * 50)

    stocks = fetch_lhb_list(date_str)
    if not stocks:
        print("无龙虎榜数据")
        return

    detail_map = fetch_seat_detail(stocks, date_str)

    results = {'纯共振': [], '标X': [], '不达标': []}
    for s in stocks:
        code = s['code']
        seats = detail_map.get(code, {})

        # 机构：取机构专用席位
        inst = seats.get('机构', {'buy': 0, 'sell': 0})
        # 非机构：北向+游资+量化+未识别
        other_buy = 0
        other_sell = 0
        for stype in ('北向', '游资', '量化', '未识别'):
            d = seats.get(stype, {'buy': 0, 'sell': 0})
            other_buy += d['buy']
            other_sell += d['sell']

        cat, inst_net, other_net = classify(
            inst['buy'], inst['sell'],
            other_buy, other_sell
        )

        # 席位明细（类型→金额，紧凑格式）
        seat_detail = {}
        for stype in ('机构', '北向', '游资', '量化', '未识别'):
            d = seats.get(stype, {'buy': 0, 'sell': 0})
            if d['buy'] > 0 or d['sell'] > 0:
                seat_detail[stype] = {
                    'buy': round(d['buy'], 1),
                    'sell': round(d['sell'], 1),
                }

        results[cat].append({
            'code': code,
            'name': s['name'],
            'price': s['price'],
            'pct': s['pct'],
            'reason': s['reason'],
            'category': cat,
            'inst_net_万': round(inst_net, 1),
            'inst_buy_万': round(inst['buy'], 1),
            'inst_sell_万': round(inst['sell'], 1),
            'yz_net_万': round(other_net, 1),
            'yz_buy_万': round(other_buy, 1),
            'yz_sell_万': round(other_sell, 1),
            'seats': seat_detail,  # 席位明细
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

    # 机游共振日历
    _update_lhb_history(results, date_str)

    print(f"\n完成！")
    print(f"  纯共振：{len(results['纯共振'])} 只")
    for r in results['纯共振'][:5]:
        types = '/'.join(r['seats'].keys()) if r.get('seats') else '无'
        print(f"    {r['code']} {r['name']} 机构{r['inst_net_万']}万 其他{r['yz_net_万']}万 [{types}]")
    print(f"  标X：{len(results['标X'])} 只")
    print(f"  不达标：{len(results['不达标'])} 只")

def _update_lhb_history(results, date_str):
    """只写入纯共振数据到机游共振日历"""
    path = "data/lhb_history.json"
    hist = {}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                hist = json.load(f)
        except Exception:
            pass
    pure_simple = []
    for item in results['纯共振']:
        pure_simple.append({
            'code': item['code'],
            'name': item['name'],
            'amount': f"{item['inst_net_万']/10000:.2f}亿" if abs(item['inst_net_万']) >= 10000 else f"{item['inst_net_万']:.0f}万",
        })
    if len(date_str) == 8:
        fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    else:
        fmt_date = datetime.date.today().strftime('%Y-%m-%d')
    hist[fmt_date] = {'trading': True, 'pure': pure_simple}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    main()
