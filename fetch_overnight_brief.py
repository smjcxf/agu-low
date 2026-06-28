#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全球速报时间轴 — 美股/外汇/黄金原油/VIX/隔夜头条 → 时间轴列表
输出: data/overnight_timeline.json（保留48小时）
用法: python fetch_overnight_brief.py              # 全量
     python fetch_overnight_brief.py --news-only   # 仅抓新闻，继承海外数据
"""
import json, os, sys, re
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
TIMELINE_FILE = os.path.join(DATA_DIR, "overnight_timeline.json")
MAX_HOURS = 72  # 保留3天（新条目在顶部，3日后自动删除）

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def fetch_sina(codes, timeout=15):
    import requests
    try:
        url = f'https://hq.sinajs.cn/list={",".join(codes)}'
        r = requests.get(url, headers={'Referer': 'https://finance.sina.com.cn'}, timeout=timeout)
        r.encoding = 'gbk'
        results = {}
        for line in r.text.strip().split(';'):
            if 'var hq_str_' not in line: continue
            prefix = 'var hq_str_'
            start = line.find(prefix) + len(prefix)
            end = line.find('="')
            code = line[start:end]
            data_str = line.split('"')[1]
            results[code] = data_str.split(',')
        return results
    except Exception as e:
        log(f"  Sina请求失败: {e}")
        return {}

def fetch_us_stocks():
    data = fetch_sina(['gb_dji', 'gb_inx', 'gb_ixic'])
    result = []
    name_map = {'gb_dji': '道琼斯', 'gb_inx': '标普500', 'gb_ixic': '纳斯达克'}
    for code, name in name_map.items():
        parts = data.get(code, [])
        if len(parts) < 3: continue
        price = float(parts[1])
        pct = float(parts[2])
        result.append({'name': name, 'price': round(price, 2), 'pct': pct})
    return result

def fetch_asia_stocks():
    """获取亚洲主要股市指数（实时）
    恒生/恒生科技/日经 → Sina; 韩国KOSPI → Sina global index"""
    result = []
    # 1. 恒生指数 + 日经225 + 港股科技 (hkHSTECH 格式不同于 int_ 前缀)
    sina_data = fetch_sina(['int_hangseng', 'int_nikkei'])
    # 恒生（排第一）
    parts = sina_data.get('int_hangseng', [])
    if len(parts) >= 4:
        result.append({'name': '恒生指数', 'price': round(float(parts[1]), 2), 'pct': float(parts[3])})
    # 恒生科技指数 (单独处理，格式不同)
    try:
        hktech_data = fetch_sina(['hkHSTECH'])
        hkparts = hktech_data.get('hkHSTECH', [])
        if len(hkparts) >= 9:
            result.append({'name': '恒生科技', 'price': round(float(hkparts[2]), 2), 'pct': float(hkparts[8])})
    except Exception:
        pass
    # 日经225
    parts = sina_data.get('int_nikkei', [])
    if len(parts) >= 4:
        result.append({'name': '日经225', 'price': round(float(parts[1]), 2), 'pct': float(parts[3])})
    # 2. KOSPI: 通过 akshare index_global_hist_sina
    try:
        import akshare as ak
        df = ak.index_global_hist_sina(symbol='首尔综合指数')
        if df is not None and len(df) > 1:
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            price = latest['close']
            pct = round((price - prev['close']) / prev['close'] * 100, 2) if prev['close'] else 0
            result.append({'name': '韩国KOSPI', 'price': round(float(price), 2), 'pct': pct})
    except Exception as e:
        log(f"  KOSPI获取失败: {e}")
    return result

def fetch_fx():
    data = fetch_sina(['gb_uup', 'fx_susdcnh'])
    result = []
    parts = data.get('gb_uup', [])
    if len(parts) >= 3:
        result.append({'name': '美元指数(UUP)', 'price': round(float(parts[1]), 2), 'pct': float(parts[2])})
    parts = data.get('fx_susdcnh', [])
    if len(parts) >= 3:
        price = float(parts[1])
        pre_close = float(parts[2])
        pct = round((price - pre_close) / pre_close * 100, 4) if pre_close else 0
        result.append({'name': '离岸人民币', 'price': round(price, 4), 'pct': pct})
    return result

def fetch_commodities():
    data = fetch_sina(['hf_XAU', 'hf_CL'])
    result = []
    name_map = {'hf_XAU': 'COMEX黄金', 'hf_CL': 'WTI原油'}
    for code, name in name_map.items():
        parts = data.get(code, [])
        if len(parts) < 8: continue
        price = float(parts[0])
        pre_close = float(parts[7])
        pct = round((price - pre_close) / pre_close * 100, 2) if pre_close else 0
        result.append({'name': name, 'price': round(price, 2), 'pct': pct})
    return result

def fetch_vix():
    data = fetch_sina(['gb_vixy'])
    parts = data.get('gb_vixy', [])
    if len(parts) >= 3:
        return {'price': round(float(parts[1]), 2), 'pct': float(parts[2])}
    return None

def fetch_news_headlines():
    headlines = []
    try:
        import requests
        r = requests.get(
            'https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=8',
            headers={'User-Agent': 'Mozilla/5.0'}, timeout=10
        )
        if r.status_code == 200:
            items = r.json().get('data', {}).get('items', [])
            for item in items[:6]:
                content = item.get('content_text', '') or item.get('title', '')
                content = re.sub(r'<[^>]+>', '', content)
                if len(content) > 8:
                    headlines.append({'source': '华尔街', 'text': content[:120]})
    except Exception as e:
        log(f"  华尔街见闻: {e}")
    try:
        import requests
        r = requests.get(
            'https://www.cls.cn/api/sw?app=CailianpressWeb&os=web&sv=8.4.6',
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cls.cn/telegraph'},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            rolls = data.get('data', {}).get('roll_data', [])
            for item in rolls[:8]:
                content = item.get('content', '') or item.get('title', '')
                title = item.get('title', '')
                txt = title or content
                txt = re.sub(r'<[^>]+>', '', txt)
                if len(txt) > 8:
                    headlines.append({'source': '财联社', 'text': txt[:120]})
    except Exception:
        pass
    try:
        # 新浪财经快讯（官方滚动新闻）
        import requests
        r = requests.get(
            'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num=10&page=1',
            headers={'User-Agent': 'Mozilla/5.0'}, timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            items = data.get('result', {}).get('data', [])
            for item in items[:8]:
                txt = item.get('title', '') or item.get('ctime', '')
                txt = re.sub(r'<[^>]+>', '', txt)
                if len(txt) > 10:
                    headlines.append({'source': '新浪财经', 'text': txt[:120]})
    except Exception:
        pass
    seen = set()
    unique = []
    for h in headlines:
        key = h['text'][:30]
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique[:12]

# ===== 主流程 =====
def main():
    news_only = '--news-only' in sys.argv
    now = datetime.now()
    task_name = "早间全量速报" if not news_only else "盘中新闻增量"

    log("=" * 50)
    log(f"全球速报 — {task_name}")
    log("=" * 50)
    
    # 读取已有时间轴
    timeline = []
    if os.path.exists(TIMELINE_FILE):
        try:
            with open(TIMELINE_FILE, 'r', encoding='utf-8') as f:
                timeline = json.load(f)
        except:
            pass
    
    # 清理48小时过期的条目
    cutoff = now - timedelta(hours=MAX_HOURS)
    timeline = [t for t in timeline if datetime.fromisoformat(t['timestamp']) > cutoff]
    
    # 获取上一个条目的海外数据（news-only 模式下继承）
    last_entry = timeline[0] if timeline else None
    
    # 【2026-06-26新增】盘中新闻增量去重：距上次不足60分钟跳过
    if news_only and last_entry and last_entry.get('task') == '盘中新闻增量':
        last_ts = datetime.fromisoformat(last_entry['timestamp'])
        minutes_ago = (now - last_ts).total_seconds() / 60
        if minutes_ago < 60:
            log(f"⏭ 去重：上一条盘中新闻增量仅{minutes_ago:.0f}分钟前，跳过本次（≥60分钟才刷新）")
            return  # 静默退出，不写入新条目
    
    asia_stocks = []  # 非 news_only 模式默认空
    if news_only:
        # 盘中增量：不继承美股（未开盘），改为抓亚洲股市
        us_stocks = []
        fx = []
        commodities = []
        vix = None
        asia_stocks = fetch_asia_stocks()
        log(f"  亚洲: {len(asia_stocks)}只")
    else:
        us_stocks = fetch_us_stocks()
        log(f"  美股: {len(us_stocks)}只")
        fx = fetch_fx()
        log(f"  外汇: {len(fx)}项")
        commodities = fetch_commodities()
        log(f"  大宗商品: {len(commodities)}项")
        vix = fetch_vix()
        log(f"  VIX: {'✓' if vix else '✗'}")
    
    news = fetch_news_headlines()
    log(f"  头条: {len(news)}条")
    
    # 构建新条目（插入到最前面）
    entry = {
        'timestamp': now.isoformat(),
        'task': task_name,
        'us_stocks': us_stocks,
        'asia_stocks': asia_stocks if news_only else [],
        'fx': fx,
        'commodities': commodities,
        'vix': vix,
        'news': news,
    }
    timeline.insert(0, entry)
    
    # 清理过期（再跑一次确保干净）
    timeline = [t for t in timeline if datetime.fromisoformat(t['timestamp']) > cutoff]
    
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TIMELINE_FILE, 'w', encoding='utf-8') as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)
    
    # 打印速报
    print("\n" + "=" * 50)
    print(f"📰 全球速报 — {now.strftime('%m-%d %H:%M')} [{task_name}]")
    print("=" * 50)
    if not news_only:
        print("\n📈 美股收盘:")
        for s in us_stocks:
            arrow = '🔴' if s['pct'] > 0 else '🟢' if s['pct'] < 0 else '⚪'
            print(f"  {arrow} {s['name']}: {s['price']:.2f}  {s['pct']:+.2f}%")
        print("\n💱 外汇:")
        for f in fx:
            print(f"  {f['name']}: {f['price']:.4f}  {f['pct']:+.2f}%")
    if asia_stocks:
        print("\n🏯 亚洲股市（盘中）:")
        for s in asia_stocks:
            arrow = '🔴' if s['pct'] > 0 else '🟢' if s['pct'] < 0 else '⚪'
            print(f"  {arrow} {s['name']}: {s['price']:.2f}  {s['pct']:+.2f}%")
        print("\n🛢️ 大宗商品:")
        for c in commodities:
            print(f"  {c['name']}: {c['price']:.2f}  {c['pct']:+.2f}%")
        if vix:
            print(f"\n😱 VIX: {vix['price']:.2f} ({vix['pct']:+.2f}%)")
    print(f"\n📰 隔夜头条 ({len(news)}条):")
    for n in news[:10]:
        print(f"  [{n['source']}] {n['text']}")
    print(f"\n✅ 时间轴: {len(timeline)}条 (保留{MAX_HOURS}h)")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise

