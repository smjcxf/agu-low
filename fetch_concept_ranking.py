#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
概念涨跌幅排名 Top40（涨幅前20 + 跌幅前20）
用法：python fetch_concept_ranking.py
输出：data/concept_ranking.json
"""

import akshare as ak
import json
import datetime
import os
import time

OUT = "data/concept_ranking.json"
MAX_RETRY = 3
TOP_N = 20  # 涨幅/跌幅各取前N名


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


def fetch_concept_ranking():
    """获取概念板块涨跌幅排名"""
    df = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            log(f"获取概念板块列表（第{attempt}次）...")
            df = ak.stock_board_concept_name_em()
            log(f"✓ 获取到 {len(df)} 个概念板块")
            break
        except Exception as e:
            log(f"✗ 第{attempt}次失败: {e}")
            if attempt < MAX_RETRY:
                time.sleep(2)
            else:
                return []

    if df is None or len(df) == 0:
        return []

    # 找涨跌幅字段
    pct_col = None
    for col in df.columns:
        if '涨跌幅' in str(col) or 'pct' in str(col).lower() or 'change' in str(col).lower():
            pct_col = col
            break

    if not pct_col:
        # 默认用第3列（索引2）
        pct_col = df.columns[2]
        log(f"⚠ 未找到涨跌幅字段，尝试使用: {pct_col}")

    log(f"使用涨跌幅字段: {pct_col}")

    # 找名称字段
    name_col = df.columns[0]  # 默认第1列是名称
    for col in df.columns:
        if '名称' in str(col) or 'name' in str(col).lower() or '板块' in str(col):
            name_col = col
            break
    log(f"使用名称字段: {name_col}")

    # 转换为数字
    df[pct_col] = df[pct_col].astype(float)

    # 按涨跌幅排序
    df_sorted = df.sort_values(by=pct_col, ascending=False)

    # 涨幅前TOP_N
    top_gainers = df_sorted.head(TOP_N)
    # 跌幅前TOP_N（排序让跌幅最大的排第一）
    top_losers = df_sorted.tail(TOP_N).iloc[::-1]

    ranking = []
    for _, row in top_gainers.iterrows():
        ranking.append({
            'name': str(row[name_col]),
            'pct': round(float(row[pct_col]), 2),
        })

    for _, row in top_losers.iterrows():
        ranking.append({
            'name': str(row[name_col]),
            'pct': round(float(row[pct_col]), 2),
        })

    return ranking


def main():
    log("概念涨跌幅排名 v2")
    print("=" * 50)

    ranking = fetch_concept_ranking()
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not ranking:
        log("⚠ 无数据，保留已有文件，不覆盖")
        if os.path.exists(OUT):
            log(f"✓ 已有数据保留: {OUT}")
        else:
            log("⚠ 无已有数据，写入空结构")
            output = {'update_time': now_str, 'ranking': []}
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, 'w', encoding='utf-8') as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
        return

    output = {
        'update_time': now_str,
        'ranking': ranking,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log(f"✓ 完成！共 {len(ranking)} 个概念")
    for i, x in enumerate(ranking, 1):
        arrow = '▲' if x['pct'] > 0 else '▼'
        print(f"  {i}. {x['name']} {arrow}{abs(x['pct']):.2f}%")


if __name__ == '__main__':
    main()
