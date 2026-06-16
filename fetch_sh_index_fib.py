#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上证指数 / 深证成指 斐波那契时间窗口监控 v2.0
新功能: 窗口日追踪 → 反转确认 → 自动推算下一轮周期

用法:
  python fetch_sh_index_fib.py
"""

import json, os, sys
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SH_OUT = os.path.join(DATA_DIR, "sh_index_fib.json")
SZ_OUT = os.path.join(DATA_DIR, "sz_index_fib.json")

# Fib 时间窗口（手动维护，窗口日过后自动追踪反转）
SH_FIB_WINDOWS = [
    {"name": "F(3)",  "date": "2026-05-19", "desc": "小反弹窗口"},
    {"name": "F(5)",  "date": "2026-05-21", "desc": "短期变盘"},
    {"name": "F(8)",  "date": "2026-05-26", "desc": "8日变盘"},
    {"name": "F(13)", "date": "2026-06-02", "desc": "13日重要窗口"},
    {"name": "F(21)", "date": "2026-06-12", "desc": "21日大窗口 · SpaceX IPO日"},
    {"name": "F(34)", "date": "2026-07-02", "desc": "34日中期窗口"},
    {"name": "F(55)", "date": "2026-07-31", "desc": "55日长期窗口"},
]
SZ_FIB_WINDOWS = SH_FIB_WINDOWS

def fetch_index_history(symbol, days=120):
    """获取指数历史K线（baostock）"""
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code != '0':
            return []
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        rs = bs.query_history_k_data_plus(
            symbol, 'date,open,high,low,close,volume,preclose,pctChg',
            start_date=start_date, end_date=end_date, frequency='d'
        )
        data = []
        while rs.next():
            row = rs.get_row_data()
            try:
                data.append({
                    'date': row[0], 'open': float(row[1]), 'high': float(row[2]),
                    'low': float(row[3]), 'close': float(row[4]),
                    'volume': float(row[5]), 'preclose': float(row[6]), 'pctChg': float(row[7]),
                })
            except (ValueError, IndexError):
                continue
        bs.logout()
        return data
    except Exception as e:
        print(f"  ⚠️ baostock失败: {e}")
        return []

def get_index_on_date(history, target_date):
    """在K线中找目标日期（±2天容差）"""
    target = datetime.strptime(target_date, "%Y-%m-%d")
    for d in history:
        try:
            dd = datetime.strptime(d['date'], "%Y-%m-%d")
            if abs((dd - target).days) <= 2:
                return d
        except:
            continue
    return None

def check_reversal(history, window_date):
    """检查窗口日后是否形成有效反转"""
    win_idx = None
    for i, d in enumerate(history):
        if d['date'] >= window_date:
            win_idx = i
            break
    if win_idx is None or win_idx + 3 >= len(history):
        return {"reversal": "tracking", "note": "追踪中(数据不足)"}
    
    after = history[win_idx:win_idx+6]
    win_bar = after[0]
    current = after[-1]
    
    # 最低点
    lows = [win_bar['low']] + [b['low'] for b in after[1:]]
    min_low = min(lows)
    rebound = (current['close'] - min_low) / min_low * 100 if min_low > 0 else 0
    change = (current['close'] - win_bar['close']) / win_bar['close'] * 100
    
    if rebound > 2 and current['close'] > current.get('open', 0):
        return {"reversal": "confirmed", "verified": True,
                "note": f"反弹{rebound:.1f}%，反转确认",
                "rebound_pct": round(rebound,1), "change_pct": round(change,1),
                "low_point": round(min_low,2)}
    elif change > 0:
        return {"reversal": "tracking", "verified": False,
                "note": f"追踪中(涨{change:.1f}%，待确认)",
                "rebound_pct": round(rebound,1), "change_pct": round(change,1)}
    else:
        return {"reversal": "none", "verified": False,
                "note": f"未触发(仍跌{abs(change):.1f}%)",
                "change_pct": round(change,1)}

def build_windows(windows, history, today_str):
    """构建带追踪状态的窗口"""
    result = []
    reversal_date = None
    for w in windows:
        wd = w["date"]
        try:
            days_left = (datetime.strptime(wd, "%Y-%m-%d") - datetime.strptime(today_str, "%Y-%m-%d")).days
        except:
            days_left = 999
        
        entry = {"name": w["name"], "date": wd, "desc": w.get("desc",""), "days_left": days_left}
        
        if days_left > 3:
            entry["status"] = "future"
        elif days_left >= -1:
            entry["status"] = "active"
        else:
            bar = get_index_on_date(history, wd)
            if bar:
                rev = check_reversal(history, wd)
                entry["observation"] = {
                    "index": round(bar['close'],2),
                    "change_pct": round(bar.get('pctChg',0),2),
                    "volume_yi": round(bar.get('volume',0)/1e8, 1),
                }
                entry["observation"].update(rev)
                if rev["reversal"] == "confirmed":
                    entry["status"] = "triggered"
                    reversal_date = wd
                elif rev["reversal"] == "tracking":
                    entry["status"] = "tracking"
                else:
                    entry["status"] = "missed"
            else:
                entry["status"] = "passed"
        result.append(entry)
    return result, reversal_date

def calc_next_cycle(anchor_date, today_str):
    """推算下一轮周期"""
    weeks = datetime.strptime(today_str, "%Y-%m-%d") - datetime.strptime(anchor_date, "%Y-%m-%d")
    if weeks.days <= 0:
        return []
    fibs = [3, 5, 8, 13, 21, 34, 55]
    next_wins = []
    anchor = datetime.strptime(anchor_date, "%Y-%m-%d")
    for n in fibs:
        d = anchor + timedelta(days=int(n*1.4))
        while d.weekday() >= 5:
            d += timedelta(days=1)
        ds = d.strftime("%Y-%m-%d")
        if ds > today_str:
            next_wins.append({"name": f"F({n})", "date": ds, "desc": f"下轮{n}日"})
    return next_wins

def fetch_realtime():
    """获取实时行情"""
    try:
        import akshare as ak
        df = ak.stock_zh_index_spot_em()
        sh = df[df['代码'] == '000001']
        sz = df[df['代码'] == '399001']
        sh_d, sz_d = {}, {}
        if not sh.empty:
            r = sh.iloc[0]
            sh_d = {"index": float(r['最新价']), "change_pct": float(r['涨跌幅']),
                    "change_points": float(r['涨跌额'])}
        if not sz.empty:
            r = sz.iloc[0]
            sz_d = {"index": float(r['最新价']), "change_pct": float(r['涨跌幅']),
                    "change_points": float(r['涨跌额'])}
        return sh_d, sz_d
    except:
        return {}, {}

def calc_down_stats(history):
    if not history or len(history) < 5:
        return {"days_down":0,"total_pct":0,"total_points":0,"avg_pct":0,"peak_date":"","peak_close":0,"current_close":0}
    recent = history[-60:]
    pk, pc = 0, recent[0]['close']
    for i,d in enumerate(recent):
        if d['close'] > pc: pk, pc = i, d['close']
    peak_date = recent[pk]['date']
    cur = recent[-1]
    days_down = len(recent) - pk
    total_pct = round((cur['close']-pc)/pc*100,2)
    total_points = round(cur['close']-pc,2)
    avg_pct = round(abs(total_pct)/max(days_down,1),2)
    return {"days_down":days_down,"total_pct":total_pct,"total_points":total_points,
            "avg_pct":avg_pct,"peak_date":peak_date,"peak_close":round(pc,2),"current_close":round(cur['close'],2)}

def build_fib_json(windows, index_data, history):
    """构建完整Fib JSON"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    tracked_wins, reversal_date = build_windows(windows, history, today_str)
    
    # 下跌统计
    down = calc_down_stats(history)
    if index_data.get('index', 0) > 0 and abs(index_data['index'] - down['current_close']) > 1:
        down['total_pct'] = round((index_data['index'] - down['peak_close']) / down['peak_close'] * 100, 2)
        down['current_close'] = index_data['index']
    
    if down['total_pct'] >= 0:
        mode = "上涨中"
    elif down['total_pct'] >= -3:
        mode = "震荡整理"
    elif down['avg_pct'] >= 1.0:
        mode = "急跌"
    elif down['days_down'] >= 15:
        mode = "阴跌磨底"
    else:
        mode = "温和下跌"
    
    current = {
        "index": index_data.get('index', down.get('current_close', 0)),
        "change_pct": round(index_data.get('change_pct', 0), 2),
        "change_points": round(index_data.get('change_points', 0), 2),
        "days_down": down['days_down'], "total_pct": down['total_pct'],
        "total_points": down['total_points'], "avg_pct": down['avg_pct'],
        "peak_date": down['peak_date'], "peak_close": down['peak_close'],
        "date": today_str, "mode": mode,
    }
    
    judgement = {
        "summary": f"从{down['peak_date']}高点跌{down['days_down']}天（{down['total_pct']}%），{mode}",
        "key_window": "",
    }
    
    next_cycle = []
    if reversal_date:
        next_cycle = calc_next_cycle(reversal_date, today_str)
        if next_cycle:
            judgement["key_window"] = f"⚡ F(21)窗口({reversal_date})反转确认，下轮周期已推算"
        else:
            judgement["key_window"] = f"⚡ F(21)窗口({reversal_date})反转确认"
    else:
        tracking = [w for w in tracked_wins if w["status"] == "tracking"]
        future = [w for w in tracked_wins if w["status"] == "future"]
        if tracking:
            t = tracking[-1]
            judgement["key_window"] = f"🔄 {t['name']}({t['date']})追踪中，" + t.get("observation", {}).get("note", "")
        elif future:
            f = future[0]
            judgement["key_window"] = f"🎯 下个窗口: {f['name']}（{f['date']}）"
    
    return {
        "current": current, "windows": tracked_wins,
        "next_cycle": next_cycle, "judgement": judgement,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    print("斐波那契窗口追踪 v2.0")
    
    sh_data, sz_data = fetch_realtime()
    print(f"  📊 获取K线...")
    sh_history = fetch_index_history('sh.000001', 120)
    sz_history = fetch_index_history('sz.399001', 120)
    print(f"  ✓ 上证{len(sh_history)}天, 深证{len(sz_history)}天")
    
    for code, windows, history, out_path, idx_data, label in [
        ("sh", SH_FIB_WINDOWS, sh_history, SH_OUT, sh_data, "上证"),
        ("sz", SZ_FIB_WINDOWS, sz_history, SZ_OUT, sz_data, "深证"),
    ]:
        if not history:
            print(f"  ⚠️ {label}无数据")
            continue
        fib = build_fib_json(windows, idx_data, history)
        
        # 打印状态
        for w in fib['windows']:
            icon = {"triggered":"⚡","tracking":"🔄","active":"🔴","future":"📅","missed":"❌","passed":"✅"}.get(w["status"],"")
            obs = w.get("observation", {})
            note = ""
            if obs.get("index"):
                note = f" → 当日{obs['index']:.0f} {obs.get('change_pct',0):+.1f}%"
                if obs.get("note"):
                    note += f" ({obs['note']})"
            print(f"  {icon} {w['name']}({w['date']}) [{w['status']}]{note}")
        
        if fib['next_cycle']:
            print(f"  📐 下轮周期: {', '.join(n['name']+'('+n['date']+')' for n in fib['next_cycle'])}")
        
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(fib, f, ensure_ascii=False, indent=2)
        print(f"  ✓ {label}: {out_path}")
    
    print("完成")

if __name__ == "__main__":
    main()
