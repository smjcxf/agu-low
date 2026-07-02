#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
52周新高板块归属
用法：python fetch_52w_high.py
输出：data/52w_high.json
   - stocks: 创52周新高的个股列表
   - sectors: 按概念/行业分组的52周新高计数
   - summary: 汇总统计（总数、领涨板块等）
"""
import json, os, sys, datetime, requests as req

OUT = "data/52w_high.json"
NEODATA_URL = "https://copilot.tencent.com/agenttool/v1/neodata"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".neodata_token")

# ── Token ──
token = None
if not os.path.exists(TOKEN_FILE):
    alt_paths = [
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
                    if __import__('time').time() - saved < 43200: break
                    else: token = None
            except: continue
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
    if not token: return []
    try:
        resp = req.post(NEODATA_URL, json={
            "query": query_text, "channel": "neodata", "sub_channel": "workbuddy"
        }, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=30)
        if resp.status_code != 200: return []
        data = resp.json()
        if not data.get("suc"): return []
        return data.get("data", {}).get("apiData", {}).get("apiRecall", [])
    except: return []

def parse_sector_from_neodata(api_recall):
    """从neodata返回的表格提取个股→概念/行业映射"""
    mapping = {}  # {code: {name, sectors: []}}
    for item in api_recall:
        content = item.get("content", "")
        # 解析每行：代码 名称 概念名
        for line in content.strip().split("\n"):
            cols = [c.strip() for c in line.split("|")]
            if len(cols) < 3: continue
            if ":---:" in cols[1]: continue
            code = cols[1] if len(cols) > 1 else ""
            name = cols[2] if len(cols) > 2 else ""
            sector = cols[3] if len(cols) > 3 else ""
            if not code or not name: continue
            code = code.zfill(6)
            if code not in mapping:
                mapping[code] = {"name": name, "sectors": []}
            if sector and sector not in mapping[code]["sectors"]:
                mapping[code]["sectors"].append(sector)
    return mapping

def main():
    log("52周新高抓取...")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. 获取创52周新高个股
    try:
        import akshare as ak
        df = ak.stock_rank_cxg_ths()
        stocks = []
        for _, row in df.iterrows():
            name = row["股票简称"]
            code = str(row["股票代码"]).zfill(6)
            # ── 过滤垃圾股：退市股 + ST股 ──
            if "退" in name: continue
            if name.startswith("*ST") or name.startswith("ST"): continue
            stocks.append({
                "code": code,
                "name": name,
                "pct_chg": float(row.get("涨跌幅", 0) or 0),
                "price": float(row.get("最新价", 0) or 0),
                "prev_high": float(row.get("前期高点", 0) or 0),
                "prev_high_date": str(row.get("前期高点日期", "")),
                "turnover": float(row.get("换手率", 0) or 0)
            })
        log(f"✓ akshare获取到 {len(stocks)} 只创52周新高个股（已过滤退市/ST）")
    except Exception as e:
        log(f"⚠️ akshare失败: {e}，尝试neodata")
        stocks = []

    # 2. 如果有neodata token，查询概念归属
    sector_count = {}
    if token and stocks:
        for batch_idx in range(0, len(stocks), 50):
            batch = stocks[batch_idx:batch_idx+50]
            codes = [s["code"] for s in batch]
            # 查询最新概念排行中是否有这些个股
            query = f"查询以下A股代码最近所属的概念板块，每个代码一行：{','.join(codes[:20])}"
            try:
                mapping = parse_sector_from_neodata(query_neodata(query))
                for s in batch:
                    code = s["code"]
                    if code in mapping:
                        for sec in mapping[code]["sectors"]:
                            sector_count[sec] = sector_count.get(sec, 0) + 1
            except:
                pass

    # 3. 汇总统计
    sorted_sectors = sorted(sector_count.items(), key=lambda x: x[1], reverse=True)
    top_sectors = [{"name": k, "count": v} for k, v in sorted_sectors[:15]]
    # 涨跌幅靠前的个股
    top_gainers = sorted([s for s in stocks if s["pct_chg"] > 0], key=lambda x: x["pct_chg"], reverse=True)[:15]

    result = {
        "update_time": now_str,
        "total": len(stocks),
        "top_gainers": [{"code": s["code"], "name": s["name"], "pct_chg": s["pct_chg"]} for s in top_gainers],
        "top_sectors": top_sectors,
        "stocks": stocks[:200],  # 最多保留200只详情
        "note": "数据源: akshare stock_rank_cxg_ths(), 板块分析需neodata支持"
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"✅ 已保存: {OUT} (共{len(stocks)}只, {len(top_sectors)}个领涨板块)")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
