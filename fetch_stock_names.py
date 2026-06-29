#!/usr/bin/env python3
"""获取 A 股 + 港股全量股票名称列表（每周更新一次即可）"""

import json, os, time
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT = os.path.join(DATA_DIR, "stock_names.json")

def main():
    print("=" * 50)
    print("  A 股 + 港股全量股票名称列表更新")
    print("=" * 50)

    all_stocks = []

    # ── A 股 ──
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            print("  ⚠️ A股无数据，跳过")
        else:
            for _, row in df.iterrows():
                code = str(row.get("代码", "")).strip()
                name = str(row.get("名称", "")).strip()
                if not code or not name:
                    continue
                prefix = "sz" if code.startswith(("0", "3")) else "sh"
                all_stocks.append({
                    "code": code,
                    "name": name,
                    "full_code": prefix + code,
                })
            print(f"  ✅ A股: {len(all_stocks)} 只")
    except Exception as e:
        print(f"  ⚠️ A股获取失败: {e}")

    # ── 港股 ──
    try:
        import akshare as ak
        time.sleep(1)  # 避免请求过于密集
        df_hk = ak.stock_hk_spot_em()
        if df_hk is None or df_hk.empty:
            print("  ⚠️ 港股无数据")
        else:
            hk_count = 0
            for _, row in df_hk.iterrows():
                code = str(row.get("代码", "")).strip()
                name = str(row.get("名称", "")).strip()
                if not code or not name:
                    continue
                # 去重：跳过已在A股列表中的相同code
                if any(s["code"] == code for s in all_stocks):
                    continue
                all_stocks.append({
                    "code": code,
                    "name": name,
                    "full_code": "hk" + code,
                })
                hk_count += 1
            print(f"  ✅ 港股: {hk_count} 只")
    except Exception as e:
        print(f"  ⚠️ 港股获取失败: {e}")

    if len(all_stocks) < 4000:
        print(f"  ⚠️ 总数 {len(all_stocks)} 不足（预期>4000），保留旧文件")
        return

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(all_stocks, f, ensure_ascii=False, indent=0)

    print(f"  ✅ 总计 {len(all_stocks)} 只 → {OUTPUT}")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
