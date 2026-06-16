#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北向资金监控 — 仅从API获取真实数据
用法: python fetch_north_fund.py
输出: data/north_fund.json

原则: 不构造数据，API无数据时保留旧数据
"""
import os, sys, json, datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "north_fund.json")

def fetch_summary():
    """从akshare获取北向资金当日汇总"""
    try:
        import akshare as ak
        df = ak.stock_hsgt_fund_flow_summary_em()
        north = df[df['资金方向'] == '北向']
        if len(north) == 0:
            return None
        sh = north[north['板块'] == '沪股通']
        sz = north[north['板块'] == '深股通']
        total = 0.0
        for subset in [sh, sz]:
            if len(subset) > 0:
                total += float(subset.iloc[-1].get('资金净流入', 0) or 0)
        if total == 0:
            return None
        direction = "流入" if total >= 0 else "流出"
        return {"total": round(abs(total), 2), "unit": "亿", "direction": direction}
    except Exception as e:
        print(f"  [API] {e}")
        return None


def load_old_data():
    """加载旧数据，用于API空数据回退"""
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            # 旧数据只要有top_buy或有净流入就算有效
            if old.get("top_buy") or (old.get("net_flow", {}).get("total", 0) > 0):
                return old
        except:
            pass
    return None


def main():
    print("=" * 50)
    print("  北向资金监控 (仅真实API数据)")
    print("=" * 50)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    old_data = load_old_data()

    result = {
        "update_time": now_str,
        "data_date": None,
        "top_buy": [],
        "consecutive": [],
        "net_flow": {"total": 0, "unit": "亿", "direction": "未获取"},
        "data_available": False,
        "data_source": "API无数据",
    }

    print("  查询北向资金API...")
    summary = fetch_summary()
    if summary and summary["total"] > 0:
        result["net_flow"] = summary
        result["data_available"] = True
        result["data_date"] = datetime.datetime.now().strftime("%Y-%m-%d")
        result["data_source"] = "akshare API"
        print(f"  OK {summary['direction']} {summary['total']}{summary['unit']}")
    else:
        # 盘后/非交易日空数据保护：保留旧数据
        if old_data:
            print("  WARN API无数据，保留最近一次有效数据")
            result = old_data
            result["update_time"] = now_str  # 更新时间
        else:
            print("  WARN API无数据且无旧数据可回退")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  已保存: {OUTPUT_FILE}")
    print(f"   available={result.get('data_available', False)}")

if __name__ == "__main__":
    main()
