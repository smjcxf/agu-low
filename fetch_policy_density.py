#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
政策信号密度
用法：python fetch_policy_density.py
输出：data/policy_density.json

方案：用neodata NLP能力汇总近期政策信号，计算信号密度指数。
关键词集：降准/降息/LPR/MLF/逆回购/财政/税收/产业补贴/注册制/退市/再融资...
"""
import json, os, sys, datetime, time as _time, re
import requests as req

OUT = "data/policy_density.json"
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

# 政策关键词库（含权重）
POLICY_KEYWORDS = {
    # 货币政策（权重3=重大）
    "降准": 3, "降息": 3, "LPR下调": 3, "MLF操作": 2, "逆回购": 1,
    "再贷款": 2, "定向降准": 3, "结构性货币政策": 2,
    # 财政政策（权重3）
    "财政赤字": 3, "特别国债": 3, "专项债": 2, "减税降费": 2,
    "转移支付": 1, "消费补贴": 2,
    # 产业政策（权重2）
    "产业补贴": 2, "新质生产力": 2, "国产替代": 2, "芯片": 2,
    "新能源": 1, "人工智能": 1, "数据要素": 1,
    # 资本市场（权重2）
    "注册制": 2, "退市": 2, "再融资": 1, "并购重组": 1,
    "印花税": 2, "T+0": 2,
    # 房地产（权重2）
    "房地产": 1, "房贷利率": 2, "限购放松": 2, "保障房": 1,
    # 国际（权重1）
    "关税": 1, "中美": 1, "制裁": 1,
}

def calc_density(content_text):
    """计算政策信号密度"""
    score = 0
    hits = {}
    for kw, weight in POLICY_KEYWORDS.items():
        count = len(re.findall(kw, content_text))
        if count > 0:
            hits[kw] = count * weight
            score += count * weight
    # 归一化到0-100
    density = min(100, score / 15 * 100)
    return {
        "density": round(density, 1),
        "hits": hits,
        "total_score": score,
        "level": "高" if density >= 60 else "中" if density >= 30 else "低"
    }

def main():
    log("政策信号密度抓取...")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    result = {"update_time": now_str, "density": 0, "level": "低", "signals": [],
              "summary": "", "note": ""}

    if not token:
        result["note"] = "neodata token未找到，跳过"
        log("⚠️ 无token")
    else:
        # 查询政策信号
        data = query_neodata("汇总今日(2026年6月26日)中国A股市场相关的最新政策信号，包括货币政策、财政政策、产业政策、资本市场改革等，列出所有具体政策事件和时间")
        text_all = ""
        signals = []
        for item in data:
            content = item.get("content", "")
            text_all += content

        # 提取政策事件（按段落分割）
        if text_all:
            # 计算密度
            density_info = calc_density(text_all)
            result.update(density_info)
            result["signals"] = [{"event": s.strip()} for s in text_all.split("\n") if len(s.strip()) > 10][:20]
            result["summary"] = text_all[:2000]

        # 补充：如果neodata无结果，用akshare财联社电报做回退
        if not result["signals"]:
            try:
                import akshare as ak
                df = ak.stock_info_global_cls()
                if not df.empty:
                    recent = df.head(50)
                    text_all = " ".join(recent["content"].fillna(""))
                    density_info = calc_density(text_all)
                    result.update(density_info)
                    result["signals"] = [{"event": str(c)} for c in recent["content"].head(20)]
                    result["note"] += "数据源: akshare财联社电报"
            except Exception as e:
                result["note"] = f"akshare回退失败: {e}"

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"✅ 已保存: {OUT} (密度{result.get('density',0)}, 级别{result.get('level','低')})")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
