#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全市场异动速览
用法：python fetch_market_alerts.py
输出：data/market_alerts.json
"""

import akshare as ak
import json
import datetime
import os
import time
import requests

OUT = "data/market_alerts.json"
MAX_RETRY = 2  # 原3次，akshare频繁RemoteDisconnected，降为2次加速降级新浪

# 指数名称 → Sina代码映射（用于补齐深交所指数）
INDEX_SINA_MAP = {
    '上证指数': 's_sh000001',
    '深证成指': 's_sz399001',
    '创业板指': 's_sz399006',
    '科创50':  's_sh000688',
}

# 海外指数 → Sina代码映射（盘中实时，港股日韩跟随A股指数一起刷新）
FOREIGN_SINA_MAP = {
    '日经225': 'int_nikkei',
}

# 海外指数 → 名称（需单独akshare获取的）
FOREIGN_AKSHARE = {
    '韩国KOSPI': '首尔综合指数',
}


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


def fetch_sina_indices():
    """从新浪API获取指数涨跌幅（覆盖A股+海外指数）"""
    all_sina = {**INDEX_SINA_MAP, **FOREIGN_SINA_MAP}
    codes = ','.join(all_sina.values())
    try:
        r = requests.get(
            f'https://hq.sinajs.cn/list={codes}',
            headers={'Referer': 'https://finance.sina.com.cn'},
            timeout=15
        )
        if r.status_code != 200:
            return {}
        result = {}
        for line in r.text.strip().split(';'):
            line = line.strip()
            if not line or 'var hq_str_' not in line:
                continue
            prefix = 'var hq_str_'
            start = line.find(prefix) + len(prefix)
            end = line.find('="')
            code = line[start:end]
            data_str = line.split('"')[1]
            parts = data_str.split(',')
            if len(parts) >= 4:
                # A股指数（s_前缀）和海外指数（int_前缀）：parts[3]=涨跌幅%
                if code.startswith('s_') or code.startswith('int_'):
                    pct = float(parts[3]) if parts[3] else 0
                else:
                    price = float(parts[3])
                    pre_close = float(parts[2])
                    if pre_close > 0:
                        pct = round((price - pre_close) / pre_close * 100, 2)
                    else:
                        pct = 0
                # 反向查找中文名
                name = next((k for k, v in {**INDEX_SINA_MAP, **FOREIGN_SINA_MAP}.items() if v == code), parts[0])
                result[name] = pct
        return result
    except Exception as e:
        log(f"  Sina指数获取失败: {e}")
        return {}


def fetch_index_spot():
    """获取主要指数实时行情（akshare + Sina兜底，含日经/韩股）"""
    result = []
    # 固定顺序：A股4大指数 → 韩股 → 日经（符合用户阅读习惯）
    targets = ['上证指数', '深证成指', '创业板指', '科创50']
    foreign_targets = ['韩国KOSPI', '日经225']  # 韩股在创业板指后，日经最后

    # Step 1: akshare（上交所指数）
    for attempt in range(1, MAX_RETRY + 1):
        try:
            df = ak.stock_zh_index_spot_em()
            log(f"✓ akshare获取到 {len(df)} 条指数行情")
            for _, row in df.iterrows():
                name = str(row.get('名称', row.iloc[0]))
                for t in targets:
                    if t in name:
                        pct = float(row.get('涨跌幅', row.get('涨跌幅(%)', 0)))
                        result.append({'name': t, 'pct': round(pct, 2)})
                        break
            break
        except Exception as e:
            log(f"✗ akshare指数获取失败(第{attempt}次): {e}")
            if attempt < MAX_RETRY:
                time.sleep(2)

    # Step 2: Sina补齐深交所+海外缺失的指数
    got = {r['name'] for r in result}
    all_targets = targets + foreign_targets
    missing = [t for t in all_targets if t not in got]
    if missing:
        log(f"  补齐缺失指数: {missing}")
        sina = fetch_sina_indices()
        # 盘后Sina返回全0，跳过以避免覆盖有效数据
        if sina and all(abs(v) < 0.01 for v in sina.values()):
            log(f"  ⚠️ Sina返回全0%（盘后），跳过补全")
        else:
            for m in missing:
                if m in sina:
                    result.append({'name': m, 'pct': sina[m]})
                    log(f"    ✓ {m} {sina[m]:+.2f}% (Sina)")
                elif m in FOREIGN_AKSHARE:
                    # KOSPI: Sina不支持，用akshare单独获取
                    kospi = fetch_kospi_spot()
                    if kospi:
                        result.append(kospi)
                        log(f"    ✓ {m} {kospi['pct']:+.2f}% (akshare)")
                    else:
                        log(f"    ✗ {m} 无法获取")
                else:
                    log(f"    ✗ {m} 无法获取")
    
    # Step 3: 获取KOSPI（即使Sina已尝试，确保数据准确）
    for ft in foreign_targets:
        if ft not in {r['name'] for r in result}:
            if ft in FOREIGN_AKSHARE:
                kospi = fetch_kospi_spot()
                if kospi:
                    result.append(kospi)
                    log(f"    ✓ {ft} {kospi['pct']:+.2f}% (akshare)")
    
    # Step 4: 按固定顺序重排，确保显示顺序一致
    order_map = {name: i for i, name in enumerate(all_targets)}
    result.sort(key=lambda x: order_map.get(x['name'], 99))
    
    return result


def fetch_kospi_spot():
    """获取韩国KOSPI指数最新行情"""
    try:
        df = ak.index_global_hist_sina(symbol='首尔综合指数')
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            price = float(latest['close'])
            if len(df) >= 2:
                prev = float(df.iloc[-2]['close'])
                pct = round((price - prev) / prev * 100, 2) if prev > 0 else 0
            else:
                pct = 0
            return {'name': '韩国KOSPI', 'pct': pct}
    except Exception as e:
        log(f"  ⚠️ KOSPI获取失败: {e}")
    return None


def fetch_sector_board():
    """获取行业板块涨跌幅"""
    for attempt in range(1, MAX_RETRY + 1):
        try:
            df = ak.stock_board_industry_name_em()
            log(f"✓ 获取到 {len(df)} 个行业板块")
            # 找涨跌幅字段
            pct_col = None
            for col in df.columns:
                if '涨跌幅' in str(col):
                    pct_col = col
                    break
            if not pct_col and len(df.columns) >= 3:
                pct_col = df.columns[2]

            name_col = df.columns[0]
            for col in df.columns:
                if '名称' in str(col):
                    name_col = col
                    break

            df[pct_col] = df[pct_col].astype(float)
            df_sorted = df.sort_values(by=pct_col, ascending=False)

            top = df_sorted.head(3)
            bottom = df_sorted.tail(3).iloc[::-1]

            top_list = []
            for _, row in top.iterrows():
                top_list.append({'name': str(row[name_col]), 'pct': round(float(row[pct_col]), 2)})

            bottom_list = []
            for _, row in bottom.iterrows():
                bottom_list.append({'name': str(row[name_col]), 'pct': round(float(row[pct_col]), 2)})

            return top_list, bottom_list
        except Exception as e:
            log(f"✗ 板块获取失败(第{attempt}次): {e}")
            if attempt < MAX_RETRY:
                time.sleep(2)
    return [], []


def fetch_a_spot():
    """获取A股全市场涨跌统计"""
    for attempt in range(1, MAX_RETRY + 1):
        try:
            df = ak.stock_zh_a_spot_em()
            log(f"✓ 获取到 {len(df)} 只A股行情")
            pct_col = None
            for col in df.columns:
                if '涨跌幅' in str(col):
                    pct_col = col
                    break
            if not pct_col and len(df.columns) >= 3:
                pct_col = df.columns[2]

            df[pct_col] = df[pct_col].astype(float)
            up = (df[pct_col] > 0).sum()
            down = (df[pct_col] < 0).sum()
            flat = (df[pct_col] == 0).sum()
            limit_up = (df[pct_col] >= 9.9).sum()
            limit_down = (df[pct_col] <= -9.9).sum()

            return {
                'up': int(up),
                'down': int(down),
                'flat': int(flat),
                'limit_up': int(limit_up),
                'limit_down': int(limit_down),
            }
        except Exception as e:
            log(f"✗ 个股获取失败(第{attempt}次): {e}")
            if attempt < MAX_RETRY:
                time.sleep(2)
    return {}


def build_summary(indices, top_sectors, bottom_sectors, mood):
    """生成一句话总结"""
    parts = []

    # 指数状态
    if indices:
        sh = next((i for i in indices if i['name'] == '上证指数'), None)
        if sh:
            dir_text = '涨' if sh['pct'] > 0 else '跌' if sh['pct'] < 0 else '平'
            parts.append(f"上证指数{dir_text}{abs(sh['pct']):.2f}%")

    # 领涨板块
    if top_sectors:
        names = '、'.join([s['name'] for s in top_sectors[:2]])
        parts.append(f"{names}领涨")

    # 领跌板块
    if bottom_sectors:
        names = '、'.join([s['name'] for s in bottom_sectors[:2]])
        parts.append(f"{names}领跌")

    # 情绪
    if mood.get('limit_up') is not None and mood.get('limit_down') is not None:
        parts.append(f"涨停{mood['limit_up']}只、跌停{mood['limit_down']}只")

    if not parts:
        return "市场数据获取中..."

    summary = '，'.join(parts) + '。'

    # 加情绪判断
    if mood.get('limit_up') is not None and mood.get('limit_down') is not None:
        ratio = mood['limit_up'] / max(mood['limit_down'], 1)
        if ratio >= 3:
            summary += '情绪积极。'
        elif ratio <= 0.5:
            summary += '情绪谨慎。'
        else:
            summary += '情绪中性。'

    return summary


def main():
    log("全市场异动速览 v1")
    print("=" * 50)

    indices = fetch_index_spot()
    top_sectors, bottom_sectors = fetch_sector_board()
    mood = fetch_a_spot()

    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 全部失败时写入空数据，不保留旧数据（避免误导用户）
    if not indices and not top_sectors and not mood:
        log("⚠ 全部获取失败，写入空数据（数据更新中）")
        output = {'update_time': now_str, 'data_available': False, 'summary': '', 'indices': [], 'top_sectors': [], 'bottom_sectors': [], 'mood': {}}
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        log(f"✓ 已写入空结构: {OUT}")
        return

    summary = build_summary(indices, top_sectors, bottom_sectors, mood)

    output = {
        'update_time': now_str,
        'summary': summary,
        'indices': indices,
        'top_sectors': top_sectors,
        'bottom_sectors': bottom_sectors,
        'mood': mood,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log(f"✓ 完成！总结: {summary}")

    log(f"✓ 完成！")
    print(f"  总结：{summary}")
    if indices:
        print(f"  指数：{', '.join(f'{i['name']} {i['pct']:+.2f}%' for i in indices)}")
    if top_sectors:
        print(f"  领涨：{', '.join(f'{s['name']} +{s['pct']:.2f}%' for s in top_sectors)}")
    if bottom_sectors:
        print(f"  领跌：{', '.join(f'{s['name']} {s['pct']:.2f}%' for s in bottom_sectors)}")
    if mood:
        print(f"  情绪：涨{mood.get('up',0)} 跌{mood.get('down',0)} 涨停{mood.get('limit_up',0)} 跌停{mood.get('limit_down',0)}")


if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise

