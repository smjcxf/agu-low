#!/usr/bin/env python3
"""
fetch_margin.py - 抓取上交所两融（融资融券）日数据
输出: data/margin_data.json
"""
import akshare as ak
import json
import os
from datetime import datetime, timedelta

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

def main():
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    print("抓取上交所两融数据...")
    try:
        df = ak.stock_margin_sse(start_date=start, end_date=end)
        result = {"sh": [], "sz": [], "update_time": ""}
        for _, row in df.iterrows():
            dt = str(row["信用交易日期"]).strip()
            # 兼容多种日期格式
            dt_fmt = dt
            for fmt in ["%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"]:
                try:
                    d_obj = datetime.strptime(dt, fmt)
                    dt_fmt = str(d_obj.month) + "/" + str(d_obj.day)
                    break
                except Exception:
                    continue

            v1 = float(row["融资余额"])
            v2 = float(row["融资买入额"])
            v3 = float(row["融券余量金额"])
            v4 = float(row["融资融券余额"])

            entry = {
                "date": dt_fmt,
                "date_raw": dt,
                "rz_balance": round(v1 / 1e8),
                "rz_buy": round(v2 / 1e8),
                "rq_balance_amt": round(v3 / 1e8),
                "total": round(v4 / 1e8),
            }
            result["sh"].append(entry)

        # 按日期升序排列（旧→新，图表左旧右新）
        result["sh"].sort(key=lambda x: x["date_raw"])

        result["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        out = os.path.join(DATA_DIR, "margin_data.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("  已保存：" + out + "（" + str(len(result["sh"])) + " 条，最新: " + result["sh"][-1]["date"] + "）")
    except Exception as e:
        print("  失败：" + str(e))

if __name__ == "__main__":
    main()
