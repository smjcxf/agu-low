#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源官网/同源对比完全自动化脚本 v2

策略：
- 对每个数据源，重新调用相同的API（akshare/westock-data/eastmoney）获取最新数据
- 与本地存储的 JSON 文件做关键字段对比
- 差异超过阈值则报警

覆盖4个关键数据源：
1. north_fund.json  — 南向资金 (akshare)
2. herding_data.json — 行业+概念资金流 (akshare)
3. main_stock.json   — 个股主力资金 (westock-data asfund)
4. sector_fund_flow.json — 板块资金流 (akshare)

输出：控制台报告 + data/verify_report.json（持久化）
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
REPORT_FILE = os.path.join(DATA_DIR, "verify_report.json")

# 全局结果收集
report = {
    "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "checks": [],
    "summary": {"total": 0, "passed": 0, "warned": 0, "failed": 0, "skipped": 0},
}


def load_json(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return None


def record_check(source_name, status, detail="", issues=None):
    entry = {
        "source": source_name,
        "status": status,  # PASS / WARN / FAIL / SKIP
        "detail": detail,
        "issues": issues or [],
        "time": datetime.now().strftime("%H:%M:%S"),
    }
    report["checks"].append(entry)
    report["summary"]["total"] += 1
    report["summary"][{"PASS": "passed", "WARN": "warned", "FAIL": "failed", "SKIP": "skipped"}[status]] += 1


def check_north_fund():
    """验证 north_fund.json — 用 akshare 重新获取南向资金对比"""
    print("\n" + "=" * 60)
    print("📊 [1/4] 验证 north_fund.json（南向资金 / akshare）")
    print("=" * 60)

    local = load_json("north_fund.json")
    if not local:
        record_check("north_fund.json", "FAIL", "本地文件不存在")
        print("  ❌ 本地文件不存在")
        return

    # 检查基本结构
    south_flow = local.get("south_flow", {})
    if not south_flow or south_flow.get("total", 0) == 0:
        record_check("north_fund.json", "WARN",
                     f"无有效南向资金数据（可能非交易日），"
                     f"update_time={local.get('update_time', '?')}")
        print(f"  ⚠️ 无效数据（非交易日？），更新于 {local.get('update_time')}")
        # 不算失败，周末没数据正常
        return

    # 用 akshare 重新获取做对比
    issues = []
    try:
        import akshare as ak

        # 1) 对比当日汇总
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is not None and len(df) > 0:
            south_rows = df[df['资金方向'] == '南向']
            if len(south_rows) > 0:
                sh_row = south_rows[south_rows['板块'] == '港股通(沪)']
                sz_row = south_rows[south_rows['板块'] == '港股通(深)']
                sh_net = float(sh_row.iloc[0].get('成交净买额', 0) or 0) if len(sh_row) > 0 else 0
                sz_net = float(sz_row.iloc[0].get('成交净买额', 0) or 0) if len(sz_row) > 0 else 0
                api_total = round(sh_net + sz_net, 2)
                api_dir = "流入" if api_total >= 0 else "流出"

                local_total = south_flow.get("total", 0)
                local_dir = south_flow.get("direction", "")

                diff = abs(api_total) - abs(local_total)
                diff_pct = (diff / max(abs(api_total), abs(local_total), 0.01)) * 100

                print(f"  本地: {local_dir} {abs(local_total)}亿 "
                      f"(沪{south_flow.get('sh_net')} 深{south_flow.get('sz_net')})")
                print(f"  API:  {api_dir} {abs(api_total)}亿 (沪{sh_net:.2f} 深{sz_net:.2f})")

                # 允许 ±5% 偏差（四舍五入、时间差异）
                if diff_pct <= 5:
                    print(f"  ✅ 南向汇总一致（偏差 {diff_pct:.1f}% ≤ 5%）")
                elif diff_pct <= 15:
                    msg = f"南向汇总偏差较大 ({diff_pct:.1f}%)，本地={abs(local_total)} API={abs(api_total)}"
                    issues.append(msg)
                    print(f"  ⚠️  {msg}")
                else:
                    msg = f"南向汇总严重偏差 ({diff_pct:.1f}%)！本地={abs(local_total)} API={abs(api_total)}"
                    issues.append(msg)
                    print(f"  ❌ {msg}")

            else:
                print("  ℹ️  API 无南向数据（非交易日），无法对比数值")
        else:
            print("  ⚠️  akshare 返回空数据（网络/API问题），跳过数值对比")

        # 2) 对比个股排行（如果有）
        south_individual = local.get("south_individual")
        if south_individual and south_individual.get("top_buy"):
            try:
                df_ind = ak.stock_hsgt_individual_em(symbol="南向")
                if df_ind is not None and len(df_ind) > 0:
                    local_top1 = south_individual["top_buy"][0]
                    print(f"\n  本地TOP1: {local_top1.get('name')}({local_top1.get('code')}) "
                          f"净买{local_top1.get('net_buy')}亿")
                    # API TOP1
                    df_clean = df_ind.dropna(subset=["当日成交净买额"]).copy()
                    df_clean["_n"] = df_clean["当日成交净买额"].astype(float)
                    df_sorted = df_clean.sort_values("_n", ascending=False)
                    if len(df_sorted) > 0:
                        row = df_sorted.iloc[0]
                        api_top1_name = str(row.get("名称", ""))
                        api_top1_val = round(float(row["当日成交净买额"]), 2)
                        print(f"  API TOP1: {api_top1_name} 净买{api_top1_val}亿")

                        # 只检查是否在同一只或相近（排名可能有变化）
                        if api_top1_name == local_top1.get("name"):
                            print("  ✅ 个股TOP1 一致")
                        else:
                            msg = f"个股TOP1不一致: 本地={local_top1.get('name')} API={api_top1_name}"
                            issues.append(msg)
                            print(f"  ⚠️  {msg}")
            except Exception as e:
                print(f"  ℹ️  个股对比失败: {e}（不影响主结论）")

        # 数据新鲜度
        update_time_str = local.get("update_time", "")
        if update_time_str:
            try:
                dt = datetime.strptime(update_time_str[:19], "%Y-%m-%d %H:%M:%S")
                hours_ago = (datetime.now() - dt).total_seconds() / 3600
                print(f"\n  📅 数据年龄: {hours_ago:.1f} 小时前")
                if hours_ago > 72 and datetime.now().weekday() >= 5:
                    # 周末 > 72h 正常
                    pass
                elif hours_ago > 48:
                    msg = f"数据较旧 ({hours_ago:.0f}h)，可能需要刷新"
                    issues.append(msg)
            except ValueError:
                issues.append("update_time 格式无法解析")

        # 判定结果
        status = "FAIL" if any("严重偏差" in i for i in issues) else (
            "WARN" if issues else "PASS")
        record_check("north_fund.json", status,
                     f"南向资金 {south_flow.get('direction')} {south_flow.get('total')}亿",
                     issues)

    except ImportError:
        record_check("north_fund.json", "WARN",
                     "akshare 未安装，仅做了本地合理性检查")
        print("  ⚠️  akshare 未安装，无法做同源对比")
    except Exception as e:
        record_check("north_fund.json", "WARN", f"同源对比异常: {e}")
        print(f"  ⚠️  同源对比异常: {e}")


def check_herding_data():
    """验证 herding_data.json — 用 akshare stock_fund_flow_industry/concept 重新获取对比"""
    print("\n" + "=" * 60)
    print("📊 [2/4] 验证 herding_data.json（行业+概念资金流 / akshare）")
    print("=" * 60)

    local = load_json("herding_data.json")
    if not local:
        record_check("herding_data.json", "FAIL", "本地文件不存在")
        print("  ❌ 本地文件不存在")
        return

    issues = []
    clusters = local.get("current_clusters", [])
    high_prob = local.get("high_prob", [])
    industry_local = local.get("industry_flow", {}).get("inflow", [])

    if not clusters and not high_prob:
        record_check("herding_data.json", "WARN",
                     f"无有效抱团数据（可能非交易日），"
                     f"update_time={local.get('update_time', '?')}")
        print(f"  ⚠️ 无效数据，更新于 {local.get('update_time')}")
        return

    print(f"  本地当前抱团: {len(clusters)} 方向")
    if clusters:
        print(f"     🥇 {clusters[0]['sector']} +{clusters[0]['amount']}亿 "
              f"(领涨:{clusters[0].get('leader','?')})")
    print(f"  本地接力方向: {len(high_prob)} 个")
    if high_prob:
        print(f"     ① {high_prob[0]['sector']} +{high_prob[0]['net']}亿")

    # 用 akshare 重新获取
    try:
        import akshare as ak

        # 行业资金流向
        df_ind = ak.stock_fund_flow_industry()
        api_ind_inflow = []
        if df_ind is not None and len(df_ind) > 0:
            for _, row in df_ind.iterrows():
                name = str(row.get('行业', ''))
                net = float(row.get('净额', 0) or 0)
                if name and net > 0.5:
                    api_ind_inflow.append({'name': name, 'net': round(net, 2)})
            api_ind_inflow.sort(key=lambda x: x['net'], reverse=True)

        if api_ind_inflow:
            print(f"\n  API 行业流入TOP1: {api_ind_inflow[0]['name']} +{api_ind_inflow[0]['net']}亿")

            # 对比行业流入TOP1是否一致
            if clusters:
                local_top_sector = clusters[0]["sector"]
                local_top_amount = clusters[0]["amount"]
                api_top_sector = api_ind_inflow[0]["name"]
                api_top_amount = api_ind_inflow[0]["net"]

                if local_top_sector == api_top_sector:
                    diff_pct = abs(local_top_amount - api_top_amount) / max(
                        abs(api_top_amount), 0.01) * 100
                    if diff_pct <= 10:
                        print(f"  ✅ 行业TOP1 一致: {local_top_sector}"
                              f" (本地{local_top_amount}亿 vs API{api_top_amount}亿)")
                    else:
                        msg = (f"行业TOP1金额偏差大: "
                               f"{local_top_sector} 本地={local_top_amount}亿 vs API={api_top_amount}亿")
                        issues.append(msg)
                        print(f"  ⚠️  {msg}")
                else:
                    # 可能是不同时间段导致排名差异，检查是否都在TOP3
                    api_top3_names = [x['name'] for x in api_ind_inflow[:3]]
                    if local_top_sector in api_top3_names:
                        print(f"  ✅ 行业TOP1在API TOP3内（时间差异导致排名不同）")
                    else:
                        msg = (f"行业TOP1差异大: 本地={local_top_sector} vs API={api_top_sector}, "
                               f"API_TOP3={api_top3_names}")
                        issues.append(msg)
                        print(f"  ⚠️  {msg}")
        else:
            print("  ℹ️  API 无行业数据（非交易日），无法对比")

        # 数据新鲜度
        update_time_str = local.get("update_time", "")
        if update_time_str:
            try:
                dt = datetime.strptime(update_time_str[:19], "%Y-%m-%d %H:%M:%S")
                hours_ago = (datetime.now() - dt).total_seconds() / 3600
                print(f"\n  📅 数据年龄: {hours_ago:.1f} 小时前")
                if hours_ago > 48:
                    msg = f"数据较旧 ({hours_ago:.0f}h)"
                    issues.append(msg)
            except ValueError:
                pass

        status = "FAIL" if any("严重" in i or "差异大" in i for i in issues) else (
            "WARN" if issues else "PASS")
        record_check("herding_data.json", status,
                     f"抱团{len(clusters)}方向 + 接力{len(high_prob)}个", issues)

    except ImportError:
        record_check("herding_data.json", "WARN", "akshare 未安装")
        print("  ⚠️  akshare 未安装")
    except Exception as e:
        record_check("herding_data.json", "WARN", f"异常: {e}")
        print(f"  ⚠️  异常: {e}")


def check_main_stock():
    """验证 main_stock.json — 用 westock-data CLI 重新查询几只股票对比"""
    print("\n" + "=" * 60)
    print("📊 [3/4] 验证 main_stock.json（个股主力资金 / westock-data）")
    print("=" * 60)

    local = load_json("main_stock.json")
    if not local:
        record_check("main_stock.json", "FAIL", "本地文件不存在")
        print("  ❌ 本地文件不存在")
        return

    top_in = local.get("top_main_in", [])
    top_out = local.get("top_main_out", [])

    if not top_in and not top_out:
        record_check("main_stock.json", "WARN",
                     f"无有效主力数据（可能非交易日），"
                     f"update_time={local.get('update_time', '?')}")
        print(f"  ⚠️ 无效数据，更新于 {local.get('update_time')}")
        return

    issues = []
    print(f"  本地主力净流入 TOP:")
    for s in top_in[:5]:
        print(f"     {s['name']}({s['code']}) +{s['net_in']}{s['unit']} 连{s['day_count']}日")
    print(f"  本地主力净流出 TOP:")
    for s in top_out[:5]:
        print(f"     {s['name']}({s['code']}) -{s['net_out']}{s['unit']} 连{s['day_count']}日")

    # 用 westock-data 重新查询前3只流入 + 前3只流出做抽样验证
    try:
        NODE_PATH = os.path.join(os.path.expanduser("~"),
                                 ".workbuddy", "binaries", "node", "versions",
                                 "22.22.2", "node.exe")
        WESTOCK_DIR = os.path.join(os.path.expanduser("~"),
                                    ".workbuddy", "plugins", "marketplaces",
                                    "cb_teams_marketplace", "plugins", "finance-data",
                                    "skills", "westock-data")
        WESTOCK_SCRIPT = os.path.join(WESTOCK_DIR, "scripts", "index.js")

        if not os.path.exists(WESTOCK_SCRIPT):
            raise FileNotFoundError(f"westock-data script not found at {WESTOCK_SCRIPT}")

        import subprocess

        today = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")

        # 抽样验证：取 top_in 前只 + top_out 前3只
        sample_stocks = []
        for s in (top_in[:3] + top_out[:3]):
            code = s['code']
            prefix = 'sh' if code.startswith(('6', '68')) else 'sz'
            sample_stocks.append(f"{prefix}{code}")

        batch_codes = ",".join(sample_stocks)
        print(f"\n  🔍 抽样验证 {len(sample_stocks)} 只股票...")

        result = subprocess.run(
            [NODE_PATH, WESTOCK_SCRIPT, "asfund", batch_codes,
             "--start", start_date, "--end", today],
            capture_output=True, encoding='utf-8', errors='replace',
            timeout=60, cwd=os.path.dirname(os.path.abspath(__file__))
        )

        if result.returncode != 0:
            msg = f"westock-data CLI 执行失败: {result.stderr[:200]}"
            issues.append(msg)
            print(f"  ⚠️  {msg}")
        elif result.stdout:
            # 解析 Markdown 表格
            output = result.stdout
            api_flows = {}
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
                        code_raw = parts[1]
                        code = code_raw[2:] if code_raw.startswith(("sh","sz","bj")) and len(code_raw)==8 else code_raw
                        date = parts[3]
                        flow = float(parts[9]) if len(parts) > 9 and parts[9] else 0
                        if code not in api_flows:
                            api_flows[code] = []
                        api_flows[code].append({"date": date, "MainNetFlow": flow})
                    except (ValueError, IndexError):
                        continue

            # 对比今日数据
            matched = 0
            mismatched = 0
            for s in (top_in[:3] + top_out[:3]):
                code = s['code']
                if code not in api_flows:
                    continue
                today_api = [f for f in api_flows[code] if f["date"] == today]
                if not today_api:
                    continue
                api_today_net = today_api[0]["MainNetFlow"]

                if s in top_in:
                    local_net_yi = s['net_in']  # 亿元
                    api_net_yi = round(api_today_net / 1e8, 1)
                    direction = "in"
                else:
                    local_net_yi = s['net_out']
                    api_net_yi = round(abs(api_today_net) / 1e8, 1)
                    direction = "out"

                diff_pct = abs(local_net_yi - api_net_yi) / max(
                    abs(api_net_yi), 0.01) * 100
                marker = "✅" if diff_pct <= 20 else ("⚠️ " if diff_pct <= 50 else "❌")
                print(f"  {marker} {s['name']}({code}): "
                      f"本地={local_net_yi}亿 vs API={api_net_yi}亿 (偏差{diff_pct:.0f}%)")

                if diff_pct <= 50:
                    matched += 1
                else:
                    mismatched += 1
                    msg = (f"{s['name']} 主力{'净流入' if direction=='in' else '净流出'}偏差大: "
                           f"本地={local_net_yi}亿 vs API={api_net_yi}亿")
                    issues.append(msg)

            total_checked = matched + mismatched
            if total_checked > 0:
                print(f"\n  抽样结果: {matched}/{total_checked} 一致")

    except FileNotFoundError:
        record_check("main_stock.json", "WARN", "westock-data CLI 未找到")
        print("  ⚠️  westock-data CLI 未找到，跳过抽样验证")
        return
    except subprocess.TimeoutExpired:
        issues.append("westock-data 超时")
        print("  ❌ westock-data 超时")
    except Exception as e:
        issues.append(str(e)[:100])
        print(f"  ⚠️  抽样验证异常: {e}")

    # 数据新鲜度
    update_time_str = local.get("update_time", "")
    if update_time_str:
        try:
            dt = datetime.strptime(update_time_str[:19], "%Y-%m-%d %H:%M:%S")
            hours_ago = (datetime.now() - dt).total_seconds() / 3600
            print(f"\n  📅 数据年龄: {hours_ago:.1f} 小时前")
            if hours_ago > 120:
                issues.append(f"主力数据过旧 ({hours_ago:.0f}h)")
        except ValueError:
            pass

    status = "FAIL" if any("严重" in i for i in issues) else (
        "WARN" if issues else "PASS")
    record_check("main_stock.json", status,
                 f"流入{len(top_in)}只 流出{len(top_out)}只", issues)


def _try_akshare_fund_flow(flow_type="industry"):
    """兼容 akshare 新旧版 API 获取资金流数据"""
    import akshare as ak
    try:
        if flow_type == "industry":
            return ak.stock_fund_flow_industry()
        elif flow_type == "concept":
            return ak.stock_fund_flow_concept()
    except AttributeError:
        pass
    # 降级尝试旧版
    if flow_type == "industry":
        try:
            return ak.stock_board_industry_flow_em(symbol="今日")
        except AttributeError:
            return None
    elif flow_type == "concept":
        try:
            return ak.stock_board_concept_flow_em(symbol="今日")
        except AttributeError:
            return None
    return None


def check_sector_fund_flow():
    """验证 sector_fund_flow.json — 用 akshare 重新获取板块资金流对比"""
    print("\n" + "=" * 60)
    print("📊 [4/4] 验证 sector_fund_flow.json（板块资金流 / akshare）")
    print("=" * 60)

    local = load_json("sector_fund_flow.json")
    if not local:
        record_check("sector_fund_flow.json", "FAIL", "本地文件不存在")
        print("  ❌ 本地文件不存在")
        return

    data_type = local.get("data_type", "?")
    sectors_in = local.get("sectors_in", [])
    sectors_out = local.get("sectors_out", [])

    print(f"  数据类型: {data_type}")
    print(f"  大幅流入: {len(sectors_in)} 个")
    if sectors_in:
        for s in sectors_in[:3]:
            print(f"     {s['name']} +{s.get('net',0):.1f}亿"
                  f"(连{s.get('consecutive_days',0)}天)" if s.get('consecutive_days',0)>1 else "")
    print(f"  大幅流出: {len(sectors_out)} 个")
    if sectors_out:
        for s in sectors_out[:3]:
            print(f"     {s['name']} {s.get('net',0):.1f}亿")

    issues = []

    # 如果是 mock 数据，直接标记警告
    if data_type == "mock":
        msg = "板块资金流使用的是模拟数据（非真实市场数据）"
        issues.append(msg)
        print(f"  🔴 {msg}")
        record_check("sector_fund_flow.json", "FAIL",
                     f"MOCK数据! 流入{len(sectors_in)} 流出{len(sectors_out)}", issues)
        return

    if data_type == "neodata":
        msg = "板块资金流来自 neodata（备选源），未经过东方财富交叉验证"
        issues.append(msg)
        print(f"  ⚠️  {msg}")

    # 用 akshare 重新获取做对比
    # 注意：新版akshare已移除 stock_board_industry_flow_em，改用 stock_fund_flow_industry
    try:
        import akshare as ak

        df = _try_akshare_fund_flow("industry")
        api_sectors = []
        if df is not None and len(df) > 0:
            for _, row in df.iterrows():
                name = str(row.get("行业", "")).strip()
                # 兼容新旧列名
                has_main_net_col = "主力净流入" in df.columns
                try:
                    if has_main_net_col:
                        net = float(row.get("主力净流入", 0)) / 1e8
                    else:
                        net = float(row.get("净额", 0) or 0)
                except (ValueError, TypeError):
                    net = 0
                if name and net != 0:
                    api_sectors.append({"name": name, "net": round(net, 2)})
            api_sectors.sort(key=lambda x: x["net"], reverse=True)

        if api_sectors:
            print(f"\n  API 获取到 {len(api_sectors)} 个行业板块")
            print(f"  API TOP3: ", end="")
            for s in api_sectors[:3]:
                print(f"{s['name']}+{s['net']:.1f}亿 ", end="")
            print()

            # 对比TOP1
            if sectors_in:
                local_top = sectors_in[0]
                api_top = api_sectors[0]

                if local_top["name"] == api_top["name"]:
                    diff_pct = abs(local_top["net"] - api_top["net"]) / max(
                        abs(api_top["net"]), 0.01) * 100
                    if diff_pct <= 10:
                        print(f"  ✅ 板块TOP1 一致: {local_top['name']}"
                              f" (本地{local_top['net']}亿 vs API{api_top['net']}亿)")
                    else:
                        msg = (f"板块TOP1金额偏差: {local_top['name']} "
                               f"本地={local_top['net']}亿 vs API={api_top['net']}亿")
                        issues.append(msg)
                        print(f"  ⚠️  {msg}")
                else:
                    api_top3 = [s["name"] for s in api_sectors[:3]]
                    if local_top["name"] in api_top3:
                        print(f"  ✅ 本地TOP1在API TOP3内（时间差异）")
                    else:
                        msg = (f"板块TOP1差异: 本地={local_top['name']} vs API={api_top['name']}, "
                               f"API_TOP3={api_top3}")
                        issues.append(msg)
                        print(f"  ⚠️  {msg}")
        else:
            print("  ℹ️  API 无数据（非交易日或网络问题）")

        # 新鲜度
        update_time_str = local.get("update_time", "")
        if update_time_str:
            try:
                dt = datetime.strptime(update_time_str[:19], "%Y-%m-%d %H:%M:%S")
                hours_ago = (datetime.now() - dt).total_seconds() / 3600
                print(f"\n  📅 数据年龄: {hours_ago:.1f} 小时前")
                if hours_ago > 24:
                    msg = f"板块数据较新但应每日刷新 ({hours_ago:.0f}h)"
                    issues.append(msg)
            except ValueError:
                pass

        status = "FAIL" if data_type == "mock" or any("严重" in i for i in issues) else (
            "WARN" if issues else "PASS")
        record_check("sector_fund_flow.json", status,
                     f"[{data_type}] 流入{len(sectors_in)} 流出{len(sectors_out)}", issues)

    except ImportError:
        record_check("sector_fund_flow.json", "WARN", "akshare 未安装")
        print("  ⚠️  akshare 未安装")
    except Exception as e:
        record_check("sector_fund_flow.json", "WARN", f"异常: {e}")
        print(f"  ⚠️  异常: {e}")


def main():
    print("=" * 60)
    print("  数据源同源对比自动化验证 v2")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    t0 = time.time()

    # 依次执行4个数据源验证
    check_north_fund()
    check_herding_data()
    check_main_stock()
    check_sector_fund_flow()

    elapsed = time.time() - t0

    # 输出总结
    print("\n" + "=" * 60)
    s = report["summary"]
    print(f"  验证完成 | 耗时: {elapsed:.1f}s")
    print(f"  总计: {s['total']} | ✅ 通过: {s['passed']} | "
          f"⚠️  警告: {s['warned']} | ❌ 失败: {s['failed']} | "
          f"⏭️ 跳过: {s['skipped']}")
    print("=" * 60)

    # 输出所有issues
    all_issues = [(c["source"], c["issues"]) for c in report["checks"] if c["issues"]]
    if all_issues:
        print("\n📋 问题清单:")
        for src, iss_list in all_issues:
            for iss in iss_list:
                print(f"  • [{src}] {iss}")

    # 保存报告
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📄 详细报告已保存: {REPORT_FILE}")

    # 返回退出码
    if s["failed"] > 0:
        print("\n🔴 有失败项，请检查!")
        return 1
    elif s["warned"] > 0:
        print("\n🟡 有警告项，建议关注。")
        return 0
    else:
        print("\n🟢 所有检查通过!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
