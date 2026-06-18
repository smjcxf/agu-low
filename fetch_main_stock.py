#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主力资金监控数据获取 — 使用 westock-data CLI
输出: data/main_stock.json

数据来源: westock-data asfund (A股资金流向)
"""
import os, sys, json, datetime, subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "main_stock.json")

# westock-data CLI 路径
WESTOCK_DIR = os.path.join(
    os.path.expanduser("~"),
    ".workbuddy/plugins/marketplaces/cb_teams_marketplace/plugins/finance-data/skills/westock-data"
)
WESTOCK_SCRIPT = os.path.join(WESTOCK_DIR, "scripts", "index.js")
NODE_PATH = os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries", "node", "versions", "22.22.2", "node.exe")

# 核心监控池: 大盘蓝筹 + 活跃个股
WATCHLIST = {
    # 金融
    "601398": "工商银行", "601939": "建设银行", "601288": "农业银行",
    "600036": "招商银行", "601318": "中国平安", "600030": "中信证券",
    # 白酒消费
    "600519": "贵州茅台", "000858": "五粮液", "000568": "泸州老窖",
    # 新能源
    "300750": "宁德时代", "002594": "比亚迪", "601012": "隆基绿能",
    # 科技
    "000725": "京东方A", "002475": "立讯精密", "603019": "中科曙光",
    "688981": "中芯国际", "000063": "中兴通讯",
    # 医药
    "600276": "恒瑞医药", "603259": "药明康德",
    # 资源
    "601899": "紫金矿业", "601857": "中国石油", "600028": "中国石化",
    # AI/芯片
    "688256": "寒武纪", "300308": "中际旭创", "603501": "韦尔股份",
    "688041": "海光信息",
    # 其他活跃
    "300274": "阳光电源", "600900": "长江电力", "601166": "兴业银行",
    "600809": "山西汾酒", "300502": "新易盛", "600585": "海螺水泥",
    "688111": "金山办公",
}

def run_westock(cmd_args):
    """运行 westock-data CLI"""
    try:
        result = subprocess.run(
            [NODE_PATH, WESTOCK_SCRIPT] + cmd_args,
            capture_output=True, encoding='utf-8', errors='replace', timeout=60,
            cwd=BASE_DIR
        )
        if result.returncode == 0:
            return result.stdout
        print(f"  CLI ERR: {result.stderr[:200]}")
        return None
    except Exception as e:
        print(f"  CLI FAIL: {e}")
        return None

def parse_asfund_batch(output):
    """解析 westock-data asfund 批量查询输出 (Markdown 表格)"""
    results = {}  # code -> list of {date, MainNetFlow}
    if not output:
        return results
    
    # 解析 Markdown 表格行
    in_table = False
    for line in output.strip().split("\n"):
        line = line.strip()
        if "| symbol |" in line or "| --- |" in line:
            in_table = True
            continue
        if in_table and line.startswith("|") and line.endswith("|"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 8:
                continue
            try:
                code = parts[1].strip()
                # 去掉 sh/sz/bj 前缀
                if code.startswith(("sh", "sz", "bj")) and len(code) == 8:
                    code = code[2:]
                date = parts[3].strip()
                main_net_flow = float(parts[9].strip()) if parts[9].strip() else 0
                if code not in results:
                    results[code] = []
                results[code].append({"date": date, "MainNetFlow": main_net_flow})
            except (ValueError, IndexError):
                continue
    return results

def load_old_data():
    """加载旧数据，用于增量更新"""
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return None

def compute_consecutive(flows, direction="in"):
    """计算连续净流入/流出天数（从最新日期往前数）"""
    if not flows:
        return 0
    # 按日期降序排列
    sorted_flows = sorted(flows, key=lambda x: x["date"], reverse=True)
    count = 0
    for f in sorted_flows:
        if direction == "in" and f["MainNetFlow"] > 0:
            count += 1
        elif direction == "out" and f["MainNetFlow"] < 0:
            count += 1
        else:
            break
    return count

def main():
    print("=" * 50)
    print("  主力资金监控数据获取 (westock-data)")
    print("=" * 50)

    # 分批查询（每批10只，避免超时）
    codes = list(WATCHLIST.keys())
    batch_size = 10
    all_flows = {}

    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        batch_codes = ",".join(f"sh{c}" if c.startswith("6") or c.startswith("68") else f"sz{c}" for c in batch)
        
        print(f"\n  [{i//batch_size + 1}/{(len(codes) + batch_size - 1)//batch_size}] 查询 {len(batch)} 只...")
        
        # 查询近10个交易日
        output = run_westock(["asfund", batch_codes, "--start", 
                             (datetime.datetime.now() - datetime.timedelta(days=20)).strftime("%Y-%m-%d"),
                             "--end", datetime.datetime.now().strftime("%Y-%m-%d")])
        
        if output:
            batch_results = parse_asfund_batch(output)
            all_flows.update(batch_results)
            print(f"    获取到 {len(batch_results)} 只股票数据")

    print(f"\n  共获取 {len(all_flows)} 只股票资金数据")

    # 计算今日净流入排名
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    stock_scores = []
    for code, name in WATCHLIST.items():
        if code not in all_flows:
            continue
        flows = all_flows[code]
        # 今日净流入
        today_flows = [f for f in flows if f["date"] == today]
        today_net = today_flows[0]["MainNetFlow"] if today_flows else 0
        # 近5日累计
        recent_flows = sorted(flows, key=lambda x: x["date"], reverse=True)[:5]
        total_5d = sum(f["MainNetFlow"] for f in recent_flows)
        # 连续天数
        consec = compute_consecutive(flows, "in" if today_net > 0 else "out")
        
        stock_scores.append({
            "code": code,
            "name": name,
            "today_net": today_net,
            "total_5d": total_5d,
            "consec": consec,
        })

    # 排序：今日净流入降序
    stock_scores.sort(key=lambda x: x["today_net"], reverse=True)

    # 构建 top_main_in (含今日净流入为正 + 连续天数 >= 1)
    top_in = []
    for s in stock_scores:
        if s["today_net"] > 0 and s["consec"] >= 1:
            net_in = round(abs(s["today_net"]) / 1e8, 1)
            if net_in >= 0.5:  # 过滤净流入小于 0.5 亿
                top_in.append({
                    "code": s["code"],
                    "name": s["name"],
                    "net_in": net_in,
                    "unit": "亿",
                    "day_count": s["consec"],
                })
    top_in = top_in[:8]  # 最多8只

    # 构建 top_main_out (今日净流出 + 连续天数 >= 1)
    bottom = sorted(stock_scores, key=lambda x: x["today_net"])  # 升序 = 最大流出在前
    top_out = []
    for s in bottom:
        if s["today_net"] < 0 and s["consec"] >= 1:
            net_out = round(abs(s["today_net"]) / 1e8, 1)
            if net_out >= 0.5:
                top_out.append({
                    "code": s["code"],
                    "name": s["name"],
                    "net_out": net_out,
                    "unit": "亿",
                    "day_count": s["consec"],
                })
    top_out = top_out[:8]

    # 构建结果
    result = {
        "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "top_main_in": top_in,
        "top_main_out": top_out,
    }

    # 空数据保护：从旧数据补充
    if not top_in and not top_out:
        old = load_old_data()
        if old and (old.get("top_main_in") or old.get("top_main_out")):
            print(f"\n  ⚠️ 今日无有效主力数据，保留旧数据")
            result["top_main_in"] = old.get("top_main_in", [])
            result["top_main_out"] = old.get("top_main_out", [])
            result["update_time"] = old.get("update_time", result["update_time"])

    # 保存
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 已保存: {OUTPUT_FILE}")
    print(f"   主力净流入: {len(top_in)} 只")
    for s in top_in[:5]:
        print(f"     {s['name']} +{s['net_in']}{s['unit']} 连{s['day_count']}日")
    print(f"   主力净流出: {len(top_out)} 只")
    for s in top_out[:5]:
        print(f"     {s['name']} -{s['net_out']}{s['unit']} 连{s['day_count']}日")
    print(f"   更新时间: {result['update_time']}")

    return result

if __name__ == "__main__":
    main()
