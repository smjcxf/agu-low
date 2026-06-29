#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
沪深港通资金监控 — 南向资金(可用) + 北向成交总额(可用) + 北向净买额(已停)
用法: python fetch_north_fund.py
输出: data/north_fund.json

说明:
- 北向净买额自2024年5月起港交所不再披露，akshare数据止于2024-08-16
- 北向成交总额仍每日发布（收盘后），从 eastmoney 页面抓取
- 南向资金数据完整可用（净买额+成交额+历史）

原则: 不构造数据，API无数据时保留旧数据
"""
import os, sys, json, re, datetime, urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "north_fund.json")


def fetch_south_summary():
    """从akshare获取南向资金当日汇总"""
    try:
        import akshare as ak
        df = ak.stock_hsgt_fund_flow_summary_em()
        south = df[df['资金方向'] == '南向']
        if len(south) == 0:
            return None
        sh_row = south[south['板块'] == '港股通(沪)']
        sz_row = south[south['板块'] == '港股通(深)']
        sh_net = 0.0
        sz_net = 0.0
        if len(sh_row) > 0:
            sh_net = float(sh_row.iloc[0].get('成交净买额', 0) or 0)
        if len(sz_row) > 0:
            sz_net = float(sz_row.iloc[0].get('成交净买额', 0) or 0)
        total = sh_net + sz_net
        if abs(total) < 0.01:
            return None
        direction = "流入" if total >= 0 else "流出"
        return {
            "total": round(abs(total), 2),
            "unit": "亿",
            "direction": direction,
            "sh_net": round(sh_net, 2),
            "sz_net": round(sz_net, 2)
        }
    except Exception as e:
        print(f"  [south summary] {e}")
        return None


def fetch_south_weekly():
    """获取本周南向资金累计净流入（最近5个交易日）"""
    try:
        import akshare as ak
        df = ak.stock_hsgt_hist_em(symbol="南向资金")
        if df is None or len(df) == 0:
            return None
        valid = df.dropna(subset=["当日成交净买额"]).sort_values("日期", ascending=False)
        if len(valid) == 0:
            return None
        recent = valid.head(5)
        weekly_total = recent["当日成交净买额"].sum()
        if abs(weekly_total) < 0.01:
            return None
        direction = "流入" if weekly_total >= 0 else "流出"
        return {
            "total": round(abs(weekly_total), 2),
            "unit": "亿",
            "direction": direction,
            "days": len(recent),
            "date_range": f"{recent.iloc[-1]['日期']} — {recent.iloc[0]['日期']}"
        }
    except Exception as e:
        print(f"  [south weekly] {e}")
        return None


def fetch_south_history_days(days=10):
    """获取南向资金最近N日明细（用于趋势图）"""
    try:
        import akshare as ak
        df = ak.stock_hsgt_hist_em(symbol="南向资金")
        if df is None or len(df) == 0:
            return None
        valid = df.dropna(subset=["当日成交净买额"]).sort_values("日期", ascending=False)
        if len(valid) == 0:
            return None
        recent = valid.head(days)
        result = []
        for _, row in recent.iterrows():
            result.append({
                "date": str(row["日期"]),
                "net_buy": round(float(row.get("当日成交净买额", 0) or 0), 2)
            })
        return list(reversed(result))  # 时间升序
    except Exception as e:
        print(f"  [south history] {e}")
        return None


def fetch_south_individual():
    """获取南向资金个股净买入排行（流入TOP5 + 流出TOP5）"""
    try:
        import akshare as ak
        df = ak.stock_hsgt_individual_em(symbol="南向")
        if df is None or len(df) == 0:
            return None

        # 按当日成交净买额降序
        if "当日成交净买额" not in df.columns:
            print("    WARN 个股数据无'当日成交净买额'列")
            return None

        df = df.dropna(subset=["当日成交净买额"]).copy()
        df["_net"] = df["当日成交净买额"].astype(float)
        df = df.sort_values("_net", ascending=False)

        top_buy = []
        for _, row in df.head(5).iterrows():
            top_buy.append({
                "name": str(row.get("名称", "")),
                "code": str(row.get("代码", "")),
                "net_buy": round(float(row["当日成交净买额"]), 2),
            })

        top_sell = []
        df_asc = df.sort_values("_net", ascending=True)
        for _, row in df_asc.head(5).iterrows():
            val = float(row["当日成交净买额"])
            if val >= 0:  # 全部都是流入就不展示流出
                break
            top_sell.append({
                "name": str(row.get("名称", "")),
                "code": str(row.get("代码", "")),
                "net_buy": round(val, 2),
            })

        result = {"top_buy": top_buy, "top_sell": top_sell}
        print(f"    OK 流入{len(top_buy)}只 流出{len(top_sell)}只")
        return result
    except Exception as e:
        print(f"  [south individual] {e}")
        return None


def fetch_north_total_txn():
    """从eastmoney抓取北向资金成交总额"""
    try:
        url = "https://push2.eastmoney.com/api/qt/kamt.kline/get"
        params = {
            "fields1": "f1,f2,f3,f4",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60",
            "klt": "101",
            "lmt": "5",
            "secid": "1.000001"
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        full_url = f"{url}?{qs}"
        req = urllib.request.Request(full_url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.eastmoney.com/"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("rc") != 0:
                return None
            d = data.get("data", {})

            def parse_kamt(arr):
                if not arr:
                    return None
                parts = arr[-1].split(",")
                # Format: date, net_buy, quota_remaining?, value3
                if len(parts) >= 4:
                    return {
                        "date": parts[0],
                        "net": float(parts[1]) if parts[1] else 0,
                        "quota": float(parts[2]) if parts[2] else 0,
                    }
                return None

            sh2hk = parse_kamt(d.get("sh2hk", []))  # 沪股通→港交所 (北向沪)
            sz2hk = parse_kamt(d.get("sz2hk", []))  # 深股通→港交所 (北向深)

            north_data = {
                "date": datetime.datetime.now().strftime("%Y-%m-%d"),
                "status": "北向净买额已停更(2024.5起港交所新规)，仅保留南向资金数据",
                "last_available": "2024-08-16"
            }

            return north_data
    except Exception as e:
        print(f"  [north total txn] {e}")
        return None


def load_old_data():
    """加载旧数据，用于API空数据回退"""
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            # 检查是否有有效数据
            sf = old.get("south_flow", {})
            if sf.get("total", 0) > 0:
                return old
        except:
            pass
    return None


def main():
    print("=" * 50)
    print("  沪深港通资金监控")
    print("=" * 50)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    old_data = load_old_data()

    result = {
        "update_time": now_str,
        "data_date": None,  # 北向净买额已停更(2024.5起)，无有效数据日期
        "south_flow": {
            "total": 0, "unit": "亿", "direction": "—",
            "sh_net": 0, "sz_net": 0
        },
        "south_week": None,
        "south_history": None,
        "south_individual": None,
        "north_info": {
            "note": "北向净买额自2024年5月起不再披露（港交所新规），仅保留成交总额参考",
            "last_available": "2024-08-16"
        },
        "data_available": False,
        "data_source": "akshare + eastmoney",
    }

    has_any_data = False

    # 1. 南向当日汇总
    print("\n  [1/4] 南向当日净流入...")
    south = fetch_south_summary()
    if south and south["total"] > 0:
        result["south_flow"] = south
        has_any_data = True
        print(f"    OK {south['direction']} {south['total']}{south['unit']} (沪:{south['sh_net']} 深:{south['sz_net']})")
    else:
        print("    WARN 无数据（可能非交易日或盘中未更新）")

    # 2. 南向周累计
    print("  [2/4] 南向周累计...")
    week = fetch_south_weekly()
    if week:
        result["south_week"] = week
        has_any_data = True
        print(f"    OK 本周{week['direction']} {week['total']}{week['unit']} ({week['date_range']})")
    else:
        print("    WARN 无数据")

    # 3. 南向30日趋势
    print("  [3/4] 南向30日趋势...")
    history = fetch_south_history_days(30)
    if history:
        result["south_history"] = history
        has_any_data = True
        print(f"    OK {len(history)} 日明细")
    else:
        print("    WARN 无数据")

    # 4. 南向个股明细（流入TOP5 / 流出TOP5）
    print("  [4/5] 南向个股明细...")
    individual = fetch_south_individual()
    if individual:
        result["south_individual"] = individual
        has_any_data = True
    else:
        print("    WARN 无数据")

    # 5. 北向额度信息
    print("  [5/5] 北向额度...")
    north = fetch_north_total_txn()
    if north:
        result["north_info"] = {**result["north_info"], **north}
        print(f"    OK 沪已用:{north.get('sh_quota_used', '—')}亿 深已用:{north.get('sz_quota_used', '—')}亿")
    else:
        print("    WARN 无数据")

    # 5. 数据完整性判断
    if has_any_data:
        result["data_available"] = True
    else:
        if old_data:
            print("\n  ⚠️ 所有API均无数据，保留最近一次有效数据")
            # 只保留旧数据，但更新时间戳
            old_data["update_time"] = now_str
            result = old_data
        else:
            print("\n  ⚠️ 无数据且无旧数据可回退")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 已保存: {OUTPUT_FILE}")
    print(f"   available={result.get('data_available', False)}")
    print(f"   南向当日={result.get('south_flow', {}).get('total', 0)}{result.get('south_flow', {}).get('unit', '')}")


if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
