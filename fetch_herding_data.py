#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金抱团预判数据获取 -- 每天收盘后自动更新
用法: python fetch_herding_data.py
输出: data/herding_data.json
"""
import os, sys, json, datetime, subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "herding_data.json")

# NeoData 脚本位置
NEODATA_DIR = os.path.join(
    os.path.expanduser("~"),
    ".workbuddy/plugins/marketplaces/cb_teams_marketplace/plugins/finance-data/skills/neodata-financial-search/scripts"
)
QUERY_SCRIPT = os.path.join(NEODATA_DIR, "query.py")

def query_neodata(query):
    """调用 NeoData 接口查询"""
    try:
        result = subprocess.run(
            ["python", QUERY_SCRIPT, "--query", query],
            capture_output=True, text=True, timeout=30,
            cwd=BASE_DIR
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        return None
    except Exception as e:
        print(f"  WARN NeoData query failed: {e}")
        return None

def extract_sector_flows(data):
    """从 NeoData 返回中提取板块资金流向"""
    flows = []
    if not data:
        return flows
    api_data = data.get("data", {}).get("apiData", {})
    for recall in api_data.get("apiRecall", []):
        content = recall.get("content", "")
        if not content:
            continue
        lines = content.strip().split("\n")
        header_found = False
        for line in lines:
            if "板块名称" in line and "主力净流入" in line:
                header_found = True
                continue
            if header_found and "|" in line and "pt" in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 12:
                    try:
                        name = parts[4].strip() if len(parts) > 4 else ""
                        net_in = float(parts[10].strip()) if len(parts) > 10 else 0
                        flows.append({"name": name, "net_in": net_in})
                    except (ValueError, IndexError):
                        continue
    return flows

def extract_doc_insights(data, keyword=""):
    """提取机构观点摘要"""
    insights = []
    if not data:
        return insights
    doc_data = data.get("data", {}).get("docData", {})
    for recall in doc_data.get("docRecall", []):
        for doc in recall.get("docList", []):
            title = doc.get("title", "")
            content = doc.get("content", "")
            if keyword and keyword not in title + content:
                continue
            text = title[:80] if title else content[:100]
            if text:
                insights.append(text)
    return insights[:5]


def load_old_data():
    """加载旧数据，用于盘后空数据回退"""
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            if old.get("current_clusters") or old.get("broker_views"):
                return old
        except:
            pass
    return None


def is_result_empty(result):
    """判断结果是否所有数据字段都为空"""
    return (not result.get("current_clusters")
            and not result.get("high_prob")
            and not result.get("cautious")
            and not result.get("catalysts")
            and not result.get("broker_views"))


def analyze_and_generate():
    """主分析逻辑"""
    print("=" * 50)
    print("  资金抱团预判数据获取")
    print("=" * 50)

    # 先加载旧数据备用
    old_data = load_old_data()

    # 查询1：近5日行业板块主力资金流向
    print("\n[1/4] 查询行业板块资金流向...")
    data1 = query_neodata("近5日A股行业板块主力资金净流入排名，哪些板块获资金持续加仓")
    sector_flows = extract_sector_flows(data1)

    # 查询2：近5日概念板块资金流向
    print("[2/4] 查询概念板块资金流向...")
    data2 = query_neodata("近5日A股概念板块涨跌幅和主力资金流向排名")

    # 查询3：机构推荐方向
    print("[3/4] 查询机构推荐方向...")
    data3 = query_neodata("最近一周券商集中推荐看好的板块和方向，机构最新投资观点")
    broker_views = extract_doc_insights(data3, "券商")

    # 查询4：重要催化剂事件
    print("[4/4] 查询下周重要事件...")
    data4 = query_neodata("下周A股重要事件和催化剂，美联储利率决议，科技发布会")

    # ===== 分析生成 =====
    result = {
        "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "current_clusters": [],
        "high_prob": [],
        "cautious": [],
        "catalysts": [],
        "broker_views": broker_views[:3] if broker_views else [],
    }

    # 分析当前抱团
    if sector_flows:
        sorted_flows = sorted(sector_flows, key=lambda x: abs(x["net_in"]), reverse=True)
        medals = ["🥇", "🥈", "🥉", ""]
        for i, f in enumerate(sorted_flows[:4]):
            direction = "流入" if f["net_in"] > 0 else "流出"
            result["current_clusters"].append({
                "rank": i + 1,
                "medal": medals[i],
                "sector": f["name"],
                "amount": abs(f["net_in"]) / 10000,
                "unit": "亿",
                "direction": direction,
            })

    # ===== 盘后空数据保护 =====
    if is_result_empty(result) and old_data:
        print("\n  WARN 盘后数据为空，保留最近一次有效数据")
        result = old_data
    elif old_data and not is_result_empty(result):
        # 合并：新数据覆盖同名字段，旧数据保留未更新字段
        for key in ["high_prob", "cautious", "catalysts"]:
            if not result[key] and old_data.get(key):
                result[key] = old_data[key]

    # 保存
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  已保存: {OUTPUT_FILE}")
    print(f"   当前抱团: {len(result['current_clusters'])} 个方向")
    print(f"   接力方向: {len(result['high_prob'])} 个")
    print(f"   更新时间: {result['update_time']}")

    return result


if __name__ == "__main__":
    analyze_and_generate()
