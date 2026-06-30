#!/usr/bin/env python3
"""
fetch_limit_up_heatmap.py — 涨停热力矩阵数据采集
- 每日获取涨停股票 → 按概念板块归类统计 → 构建10日热力矩阵
- 输出 data/limit_up_heatmap.json
- 数据源：akshare stock_zt_pool_strong_em（近10日强势涨停）
"""
import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

try:
    import akshare as ak
except ImportError:
    print("✗ akshare 未安装")
    sys.exit(1)

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(WORKSPACE, "data")
OUTPUT = os.path.join(DATA_DIR, "limit_up_heatmap.json")

# 概念板块关键词映射（从涨停股票所属概念中匹配）
SECTOR_KEYWORDS = [
    "新能源车", "人工智能", "半导体", "机器人", "光伏",
    "低空经济", "医药", "消费电子", "军工", "信创",
    "算力", "人形机器人", "无人驾驶", "固态电池", "储能",
    "数据要素", "6G", "商业航天", "氢能源", "芯片",
    "通信设备", "物联网", "智能驾驶", "光模块", "液冷",
]


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def get_limit_up_data():
    """获取近期涨停股票数据"""
    limit_stocks = []
    today = datetime.now()

    # 尝试多种数据源
    # 方案1：强势股池（含多次涨停统计）
    try:
        df = ak.stock_zt_pool_strong_em(date=today.strftime("%Y%m%d"))
        if df is not None and len(df) > 0:
            for _, row in df.iterrows():
                limit_stocks.append({
                    "name": str(row.get("名称", "")),
                    "code": str(row.get("代码", "")),
                    "pct_chg": float(row.get("涨跌幅", 0)) if row.get("涨跌幅") else 0,
                    "limit_times": int(row.get("涨停次数", 1)) if row.get("涨停次数") else 1,
                    "sector": str(row.get("所属行业", "")),
                })
            if limit_stocks:
                print(f"  📊 强势股池: {len(limit_stocks)} 只")
                return limit_stocks
    except Exception as e:
        print(f"  ⚠ 强势股池失败: {e}")

    # 方案2：当日涨停池 + 行业信息
    try:
        df = ak.stock_zt_pool_em(date=today.strftime("%Y%m%d"))
        if df is not None and len(df) > 0:
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                limit_stocks.append({
                    "name": str(row.get("名称", "")),
                    "code": code,
                    "pct_chg": float(row.get("涨跌幅", 0)) if row.get("涨跌幅") else 0,
                    "limit_times": int(row.get("连板数", 1)) if row.get("连板数") else 1,
                    "sector": str(row.get("所属行业", "")),
                })
            if limit_stocks:
                print(f"  📊 当日涨停: {len(limit_stocks)} 只")
                return limit_stocks
    except Exception as e:
        print(f"  ⚠ 当日涨停池失败: {e}")

    return limit_stocks


def classify_by_sector(stocks, industry_map=None):
    """将涨停股票归类到概念板块"""
    sector_counts = defaultdict(lambda: defaultdict(int))

    # 建立关键词→板块名映射
    keyword_map = {}
    for kw in SECTOR_KEYWORDS:
        # 模糊匹配：如果行业/概念名包含关键词则归类
        keyword_map[kw.lower()] = kw

    for s in stocks:
        sector_str = (s.get("sector", "") or "").strip()
        if not sector_str:
            continue

        matched = False
        for kw in SECTOR_KEYWORDS:
            if kw.lower() in sector_str.lower() or sector_str.lower() in kw.lower():
                sector_counts[kw][s["name"]] = s["limit_times"]
                matched = True
                break

        if not matched:
            # 未匹配的归入"其他"（如果板块名有实际内容）
            sector_counts["其他"][s["name"]] = s.get("limit_times", 1)

    return sector_counts


def main():
    print("=" * 60)
    print(f"  涨停热力矩阵采集  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── 1. 获取当前数据 ──
    existing = load_json(OUTPUT, {"dates": [], "sectors": []})
    existing_dates = existing.get("dates", [])
    existing_sectors = existing.get("sectors", [])

    # ── 2. 获取今日涨停 ──
    limit_stocks = get_limit_up_data()
    if not limit_stocks:
        print("  ⚠️  今日无涨停数据（休市或API异常），写入空数据")
        output = {"dates": existing_dates or [], "sectors": existing_sectors or [], "data_available": False, "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
        with open(OUTPUT, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"  ✅ 已写入空结构: {OUTPUT}")
        return

    # ── 3. 按板块归类并统计 ──
    sector_counts = classify_by_sector(limit_stocks)
    if not sector_counts:
        print("  ⚠️  板块归类为空")
        return

    today_str = datetime.now().strftime("%m/%d")
    print(f"  📅 今日: {today_str}")

    # ── 4. 更新热力矩阵 ──
    # 构建现有的 sector→data 映射
    sector_map = {}
    for s in existing_sectors:
        sector_map[s["name"]] = s["data"]

    # 获取或初始化所有板块
    all_sectors = set(sector_map.keys()) | set(sector_counts.keys())
    # 排序：按今日涨停数降序
    sorted_sectors = sorted(all_sectors, key=lambda x: sum(sector_counts.get(x, {}).values()), reverse=True)

    # 取前15个板块
    top_sectors = sorted_sectors[:15]

    # 更新数据
    new_dates = existing_dates[-9:] + [today_str] if len(existing_dates) >= 9 else existing_dates + [today_str]
    # 确保日期长度不超过10
    if len(new_dates) > 10:
        new_dates = new_dates[-10:]

    new_sectors_data = []
    for sec in top_sectors:
        old_data = sector_map.get(sec, [])
        # 补齐长度到 (len(new_dates) - 1)
        while len(old_data) < len(new_dates) - 1:
            old_data.append(0)
        # 截取
        old_data = old_data[-(len(new_dates) - 1):] if len(old_data) > len(new_dates) - 1 else old_data

        # 今日数据
        today_count = sum(sector_counts.get(sec, {}).values())
        sec_data = old_data + [today_count]
        # 确保长度一致
        while len(sec_data) < len(new_dates):
            sec_data.insert(0, 0)
        sec_data = sec_data[-len(new_dates):]

        new_sectors_data.append({
            "name": sec,
            "data": sec_data,
        })

    result = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dates": new_dates,
        "sectors": new_sectors_data,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 热力矩阵: {len(new_dates)} 日 × {len(new_sectors_data)} 板块")
    for s in new_sectors_data:
        total = sum(s["data"])
        print(f"     {s['name']}: {s['data']}  (累计{total})")
    print(f"\n  输出: {OUTPUT}")
    print(f"\n  结果: ✓ 成功 ({datetime.now().strftime('%H:%M:%S')})")


if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
