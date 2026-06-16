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

OUT = "data/market_alerts.json"
MAX_RETRY = 3


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


def fetch_index_spot():
    """获取主要指数实时行情"""
    for attempt in range(1, MAX_RETRY + 1):
        try:
            df = ak.stock_zh_index_spot_em()
            log(f"✓ 获取到 {len(df)} 条指数行情")
            # 筛选主要指数
            targets = ['上证指数', '深证成指', '创业板指', '科创50']
            result = []
            for _, row in df.iterrows():
                name = str(row.get('名称', row.iloc[0]))
                for t in targets:
                    if t in name:
                        pct = float(row.get('涨跌幅', row.get('涨跌幅(%)', 0)))
                        result.append({'name': t, 'pct': round(pct, 2)})
                        break
            return result
        except Exception as e:
            log(f"✗ 指数获取失败(第{attempt}次): {e}")
            if attempt < MAX_RETRY:
                time.sleep(2)
    return []


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

    # ✅ 修复：全部失败时保留已有数据，不写空文件
    if not indices and not top_sectors and not mood:
        log("⚠ 全部获取失败，保留已有数据，不覆盖")
        if os.path.exists(OUT):
            log(f"✓ 已有数据保留: {OUT}")
        else:
            log("⚠ 无已有数据，写入空结构")
            output = {'update_time': now_str, 'summary': '', 'indices': [], 'top_sectors': [], 'bottom_sectors': [], 'mood': {}}
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, 'w', encoding='utf-8') as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
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


if __name__ == '__main__':
    main()
