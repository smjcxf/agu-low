#!/usr/bin/env python3
"""
generate_top10.py — 多维共振评分 + 每日TOP10精选
- 从 gold_pool.json 读取所有金股池股票
- 结合多维度数据（板块资金/龙虎榜/主力/北向/投行/分析师）计算综合共振评分
- 输出 data/top10_daily.json（TOP20 + 评分明细）
"""
import json
import os
import sys
from datetime import datetime

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(WORKSPACE, "data")
OUTPUT = os.path.join(DATA_DIR, "top10_daily.json")


def load_json(path, default=None):
    """安全加载JSON"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def main():
    print("=" * 60)
    print(f"  多维共振评分 · 每日TOP20精选  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── 1. 加载金股池 ──
    gold_pool = load_json(os.path.join(DATA_DIR, "gold_pool.json"), {"stocks": {}})
    gp_stocks = gold_pool.get("stocks", {})
    if not gp_stocks:
        print("  ⚠️  金股池为空，跳过")
        print(f"\n  结果: 跳过 (金股池为空)")
        return
    print(f"  📊 金股池: {len(gp_stocks)} 只")

    # ── 2. 加载辅助数据 ──
    sector_flow = load_json(os.path.join(DATA_DIR, "sector_fund_flow.json"), {})
    lhb_data = load_json(os.path.join(DATA_DIR, "lhb_result.json"), {})
    main_stock = load_json(os.path.join(DATA_DIR, "main_stock.json"), {})
    north_fund = load_json(os.path.join(DATA_DIR, "north_fund.json"), {})
    mahoro = load_json(os.path.join(DATA_DIR, "mahoro_signals.json"), {})
    w52_high = load_json(os.path.join(DATA_DIR, "52w_high.json"), {})
    analyst = load_json(os.path.join(DATA_DIR, "analyst_ratings.json"), {})
    industry_map = load_json(os.path.join(DATA_DIR, "industry_map.json"), {})

    # ── 3. 构建辅助查询映射 ──
    # 板块资金：板块名→净流入(亿)
    sector_flow_in = {}
    for s in sector_flow.get("sectors_in", []):
        sector_flow_in[s.get("name", "")] = s.get("net", 0)

    # 龙虎榜：code→inst_net_万
    lhb_map = {}
    for s in lhb_data.get("stocks", []):
        code = s.get("code", "")
        if code:
            lhb_map[code] = {
                "inst_net": s.get("inst_net_万", 0),
                "category": s.get("category", ""),
            }

    # 主力：code→net
    main_map = {}
    for s in main_stock.get("top_main_in", []):
        main_map[s.get("code", "")] = s.get("net", 0)
    for s in main_stock.get("top_main_out", []):
        code = s.get("code", "")
        if code not in main_map:
            main_map[code] = s.get("net", 0)

    # 投行覆盖：code→stance
    mahoro_map = {}
    for m in mahoro.get("gold_pool_matches", []):
        mahoro_map[m.get("code", "")] = m.get("stance", "")

    # 52周新高 (按名称粗略匹配)
    w52_names = set()
    for s in w52_high.get("stocks", []):
        w52_names.add(s.get("name", ""))

    # 分析师转向 (按名称)
    analyst_names = set()
    for a in analyst.get("upgrades", []):
        analyst_names.add(a.get("name", ""))

    # 行业映射：code→[sector_names]
    ind_map = {}
    im_stocks = industry_map.get("stocks", {})
    if isinstance(im_stocks, dict):
        for code_key, sectors in im_stocks.items():
            # normalize code
            clean = code_key.replace("sh_", "").replace("sz_", "").replace("hk_", "").replace("bj_", "")
            ind_map[clean] = sectors if isinstance(sectors, list) else sectors.get("sectors", [])

    # ── 4. 计算多维共振评分 ──
    scored = []
    for key, s in gp_stocks.items():
        hist = s.get("history", [])
        latest = hist[-1] if hist else {}
        if isinstance(latest, dict) and "latest" in latest:
            latest = latest["latest"]

        name = s.get("name", "")
        code = s.get("code", "")
        raw_code = code or key.replace("sz_", "").replace("sh_", "").replace("hk_", "")

        # 基础信号 (0-100)
        has_chan = bool(latest.get("缠论买_日K"))
        has_qizhang = bool(latest.get("金钻_起涨"))
        has_huangzhu = bool(latest.get("金钻_黄柱"))
        has_jigou = bool(latest.get("四量图_机构变红"))
        has_trend = bool(latest.get("上涨趋势"))
        sig_count = sum([has_chan, has_qizhang or has_huangzhu, has_jigou, has_trend])

        base = 0
        if has_chan:
            base += 25
        if has_qizhang or has_huangzhu:
            base += 25
        if has_jigou:
            base += 25
        if has_trend:
            base += 25
        if has_chan and has_qizhang:
            base += 10
        elif has_chan and has_huangzhu:
            base += 5

        # 增强因子 (-10 ~ +13)
        enhance = 0
        pct20 = latest.get("pct_chg_20d") or s.get("pct_chg_20d") or 0
        if pct20 >= 50:
            enhance -= 5
        elif pct20 >= 35:
            enhance += 5
        elif pct20 >= 20:
            enhance += 3

        rsi = latest.get("rsi_14") or s.get("rsi_14") or 50
        if rsi > 70:
            enhance -= 5
        elif rsi < 30:
            enhance += 3

        # 连续共振天数
        consecutive = 0
        sorted_hist = sorted(hist, key=lambda h: h.get("date", ""), reverse=True)
        for h in sorted_hist:
            h_sig = sum([
                bool(h.get("缠论买_日K")),
                bool(h.get("金钻_起涨") or h.get("金钻_黄柱")),
                bool(h.get("四量图_机构变红")),
                bool(h.get("上涨趋势")),
            ])
            if h_sig >= 3:
                consecutive += 1
            else:
                break
        enhance += min(consecutive * 2, 8)

        # 资金动力 (0 ~ +15)
        fund = 0
        fund_detail = []

        # 主力
        main_net = main_map.get(raw_code, 0)
        if main_net > 1000:
            fund += 5
            fund_detail.append(f"主力+{main_net:.0f}万")
        elif main_net > 0:
            fund += 2
            fund_detail.append(f"主力+{main_net:.0f}万")

        # 龙虎榜
        lhb_info = lhb_map.get(raw_code)
        if lhb_info and lhb_info["category"] == "纯共振":
            fund += 5
            fund_detail.append(f"龙虎榜纯共振")
        elif lhb_info and lhb_info["inst_net"] > 0:
            fund += 3
            fund_detail.append(f"龙虎榜+{lhb_info['inst_net']:.0f}万")

        # 北向资金：2024年5月起港交所不再披露明细，仅data_date空壳，不再加分
        # 铁律：宁可空着也不用假数据

        # 板块共振 (0 ~ +10)
        sector_score = 0
        sector_detail = ""
        stock_sectors = ind_map.get(raw_code, []) or s.get("sectors", [])
        if isinstance(stock_sectors, dict):
            # industry_map 格式可能是 {sector_name: ...}
            stock_sectors = list(stock_sectors.keys()) if isinstance(stock_sectors, dict) else []
        elif isinstance(stock_sectors, str):
            stock_sectors = [stock_sectors]

        sector = s.get("sector", "")
        if sector and sector not in stock_sectors:
            stock_sectors = [sector] + stock_sectors

        best_sector_flow = 0
        best_sector_name = ""
        for sec_name in stock_sectors:
            flow = sector_flow_in.get(sec_name, 0)
            if flow > best_sector_flow:
                best_sector_flow = flow
                best_sector_name = sec_name

        if best_sector_flow > 5:
            sector_score += 5
            sector_detail = f"{best_sector_name}+{best_sector_flow:.1f}亿"
        elif best_sector_flow > 1:
            sector_score += 2
            sector_detail = f"{best_sector_name}+{best_sector_flow:.1f}亿"
        elif best_sector_flow < -5:
            sector_score -= 3
            sector_detail = f"{best_sector_name}{best_sector_flow:.1f}亿"

        # 机构/投行 (0 ~ +10)
        inst = 0
        inst_detail = []

        stance = mahoro_map.get(raw_code, "")
        if stance == "bullish":
            inst += 3
            inst_detail.append("投行看多")
        elif stance in ("neutral", "mixed"):
            inst += 1
            inst_detail.append("投行关注")

        if name in w52_names:
            inst += 4
            inst_detail.append("52周新高")

        if name in analyst_names:
            inst += 3
            analyst_detail_name = name  # just use name
            inst_detail.append("分析师转向")

        # ── 止损位 / 目标价 ──
        close_price = latest.get("close") or s.get("close") or 0
        # 近5日最低/最高收盘价（用于辅助计算）
        recent_closes = []
        sorted_hist_all = sorted(hist, key=lambda h: h.get("date", ""), reverse=False)
        for h in sorted_hist_all:
            hc = h.get("close", 0)
            if hc and hc > 0:
                recent_closes.append(hc)
        recent5 = recent_closes[-5:] if len(recent_closes) >= 5 else recent_closes
        recent20 = recent_closes[-20:] if len(recent_closes) >= 20 else recent_closes

        if close_price and close_price > 0:
            # 止损 = 收盘价×0.93 与 近5日最低价 取更紧者
            pct_stop = round(close_price * 0.93, 2)
            low5 = round(min(recent5), 2) if recent5 else pct_stop
            stop_loss = min(pct_stop, low5)
            # 目标 = 收盘价×1.12 与 近20日最高价 取更高者
            pct_target = round(close_price * 1.12, 2)
            high20 = round(max(recent20), 2) if recent20 else pct_target
            target_price = max(pct_target, high20)
        else:
            stop_loss = 0
            target_price = 0

        # ── 总分 ──
        total = base + enhance + fund + sector_score + inst

        scored.append({
            "code": raw_code,
            "full_code": key,
            "name": name,
            "market": s.get("market", ""),
            "board": s.get("board_label", ""),
            "sig_count": sig_count,
            "close": latest.get("close") or s.get("close") or 0,
            "pct_chg": latest.get("pct_chg") or s.get("pct_chg") or 0,
            "pct_chg_20d": pct20 or 0,
            "total_score": total,
            "sectors": stock_sectors[:8] if isinstance(stock_sectors, list) else [],
            "stop_loss": stop_loss,
            "target_price": target_price,
            "breakdown": {
                "base": base,
                "enhance": enhance,
                "fund": fund,
                "sector": sector_score,
                "inst": inst,
                "signals": {
                    "chan": has_chan,
                    "jinzuan": has_qizhang or has_huangzhu,
                    "jigou": has_jigou,
                    "trend": has_trend,
                },
            },
            "details": {
                "consecutive_days": consecutive,
                "fund": " | ".join(fund_detail) if fund_detail else "",
                "sector": sector_detail,
                "inst": " | ".join(inst_detail) if inst_detail else "",
            },
        })

    # ── 5. 排序取TOP20 ──
    scored.sort(key=lambda x: -x["total_score"])

    # 格式化为简洁输出（含完整评分明细）
    top10 = []
    for i, s in enumerate(scored[:20]):
        bd = s["breakdown"]
        dt = s["details"]
        top10.append({
            "rank": i + 1,
            "code": s["code"],
            "name": s["name"],
            "market": s["market"],
            "board": s["board"],
            "sig_count": s["sig_count"],
            "close": s["close"],
            "pct_chg": s["pct_chg"],
            "pct_chg_20d": s["pct_chg_20d"],
            "total_score": s["total_score"],
            "sectors": s["sectors"],
            "stop_loss": s["stop_loss"],
            "target_price": s["target_price"],
            "score_base": bd["base"],
            "score_enhance": bd["enhance"],
            "score_fund": bd["fund"],
            "score_sector": bd["sector"],
            "score_inst": bd["inst"],
            "signals": bd["signals"],
            "consecutive_days": dt["consecutive_days"],
            "fund_detail": dt["fund"],
            "sector_detail": dt["sector"],
            "inst_detail": dt["inst"],
        })

    count_80plus = sum(1 for s in scored if s.get("total_score", 0) >= 80)
    result = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_scored": len(scored),
        "count_80plus": count_80plus,
        "top10": top10,
    }

    # 保存
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  ✅ TOP10 已生成: {len(top10)} 只")
    for t in top10:
        print(f"     #{t['rank']} {t['name']}({t['code']}) 评分{t['total_score']} "
              f"基础{t['score_base']}+增强{t['score_enhance']}+资金{t['score_fund']}+"
              f"板块{t['score_sector']}+机构{t['score_inst']}")
    print(f"  总评分: {len(scored)} 只")
    print(f"\n  输出: {OUTPUT}")
    print(f"\n  结果: ✓ 成功 ({datetime.now().strftime('%H:%M:%S')})")


if __name__ == "__main__":
    main()
