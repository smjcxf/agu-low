#!/usr/bin/env python3
"""
板块资金流向汇总 — 抓取行业/概念板块主力净流入，生成汇总报告
输出: data/sector_fund_flow.json

功能：
- 追踪历史数据，计算连续流入/流出天数
- 数据保存在 data/sector_fund_flow_history.json
- 多重API降级：优先akshare，失败则用模拟数据（标注）
"""
import json
import os
import time
from datetime import datetime, timedelta
import requests

try:
    import akshare as ak
except ImportError:
    print("❌ akshare 未安装，将使用模拟数据")
    ak = None

HISTORY_FILE = "data/sector_fund_flow_history.json"
OUTPUT_FILE = "data/sector_fund_flow.json"

def load_history():
    """加载历史数据"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_history(history):
    """保存历史数据（只保留最近60天）"""
    os.makedirs("data", exist_ok=True)
    # 清理旧数据
    for name in history:
        history[name] = history[name][-60:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def calc_consecutive_days(records):
    """
    计算连续流入/流出天数
    records: [{"date": "2026-06-05", "net": 28.5}, ...] 按日期升序
    返回: (days, trend)  days=天数, trend="in"/"out"/"neutral"
    """
    if not records:
        return 0, "neutral"
    
    days = 0
    trend = None
    
    for record in reversed(records):  # 从最近开始
        net = record["net"]
        if trend is None:
            if net > 0:
                trend = "in"
            elif net < 0:
                trend = "out"
            else:
                return 0, "neutral"
            days = 1
        else:
            if trend == "in" and net > 0:
                days += 1
            elif trend == "out" and net < 0:
                days += 1
            else:
                break
    
    return days, trend

def fetch_with_retry(func, max_retries=3, delay=2):
    """带重试的抓取函数"""
    for i in range(max_retries):
        try:
            return func()
        except Exception as e:
            if i < max_retries - 1:
                print(f"  ⚠️ 重试 {i+1}/{max_retries}: {e}")
                time.sleep(delay)
            else:
                raise e

def get_mock_data():
    """生成模拟数据（用于API失败时的降级）"""
    import random
    sectors = [
        ("半导体", "行业"), ("通信设备", "行业"), ("机器人", "概念"),
        ("电力", "行业"), ("医疗器械", "行业"), ("汽车零部件", "行业"),
        ("光伏", "行业"), ("白酒", "行业"), ("银行", "行业"),
        ("地产", "行业"), ("汽车零部件", "行业"), ("锂电池", "概念"),
        ("AI算力", "概念"), ("军工", "行业"), ("农业", "行业"),
    ]
    
    top_list = []
    for name, stype in sectors:
        # 随机生成资金流（-30亿到+30亿）
        net = round(random.uniform(-30, 30), 1)
        top_list.append({
            "name": name,
            "net": net,
            "type": stype
        })
    
    top_list.sort(key=lambda x: x["net"], reverse=True)
    return top_list

def fetch_sector_flow():
    """抓取板块资金流向"""
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    result = {
        "update_time": now_str,
        "data_type": "real",  # "real" 或 "mock"
        "summary": {},
        "sectors_in": [],
        "sectors_out": [],
        "top_list": [],
        "consecutive": {}
    }
    
    top_list = []
    use_mock = False
    
    # 尝试从akshare获取真实数据
    if ak is not None:
        print("📊 正在抓取板块资金流向...")
        
        # 方法1: 行业板块
        try:
            print("  📊 方法1: 行业板块资金流...")
            df = fetch_with_retry(
                lambda: ak.stock_board_industry_flow_em(symbol="今日"),
                max_retries=2
            )
            if df is not None and len(df) > 0:
                for _, row in df.iterrows():
                    name = str(row.get("名称", "")).strip()
                    try:
                        net = float(row.get("主力净流入", 0)) / 100000000  # 转为亿元
                    except:
                        net = 0
                    if name and net != 0:
                        top_list.append({
                            "name": name,
                            "net": round(net, 2),
                            "type": "行业"
                        })
                print(f"    ✅ 获取到 {len(top_list)} 个行业板块")
        except Exception as e:
            print(f"    ⚠️ 方法1失败: {e}")
        
        # 方法2: 概念板块
        try:
            print("  📊 方法2: 概念板块资金流...")
            df2 = fetch_with_retry(
                lambda: ak.stock_board_concept_flow_em(symbol="今日"),
                max_retries=2
            )
            if df2 is not None and len(df2) > 0:
                for _, row in df2.iterrows():
                    name = str(row.get("名称", "")).strip()
                    try:
                        net = float(row.get("主力净流入", 0)) / 100000000
                    except:
                        net = 0
                    if name and net != 0:
                        # 去重
                        if not any(x["name"] == name for x in top_list):
                            top_list.append({
                                "name": name,
                                "net": round(net, 2),
                                "type": "概念"
                            })
                print(f"    ✅ 获取到 {len(top_list)} 个板块（含概念）")
        except Exception as e:
            print(f"    ⚠️ 方法2失败: {e}")
    
    # 如果真实数据获取失败，使用模拟数据
    if not top_list:
        print("⚠️ 真实数据获取失败，使用模拟数据（标注为模拟）")
        top_list = get_mock_data()
        use_mock = True
        result["data_type"] = "mock"
    
    # 去重并排序
    seen = {}
    for item in top_list:
        name = item["name"]
        if name not in seen or abs(item["net"]) > abs(seen[name]["net"]):
            seen[name] = item
    top_list = list(seen.values())
    top_list.sort(key=lambda x: x["net"], reverse=True)
    result["top_list"] = top_list[:15]
    
    # 加载历史数据
    history = load_history()
    
    # 更新今日数据到历史
    for item in result["top_list"]:
        name = item["name"]
        net = item["net"]
        
        if name not in history:
            history[name] = []
        
        # 检查今天是否已有记录
        if history[name] and history[name][-1].get("date") == today:
            history[name][-1] = {"date": today, "net": net}
        else:
            history[name].append({"date": today, "net": net})
        
        # 只保留最近60天
        history[name] = history[name][-60:]
    
    # 计算连续天数
    for item in result["top_list"]:
        name = item["name"]
        days, trend = calc_consecutive_days(history.get(name, []))
        item["consecutive_days"] = days
        item["trend"] = trend
        result["consecutive"][name] = {"days": days, "trend": trend}
    
    # 保存历史
    save_history(history)
    
    # 生成汇总
    THRESHOLD = 5.0
    for item in result["top_list"]:
        if item["net"] >= THRESHOLD:
            result["sectors_in"].append(item)
        elif item["net"] <= -THRESHOLD:
            result["sectors_out"].append(item)
    
    in_names = [f"{s['name']}({s['net']:.1f}亿)" for s in result["sectors_in"]]
    out_names = [f"{s['name']}({s['net']:.1f}亿)" for s in result["sectors_out"]]
    
    result["summary"] = {
        "in_count": len(result["sectors_in"]),
        "out_count": len(result["sectors_out"]),
        "in_text": "、".join(in_names[:5]) if in_names else "无",
        "out_text": "、".join(out_names[:5]) if out_names else "无",
        "alert": ""
    }
    
    # 生成预警（简洁格式）
    alerts = []
    if len(result["sectors_in"]) >= 3:
        alerts.append(f"🔥 {len(result['sectors_in'])}个板块大幅流入")
    if len(result["sectors_out"]) >= 3:
        alerts.append(f"⚠️ {len(result['sectors_out'])}个板块大幅流出")
    
    # 流入明细（紧凑格式）
    in_details = []
    for s in result["sectors_in"][:3]:
        if s["net"] >= 10:
            detail = f"{s['name']}+{s['net']:.1f}亿"
            if s.get("consecutive_days", 0) > 1:
                detail += f"(连{s['consecutive_days']}天)"
            in_details.append(detail)
    if in_details:
        alerts.append("🚀 " + "、".join(in_details))
    
    # 流出明细（紧凑格式）
    out_details = []
    for s in result["sectors_out"][:3]:
        if s["net"] <= -10:
            detail = f"{s['name']}{s['net']:.1f}亿"
            if s.get("consecutive_days", 0) > 1:
                detail += f"(连{s['consecutive_days']}天)"
            out_details.append(detail)
    if out_details:
        alerts.append("💨 " + "、".join(out_details))
    
    result["summary"]["alert"] = "；".join(alerts) if alerts else "板块资金流向平稳"
    
    # 写文件
    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 板块资金流向已保存: {OUTPUT_FILE}")
    print(f"   数据类型: {'真实数据' if not use_mock else '⚠️ 模拟数据'}")
    print(f"   大幅流入: {len(result['sectors_in'])} 个")
    print(f"   大幅流出: {len(result['sectors_out'])} 个")
    if result.get("summary", {}).get("alert"):
        print(f"   预警: {result['summary']['alert']}")
    
    return result

if __name__ == "__main__":
    fetch_sector_flow()
