#!/usr/bin/env python3
"""全A股3日累积偏离值计算 → stock_deviation.json
用于个股查询页异动停牌检测卡片
规则：连续3个交易日涨幅/跌幅偏离值累计达±20%触发异动停牌
"""
import akshare as ak
import json
import os
import time
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT = os.path.join(DATA_DIR, "stock_deviation.json")
THRESHOLD = 20
MAX_SCAN = 200  # 优先扫描近期活跃股，控制API调用量

def get_trade_dates(n=5):
    """获取最近N个交易日"""
    today = datetime.now()
    # 周末回退到周五
    weekday = today.weekday()
    if weekday >= 5:
        days_back = weekday - 4
        today = today - timedelta(days=days_back)
    # 从东方财富获取交易日历
    try:
        df = ak.tool_trade_date_hist_sina()
        dates = sorted(df["trade_date"].tolist(), reverse=True)
        return [d for d in dates[:n] if d <= today.strftime("%Y-%m-%d")]
    except Exception:
        # fallback：简单推算
        dates = []
        d = today
        while len(dates) < n:
            if d.weekday() < 5:
                dates.append(d.strftime("%Y-%m-%d"))
            d -= timedelta(days=1)
        return dates

def fetch_deviations():
    """逐只扫描活跃A股，计算3日累积偏离值"""
    trade_dates = get_trade_dates(5)
    if len(trade_dates) < 2:
        print(f"  [异动] 交易日不足({len(trade_dates)}天)，跳过")
        return {}

    # 获取涨停板池活跃股作为扫描候选
    candidates = {}
    pool_dates = [trade_dates[0].replace("-", "")]
    for d in pool_dates:
        try:
            df = ak.stock_zt_pool_em(date=d)
            if df is not None and len(df) > 0:
                for _, row in df.iterrows():
                    code = str(row.get("代码", "")).strip()
                    name = str(row.get("名称", "")).strip()
                    if code and name:
                        candidates[code] = name
        except Exception:
            pass

    # 补充概念龙头
    try:
        ranking_path = os.path.join(DATA_DIR, "concept_ranking.json")
        if os.path.exists(ranking_path):
            with open(ranking_path, encoding="utf-8") as f:
                cr = json.load(f)
            for item in cr.get("hot_list", [])[:20]:
                for stock in item.get("leading_stocks", []):
                    code = stock.get("code", "")
                    name = stock.get("name", "")
                    if code and name:
                        candidates[code] = name
    except Exception:
        pass

    # 补充龙虎榜上榜股
    try:
        lhb_path = os.path.join(DATA_DIR, "lhb_result.json")
        if os.path.exists(lhb_path):
            with open(lhb_path, encoding="utf-8") as f:
                lhb = json.load(f)
            for s in lhb.get("stocks", []):
                candidates[s["code"]] = s["name"]
    except Exception:
        pass

    if not candidates:
        print("  [异动] 无候选股")
        return {}

    # 限流扫描
    results = {}
    codes = list(candidates.keys())[:MAX_SCAN]
    for i, code in enumerate(codes):
        try:
            hist = ak.stock_zh_a_hist(symbol=code, period="daily",
                                      start_date=trade_dates[-1],
                                      end_date=trade_dates[0],
                                      adjust="qfq")
            if hist is None or len(hist) < 2:
                continue
            # 取最近N天收盘价
            closes = hist["收盘"].tolist()[-min(len(trade_dates), len(hist)):]
            if len(closes) < 2:
                continue
            # 3日累积偏离值
            cum_change = ((closes[-1] / closes[0]) - 1) * 100 if len(closes) >= 3 else ((closes[-1] / closes[0]) - 1) * 100
            results[code] = {
                "name": candidates[code],
                "deviation": round(cum_change, 1),
                "gap": round(max(0, THRESHOLD - abs(cum_change)), 1),
                "threshold": THRESHOLD,
                "close": round(closes[-1], 2),
            }
            if (i+1) % 20 == 0:
                print(f"  [异动] {i+1}/{len(codes)}...")
            time.sleep(0.2)
        except Exception:
            pass

    print(f"  [异动] 扫描{len(codes)}只，有效{len(results)}只")
    return results

def main():
    print("=" * 50)
    print("  个股异动偏离值计算")
    print("=" * 50)

    deviations = fetch_deviations()

    result = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "threshold": THRESHOLD,
        "stocks": deviations,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 已保存: {OUTPUT} ({len(deviations)} 只)")

    # 展示接近触发的股票
    near = [(k,v) for k,v in deviations.items() if abs(v["deviation"]) >= 10]
    near.sort(key=lambda x: abs(x[1]["deviation"]), reverse=True)
    if near:
        print(f"  接近触发(≥10%):")
        for code, v in near[:10]:
            gap_info = f" · 距触发 {v['gap']}%" if v['gap'] > 0 else ""
            print(f"    {code} {v['name']} {v['deviation']:+.1f}%{gap_info}")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
