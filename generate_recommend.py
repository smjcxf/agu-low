#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_recommend.py
─────────────────────
从 scan_result.json + watch_result.json 提取三线共振股票，
自动生成 recommend.json，并精确追踪每只股票连续在三线共振中的天数。

运行时机：每次全盘扫描 / 观澜台扫描之后
"""

import json
import os
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SCAN_RESULT = os.path.join(DATA_DIR, "scan_result.json")
WATCH_RESULT = os.path.join(DATA_DIR, "watch_result.json")
RECOMMEND_OUT = os.path.join(DATA_DIR, "recommend.json")
RESONANCE_HIST = os.path.join(DATA_DIR, "resonance_history.json")

# 保留最近 90 天的历史（足够计算连续天数）
MAX_HISTORY_DAYS = 90


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠️  读取失败 {path}: {e}")
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_triple_signals(scan_data, watch_data):
    """从扫描结果中提取所有三线共振股票（去重）"""
    triple_map = {}
    for source_name, source_data in [("scan", scan_data), ("watch", watch_data)]:
        if not source_data:
            continue
        for s in source_data.get("triple_signals", []):
            code = s.get("code", "")
            if not code:
                continue
            # 以最新数据为准，但保留来源信息
            if code not in triple_map:
                triple_map[code] = dict(s)
                triple_map[code]["_sources"] = [source_name]
            else:
                # 合并来源标记
                if source_name not in triple_map[code].get("_sources", []):
                    triple_map[code]["_sources"].append(source_name)
                # 如果新数据评分更高，覆盖
                if s.get("score", 0) > triple_map[code].get("score", 0):
                    triple_map[code].update(s)
    return list(triple_map.values())


def build_recommend_item(stock):
    """将扫描结果转换为 recommend.json 格式"""
    # 计算止损/目标价（基于ATR或固定比例）
    close = stock.get("close", 0)
    pct_chg = stock.get("pct_chg", 0)
    # 简单策略：止损 -7%，目标 +15%
    stop_loss = round(close * 0.93, 2) if close else 0
    target = round(close * 1.15, 2) if close else 0

    # 获取 board / fund_type
    board = stock.get("board_label", stock.get("board", ""))
    if board == "创业板":
        board_tag = "创业板"
    elif board == "科创板":
        board_tag = "科创板"
    elif board == "港股":
        board_tag = "港股"
    else:
        board_tag = "主板"

    # 构建 reasons
    reasons = []
    if stock.get("三线共振"):
        reasons.append("三线共振（缠论买+金钻+机构变红同时触发），胜率最高")
    if stock.get("四量图_机构变红"):
        reasons.append("四量图机构持仓变红，机构中期看多")
    if stock.get("缠论买_日K") or stock.get("缠论买_次数", 0) > 0:
        reasons.append("缠论买字确认局部低点，趋势转折信号")
    if stock.get("上涨趋势"):
        reasons.append("上涨趋势条件满足，均线多头排列")
    if stock.get("金钻_黄柱") or stock.get("金钻_起涨"):
        reasons.append("金钻信号出现，起涨点确认")

    # sources
    sources = stock.get("sources", ["三足鼎立"])
    if not sources:
        sources = ["三足鼎立"]

    return {
        "code": stock.get("code", ""),
        "name": stock.get("name", ""),
        "board": board_tag,
        "fund_type": stock.get("fund_type", "混合"),
        "score": stock.get("score", 0),
        "sig_count": stock.get("signal_count", 0),
        "max_sig": stock.get("max_signal", stock.get("signal_count", 0)),
        "action": "BUY",
        "stop_loss": stop_loss,
        "target": target,
        "close": close,
        "pct_chg": pct_chg,
        "volume_str": stock.get("volume_str", "-"),
        "开盘_标签": stock.get("开盘_标签", "—"),
        "reasons": reasons,
        "sources": sources,
        "days_in_pool": stock.get("days_in_pool", 1),
        "pct20": stock.get("pct_chg_20d", stock.get("pct20", 0)),
        "_raw": stock,  # 保留原始数据，方便调试
    }


def update_resonance_history(triple_codes, today_str):
    """
    更新共振历史记录，返回每只股票的连续共振天数
    """
    history = load_json(RESONANCE_HIST, {"history": {}})
    hist = history.get("history", {})

    # 添加今日记录
    hist[today_str] = sorted(triple_codes)

    # 清理过期记录
    cutoff = (datetime.now() - timedelta(days=MAX_HISTORY_DAYS)).strftime("%Y-%m-%d")
    hist = {k: v for k, v in hist.items() if k >= cutoff}
    history["history"] = hist

    # 计算每只股票的连续共振天数
    days_map = {}
    sorted_dates = sorted(hist.keys())
    for code in triple_codes:
        # 从今天往前数，连续出现在三线共振中的天数
        consecutive = 0
        for d in reversed(sorted_dates):
            if code in hist.get(d, []):
                consecutive += 1
            else:
                break
        days_map[code] = consecutive

    save_json(RESONANCE_HIST, history)
    return days_map


def main():
    today_str = datetime.now().strftime("%Y-%m-%d")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  生成 强烈关注推荐")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # 读取扫描结果
    scan_data = load_json(SCAN_RESULT, {})
    watch_data = load_json(WATCH_RESULT, {})

    # 提取三线共振
    triple_list = extract_triple_signals(scan_data, watch_data)
    print(f"\n📊 三线共振股票: {len(triple_list)} 只")
    for s in triple_list:
        print(f"  • {s.get('code')} {s.get('name')} 评分:{s.get('score',0)}")

    if not triple_list:
        # 没有三线共振，输出空数组
        save_json(RECOMMEND_OUT, [])
        print("\n⚠️  当前无三线共振股票，recommend.json 已清空")
        return

    # 更新共振历史并计算连续天数
    triple_codes = [s["code"] for s in triple_list if s.get("code")]
    days_map = update_resonance_history(triple_codes, today_str)

    # 构建推荐列表
    recommend = []
    for stock in triple_list:
        item = build_recommend_item(stock)
        item["days_in_resonance"] = days_map.get(item["code"], 1)
        recommend.append(item)

    # 排序：连续共振天数降序 → 评分降序 → 涨跌幅降序
    recommend.sort(key=lambda x: (
        -x.get("days_in_resonance", 0),
        -x.get("score", 0),
        -abs(x.get("pct_chg", 0)),
    ))

    # 打印排序结果
    print("\n📋 推荐排序:")
    for i, r in enumerate(recommend, 1):
        print(f"  #{i} {r['code']} {r['name']} "
              f"共振{r['days_in_resonance']}天 评分{r['score']} "
              f"涨幅{r['pct_chg']:+.2f}%")

    # 保存
    save_json(RECOMMEND_OUT, recommend)
    print(f"\n✅ 已保存: {RECOMMEND_OUT} ({len(recommend)} 只)")


if __name__ == "__main__":
    main()
