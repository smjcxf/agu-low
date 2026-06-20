#!/usr/bin/env python3
"""获取主力资金周维度板块流向（东方财富 5日 行业资金流排名）
来源：akshare.stock_sector_fund_flow_rank(indicator='5日')
数据：https://data.eastmoney.com/bkzj/hy.html
"""

import json, os, sys
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "main_week.json")

def fetch_main_week():
    """获取5日行业资金流排名"""
    try:
        import akshare as ak
        df = ak.stock_sector_fund_flow_rank(indicator="5日", sector_type="行业资金流")
        if df is None or df.empty:
            print("  [WARN] 5日板块资金流 无数据")
            return None, None

        # 列名映射（东方财富返回中文列名）
        # 名称, 今日涨跌幅, 主力净流入-净额, 主力净流入-净占比, 超大单净流入-净额, ...
        name_col = "名称"
        net_col = None
        pct_col = "今日涨跌幅"
        for col in df.columns:
            if "主力净流入-净额" in col:
                net_col = col
                break
        if not net_col:
            for col in df.columns:
                if "净流入" in col and "净额" in col:
                    net_col = col
                    break

        buy_top5 = []
        sell_top5 = []

        if net_col:
            valid = df[df[net_col].notna()].copy()
            valid = valid.sort_values(net_col, ascending=False)
            # 流入TOP5
            inflow = valid[valid[net_col] > 0].head(5)
            for _, row in inflow.iterrows():
                buy_top5.append({
                    "name": str(row.get(name_col, "")).strip(),
                    "net": round(float(row[net_col]) / 1e8, 2),  # 元→亿
                    "unit": "亿",
                    "pct": round(float(row.get(pct_col, 0) or 0), 2),
                })
            # 流出TOP5
            outflow = valid[valid[net_col] < 0].head(5)
            for _, row in outflow.iterrows():
                sell_top5.append({
                    "name": str(row.get(name_col, "")).strip(),
                    "net": round(float(row[net_col]) / 1e8, 2),
                    "unit": "亿",
                    "pct": round(float(row.get(pct_col, 0) or 0), 2),
                })

        return buy_top5, sell_top5

    except Exception as e:
        print(f"  [WARN] fetch_main_week 异常: {e}")
        return None, None


def main():
    print("=" * 50)
    print("  主力资金周维度板块流向 (5日)")
    print("=" * 50)

    buy, sell = fetch_main_week()

    result = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "东方财富-行业资金流-5日",
        "type": "week",
        "buy_top5": buy or [],
        "sell_top5": sell or [],
    }

    if not buy and not sell:
        # 保留已有数据
        if os.path.exists(OUTPUT_FILE):
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            print("  ⚠️ 无新数据，保留旧文件")
            return
        result["available"] = False
    else:
        result["available"] = True
        print(f"  增持: {len(buy or [])} | 减持: {len(sell or [])}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 已保存: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
