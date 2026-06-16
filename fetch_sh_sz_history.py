#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上证/深证 每日成交金额历史
生成: sh_sz_history.json  （仅含 amount_history）
涨跌家数统计由 fetch_up_down_stats.py 独立维护

数据源: 新浪财经 (k线 + 实时)

用法:
  python fetch_sh_sz_history.py          # 生成全部
  python fetch_sh_sz_history.py --days 60  # 保留最近N天
"""

import json, os, sys, argparse, time, requests
from datetime import datetime, timedelta

DATA_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT_FILE  = os.path.join(DATA_DIR, "sh_sz_history.json")

DEFAULT_DAYS = 60

SINA_KLINE_URL   = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
SINA_REALTIME_URL = "https://hq.sinajs.cn/list={}"


def fetch_sina_kline(symbol, days=DEFAULT_DAYS):
    """
    获取指数历史k线数据
    返回: [{"day": "2026-06-09", "open": ..., "close": ..., "high": ..., "low": ..., "volume": ...}, ...]
    """
    url = f"{SINA_KLINE_URL}?symbol={symbol}&scale=240&ma=5&datalen={days}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            print(f"    {symbol} k线请求失败: {r.status_code}")
            return []
        data = json.loads(r.text)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"    {symbol} k线获取失败: {e}")
        return []


def fetch_sina_realtime(symbols):
    """
    获取指数实时数据
    symbols: 逗号分隔的代码，如 "sh000001,sz399001"
    返回: {"sh000001": {"volume": ..., "amount": ...}, ...}
    """
    result = {}
    url = SINA_REALTIME_URL.format(symbols)
    headers = {"Referer": "https://finance.sina.com.cn"}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            print(f"    实时数据请求失败: {r.status_code}")
            return result
        for line in r.text.strip().split(";"):
            line = line.strip()
            if not line or "var hq_str_" not in line:
                continue
            prefix = 'var hq_str_'
            start = line.find(prefix) + len(prefix)
            end = line.find('="')
            symbol = line[start:end]
            data_str = line.split('"')[1]
            parts = data_str.split(",")
            if len(parts) >= 10:
                result[symbol] = {
                    "name":   parts[0],
                    "open":   float(parts[1]),
                    "pre_close": float(parts[2]),
                    "price":  float(parts[3]),
                    "high":   float(parts[4]),
                    "low":    float(parts[5]),
                    "volume": float(parts[8]),   # 成交量（手）
                    "amount": float(parts[9]),   # 成交额（元）
                }
    except Exception as e:
        print(f"    实时数据获取失败: {e}")
    return result


def build_amount_history(sh_kline, sz_kline, sh_ratio, sz_ratio):
    """
    构建成交金额历史
    sh_ratio: 上证 成交额/成交量 比值（元/手）
    sz_ratio: 深证 成交额/成交量 比值（元/手）
    """
    result = []
    sh_map = {d["day"]: d for d in sh_kline}
    sz_map = {d["day"]: d for d in sz_kline}
    all_dates = sorted(set(sh_map.keys()) | set(sz_map.keys()))

    for dt in all_dates:
        sh = sh_map.get(dt)
        sz = sz_map.get(dt)

        # 新浪k线volume单位：上证是"股"，深证是"手"
        # 统一转为"手"后再乘以比值
        sh_vol_hand = float(sh["volume"]) / 100 if sh else 0
        sz_vol_hand = float(sz["volume"]) if sz else 0

        sh_amt = sh_vol_hand * sh_ratio if sh else 0
        sz_amt = sz_vol_hand * sz_ratio if sz else 0

        mm = dt[5:7].lstrip("0")
        dd = dt[8:10].lstrip("0")
        result.append({
            "date":       f"{mm}/{dd}",
            "sh_amount":  round(sh_amt / 1e8, 1),   # 转为亿元
            "sz_amount":  round(sz_amt / 1e8, 1),
            "total":       round((sh_amt + sz_amt) / 1e8, 1),
        })
    return result


def load_history():
    """读取已有历史，保留 up_down / daily_stats"""
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"update_time": "", "amount_history": [], "up_down": {}, "daily_stats": []}


def main():
    parser = argparse.ArgumentParser(description="上证/深证成交金额历史")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"保留最近N天 (默认{DEFAULT_DAYS})")
    args = parser.parse_args()

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  生成 上证/深证 成交金额历史")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    os.makedirs(DATA_DIR, exist_ok=True)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 读取已有数据（保留 up_down / daily_stats）
    old = load_history()
    old_up_down   = old.get("up_down", {})
    old_stats     = old.get("daily_stats", [])

    # 获取实时数据（用于计算比值）
    print("\n📊 正在获取实时数据...")
    realtime = fetch_sina_realtime("sh000001,sz399001")
    if len(realtime) < 2:
        print("  ⚠️  实时数据获取失败，保留旧数据")
        out = {
            "update_time":  now_str,
            "amount_history": old.get("amount_history", []),
            "up_down":       old_up_down,
            "daily_stats":   old_stats,
        }
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 已保存（保留旧数据）: {OUT_FILE}")
        return

    sh_rt      = realtime["sh000001"]
    sz_rt      = realtime["sz399001"]
    sh_ratio   = sh_rt["amount"] / sh_rt["volume"] if sh_rt["volume"] > 0 else 2000
    sz_ratio   = sz_rt["amount"] / sz_rt["volume"] if sz_rt["volume"] > 0 else 20
    print(f"  上证比值: {sh_ratio:.2f} 元/手")
    print(f"  深证比值: {sz_ratio:.2f} 元/手")

    # 获取k线历史
    print("\n📊 正在获取上证指数k线...")
    sh_kline = fetch_sina_kline("sh000001", args.days)
    print(f"  ✓ 获取 {len(sh_kline)} 条")

    print("\n📊 正在获取深证成指k线...")
    sz_kline = fetch_sina_kline("sz399001", args.days)
    print(f"  ✓ 获取 {len(sz_kline)} 条")

    if len(sh_kline) == 0 and len(sz_kline) == 0:
        print("\n  ⚠️  k线数据获取失败，保留旧数据")
        out = {
            "update_time":  now_str,
            "amount_history": old.get("amount_history", []),
            "up_down":       old_up_down,
            "daily_stats":   old_stats,
        }
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 已保存（保留旧数据）: {OUT_FILE}")
        return

    # 构建成交金额历史
    print("\n📊 正在构建成交金额历史...")
    amount_history = build_amount_history(sh_kline, sz_kline, sh_ratio, sz_ratio)
    print(f"  ✓ 构建 {len(amount_history)} 条记录")

    # 组装（保留 up_down / daily_stats，由 fetch_up_down_stats.py 维护）
    out = {
        "update_time":   now_str,
        "amount_history": amount_history,
        "up_down":       old_up_down,    # 不变，由独立脚本维护
        "daily_stats":   old_stats,       # 不变，由独立脚本维护
    }

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已保存: {OUT_FILE}")
    print(f"  更新时间: {now_str}")
    print(f"  ℹ️  up_down / daily_stats 由 fetch_up_down_stats.py 维护")


if __name__ == "__main__":
    main()
