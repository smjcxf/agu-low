#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
板块相对强度 & 领涨/抗跌追踪
用法：python fetch_sector_rs.py
输出：data/sector_rs.json

v2 (2026-06-26): 新增相对强度计算（板块vs大盘指数）
   - 拉取上证指数/沪深300的5日/20日涨跌
   - relative_5d = 板块5日涨跌 - 指数5日涨跌
   - relative_20d = 板块20日涨跌 - 指数20日涨跌
   - 新增 strong_relative_5d / strong_relative_20d / anti_drop 排名
"""
import json, os, sys, datetime, requests as req

OUT = "data/sector_rs.json"
NEODATA_URL = "https://copilot.tencent.com/agenttool/v1/neodata"

# 读取neodata token（优先用仓库内的 .neodata_token）
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".neodata_token")
token = None
import time as _time
# 回退：从 builtin skill 复制 token
if not os.path.exists(TOKEN_FILE):
    alt_paths = [
        "E:/workbuddy/resources/app.asar.unpacked/resources/builtin-skills/.neodata_token",
        os.path.expanduser("~/.workbuddy/.neodata_token"),
        os.path.expanduser("~/.workbuddy/skills/.neodata_token"),
    ]
    for p in alt_paths:
        if os.path.exists(p):
            try:
                with open(p) as f:
                    cache = json.load(f)
                    token = cache.get("token")
                    saved = cache.get("saved_at", 0)
                    if _time.time() - saved < 43200:
                        break
                    else:
                        token = None
            except:
                continue
else:
    try:
        with open(TOKEN_FILE) as f:
            cache = json.load(f)
            token = cache.get("token")
    except:
        with open(TOKEN_FILE) as f:
            token = f.read().strip()

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

def query_neodata(query_text):
    try:
        resp = req.post(NEODATA_URL, json={
            "query": query_text, "channel": "neodata", "sub_channel": "workbuddy"
        }, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not data.get("suc"): return []
        return data.get("data", {}).get("apiData", {}).get("apiRecall", [])
    except: return []

def parse_ranking(api_recall):
    """解析行业涨跌幅排行表格 [2]=名称 [6]=当日 [10]=5日 [11]=20日 [14]=52周"""
    results = []
    seen = set()
    for item in api_recall:
        if "排行" not in item.get("type", ""): continue
        content = item.get("content", "")
        for line in content.strip().split("\n"):
            cols = [c.strip() for c in line.split("|")]
            if len(cols) < 15: continue
            if ":---:" in cols[2]: continue
            name = cols[2]
            if not name or name in seen: continue
            seen.add(name)
            try:
                pct_day = float(cols[6]) if cols[6] and cols[6] != '-' else None
                pct_5d = float(cols[10]) if cols[10] and cols[10] != '-' else None
                pct_20d = float(cols[11]) if cols[11] and cols[11] != '-' else None
                pct_52w = float(cols[14]) if cols[14] and cols[14] != '-' else None
            except: continue
            results.append({"name": name, "pct_day": pct_day, "pct_5d": pct_5d, "pct_20d": pct_20d, "pct_52w": pct_52w})
    return results

def get_index_pct(api_recall):
    """从neodata OHLCV表格提取指数5日/20日涨跌。neodata返回每日行情表，需累加每日涨跌幅计算。"""
    idx = {"sh": None, "hs300": None}

    for item in api_recall:
        content = item.get("content", "")
        name = ""
        if "股票名称：上证指数" in content:
            name = "sh"
        elif "股票名称：沪深300" in content:
            name = "hs300"
        else:
            continue

        # 解析OHLCV表格：分隔线后 col[4] 是单日涨跌幅
        daily_pcts = []
        past_sep = False
        for line in content.split("\n"):
            line = line.strip()
            if ":---:" in line:
                past_sep = True
                continue
            if not past_sep:
                continue
            if "省略" in line or "未开盘" in line:
                continue
            cols = [c.strip() for c in line.split("|")]
            if len(cols) < 5:
                continue
            try:
                pct_str = cols[4]
                if pct_str and pct_str not in ('-', '--', ''):
                    pct = float(pct_str)
                    daily_pcts.append(pct)
            except:
                continue

        if daily_pcts:
            five_d = round(sum(daily_pcts[-5:]), 2)
            twenty_d = round(sum(daily_pcts[-20:]), 2) if len(daily_pcts) >= 20 else round(sum(daily_pcts), 2)
            idx[name] = {"5d": five_d, "20d": twenty_d, "name": "上证指数" if name == "sh" else "沪深300"}

    return idx

def main():
    log("板块相对强度抓取...")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    if not token:
        log("⚠️ neodata token 未找到，使用默认空数据")
        result = {"update_time": now_str, "sectors": [], "strong_5d": [], "strong_20d": [], "strong_52w": [],
                  "weak_5d": [], "strong_relative_5d": [], "strong_relative_20d": [], "anti_drop": [],
                  "index": {}}
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        log(f"✅ 已保存(空): {OUT}")
        return

    # 查涨幅
    up_data = query_neodata("今日A股行业板块涨幅排名TOP15，显示5日涨跌幅、20日涨跌幅、52周涨跌幅")
    # 查跌幅
    down_data = query_neodata("今日A股行业板块跌幅排名TOP15，显示5日涨跌幅、20日涨跌幅、52周涨跌幅")
    # 查指数5日/20日涨跌（需要分别查上证和沪深300的OHLCV数据）
    sh_data = query_neodata("上证指数近20个交易日单日涨跌幅数据")
    hs300_data = query_neodata("沪深300指数近20个交易日单日涨跌幅数据")
    index_data = sh_data + hs300_data

    sectors = parse_ranking(up_data + down_data)
    log(f"✓ 获取到 {len(sectors)} 个行业板块")

    # 解析指数基准
    idx = get_index_pct(index_data)
    # 优先用沪深300，其次上证指数
    benchmark = idx.get("hs300") or idx.get("sh")
    if not benchmark:
        log("⚠️ 无法获取指数基准数据，相对强度不可用")
        benchmark = {"5d": 0, "20d": 0, "name": "未知"}

    log(f"✓ 基准指数: {benchmark['name']} 5日{benchmark['5d']:.2f}% 20日{benchmark['20d']:.2f}%")

    # 计算相对强度
    for s in sectors:
        if s["pct_5d"] is not None:
            s["relative_5d"] = round(s["pct_5d"] - benchmark["5d"], 2)
        else:
            s["relative_5d"] = None
        if s["pct_20d"] is not None:
            s["relative_20d"] = round(s["pct_20d"] - benchmark["20d"], 2)
        else:
            s["relative_20d"] = None

    # 排名
    strong_5d = sorted([s for s in sectors if s["pct_5d"] is not None], key=lambda x: x["pct_5d"], reverse=True)[:10]
    strong_20d = sorted([s for s in sectors if s["pct_20d"] is not None], key=lambda x: x["pct_20d"], reverse=True)[:10]
    strong_52w = sorted([s for s in sectors if s["pct_52w"] is not None], key=lambda x: x["pct_52w"], reverse=True)[:10]
    weak_5d = sorted([s for s in sectors if s["pct_5d"] is not None], key=lambda x: x["pct_5d"])[:10]

    # 相对强度排名（板块跑赢指数的幅度）
    strong_relative_5d = sorted([s for s in sectors if s["relative_5d"] is not None],
        key=lambda x: x["relative_5d"], reverse=True)[:10]
    strong_relative_20d = sorted([s for s in sectors if s["relative_20d"] is not None],
        key=lambda x: x["relative_20d"], reverse=True)[:10]

    # 抗跌排名（20日涨幅最低但相对强度最高的，即大盘跌时跌得少的）
    anti_drop_candidates = [s for s in sectors if s["pct_20d"] is not None and s["relative_20d"] is not None and s["pct_20d"] < 0]
    anti_drop = sorted(anti_drop_candidates, key=lambda x: x["relative_20d"], reverse=True)[:10]

    result = {
        "update_time": now_str,
        "sectors": sectors,
        "strong_5d": strong_5d,
        "strong_20d": strong_20d,
        "strong_52w": strong_52w,
        "weak_5d": weak_5d,
        "strong_relative_5d": strong_relative_5d,
        "strong_relative_20d": strong_relative_20d,
        "anti_drop": anti_drop,
        "index": {
            "name": benchmark["name"],
            "pct_5d": benchmark["5d"],
            "pct_20d": benchmark["20d"],
        },
    }
    
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"✅ 已保存: {OUT} ({len(sectors)}板块, 相对强度: {len(strong_relative_5d)}个领跑, {len(anti_drop)}个抗跌)")

if __name__ == "__main__":
    main()
