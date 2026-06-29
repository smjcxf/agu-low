#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
政策信号密度 — akshare 新闻聚合模式
用法：python fetch_policy_density.py
输出：data/policy_density.json

策略：
  1. akshare.news_cctv() — 央视新闻（权威政策源）
  2. 东财/新浪财经新闻 — 备用补充
  3. 关键词库匹配 + 密度计算
"""
import json, os, sys, datetime, time as _time, re
import akshare as ak

OUT = "data/policy_density.json"

# 政策关键词库（含权重）
POLICY_KEYWORDS = {
    # 货币政策（权重3=重大）
    "降准": 3, "降息": 3, "LPR": 2, "MLF": 2, "逆回购": 1,
    "再贷款": 2, "定向降准": 3, "结构性货币": 2, "货币政策": 2,
    "利率": 1, "存款准备金": 3,
    # 财政政策（权重3）
    "财政赤字": 3, "特别国债": 3, "专项债": 2, "减税降费": 2,
    "转移支付": 1, "消费补贴": 2, "财政政策": 2,
    # 产业政策（权重2）
    "产业补贴": 2, "新质生产力": 2, "国产替代": 2, "半导体": 1,
    "新能源": 1, "人工智能": 1, "数据要素": 1,
    # 资本市场（权重2）
    "注册制": 2, "退市": 2, "再融资": 1, "并购重组": 1,
    "印花税": 2, "资本市场改革": 2,
    # 房地产（权重1-2）
    "房贷利率": 2, "限购": 2, "保障房": 1, "房地产": 1,
    # 国际（权重1）
    "关税": 1, "中美": 1, "制裁": 1, "贸易战": 2,
    # 经济数据发布（权重1）
    "GDP": 1, "CPI": 1, "PMI": 1, "社融": 1, "出口": 1, "就业": 1,
    "统计局": 1, "央行": 2, "国务院": 2, "政治局": 3,
}

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

def calc_density(texts):
    """计算政策信号密度（输入文本列表）"""
    score = 0
    hits = {}
    all_text = " ".join(texts)
    for kw, weight in POLICY_KEYWORDS.items():
        count = len(re.findall(kw, all_text))
        if count > 0:
            hits[kw] = count * weight
            score += count * weight
    density = min(100, score / 15 * 100)
    return {
        "density": round(density, 1),
        "hits": hits,
        "total_score": score,
        "level": "高" if density >= 60 else "中" if density >= 30 else "低"
    }

def fetch_cctv_news(date_str):
    """获取央视新闻"""
    texts = []
    try:
        df = ak.news_cctv(date=date_str)
        if not df.empty:
            for _, row in df.iterrows():
                title = str(row.get("title", ""))
                content = str(row.get("content", ""))
                texts.append(title + " " + content[:500])
    except Exception as e:
        log(f"  CCTV 新闻获取失败: {e}")
    return texts

def fetch_eastmoney_news():
    """获取东方财富要闻（备用）"""
    texts = []
    try:
        df = ak.stock_info_global_em()
        if not df.empty:
            for _, row in df.head(30).iterrows():
                texts.append(str(row.get("title", "")) + " " + str(row.get("summary", ""))[:200])
    except Exception as e:
        log(f"  东财新闻获取失败: {e}")
    return texts

def main():
    log("政策信号密度抓取 (akshare)...")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    today = datetime.date.today().strftime("%Y%m%d")

    result = {
        "update_time": now_str,
        "density": 0,
        "level": "低",
        "signals": [],
        "summary": "",
        "note": "",
    }

    all_texts = []

    # 1. 央视新闻
    log("  从央视新闻获取...")
    cctv_texts = fetch_cctv_news(today)
    all_texts.extend(cctv_texts)
    log(f"  CCTV: {len(cctv_texts)} 条")

    # 2. 东财新闻补充
    log("  从东方财富补充...")
    em_texts = fetch_eastmoney_news()
    all_texts.extend(em_texts)
    log(f"  东财: {len(em_texts)} 条")

    # 计算密度
    if all_texts:
        density_info = calc_density(all_texts)
        result.update(density_info)

        # 提取政策信号（筛选含关键词的文本片段）
        signals = []
        for text in all_texts:
            for kw in POLICY_KEYWORDS:
                if kw in text:
                    # 提取关键词所在句子
                    for sent in re.split(r'[。！？\n]', text):
                        if kw in sent and len(sent.strip()) > 10:
                            signals.append(sent.strip()[:200])
                            break
                    break
        result["signals"] = [{"event": s} for s in signals[:20]]
        result["summary"] = "。".join(signals[:10])[:2000]

        log(f"  密度: {result['density']} ({result['level']}), 信号: {len(signals)} 条")
    else:
        result["note"] = "今日无新闻数据"
        log("  ⚠️ 无新闻数据")

    result["note"] = f"数据源: CCTV({len(cctv_texts)}条)+东财({len(em_texts)}条)"

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
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
