#!/usr/bin/env python3
"""获取 A 股全量股票名称列表（每周更新一次即可）"""

import json, os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT = os.path.join(DATA_DIR, "stock_names.json")

def main():
    print("=" * 50)
    print("  A 股全量股票名称列表更新")
    print("=" * 50)

    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            print("  ⚠️ 无数据，跳过")
            return

        stocks = []
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            name = str(row.get("名称", "")).strip()
            if not code or not name:
                continue
            prefix = "sz" if code.startswith(("0", "3")) else "sh"
            stocks.append({
                "code": code,
                "name": name,
                "full_code": prefix + code,
            })

        if len(stocks) < 4000:
            print(f"  ⚠️ 仅获取 {len(stocks)} 只（预期>5000），保留旧文件")
            return

        result = stocks

        with open(OUTPUT, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=0)

        print(f"  ✅ 已保存 {len(stocks)} 只股票 → {OUTPUT}")

    except Exception as e:
        print(f"  ⚠️ 获取失败: {e}")

if __name__ == "__main__":
    main()
