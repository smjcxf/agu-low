#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金抱团预判数据获取 -- 每天收盘后自动更新
用法: python fetch_herding_data.py
输出: data/herding_data.json
"""
import os, sys, json, datetime, subprocess, re

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
            [sys.executable, QUERY_SCRIPT, "--query", query],
            capture_output=True, encoding='utf-8', errors='replace', timeout=30,
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
                if len(parts) >= 13:
                    try:
                        name = parts[5].strip() if len(parts) > 5 else ""
                        net_in = float(parts[12].strip()) if len(parts) > 12 else 0
                        if name and name != "板块名称":
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

def parse_catalyst_dates(date_str):
    """解析催化剂日期字符串，返回 (start_date, end_date) 元组。
    格式支持: '6.18', '6.12-14', '6.12起', '6月下旬', '6月中旬'
    日期均为当月，若月份缺失则用当前月。
    返回 None 表示无法解析。
    """
    today = datetime.date.today()
    current_month = today.month
    current_year = today.year

    # 清理空格
    date_str = date_str.strip()

    # 格式: "6.12-14" (日-日范围)
    m = re.match(r'(\d{1,2})\.(\d{1,2})-(\d{1,2})$', date_str)
    if m:
        month, start_day, end_day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (datetime.date(current_year, month, start_day),
                datetime.date(current_year, month, end_day))

    # 格式: "6.18" (单日)
    m = re.match(r'(\d{1,2})\.(\d{1,2})$', date_str)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        d = datetime.date(current_year, month, day)
        return (d, d)

    # 格式: "6.12起" (开始于某日，持续中)
    m = re.match(r'(\d{1,2})\.(\d{1,2})起', date_str)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        start = datetime.date(current_year, month, day)
        return (start, None)  # None 表示无截止日

    # 格式: "6月下旬" / "6月中旬" / "6月上旬"
    m = re.match(r'(\d{1,2})月(上|中|下)旬', date_str)
    if m:
        month, period = int(m.group(1)), m.group(2)
        if period == '上':
            return (datetime.date(current_year, month, 1),
                    datetime.date(current_year, month, 10))
        elif period == '中':
            return (datetime.date(current_year, month, 11),
                    datetime.date(current_year, month, 20))
        else:
            return (datetime.date(current_year, month, 21),
                    datetime.date(current_year, month, 30))

    return None


def filter_expired(items, is_catalyst=True):
    """过滤已过期的事件/催化剂。
    is_catalyst=True: items 有 date 字段
    is_catalyst=False: items 有 sector/reason 字段（谨慎方向），根据上下文判断
    """
    today = datetime.date.today()
    filtered = []

    if is_catalyst:
        for item in items:
            dates = parse_catalyst_dates(item.get('date', ''))
            if dates is None:
                # 无法解析日期的，保留（可能是"本月"等模糊描述）
                filtered.append(item)
                continue
            start, end = dates
            if end is None:
                # 无截止日（如"6.12起"），始终保留
                filtered.append(item)
            elif end >= today:
                # 已结束但还没结束（或者正在进行），保留
                filtered.append(item)
            # else: end < today → 已过期，跳过
    else:
        # 谨慎方向：根据关键词判断是否已过时
        stale_keywords = ['大会临近尾声', '已充分定价', '利好兑现', '会议结束', '已过']
        for item in items:
            reason = item.get('reason', '')
            if any(kw in reason for kw in stale_keywords):
                continue  # 跳过已过时的谨慎方向
            filtered.append(item)

    return filtered
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
        "broker_views": list(dict.fromkeys(broker_views[:3])) if broker_views else [],
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

    # ===== 过滤已过期事件 =====
    result["catalysts"] = filter_expired(result.get("catalysts", []), is_catalyst=True)
    result["cautious"] = filter_expired(result.get("cautious", []), is_catalyst=False)

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
