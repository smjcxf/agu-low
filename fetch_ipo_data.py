#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打新价值评分数据获取 —— 支持申购期/上市首日/上市后追踪
用法: python fetch_ipo_data.py
输出: data/ipo_score.json

状态分类:
  - applying: 待申购（显示评分+建议申购等级）
  - listed_today: 今日上市（显示首日表现）
  - tracking: 上市后5日内追踪（显示是否值得追入）
  - 超5天: 隐藏

数据源:
  1. 东方财富 push2 API — 新股申购/上市列表
  2. 东方财富行情 API — 实时行情（收盘价、涨幅、换手率）
"""
import json
import os
import sys
import time
import subprocess
from datetime import datetime, date, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

def http_get(url, retry=3):
    """HTTP GET using curl subprocess"""
    last_err = None
    for i in range(retry):
        try:
            if i > 0:
                time.sleep(3 * i)
            result = subprocess.run([
                "curl", "-s", "--max-time", "20",
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "-H", "Referer: https://data.eastmoney.com/xg/xg/",
                "-H", "Accept: application/json, text/html, */*",
                url
            ], capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                err_msg = result.stderr[:200] or f"exit={result.returncode}"
                raise ConnectionError(f"curl {err_msg}")
            if not result.stdout or not result.stdout.strip():
                raise ValueError("Empty response")
            return json.loads(result.stdout)
        except Exception as e:
            last_err = e
    raise last_err

def board_name(market_code):
    m = {"SH": "沪市主板", "SZ": "深市主板", "CY": "创业板", "KC": "科创板", "BJ": "北交所"}
    return m.get(market_code, "其他")

def board_score(board):
    s = {"沪市主板": 15, "深市主板": 14, "创业板": 12, "科创板": 10, "北交所": 8}
    return s.get(board, 8)

def score_price(price):
    if not price or price <= 0:
        return 10
    if price <= 5: return 12
    if price <= 15: return 20
    if price <= 30: return 18
    if price <= 50: return 14
    if price <= 80: return 8
    return 4

def fetch_apply_dates_from_calendar():
    """从东方财富新股申购日历获取真实申购日期"""
    result = {}
    try:
        raw = subprocess.run(
            ["curl", "-s", "--max-time", "15",
             "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
             "https://data.eastmoney.com/xg/xg/calendar.html"],
            capture_output=True, text=True, timeout=20
        )
        if raw.returncode == 0 and raw.stdout.strip():
            import re
            html = raw.stdout
            json_pattern = re.compile(
                r'\{"SECUCODE":"[^"]+","TRADE_DATE":"([^"]+)","DATE_TYPE":"([^"]+)"'
                r',"SECURITY_CODE":"(\d{6})","SECURITY_NAME_ABBR":"([^"]+)"[^}]*\}'
            )
            matches = json_pattern.findall(html)
            for trade_date, date_type, code, name in matches:
                if date_type != "申购":
                    continue
                apply_date = trade_date.split(" ")[0].replace("-", "")
                if code and apply_date and len(apply_date) >= 8:
                    result[code] = apply_date
            if result:
                return result
    except Exception as e:
        print(f"  ⚠️ 日历抓取失败: {e}")
    return result

def fetch_realtime_quote(code, market_code):
    """获取实时行情：收盘价、涨幅、换手率"""
    secid = f"0.{code}" if market_code in ("SZ", "CY") else f"1.{code}"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f170,f168"
    try:
        data = http_get(url)
        info = data.get("data", {})
        # f43=最新价, f44=最高价, f45=最低价, f46=开盘价, f47=成交量, f48=成交额
        # f57=代码, f58=名称, f60=昨收, f170=涨幅, f168=换手率
        latest = info.get("f43", 0) or 0
        open_price = info.get("f46", 0) or 0
        prev_close = info.get("f60", 0) or 0
        change_pct = info.get("f170", 0) or 0
        turnover = info.get("f168", 0) or 0
        return {
            "latest": float(latest) / 100 if latest else 0,  # 注意：有些接口需要除以100
            "open_price": float(open_price) / 100 if open_price else 0,
            "prev_close": float(prev_close) / 100 if prev_close else 0,
            "change_pct": float(change_pct) / 100 if change_pct else 0,
            "turnover": float(turnover) / 100 if turnover else 0,
        }
    except Exception as e:
        print(f"    ⚠️ {code} 行情获取失败: {e}")
        return None

def classify_status(listing_str, today_str):
    """判断新股状态"""
    if listing_str in ("-", "", "None", None):
        return "applying", None
    try:
        listing_int = int(listing_str)
        today_int = int(today_str)
        if listing_int == today_int:
            return "listed_today", listing_int
        elif today_int - listing_int <= 5:
            return "tracking", listing_int
        else:
            return "expired", listing_int
    except:
        return "applying", None

def tracking_advice(issue_price, latest_price, change_pct, turnover):
    """上市后追踪建议：是否值得追入"""
    if not issue_price or issue_price <= 0 or not latest_price or latest_price <= 0:
        return "数据不足，无法判断", "#999", "#f5f5f5"
    
    total_return = (latest_price - issue_price) / issue_price * 100
    
    # 判断逻辑
    if total_return > 50 and change_pct > 5:
        return "🔴 强势上涨，可考虑追入", "#c62828", "#ffebee"
    elif total_return > 20 and change_pct > 0:
        return "🟡 表现良好，观望等回调", "#e65100", "#fff3e0"
    elif total_return > 0 and change_pct > -3:
        return "🟠 温和上涨，可小仓位", "#f57f17", "#fffde7"
    elif total_return < 0 or change_pct < -5:
        return "🟢 已破发或走弱，不建议追", "#2e7d32", "#e8f5e9"
    else:
        return "⚪ 震荡，建议观望", "#888", "#f5f5f5"

def fetch_ipo_list():
    """获取新股列表并分类"""
    candidates = []
    today_str = datetime.now().strftime("%Y%m%d")
    
    # push2 API: 获取按上市日期排序的新股
    url1 = ("https://push2.eastmoney.com/api/qt/clist/get?"
            "fid=f26&po=0&pz=30&pn=1&np=1&fltt=2&invt=2"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
            "&fields=f12,f14,f18,f26,f115")
    
    try:
        data = http_get(url1)
        stocks = data.get("data", {}).get("diff", [])
        apply_date_map = fetch_apply_dates_from_calendar()
        
        for s in stocks:
            code = s.get("f12", "")
            name = s.get("f14", "")
            if not code or not name:
                continue
            
            f26_raw = s.get("f26", "")
            listing_str = str(f26_raw) if f26_raw else ""
            
            status, listing_int = classify_status(listing_str, today_str)
            if status == "expired":
                continue
            
            # 提取PE和价格
            issue_pe_raw = s.get("f115", 0)
            issue_price_raw = s.get("f18", 0)
            try:
                issue_pe = float(issue_pe_raw) if issue_pe_raw and issue_pe_raw != "-" else 0
            except:
                issue_pe = 0
            try:
                issue_price = float(issue_price_raw) if issue_price_raw and issue_price_raw != "-" else 0
            except:
                issue_price = 0
            
            # 板块判断
            if code.startswith("688"): market_code = "KC"
            elif code.startswith("30"): market_code = "CY"
            elif code.startswith("92"): market_code = "BJ"
            elif code.startswith("00") or code.startswith("001"): market_code = "SZ"
            else: market_code = "SH"
            
            candidates.append({
                "code": code,
                "name": name,
                "issue_price": round(issue_price, 2) if issue_price > 0 else 0,
                "issue_pe": round(issue_pe, 2) if issue_pe > 0 else 0,
                "market_code": market_code,
                "apply_date": apply_date_map.get(code, ""),
                "listing_date": str(listing_int) if listing_int else "",
                "status": status,
            })
        
        print(f"  ✓ push2: {len(candidates)} 只新股（待申购+上市+追踪）")
    except Exception as e:
        print(f"  ⚠️ push2 API 失败: {e}")
    
    return candidates

def calculate_applying_scores(candidates):
    """计算待申购新股的评分"""
    results = []
    for c in candidates:
        if c["status"] != "applying":
            continue
        
        issue_pe = c["issue_pe"]
        price = c["issue_price"]
        board = board_name(c["market_code"])
        
        # 估算行业PE（发行PE + 板块加成）
        board_pe_add = {"沪市主板": 8, "深市主板": 8, "创业板": 15, "科创板": 20, "北交所": 5}
        industry_pe = issue_pe + board_pe_add.get(board, 10) if issue_pe > 0 else 20
        
        # PE折价评分
        if issue_pe > 0 and industry_pe > 0 and industry_pe > issue_pe:
            pe_discount = round((industry_pe - issue_pe) / industry_pe * 100, 1)
            pe_discount = min(pe_discount, 80)
        else:
            pe_discount = 0
        pe_score = min(40, max(0, pe_discount * 0.5)) if pe_discount > 0 else 0
        
        # 发行价合理性
        price_score = score_price(price)
        # 板块溢价
        board_bonus = board_score(board)
        # 行业热度（默认中等）
        heat_score = 15
        
        total = round(pe_score + heat_score + price_score + board_bonus)
        
        if total >= 80:
            recommend, tag_color, bg_color = "强烈推荐申购", "#2e7d32", "#e8f5e9"
        elif total >= 65:
            recommend, tag_color, bg_color = "建议申购", "#e65100", "#fff3e0"
        elif total >= 50:
            recommend, tag_color, bg_color = "谨慎参与", "#f57f17", "#fffde7"
        else:
            recommend, tag_color, bg_color = "不建议申购", "#c62828", "#ffebee"
        
        highlights = []
        if 10 <= price <= 30:
            highlights.append(f"发行价¥{price}适中")
        if pe_discount > 20:
            highlights.append(f"PE折价{pe_discount}%")
        if board in ("沪市主板", "深市主板"):
            highlights.append(f"{board}溢价")
        
        results.append({
            "code": c["code"], "name": c["name"],
            "issue_price": price, "issue_pe": issue_pe,
            "industry_pe": round(industry_pe, 1), "pe_discount": pe_discount,
            "board": board, "apply_date": c["apply_date"],
            "listing_date": c["listing_date"],
            "score": total, "recommend": recommend,
            "tag_color": tag_color, "bg_color": bg_color,
            "highlights": highlights[:3],
            "status": "applying",
        })
    results.sort(key=lambda x: -x["score"])
    return results

def process_listed_and_tracking(candidates):
    """处理已上市新股：抓取行情并生成建议"""
    results = []
    for c in candidates:
        if c["status"] not in ("listed_today", "tracking"):
            continue
        
        quote = fetch_realtime_quote(c["code"], c["market_code"])
        if not quote:
            continue
        
        issue_price = c["issue_price"]
        latest = quote["latest"]
        open_price = quote["open_price"]
        change_pct = quote["change_pct"]
        turnover = quote["turnover"]
        
        # 计算首日/累计收益率
        if issue_price > 0:
            total_return = round((latest - issue_price) / issue_price * 100, 2)
            open_return = round((open_price - issue_price) / issue_price * 100, 2) if open_price > 0 else 0
        else:
            total_return = 0
            open_return = 0
        
        if c["status"] == "listed_today":
            # 上市首日：展示首日表现
            recommend = "上市首日"
            tag_color = "#1565c0"
            bg_color = "#e3f2fd"
            highlights = []
            if open_return > 0:
                highlights.append(f"首日开盘涨{open_return}%→{open_price}")
            if total_return > 0:
                highlights.append(f"当前涨{total_return}%")
            if turnover > 0:
                highlights.append(f"换手率{turnover}%")
        else:
            # 上市后追踪：给出是否值得追入建议
            advise, tag_color, bg_color = tracking_advice(issue_price, latest, change_pct, turnover)
            recommend = advise
            highlights = []
            if total_return > 0:
                highlights.append(f"较发行价+{total_return}%")
            elif total_return < 0:
                highlights.append(f"已破发{abs(total_return)}%")
            if turnover > 0:
                highlights.append(f"换手率{turnover}%")
        
        results.append({
            "code": c["code"], "name": c["name"],
            "issue_price": issue_price,
            "latest_price": latest,
            "open_price": open_price,
            "change_pct": change_pct,
            "turnover": turnover,
            "total_return": total_return,
            "open_return": open_return,
            "board": board_name(c["market_code"]),
            "listing_date": c["listing_date"],
            "score": 0,  # 上市后不评分
            "recommend": recommend,
            "tag_color": tag_color, "bg_color": bg_color,
            "highlights": highlights[:3],
            "status": c["status"],
        })
    return results

def generate_summary(applying, listed, tracking):
    """生成综合打新判断"""
    parts = []
    if applying:
        high = sum(1 for r in applying if r["score"] >= 80)
        mid = sum(1 for r in applying if 65 <= r["score"] < 80)
        if high > 0: parts.append(f"{high}只强烈推荐申购")
        if mid > 0: parts.append(f"{mid}只建议申购")
        if not parts: parts.append(f"{len(applying)}只谨慎参与")
    
    if listed:
        parts.append(f"今日{len(listed)}只上市")
    
    if tracking:
        strong = sum(1 for r in tracking if r["total_return"] > 20)
        if strong > 0: parts.append(f"{strong}只上市后表现强势")
    
    if not parts:
        return "当前无可关注新股，建议关注后续IPO安排。"
    
    return f"{'，'.join(parts)}。"

def main():
    print("=" * 50)
    print("打新价值评分数据获取（申购+上市+追踪）")
    print("=" * 50)
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. 获取新股列表
    print("[1/4] 获取新股列表...")
    candidates = fetch_ipo_list()
    
    applying_list = [c for c in candidates if c["status"] == "applying"]
    listed_list = [c for c in candidates if c["status"] == "listed_today"]
    tracking_list = [c for c in candidates if c["status"] == "tracking"]
    
    print(f"  待申购: {len(applying_list)}, 今日上市: {len(listed_list)}, 追踪中: {len(tracking_list)}")
    
    # 2. 补充待申购新股的详细数据
    print("[2/4] 补充待申购新股详情...")
    for c in applying_list:
        if c["issue_price"] <= 0 or c["issue_pe"] <= 0:
            detail = fetch_realtime_quote(c["code"], c["market_code"])
            if detail and detail.get("prev_close") > 0 and c["issue_price"] <= 0:
                c["issue_price"] = round(detail["prev_close"], 2)
            time.sleep(0.3)
    
    # 3. 计算待申购评分
    print("[3/4] 计算待申购评分...")
    applying_results = calculate_applying_scores(applying_list)
    
    # 4. 处理已上市/追踪中的新股
    print("[4/4] 获取已上市新股行情...")
    listed_results = process_listed_and_tracking(listed_list)
    tracking_results = process_listed_and_tracking(tracking_list)
    
    # 合并所有结果
    all_results = applying_results + listed_results + tracking_results
    
    summary = generate_summary(applying_results, listed_results, tracking_results)
    
    ipo_data = {
        "update_time": now,
        "eligible_count": len(applying_results),
        "listed_count": len(listed_results),
        "tracking_count": len(tracking_results),
        "summary": summary,
        "stocks": all_results,
    }
    
    out_path = os.path.join(DATA_DIR, "ipo_score.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ipo_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 写入 {out_path}")
    print(f"   待申购: {len(applying_results)} 只, 上市首日: {len(listed_results)}, 追踪中: {len(tracking_results)}")
    for r in applying_results:
        print(f"   {'⭐' * (r['score']//20)}{r['score']:3d}分 {r['name']}({r['code']}) — {r['recommend']} | {r['board']}")
    for r in listed_results:
        print(f"   📈 {r['name']}({r['code']}) — 首日涨{r['total_return']:.1f}% | 开盘{r['open_return']:.1f}%")
    for r in tracking_results:
        print(f"   📊 {r['name']}({r['code']}) — {r['recommend']} | 较发行{r['total_return']:+.1f}%")
    print(f"\n💡 {summary}")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
