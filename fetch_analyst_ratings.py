#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
分析师预期转向
用法：python fetch_analyst_ratings.py
输出：data/analyst_ratings.json

策略：先用neodata汇总近期热点研报个股，再批量查详情
"""
import json, os, sys, datetime, time as _time
import requests as req

OUT = "data/analyst_ratings.json"
NEODATA_URL = "https://copilot.tencent.com/agenttool/v1/neodata"

# ── Token ──
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".neodata_token")
token = None
if not os.path.exists(TOKEN_FILE):
    for p in [os.path.expanduser("~/.workbuddy/.neodata_token"), os.path.expanduser("~/.workbuddy/skills/.neodata_token")]:
        if os.path.exists(p):
            try:
                with open(p) as f:
                    cache = json.load(f)
                    token = cache.get("token")
                    if _time.time() - cache.get("saved_at", 0) < 43200: break
            except: pass
else:
    try:
        with open(TOKEN_FILE) as f: cache = json.load(f); token = cache.get("token")
    except:
        with open(TOKEN_FILE) as f: token = f.read().strip()

def log(msg): print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")
def query_neodata(q):
    if not token: return []
    try:
        resp = req.post(NEODATA_URL, json={"query": q, "channel": "neodata", "sub_channel": "workbuddy"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=30)
        if resp.status_code != 200: return []
        data = resp.json()
        if not data.get("suc"): return []
        return data.get("data", {}).get("apiData", {}).get("apiRecall", [])
    except: return []

def parse_codes_from_text(text):
    """从文本提取6位股票代码"""
    import re
    return list(set(re.findall(r'\b\d{6}\b', text)))

def main():
    log("分析师评级抓取...")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    result = {"update_time": now_str, "upgrades": [], "downgrades": [], "new_coverage": [],
              "hot_stocks": [], "note": ""}

    if not token:
        result["note"] = "neodata token未找到，跳过"
        log("⚠️ 无token")
    else:
        # 方案1: neodata汇总
        data = query_neodata("近一周A股分析师评级发生变化的个股，列出股票名称/代码/原评级/新评级/调整机构/调整日期，按重要性列出TOP15，同时也列出近一月首次覆盖（新评级）的个股TOP10")
        hot_codes = set()
        for item in data:
            content = item.get("content", "")
            result["summary_text"] = content[:3000]  # 摘要文本
            hot_codes.update(parse_codes_from_text(content))

        if hot_codes:
            log(f"✓ neodata识别到 {len(hot_codes)} 只热点个股")
            # 方案2: akshare查详情（限速只查TOP15）
            codes = list(hot_codes)[:15]
            try:
                import akshare as ak
                for code in codes:
                    try:
                        df = ak.stock_research_report_em(symbol=code)
                        if df.empty: continue
                        row = df.iloc[0]
                        result["hot_stocks"].append({
                            "code": code,
                            "name": str(row.get("股票简称", "")),
                            "rating": str(row.get("东财评级", "")),
                            "institution": str(row.get("机构", "")),
                            "report_count_1m": int(row.get("近一月个股研报数", 0) or 0),
                        })
                    except: pass
                    _time.sleep(0.5)
            except Exception as e:
                log(f"⚠️ akshare查询失败: {e}")
    result["note"] += "数据源: neodata(研报汇总)+akshare(个股详情)"

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"✅ 已保存: {OUT} (热点{len(result['hot_stocks'])}只)")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
