#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主力资金抱团数据 — 基于东方财富行业/概念资金流向
用法: python fetch_herding_data.py
输出: data/herding_data.json

数据源: akshare stock_fund_flow_industry + stock_fund_flow_concept (东方财富免费端口)
"""
import os, sys, json, datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "herding_data.json")


def fetch_industry_flow():
    """获取行业资金流向TOP"""
    try:
        import akshare as ak
        df = ak.stock_fund_flow_industry()
        if df is None or len(df) == 0:
            return [], []
        inflow = []
        outflow = []
        for _, row in df.iterrows():
            name = str(row.get('行业', ''))
            net = float(row.get('净额', 0) or 0)
            pct = float(row.get('行业-涨跌幅', 0) or 0)
            leader = str(row.get('领涨股', ''))
            if not name or abs(net) < 0.5:
                continue
            item = {'name': name, 'net': round(net, 2), 'pct': pct, 'leader': leader}
            if net > 0:
                inflow.append(item)
            else:
                outflow.append(item)
        inflow.sort(key=lambda x: x['net'], reverse=True)
        outflow.sort(key=lambda x: x['net'])
        return inflow[:5], outflow[:5]
    except Exception as e:
        print(f"  [industry flow] {e}")
        return [], []


def fetch_concept_flow():
    """获取概念板块资金流向TOP"""
    try:
        import akshare as ak
        df = ak.stock_fund_flow_concept()
        if df is None or len(df) == 0:
            return [], []
        inflow = []
        outflow = []
        for _, row in df.iterrows():
            name = str(row.get('行业', ''))  # 概念也用"行业"字段
            net = float(row.get('净额', 0) or 0)
            pct = float(row.get('行业-涨跌幅', 0) or 0)
            leader = str(row.get('领涨股', ''))
            if not name or abs(net) < 0.5:
                continue
            item = {'name': name, 'net': round(net, 2), 'pct': pct, 'leader': leader}
            if net > 0:
                inflow.append(item)
            else:
                outflow.append(item)
        inflow.sort(key=lambda x: x['net'], reverse=True)
        outflow.sort(key=lambda x: x['net'])
        return inflow[:10], outflow[:5]
    except Exception as e:
        print(f"  [concept flow] {e}")
        return [], []


def load_old_data():
    """加载旧数据，API空数据时回退"""
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            if old.get("current_clusters"):
                return old
        except:
            pass
    return None


def main():
    print("=" * 50)
    print("  主力资金抱团（行业+概念资金流向）")
    print("=" * 50)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    old_data = load_old_data()

    print("\n[1/2] 行业资金流向...")
    ind_in, ind_out = fetch_industry_flow()
    print(f"  流入TOP{len(ind_in)} 流出TOP{len(ind_out)}")
    if ind_in:
        print(f"  领涨: {ind_in[0]['name']} +{ind_in[0]['net']}亿")

    print("[2/2] 概念资金流向...")
    con_in, con_out = fetch_concept_flow()
    print(f"  流入TOP{len(con_in)} 流出TOP{len(con_out)}")
    if con_in:
        print(f"  领涨: {con_in[0]['name']} +{con_in[0]['net']}亿")

    # 构建结果
    result = {
        "update_time": now_str,
        "current_clusters": [],
        "high_prob": [],
        "cautious": [],
        "catalysts": [],
        "broker_views": [],
        "industry_flow": {"inflow": ind_in, "outflow": ind_out},
        "concept_flow": {"inflow": con_in, "outflow": con_out},
    }

    # 当前抱团 → 行业流入TOP3 + 概念流入TOP2
    for i, item in enumerate(ind_in[:3]):
        result["current_clusters"].append({
            "rank": i + 1, "medal": ["🥇", "🥈", "🥉"][i],
            "sector": item['name'], "amount": item['net'], "unit": "亿",
            "direction": "流入", "leader": item['leader'], "pct": item['pct']
        })

    # 接力方向 → 概念流入TOP5（排序后）
    for item in con_in[:5]:
        result["high_prob"].append({
            "sector": item['name'], "net": item['net'], "unit": "亿",
            "leader": item['leader'], "pct": item['pct']
        })

    # 谨慎方向 → 行业流出TOP3
    for item in ind_out[:3]:
        result["cautious"].append({
            "sector": item['name'], "reason": f"主力净流出{item['net']}亿"
        })

    # 空数据保护
    has_data = bool(result["current_clusters"] or result["high_prob"])
    if not has_data and old_data:
        print("\n  WARN 数据为空，保留旧数据")
        result = old_data
        result["update_time"] = now_str

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  已保存: {OUTPUT_FILE}")
    print(f"  当前抱团: {len(result['current_clusters'])} 方向")
    print(f"  接力方向: {len(result['high_prob'])} 个")


if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
