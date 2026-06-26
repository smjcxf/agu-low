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

def fetch_from_neodata():
    """使用 NeoData 接口获取板块资金流向（备选数据源）"""
    import requests as req
    import re
    import time as tm

    # 尝试从缓存文件读取 token
    token = None
    token_file = os.path.join(os.path.dirname(__file__), 
        "..", ".workbuddy", "..", "..", "..", "WorkBuddy", "resources",
        "app.asar.unpacked", "resources", "builtin-skills", ".neodata_token")
    
    # 标准化路径
    token_file = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "..", "..",
        "WorkBuddy", "resources", "app.asar.unpacked",
        "resources", "builtin-skills", ".neodata_token"
    ))
    # 也尝试常见路径
    alt_paths = [
        token_file,
        "E:/WorkBuddy/resources/app.asar.unpacked/resources/builtin-skills/.neodata_token",
        os.path.expanduser("~/.workbuddy/.neodata_token")
    ]
    
    for tp in alt_paths:
        if os.path.exists(tp):
            try:
                with open(tp, "r") as f:
                    cache = json.load(f)
                    token = cache.get("token")
                    saved = cache.get("saved_at", 0)
                    # 检查是否过期（12小时 = 43200秒）
                    if tm.time() - saved < 43200:
                        break
                    else:
                        token = None  # 过期
            except:
                continue
    
    if not token:
        print("  ℹ️ neodata token 不可用或已过期")
        return []
    
    # ═══════════════════════════════════════════════════════
    # 【2026-06-26 修复】neodata 需要同时查询流入+流出
    # 旧版只查"净流入TOP10"，导致流出板块数据缺失
    # 修复：分两次查询（流入+流出），合并结果
    # ═══════════════════════════════════════════════════════
    def _parse_neodata_response(api_recall):
        """解析 neodata 返回的板块资金流表格（含5日/20日累计）"""
        results = []
        seen_local = set()
        for item in api_recall:
            if item.get("type") != "板块当日资金主力统计":
                continue
            content = item.get("content", "")
            for line in content.strip().split("\n"):
                cols = [c.strip() for c in line.split("|")]
                if len(cols) < 15:
                    continue
                hdr_keywords = ["近N天数据", "板块名称", "板块代码", ":---:"]
                if any(k in cols[2] for k in hdr_keywords):
                    continue
                pt_type = cols[1]
                name = cols[5]
                try:
                    net_wan = float(cols[12])
                    net5_wan = float(cols[13]) if cols[13] else 0
                    net20_wan = float(cols[14]) if cols[14] else 0
                except (ValueError, TypeError):
                    continue
                net_yi = round(net_wan / 10000, 2)
                net5_yi = round(net5_wan / 10000, 2)
                net20_yi = round(net20_wan / 10000, 2)
                if name and net_yi != 0 and name not in seen_local:
                    seen_local.add(name)
                    results.append({
                        "name": name,
                        "net": net_yi,
                        "net_5d": net5_yi,
                        "net_20d": net20_yi,
                        "type": "行业" if "行业" in pt_type else "概念"
                    })
        return results

    def _call_neodata(query_desc, query_text):
        """调用 neodata API，返回板块列表"""
        try:
            resp = req.post(
                "https://copilot.tencent.com/agenttool/v1/neodata",
                json={
                    "query": query_text,
                    "channel": "neodata",
                    "sub_channel": "workbuddy"
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                timeout=30
            )
            if resp.status_code != 200:
                print(f"    ❌ {query_desc} HTTP {resp.status_code}")
                return []
            data = resp.json()
            if not data.get("suc"):
                print(f"    ❌ {query_desc} 返回失败: {data.get('msg','')[:80]}")
                return []
            api_recall = data.get("data", {}).get("apiData", {}).get("apiRecall", [])
            result = _parse_neodata_response(api_recall)
            print(f"    ✓ {query_desc}: {len(result)}只板块")
            return result
        except Exception as e:
            print(f"    ❌ {query_desc}: {e}")
            return []

    # 两次查询：流入+流出
    print("  🔍 调用 neodata 接口获取板块资金流（流入+流出）...")
    inflow_list = _call_neodata(
        "流入TOP10",
        "今日A股行业板块和概念板块主力资金净流入TOP10，按净流入降序"
    )
    outflow_list = _call_neodata(
        "流出TOP10",
        "今日A股行业板块和概念板块主力资金净流出TOP10，按净流出降序"
    )
    
    # 合并结果（以名称去重，优先保留首次出现的值）
    seen = set()
    top_list = []
    for item in inflow_list + outflow_list:
        if item["name"] not in seen:
            seen.add(item["name"])
            top_list.append(item)
    
    if top_list:
        top_list.sort(key=lambda x: x["net"], reverse=True)
        in_cnt = sum(1 for x in top_list if x["net"] > 0)
        out_cnt = sum(1 for x in top_list if x["net"] < 0)
        print(f"  ✅ neodata 汇总: {len(top_list)}只板块（流入{in_cnt} 流出{out_cnt}）")
        return top_list
    else:
        print("  ⚠️ neodata 未返回有效板块数据")
        return []


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
    
    # 如果真实数据获取失败，尝试 neodata 备选
    if not top_list:
        print("⚠️ akshare数据获取失败，尝试 neodata 备选...")
        top_list = fetch_from_neodata()
        if top_list:
            in_cnt = sum(1 for x in top_list if x["net"] > 0)
            out_cnt = sum(1 for x in top_list if x["net"] < 0)
            print(f"✅ neodata 获取到 {len(top_list)} 个板块（流入{in_cnt} 流出{out_cnt}）")
            result["data_type"] = "neodata"
            # 【2026-06-26 认证】数据完整性检查：须同时有流入和流出
            if out_cnt == 0 and len(top_list) > 3:
                print(f"  ⚠️ neodata 仅返回流入板块（缺少流出数据），净流入数字可能虚高！")
                result["data_note"] = "neodata仅返回流入"
            elif in_cnt == 0:
                print(f"  ⚠️ neodata 仅返回流出板块（缺少流入数据），净流出数字可能虚高！")
                result["data_note"] = "neodata仅返回流出"
            else:
                result["data_note"] = "neodata流入+流出完整"
        else:
            print("⚠️ neodata 也失败，使用模拟数据（标注为模拟）")
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
    
    # 【2026-06-26新增】5日和20日趋势（用于资金流向追踪面板）
    # 从top_list中提取有5日/20日数据的板块，分别按净流入降序
    trend_5d = sorted(
        [x for x in top_list if x.get("net_5d") != 0],
        key=lambda x: x.get("net_5d", 0), reverse=True
    )
    trend_20d = sorted(
        [x for x in top_list if x.get("net_20d") != 0],
        key=lambda x: x.get("net_20d", 0), reverse=True
    )
    result["trend_5d"] = trend_5d[:12]
    result["trend_20d"] = trend_20d[:12]
    
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
