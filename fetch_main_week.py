#!/usr/bin/env python3
"""
获取主力资金周维度板块流向（5日累计）

原数据源 akshare.stock_sector_fund_flow_rank(indicator='5日') 因 IP 被东方财富
拒绝连接（RemoteDisconnected），改为从 sector_fund_flow_history.json 自算5日累计。

sector_fund_flow_history.json 由 fetch_sector_fund_flow.py 每次运行时追加当日数据，
因此本脚本依赖 fetch_sector_fund_flow.py 先运行。
"""

import json, os, sys
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "main_week.json")
HISTORY_FILE = os.path.join(DATA_DIR, "sector_fund_flow_history.json")


def compute_5d_from_history():
    """从行业资金流历史数据计算5日净流入/流出TOP5"""
    if not os.path.exists(HISTORY_FILE):
        print("  [WARN] sector_fund_flow_history.json 不存在")
        return None, None

    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        hist = json.load(f)

    if not hist:
        print("  [WARN] 历史数据为空")
        return None, None

    sector_5d = {}
    latest_date = ""

    for sector, entries in hist.items():
        if not entries:
            continue
        # 取最近5个交易日
        recent = entries[-5:]
        total_5d = round(sum(e["net"] for e in recent), 2)
        sector_5d[sector] = total_5d
        # 记录最新日期
        last_date = recent[-1]["date"]
        if last_date > latest_date:
            latest_date = last_date

    if not sector_5d:
        return None, None

    sorted_5d = sorted(sector_5d.items(), key=lambda x: x[1], reverse=True)

    buy_top5 = []
    sell_top5 = []

    for name, net in sorted_5d:
        if net > 0:
            buy_top5.append({"name": name, "net": net, "unit": "亿", "pct": 0})
        elif net < 0:
            sell_top5.append({"name": name, "net": net, "unit": "亿", "pct": 0})

    # 各取TOP5
    buy_top5 = buy_top5[:5]
    sell_top5 = sorted(sell_top5, key=lambda x: x["net"])[:5]  # 负值最大排前面

    print(f"  最新数据日期: {latest_date}")
    print(f"  覆盖行业: {len(sector_5d)}")
    print(f"  5日流入TOP5: {[(x['name'], x['net']) for x in buy_top5]}")
    print(f"  5日流出TOP5: {[(x['name'], x['net']) for x in sell_top5]}")

    return buy_top5, sell_top5


def main():
    print("=" * 50)
    print("  主力资金周维度板块流向 (5日累计，自算)")
    print("=" * 50)

    buy, sell = compute_5d_from_history()

    result = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "自算-行业资金流历史5日累计",
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
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
