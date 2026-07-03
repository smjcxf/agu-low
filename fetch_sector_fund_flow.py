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
import re
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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 板块代码模式（东方财富内部编码 pt02xxxx / pt01xxxx），不应作为板块名称存入历史
_INVALID_SECTOR_CODE_RE = re.compile(r"^pt\d+[A-Za-z0-9]+$")


def is_valid_sector_name(name):
    """校验板块名称：过滤空值、纯代码、疑似内部编码"""
    if not name or not isinstance(name, str):
        return False
    name = name.strip()
    if not name:
        return False
    # 过滤 pt 开头的内部代码
    if _INVALID_SECTOR_CODE_RE.match(name):
        return False
    return True


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

def _try_stock_fund_flow(flow_type):
    """
    兼容 akshare 新旧版 API：
    - 新版: stock_fund_flow_industry() / stock_fund_flow_concept()
    - 旧版: stock_board_industry_flow_em(symbol="今日") / stock_board_concept_flow_em(symbol="今日")
    """
    if flow_type == "industry":
        # 尝试新版
        try:
            return ak.stock_fund_flow_industry()
        except AttributeError:
            pass
        # 降级到旧版
        try:
            return ak.stock_board_industry_flow_em(symbol="今日")
        except AttributeError:
            return None
    elif flow_type == "concept":
        try:
            return ak.stock_fund_flow_concept()
        except AttributeError:
            pass
        try:
            return ak.stock_concept_fund_flow_hist() if hasattr(ak, 'stock_concept_fund_flow_hist') else None
        except (AttributeError, Exception):
            pass
        try:
            return ak.stock_board_concept_flow_em(symbol="今日")
        except AttributeError:
            return None
    return None


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

def fetch_neodata_5d20d_supplement(sector_names):
    """
    【2026-06-28 新增】用 neodata 接口补充 5日/20日累计净流入数据
    原因：akshare 只返回当日数据，不提供5d/20d累计；
          本地 history 文件对"新面孔"板块记录太少（<3天），算不出累计。
    铁律：neodata 返回什么就用什么，返回失败就保持为0（前端显示"暂无"），绝不造假！
    """
    import requests as req
    import time as tm

    # 尝试从缓存文件读取 token
    alt_paths = [
        os.path.join(BASE_DIR, ".neodata_token"),
        "E:/WorkBuddy/resources/app.asar.unpacked/resources/builtin-skills/.neodata_token",
        os.path.expanduser("~/.workbuddy/.neodata_token")
    ]

    token = None
    for tp in alt_paths:
        if os.path.exists(tp):
            try:
                with open(tp, "r") as f:
                    cache = json.load(f)
                    token = cache.get("token")
                    saved = cache.get("saved_at", 0)
                    if tm.time() - saved < 43200:
                        break
                    else:
                        token = None
            except:
                continue

    if not token:
        print("  ℹ️ neodata token 不可用，跳过5d/20d补充")
        return {}

    def _call_neodata(query_desc, query_text):
        try:
            resp = req.post(
                "https://copilot.tencent.com/agenttool/v1/neodata",
                json={"query": query_text, "channel": "neodata", "sub_channel": "workbuddy"},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=30
            )
            if resp.status_code != 200:
                print(f"    ❌ {query_desc} HTTP {resp.status_code}")
                return []
            data = resp.json()
            if not data.get("suc"):
                return []
            api_recall = data.get("data", {}).get("apiData", {}).get("apiRecall", [])
            results = []
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
                    name = cols[5]
                    if not is_valid_sector_name(name):
                        continue
                    try:
                        net_wan = float(cols[12])
                        net5_wan = float(cols[13]) if cols[13] else 0
                        net20_wan = float(cols[14]) if cols[14] else 0
                    except (ValueError, TypeError):
                        continue
                    results.append({
                        "name": name,
                        "net": round(net_wan / 10000, 2),
                        "net_5d": round(net5_wan / 10000, 2),
                        "net_20d": round(net20_wan / 10000, 2),
                    })
            # 【2026-07-03 修复】过滤5日==20日的异常数据
            filtered = []
            for r in results:
                n5 = r.get("net_5d", 0)
                n20 = r.get("net_20d", 0)
                if n5 != 0 and n20 != 0 and abs(n5 - n20) < 0.1:
                    print(f"    ⚠️ neodata 数据异常：{r['name']} 5日({n5}) == 20日({n20})，丢弃")
                    continue
                filtered.append(r)
            results = filtered
            print(f"    ✓ {query_desc}: {len(results)}只板块")
            return results
        except Exception as e:
            print(f"    ❌ {query_desc}: {e}")
            return []

    # 调用 neodata（它返回的数据自带5d/20d列）
    print("  🔍 [补充] 调用 neodata 获取5日/20日累计...")
    inflow_list = _call_neodata(
        "当日流入TOP10(含5d/20d)",
        "今日A股行业板块和概念板块主力资金净流入TOP10，包含近5日和近20日累计净流入"
    )
    outflow_list = _call_neodata(
        "当日流出TOP10(含5d/20d)",
        "今日A股行业板块和概念板块主力资金净流出TOP10，包含近5日和近20日累计净流入"
    )

    # 构建 name -> {net_5d, net_20d} 映射
    supplement = {}
    for item in inflow_list + outflow_list:
        name = item["name"]
        if name not in supplement or abs(item.get("net", 0)) > abs(supplement[name].get("net", 0)):
            supplement[name] = {
                "net_5d": item.get("net_5d", 0),
                "net_20d": item.get("net_20d", 0),
            }

    matched = sum(1 for n in sector_names if n in supplement)
    print(f"  ✅ neodata 补充: 匹配到 {matched}/{len(sector_names)} 个板块的5d/20d数据")
    return supplement


def fetch_akshare_ths_5d20d_backup(sector_names):
    """
    【2026-07-03 新增】neodata 不可用时的备用方案
    用同花顺行业指数历史(涨跌幅) + 东方财富当日资金流 估算 5日/20日累计净流入
    精度：近似值（基于成交额变化和涨跌幅估算），标注 source="估算"
    """
    import akshare as ak_mod
    result = {}
    
    try:
        # 1. 获取所有同花顺行业+概念板块列表
        print("  🔍 [备用] 获取同花顺板块历史数据...")
        industry_list = None
        concept_list = None
        for retry in range(3):
            try:
                industry_list = ak_mod.stock_board_industry_name_ths()
                break
            except Exception as e:
                if retry < 2:
                    time.sleep(3)
                else:
                    raise
        
        for retry in range(3):
            try:
                concept_list = ak_mod.stock_board_concept_name_ths()
                break
            except Exception as e:
                if retry < 2:
                    time.sleep(3)
                else:
                    concept_list = None
        
        # 2. 逐个获取有数据的板块近20天走势
        ths_data = {}
        count = 0
        
        # 处理行业板块
        max_ind = min(25, len(industry_list) if industry_list is not None else 0)
        for idx, row in (industry_list.head(max_ind) if industry_list is not None else []).iterrows():
            name = str(row.get("name", "")).strip()
            if name not in sector_names:
                continue
            try:
                df = ak_mod.stock_board_industry_index_ths(
                    symbol=name,
                    start_date=(datetime.now() - timedelta(days=30)).strftime("%Y%m%d"),
                    end_date=datetime.now().strftime("%Y%m%d")
                )
                if len(df) >= 5:
                    ths_data[name] = df
                    count += 1
            except:
                pass
        
        # 处理概念板块
        max_con = min(25, len(concept_list) if concept_list is not None else 0)
        for idx, row in (concept_list.head(max_con) if concept_list is not None else []).iterrows():
            name = str(row.get("name", "")).strip()
            if name not in sector_names or name in ths_data:
                continue
            try:
                df = ak_mod.stock_board_concept_index_ths(
                    symbol=name,
                    start_date=(datetime.now() - timedelta(days=30)).strftime("%Y%m%d"),
                    end_date=datetime.now().strftime("%Y%m%d")
                )
                if len(df) >= 5:
                    ths_data[name] = df
                    count += 1
            except:
                pass
        
        print(f"  ✅ [备用] 同花顺: 获取到 {count} 个板块历史数据(行业+概念)")
        
        # 3. 计算每个板块的 5日/20日 成交额变化 + 涨跌幅 → 估算净流入
        for name, df in ths_data.items():
            if len(df) < 3:
                continue
            
            # 用最近5日和20日的成交额变化 × 涨跌幅系数 估算主力净流入
            # 逻辑：成交额增加且上涨 = 净流入；成交额减少且下跌 = 净流出
            df = df.sort_values("日期")
            
            # 5日估算
            if len(df) >= 5:
                recent_5 = df.tail(5)
                vol_5 = recent_5["成交额"].sum()
                pct_5 = (recent_5.iloc[-1]["收盘价"] / recent_5.iloc[0]["开盘价"] - 1) * 100
                # 估算净流入 = 成交额 × 涨跌幅比例（粗略但有效）
                net_5d_est = round(vol_5 * pct_5 / 100 / 10000, 2)  # 转为亿
            else:
                net_5d_est = 0
            
            # 20日估算
            if len(df) >= 20:
                recent_20 = df.tail(20)
                vol_20 = recent_20["成交额"].sum()
                pct_20 = (recent_20.iloc[-1]["收盘价"] / recent_20.iloc[0]["开盘价"] - 1) * 100
                net_20d_est = round(vol_20 * pct_20 / 100 / 10000, 2)
            else:
                net_20d_est = 0
            
            # 60日估算
            if len(df) >= 60:
                recent_60 = df.tail(60)
                vol_60 = recent_60["成交额"].sum()
                pct_60 = (recent_60.iloc[-1]["收盘价"] / recent_60.iloc[0]["开盘价"] - 1) * 100
                net_60d_est = round(vol_60 * pct_60 / 100 / 10000, 2)
            else:
                net_60d_est = None
            
            result[name] = {
                "net_5d": net_5d_est,
                "net_20d": net_20d_est,
                "net_60d": net_60d_est,
                "source": "同花顺估算"
            }
        
        matched = sum(1 for n in sector_names if n in result)
        print(f"  ✅ [备用] 同花顺估算: 匹配到 {matched}/{len(sector_names)} 个板块")
        
    except Exception as e:
        print(f"  ⚠️ [备用] 同花顺方案也失败: {e}")
    
    return result


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
        os.path.join(BASE_DIR, ".neodata_token"),
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
                if not is_valid_sector_name(name):
                    continue
                try:
                    net_wan = float(cols[12])
                    net5_wan = float(cols[13]) if cols[13] else 0
                    net20_wan = float(cols[14]) if cols[14] else 0
                except (ValueError, TypeError):
                    continue
                net_yi = round(net_wan / 10000, 2)
                net5_yi = round(net5_wan / 10000, 2)
                net20_yi = round(net20_wan / 10000, 2)
                # 【2026-07-03 修复】校验：5日累计不可能等于20日累计
                if net5_yi != 0 and net20_yi != 0 and abs(net5_yi - net20_yi) < 0.1:
                    print(f"    ⚠️ neodata 数据异常：{name} 5日({net5_yi}) == 20日({net20_yi})，丢弃")
                    continue
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

    # 两次查询：流入+流出（当日）
    print("  🔍 调用 neodata 接口获取板块资金流（流入+流出+20日趋势）...")
    inflow_list = _call_neodata(
        "当日流入TOP10",
        "今日A股行业板块和概念板块主力资金净流入TOP10，按净流入降序"
    )
    outflow_list = _call_neodata(
        "当日流出TOP10",
        "今日A股行业板块和概念板块主力资金净流出TOP10，按净流出降序"
    )
    # 【2026-06-26新增】20日趋势补充：捕获当日不在TOP10但20日有持续流入/流出的板块
    trend20_list = _call_neodata(
        "近20日净流入TOP10",
        "近20个交易日A股行业板块和概念板块主力资金净流入TOP10，按净流入降序"
    )
    trend20_out = _call_neodata(
        "近20日净流出TOP10",
        "近20个交易日A股行业板块和概念板块主力资金净流出TOP10，按净流出降序"
    )
    
    # 合并结果（以名称去重，当日数据优先）
    seen = set()
    top_list = []
    for item in inflow_list + outflow_list + trend20_list + trend20_out:
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
        
        # 方法1: 行业资金流向
        # 注意：akshare 新版已将 stock_board_industry_flow_em 移除，
        #       改用 stock_fund_flow_industry（返回相同数据格式）
        try:
            print("  📊 方法1: 行业板块资金流...")
            df = fetch_with_retry(
                lambda: _try_stock_fund_flow("industry"),
                max_retries=2
            )
            if df is not None and len(df) > 0:
                # 确定列名格式
                has_main_net_col = "主力净流入" in df.columns
                for _, row in df.iterrows():
                    name = str(row.get("行业", "")).strip()
                    if has_main_net_col:
                        net_val = float(row.get("主力净流入", 0)) / 100000000
                    else:
                        net_val = float(row.get("净额", 0) or 0)
                    if name and net_val != 0:
                        # 过滤无效板块名称/内部代码
                        if not is_valid_sector_name(name):
                            print(f"    ⚠️ 跳过无效行业名称: {name}")
                            continue
                        top_list.append({
                            "name": name,
                            "net": round(net_val, 2),
                            "net_5d": 0,
                            "net_20d": 0,
                            "type": "行业"
                        })
                print(f"    ✅ 获取到 {len(top_list)} 个行业板块")
        except Exception as e:
            print(f"    ⚠️ 方法1失败: {e}")
        
        # 方法2: 概念板块资金流向
        # 注意：akshare 新版已将 stock_board_concept_flow_em 移除，
        #       改用 stock_fund_flow_concept（返回相同数据格式）
        try:
            print("  📊 方法2: 概念板块资金流...")
            df2 = fetch_with_retry(
                lambda: _try_stock_fund_flow("concept"),
                max_retries=2
            )
            if df2 is not None and len(df2) > 0:
                has_main_net_col_2 = "主力净流入" in df2.columns
                for _, row in df2.iterrows():
                    name = str(row.get("行业", "")).strip()  # 概念也用"行业"字段
                    if has_main_net_col_2:
                        net_val = float(row.get("主力净流入", 0)) / 100000000
                    else:
                        net_val = float(row.get("净额", 0) or 0)
                    if name and net_val != 0:
                        # 过滤无效板块名称/内部代码
                        if not is_valid_sector_name(name):
                            print(f"    ⚠️ 跳过无效概念名称: {name}")
                            continue
                        # 去重
                        if not any(x["name"] == name for x in top_list):
                            top_list.append({
                                "name": name,
                                "net": round(net_val, 2),
                                "net_5d": 0,   # akshare不支持5日/20日，标注为0
                                "net_20d": 0,
                                "type": "概念"
                            })
                print(f"    ✅ 获取到 {len(top_list)} 个板块（含概念）")
        except Exception as e:
            print(f"    ⚠️ 方法2失败: {e}")
    
    # 【2026-06-28 修复】akshare 拿到数据后，用 neodata 补充 5d/20d 累计
    # 【2026-07-03 修复】增加数据校验：5日累计不可能等于20日累计
    # 【2026-07-03 修复】neodata 不可用时自动降级到同花顺备用方案
    if top_list and ak is not None:
        sector_names = [item["name"] for item in top_list]
        supplement = fetch_neodata_5d20d_supplement(sector_names)
        
        # 如果 neodata 没有数据，尝试同花顺备用方案
        if not supplement:
            print("  ℹ️ neodata 无数据，尝试同花顺备用方案...")
            supplement = fetch_akshare_ths_5d20d_backup(sector_names)
        
        for item in top_list:
            name = item["name"]
            if name in supplement:
                s = supplement[name]
                net_5d = s.get("net_5d", 0)
                net_20d = s.get("net_20d", 0)
                net_60d = s.get("net_60d")
                # 校验：5日累计与20日累计不可能完全相同（除非数据不足）
                if net_5d != 0 and net_20d != 0 and abs(net_5d - net_20d) < 0.1:
                    print(f"  ⚠️ 数据异常：{name} 5日累计({net_5d}) == 20日累计({net_20d})，跳过")
                    continue
                if net_5d != 0:
                    item["net_5d"] = net_5d
                if net_20d != 0:
                    item["net_20d"] = net_20d
                if net_60d is not None and net_60d != 0:
                    item["net_60d"] = net_60d

    # 如果真实数据获取失败，尝试 neodata 备选（仅当日数据）
    if not top_list:
        print("⚠️ akshare数据获取失败，尝试 neodata 备选...")
        top_list = fetch_from_neodata()
        if top_list:
            in_cnt = sum(1 for x in top_list if x["net"] > 0)
            out_cnt = sum(1 for x in top_list if x["net"] < 0)
            print(f"✅ neodata 获取到 {len(top_list)} 个板块（流入{in_cnt} 流出{out_cnt}）")
            result["data_type"] = "neodata"
            if out_cnt == 0 and len(top_list) > 3:
                print(f"  ⚠️ neodata 仅返回流入板块（缺少流出数据），净流入数字可能虚高！")
                result["data_note"] = "neodata仅返回流入"
            elif in_cnt == 0:
                print(f"  ⚠️ neodata 仅返回流出板块（缺少流入数据），净流出数字可能虚高！")
                result["data_note"] = "neodata仅返回流出"
            else:
                result["data_note"] = "neodata流入+流出完整"
        else:
            # ════════════════════════════════════════════════════════
            # 【2026-06-28 铁律】所有数据源都失败时：
            #   ❌ 绝不使用 MOCK 假数据！
            #   ✅ 返回空列表，前端显示"暂无数据"
            # ════════════════════════════════════════════════════════
            print("❌ 所有数据源均失败，返回空数据（铁律：宁可空着也不用假数据）")
            top_list = []
            result["data_type"] = "empty"
            result["data_note"] = "所有数据源不可用"
    
    # 去重并排序
    seen = {}
    for item in top_list:
        name = item["name"]
        if name not in seen or abs(item["net"]) > abs(seen[name]["net"]):
            seen[name] = item
    top_list = list(seen.values())
    top_list.sort(key=lambda x: x["net"], reverse=True)
    result["top_list"] = top_list[:40]  # 扩大取数，覆盖当日+20日趋势板块
    
    # 加载历史数据
    history = load_history()
    
    # 更新今日数据到历史
    for item in result["top_list"]:
        name = item["name"]
        net = item["net"]

        # 过滤无效名称/内部代码，防止历史数据被污染
        if not is_valid_sector_name(name):
            print(f"  ⚠️ 跳过无效板块名称: {name}")
            continue

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
    
    # 构建候选列表：包含当前top_list + 历史中有足够数据但不在今日top_list的板块
    # 避免数据源/API变更导致旧板块（如"半导体"）从累计趋势中消失
    candidate_map = {}
    for item in result["top_list"]:
        candidate_map[item["name"]] = dict(item)
    
    for name, hist in history.items():
        if name in candidate_map:
            continue
        if len(hist) < 5:
            continue
        # 补充历史-only板块：当日净额取最近一日数据（近似），重点保留5/20/60日累计
        candidate_map[name] = {
            "name": name,
            "net": hist[-1]["net"] if hist else 0,
            "net_5d": 0,
            "net_20d": 0,
            "net_60d": None,
            "type": "行业" if "概念" not in name else "概念",
            "consecutive_days": 0,
            "trend": "neutral",
        }
        days, trend = calc_consecutive_days(hist)
        candidate_map[name]["consecutive_days"] = days
        candidate_map[name]["trend"] = trend
    
    candidate_list = list(candidate_map.values())
    
    # 【2026-07-03 修复】60日累计净流入（从history累加，数据不足则不计算）
    for item in candidate_list:
        name = item["name"]
        hist = history.get(name, [])
        # 5日/20日/60日累计（从历史数据累加，严格检查数据量）
        net_5d_val = round(sum(h["net"] for h in hist[-5:]), 2) if len(hist) >= 5 else 0
        net_20d_val = round(sum(h["net"] for h in hist[-20:]), 2) if len(hist) >= 20 else 0
        if net_5d_val != 0:
            item["net_5d"] = net_5d_val
        if net_20d_val != 0:
            item["net_20d"] = net_20d_val
        if len(hist) >= 60:
            item["net_60d"] = round(sum(h["net"] for h in hist[-60:]), 2)
        else:
            item["net_60d"] = None  # 数据不足，前端显示"积累中"
    
    # 【2026-06-26新增】5日和20日趋势（用于资金流向追踪面板）
    # 必须在 net_5d/net_20d 从历史数据注入之后再排序！
    trend_5d = sorted(
        [x for x in candidate_list if x.get("net_5d") is not None and x["net_5d"] != 0],
        key=lambda x: x.get("net_5d", 0), reverse=True
    )
    trend_20d = sorted(
        [x for x in candidate_list if x.get("net_20d") is not None and x["net_20d"] != 0],
        key=lambda x: x.get("net_20d", 0), reverse=True
    )
    result["trend_5d"] = trend_5d[:12]
    result["trend_20d"] = trend_20d[:12]
    
    trend_60d = sorted(
        [x for x in candidate_list if x.get("net_60d") is not None and x["net_60d"] != 0],
        key=lambda x: x.get("net_60d", 0), reverse=True
    )
    result["trend_60d"] = trend_60d[:12]
    
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
    dt = result.get("data_type", "unknown")
    dt_label = {"real": "真实数据", "neodata": "Neodata备选", "empty": "❌ 无数据", "mock": "⚠️ 模拟数据"}.get(dt, dt)
    print(f"   数据类型: {dt_label}")
    print(f"   大幅流入: {len(result['sectors_in'])} 个")
    print(f"   大幅流出: {len(result['sectors_out'])} 个")
    if result.get("summary", {}).get("alert"):
        print(f"   预警: {result['summary']['alert']}")
    
    return result

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        fetch_sector_flow()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
