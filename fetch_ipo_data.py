#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打新价值评分数据获取 -- 每天开盘前自动更新
用法: python fetch_ipo_data.py
输出: data/ipo_score.json

数据源:
  1. 东方财富 push2 API — 新股申购列表（发行价、PE、中签率等）
  2. 东方财富 datacenter API — 行业市盈率基准

评分维度（满分100）:
  - PE折价 (0-40分): (行业PE - 发行PE) / 行业PE * 40，上限40分
  - 行业热度 (0-25分): 基于板块资金流入方向评分
  - 发行价合理性 (0-20分): 10-30元区间最优
  - 板块溢价 (0-15分): 主板15 > 创业板12 > 科创板10 > 北交所8
"""
import json
import os
import sys
import time
import subprocess
from datetime import datetime, date

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

def http_get(url, retry=5):
    """HTTP GET using curl subprocess (sandbox compatible)"""
    last_err = None
    for i in range(retry):
        try:
            if i > 0:
                time.sleep(3 * i)  # 递增退避
            result = subprocess.run([
                "curl", "-s", "--max-time", "20",
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-H", "Referer: https://data.eastmoney.com/xg/xg/",
                "-H", "Accept: application/json, text/html, */*",
                url
            ], capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                err_msg = result.stderr[:200] or f"exit={result.returncode}"
                if result.returncode in (28, 56, 7):  # timeout, recv error, connect error
                    raise ConnectionError(f"curl {err_msg}")
                raise Exception(f"curl exit {result.returncode}: {err_msg}")
            if not result.stdout or not result.stdout.strip():
                raise ValueError("Empty response")
            return json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError, ConnectionError) as e:
            last_err = e
        except Exception as e:
            last_err = e
    raise last_err

def board_name(market_code):
    """市场代码 → 板块名称"""
    m = {
        "SH": "沪市主板", "SZ": "深市主板", "CY": "创业板",
        "KC": "科创板", "BJ": "北交所"
    }
    return m.get(market_code, "其他")

def board_score(board):
    """板块溢价评分"""
    s = {"沪市主板": 15, "深市主板": 14, "创业板": 12, "科创板": 10, "北交所": 8}
    return s.get(board, 8)

def fetch_sector_flow():
    """读取已有的板块资金流数据用于行业热度评分"""
    flow_path = os.path.join(DATA_DIR, "sector_fund_flow.json")
    if os.path.exists(flow_path):
        with open(flow_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def score_industry_heat(industry, sector_flow):
    """行业热度评分 (0-25分)"""
    if not sector_flow:
        return 15  # 默认中等
    sorted_sectors = sector_flow.get("sorted_sectors", [])
    flow_map = sector_flow.get("flows", {})
    
    # 在流入板块中查找
    rank = 0
    for s in sorted_sectors:
        rank += 1
        if industry in s.get("name", ""):
            direction = flow_map.get(s.get("name", ""), {}).get("direction", "")
            if direction == "流入":
                if rank <= 3: return 25
                if rank <= 10: return 20
                return 18
            elif direction == "流出":
                if rank <= 3: return 8
                return 10
    return 12  # 未找到，中等偏低

def score_price(price):
    """发行价合理性评分 (0-20分)"""
    if not price or price <= 0:
        return 10
    if price <= 5:
        return 12   # 低价股
    if price <= 15:
        return 20   # 黄金区间
    if price <= 30:
        return 18   # 不错
    if price <= 50:
        return 14   # 偏贵但可接受
    if price <= 80:
        return 8    # 高价
    return 4        # 超高价

def fetch_ipo_list():
    """
    从东方财富获取当前可申购新股列表
    使用 push2 API，筛选可申购状态新股
    返回 [(code, name, issue_price, issue_pe, industry_pe, lottery_rate, 
             market_code, industry_name, apply_date, apply_code), ...]
    """
    candidates = []
    
    # ═══ push2 API — 获取全A股按上市日期升序，"f26=-"的未上市新股排在最前 ═══
    url1 = ("https://push2.eastmoney.com/api/qt/clist/get?"
            "fid=f26&po=0&pz=15&pn=1&np=1&fltt=2&invt=2"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
            "&fields=f12,f14,f18,f26,f115")
    
    try:
        data = http_get(url1)
        stocks = data.get("data", {}).get("diff", [])
        if stocks:
            today_str = datetime.now().strftime("%Y%m%d")
            
            for s in stocks:
                code = s.get("f12", "")
                name = s.get("f14", "")
                if not code or not name:
                    continue
                
                f26_raw = s.get("f26", "")
                listing_str = str(f26_raw) if f26_raw else ""
                
                # 关键：f26="-" 表示未上市 → 这就是待申购新股！
                is_unlisted = (listing_str == "-" or listing_str == "" or listing_str == "None")
                
                listing_int = 0
                if not is_unlisted:
                    try:
                        listing_int = int(listing_str)
                    except:
                        is_unlisted = True
                
                # 筛掉上市超过30天的老股
                if not is_unlisted:
                    try:
                        today_int = int(today_str)
                        if listing_int < today_int - 30:
                            continue
                    except:
                        continue
                
                # 提取PE和价格（注意API返回的可能是字符串，需要类型转换）
                issue_pe_raw = s.get("f115", 0)
                issue_price_raw = s.get("f18", 0)
                
                try:
                    issue_pe = float(issue_pe_raw) if issue_pe_raw and issue_pe_raw != "-" else 0
                except (ValueError, TypeError):
                    issue_pe = 0
                try:
                    issue_price = float(issue_price_raw) if issue_price_raw and issue_price_raw != "-" else 0
                except (ValueError, TypeError):
                    issue_price = 0
                
                # 板块判断
                if code.startswith("688"):
                    market_code = "KC"
                elif code.startswith("30"):
                    market_code = "CY"
                elif code.startswith("92"):
                    market_code = "BJ"
                elif code.startswith("00") or code.startswith("001"):
                    market_code = "SZ"
                else:
                    market_code = "SH"
                
                candidates.append({
                    "code": code,
                    "name": name,
                    "issue_price": round(issue_price, 2) if issue_price > 0 else 0,
                    "issue_pe": round(issue_pe, 2) if issue_pe > 0 else 0,
                    "industry_pe": 0,
                    "lottery_rate": 0,
                    "market_code": market_code,
                    "industry": "",
                    "apply_date": listing_str if not is_unlisted else today_str,
                    "is_unlisted": is_unlisted,
                    "apply_code": code
                })
            
            unlisted = [c for c in candidates if c.get("is_unlisted")]
            listed_new = [c for c in candidates if not c.get("is_unlisted")]
            if unlisted:
                print(f"  ✓ push2: {len(unlisted)} 只待上市新股")
            if listed_new:
                print(f"  ✓ push2: {len(listed_new)} 只近30天上市新股")
    except Exception as e:
        print(f"  ⚠️ push2 API 失败: {e}")
        import traceback
        traceback.print_exc()

    if not candidates:
        print("  ℹ️  未找到可申购/近期上市新股，将输出空数据")
    
    return candidates

def fetch_stock_detail(code, market_code):
    """查询单只股票详情（发行价、PE等）"""
    secid = f"0.{code}" if market_code in ("SZ", "CY") else f"1.{code}"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f9,f18,f100,f115,f162"
    try:
        data = http_get(url)
        info = data.get("data", {})
        return {
            "issue_pe": info.get("f115", 0) or info.get("f9", 0) or 0,
            "issue_price": info.get("f18", 0) or 0,
            "industry_pe": info.get("f100", 0) or info.get("f162", 0) or 0,
        }
    except:
        return {"issue_pe": 0, "issue_price": 0, "industry_pe": 0}

def calculate_scores(candidates, sector_flow):
    """计算每个新股的评分"""
    results = []
    
    for c in candidates:
        issue_pe = c["issue_pe"]
        industry_pe = c["industry_pe"]
        price = c["issue_price"]
        board = board_name(c["market_code"])
        industry = c["industry"] or "待确认"
        
        # 如果行业PE缺失，用发行PE + 板块加成估算
        if industry_pe <= 0 and issue_pe > 0:
            board_pe_add = {"沪市主板": 8, "深市主板": 8, "创业板": 15, "科创板": 20, "北交所": 5}
            industry_pe = issue_pe + board_pe_add.get(board, 10)
        
        # PE折价评分 (0-40)
        if issue_pe > 0 and industry_pe > 0 and industry_pe > issue_pe:
            pe_discount = round((industry_pe - issue_pe) / industry_pe * 100, 1)
            pe_discount = min(pe_discount, 80)  # 封顶80%折价（防止数据异常）
        else:
            pe_discount = 0
        
        pe_score = min(40, max(0, pe_discount * 0.5)) if pe_discount > 0 else 0
        
        # 行业热度评分 (0-25)
        heat_score = score_industry_heat(industry, sector_flow)
        
        # 发行价合理性 (0-20)
        price_score = score_price(price)
        
        # 板块溢价 (0-15)
        board_bonus = board_score(board)
        
        total = round(pe_score + heat_score + price_score + board_bonus)
        
        # 推荐等级
        if total >= 80:
            recommend = "强烈推荐申购"
            tag_color = "#2e7d32"
            bg_color = "#e8f5e9"
        elif total >= 65:
            recommend = "建议申购"
            tag_color = "#e65100"
            bg_color = "#fff3e0"
        elif total >= 50:
            recommend = "谨慎参与"
            tag_color = "#f57f17"
            bg_color = "#fffde7"
        else:
            recommend = "不建议申购"
            tag_color = "#c62828"
            bg_color = "#ffebee"
        
        # 亮点文案（PE折价已在dims行显示，此处不再重复）
        highlights = []
        if c.get("lottery_rate", 0) > 0:
            highlights.append(f"中签率{c['lottery_rate']}%")
        if heat_score >= 20:
            highlights.append("行业热度高")
        if 10 <= price <= 30:
            highlights.append("发行价适中")
        if board in ("沪市主板", "深市主板"):
            highlights.append(f"{board}溢价")
        
        # 首日预估收益
        est_return = 0
        if price > 0 and pe_discount > 0:
            # 粗略估算：按PE折价的一半作为首日涨幅基础
            est_pct = min(pe_discount * 0.6, 44)  # 首个交易日44%涨停板限制
            est_return = round(price * est_pct / 100 * 500, -2)  # 每签500股
        if est_return >= 1000:
            highlights.append(f"首日预估收益{int(est_return):,}+")
        
        results.append({
            "code": c["code"],
            "name": c["name"],
            "apply_code": c.get("apply_code", c["code"]),
            "issue_price": price,
            "issue_pe": round(issue_pe, 1),
            "industry_pe": round(industry_pe, 1),
            "pe_discount": pe_discount,
            "lottery_rate": c.get("lottery_rate", 0),
            "board": board,
            "industry": industry,
            "apply_date": c.get("apply_date", ""),
            "score": total,
            "recommend": recommend,
            "tag_color": tag_color,
            "bg_color": bg_color,
            "highlights": highlights[:3],  # 最多3条
        })
    
    # 按评分降序
    results.sort(key=lambda x: -x["score"])
    return results

def generate_summary(results):
    """生成综合打新判断"""
    if not results:
        return "当前无可申购新股，建议关注后续IPO安排。"
    
    high = sum(1 for r in results if r["score"] >= 80)
    mid = sum(1 for r in results if 65 <= r["score"] < 80)
    low = sum(1 for r in results if r["score"] < 65)
    
    parts = []
    if high > 0:
        parts.append(f"{high}只强烈推荐")
    if mid > 0:
        parts.append(f"{mid}只建议申购")
    if low > 0:
        parts.append(f"{low}只需谨慎参与")
    
    sentiment = "建议积极参与" if high + mid >= 2 else "建议精选参与" if high + mid >= 1 else "建议谨慎观望"
    
    # 主板溢价判断
    main_board = [r for r in results if "主板" in r["board"]]
    if main_board:
        avg_pe_discount = sum(r["pe_discount"] for r in main_board) / len(main_board)
        if avg_pe_discount > 20:
            parts.append("当前主板新股估值优势明显")
            sentiment = "建议积极参与"
    
    return f"{'，'.join(parts)}。{sentiment}。"

def main():
    print("=" * 50)
    print("打新价值评分数据获取")
    print("=" * 50)
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. 获取可申购新股列表
    print("[1/3] 获取可申购新股列表...")
    candidates = fetch_ipo_list()
    print(f"  找到 {len(candidates)} 只可申购/待上市新股")
    
    # 2. 补充发行价、PE和行业PE（对未上市新股逐个查询）
    print("[2/3] 补充发行价和市盈率...")
    for c in candidates:
        if c.get("is_unlisted") or c["issue_price"] <= 0 or c["issue_pe"] <= 0:
            detail = fetch_stock_detail(c["code"], c.get("market_code", "SH"))
            if detail["issue_price"] > 0 and c["issue_price"] <= 0:
                c["issue_price"] = round(detail["issue_price"], 2)
            if detail["issue_pe"] > 0 and c["issue_pe"] <= 0:
                c["issue_pe"] = round(detail["issue_pe"], 2)
            if detail["industry_pe"] > 0:
                # 过滤明显离谱的值（>500 大概率不是PE）
                if detail["industry_pe"] <= 200:
                    c["industry_pe"] = round(detail["industry_pe"], 2)
            # 未上市的新股：用发行价占比估算（部分接口返回）
            if c["issue_price"] <= 0:
                c["issue_price"] = 0  # 标记为未知
            if c["issue_pe"] <= 0:
                c["issue_pe"] = 0
            time.sleep(0.5)  # 避免限流
    
    # 3. 读取板块资金流用于行业热度
    print("[3/3] 读取板块资金流...")
    sector_flow = fetch_sector_flow()
    
    # 计算评分
    results = calculate_scores(candidates, sector_flow)
    summary = generate_summary(results)
    
    # 输出
    ipo_data = {
        "update_time": now,
        "eligible_count": len(results),
        "summary": summary,
        "stocks": results
    }
    
    out_path = os.path.join(DATA_DIR, "ipo_score.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ipo_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 写入 {out_path}")
    print(f"   可申购: {len(results)} 只")
    for r in results:
        print(f"   {'⭐' * (r['score']//20)}{r['score']:3d}分 {r['name']}({r['code']}) — {r['recommend']} | PE折价{r['pe_discount']}% | {r['board']}")
    print(f"\n💡 {summary}")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
