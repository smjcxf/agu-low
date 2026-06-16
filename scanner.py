#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选股观测台 - 全市场三线共振扫描 v4.0
缠论买字(日K) + 金钻趋势(黄柱/起涨) + 四量图(机构变红)
三重数据源: mootdx(通达信直连) → BaoStock(证券宝) → 东方财富(兜底)

作者: 小九AI
创建: 2026-05-29
升级: 2026-05-29 v4.0 三重数据源
"""

import json
import os
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED, TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
import re

warnings.filterwarnings("ignore")

# ============== 配置 ==============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

OUTPUT_JSON = os.path.join(DATA_DIR, "scan_result.json")
PROGRESS_JSON = os.path.join(DATA_DIR, "scan_progress.json")
GOLD_POOL_JSON = os.path.join(DATA_DIR, "gold_pool.json")
WATCH_RESULT_JSON = os.path.join(DATA_DIR, "watch_result.json")
SIGNAL_BACKTEST_JSON = os.path.join(DATA_DIR, "signal_backtest.json")

# 历史数据长度
DAILY_BARS = 250

# 限速(秒)
RATE_LIMIT_FULL = 0.0   # 全扫限速 (mootdx本地直连无限制)
RATE_LIMIT_WATCH = 0.01 # 金股精监限速 (极小延迟避免拥塞)

# 重试次数 (避免阻塞太久)
MAX_RETRIES = 1   # 只重试1次，之前3次太慢

# 金股池保留天数
GOLD_POOL_DAYS = 10  # 保留10个交易日（排除周末节假日）的信号股，足够观察持续性


def get_n_trade_days_ago(n):
    """用 baostock 获取 n 个交易日前的日期（精确排除周末和节假日）
    fallback: 遇周末时粗略用 1.4 倍自然日近似"""
    try:
        import baostock as bs
        bs.login()
        end = datetime.now().strftime("%Y-%m-%d")
        rs = bs.query_trade_dates(start_date="2020-01-01", end_date=end)
        trade_dates = []
        while rs.next():
            row = rs.get_row_data()
            if row[1] == "1":  # 1=交易日
                trade_dates.append(row[0])
        bs.logout()
        if len(trade_dates) >= n:
            return trade_dates[-n]
        return trade_dates[0]
    except Exception as e:
        print(f"  ⚠️ baostock 交易日历获取失败 ({e})，用 1.4 倍自然日近似")
        return (datetime.now() - timedelta(days=int(n * 1.4))).strftime("%Y-%m-%d")

# 成交量排序股池配置
VOLUME_TOP_CY = 100    # 创业板成交量前N
VOLUME_TOP_KC = 100    # 科创板成交量前N
VOLUME_TOP_ZB = 100    # 主板成交量前N
VOLUME_TOP_HK = 50     # 港股成交量前N

# ============== 审计日志 ==============
AUDIT_LOG = os.path.join(DATA_DIR, "data_audit.log")
_audit_stats = {"total": 0, "ok": 0, "suspect": 0, "no_verify": 0}
_audit_results = []  # 最近审计详情
_error_details = []   # 获取失败详情列表

def _audit_log(code, source, close_price, compare_price=None, diff_pct=None, status="OK"):
    """写入数据审计日志"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {code} | source={source} | close={close_price}"
    if compare_price is not None and diff_pct is not None:
        line += f" | compare={compare_price} | diff={diff_pct:.4f}% | status={status}"
    else:
        line += f" | status={status}"
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _cross_verify(code, df_primary, source_name):
    """用第二数据源交叉校验收盘价，偏差>0.5%则标记"""
    try:
        import requests as _req
        if code.startswith("6") or code.startswith("688"):
            secid = f"1.{code}"
        else:
            secid = f"0.{code}"
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid, "fields1": "f1,f2", "fields2": "f51,f52,f53,f54,f55",
            "klt": 101, "fqt": 1, "beg": "0", "end": "20500101", "lmt": 5,
        }
        r = _req.get(url, params=params, timeout=8)
        klines = r.json().get("data", {}).get("klines", [])
        if klines:
            parts = klines[-1].split(",")
            verify_close = float(parts[2])
            primary_close = float(df_primary["close"].iloc[-1])
            diff_pct = abs(primary_close - verify_close) / verify_close * 100
            status = "SUSPECT" if diff_pct > 0.5 else "OK"
            _audit_log(code, source_name, primary_close, verify_close, diff_pct, status)
            if diff_pct > 0.5:
                print(f"  [审计] {code} 双源偏差 {diff_pct:.2f}% ({source_name}={primary_close} vs 东方财富={verify_close})")
            return diff_pct, status
    except Exception:
        pass
    return None, "NO_VERIFY"


# ============== TDX公式函数 ==============
# 从triple_signal.py复用

def ref(series, n):
    if isinstance(n, pd.Series):
        result = pd.Series(np.nan, index=series.index)
        for i in range(len(series)):
            shift_n = max(0, int(n.iloc[i])) if pd.notna(n.iloc[i]) else 0
            if i - shift_n >= 0:
                result.iloc[i] = series.iloc[i - shift_n]
        return result
    return series.shift(int(n) if pd.notna(n) else 0)

def llv(series, n):
    if isinstance(n, pd.Series):
        result = pd.Series(np.nan, index=series.index)
        for i in range(len(series)):
            window = max(1, int(n.iloc[i])) if pd.notna(n.iloc[i]) else 1
            start = max(0, i - window + 1)
            result.iloc[i] = series.iloc[start:i+1].min()
        return result
    return series.rolling(window=max(1, int(n)), min_periods=1).min()

def hhv(series, n):
    if isinstance(n, pd.Series):
        result = pd.Series(np.nan, index=series.index)
        for i in range(len(series)):
            window = max(1, int(n.iloc[i])) if pd.notna(n.iloc[i]) else 1
            start = max(0, i - window + 1)
            result.iloc[i] = series.iloc[start:i+1].max()
        return result
    return series.rolling(window=max(1, int(n)), min_periods=1).max()

def sma_tdx(series, n, m):
    result = pd.Series(np.nan, index=series.index)
    result.iloc[0] = series.iloc[0]
    for i in range(1, len(series)):
        result.iloc[i] = (series.iloc[i] * m + result.iloc[i-1] * (n - m)) / n
    return result

def xma(series, n):
    half = n // 2
    result = pd.Series(np.nan, index=series.index)
    for i in range(len(series)):
        start = max(0, i - half)
        end = min(len(series), i + half + 1)
        result.iloc[i] = series.iloc[start:end].mean()
    return result

def cross(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))

def ma(series, n):
    return series.rolling(window=n, min_periods=1).mean()

def calc_wma20(series):
    weights = list(range(20, 0, -1))
    total_weight = sum(weights)
    result = pd.Series(np.nan, index=series.index)
    for i in range(19, len(series)):
        weighted_sum = 0
        for j, w in enumerate(weights):
            if i - j >= 0:
                weighted_sum += series.iloc[i - j] * w
        result.iloc[i] = weighted_sum / total_weight
    return result


# ============== 缠论指标(优化版) ==============

def calc_chanlun_signal(df):
    """缠论极点保留 - 逐bar循环版"""
    n = len(df)
    # 确保数据类型正确
    H = df["high"].astype(float).values
    L = df["low"].astype(float).values

    极点保留 = np.zeros(n, dtype=int)

    # Step 1: 局部低/高点预选
    局部低点预选C = np.zeros(n, dtype=int)
    局部高点预选C = np.zeros(n, dtype=int)

    for i in range(4, n):
        llv5 = min(L[max(0,i-4):i+1])
        llv4_prev = min(L[max(0,i-5):i]) if i >= 5 else L[0]
        cond_a = llv5 < llv4_prev
        if i >= 2:
            llv5_prev = min(L[max(0,i-5):i])
            llv4_prev2 = min(L[max(0,i-6):i-1]) if i >= 6 else L[0]
            cond_a_prev = llv5_prev < llv4_prev2
            if not cond_a and cond_a_prev:
                局部低点预选C[i] = -1

        hhv5 = max(H[max(0,i-4):i+1])
        hhv4_prev = max(H[max(0,i-5):i]) if i >= 5 else H[0]
        cond_a2 = hhv5 > hhv4_prev
        if i >= 2:
            hhv5_prev = max(H[max(0,i-5):i])
            hhv4_prev2 = max(H[max(0,i-6):i-1]) if i >= 6 else H[0]
            cond_a2_prev = hhv5_prev > hhv4_prev2
            if not cond_a2 and cond_a2_prev:
                局部高点预选C[i] = 1

    # Step 2: 缺口判断 + 距前高/低天 + 值周期
    距前高天 = np.zeros(n, dtype=int)
    距前低天 = np.zeros(n, dtype=int)
    last_high = -1
    last_low = -1
    for i in range(n):
        if 局部高点预选C[i] == 1:
            last_high = i
        if 局部低点预选C[i] == -1:
            last_low = i
        # 修复：使用明确的条件赋值，避免类型混淆
        if last_high >= 0:
            距前高天[i] = i - last_high
        else:
            距前高天[i] = i + 1
        if last_low >= 0:
            距前低天[i] = i - last_low
        else:
            距前低天[i] = i + 1

    小值周期 = np.zeros(n, dtype=int)
    大值周期 = np.zeros(n, dtype=int)
    for i in range(n):
        c = 0
        for j in range(i-1, -1, -1):
            if L[j] > L[i]:
                c += 1
            else:
                break
        小值周期[i] = c
        c = 0
        for j in range(i-1, -1, -1):
            if H[j] < H[i]:
                c += 1
            else:
                break
        大值周期[i] = c

    def llv_arr(arr, i, window):
        start = max(0, i - window + 1)
        return min(arr[start:i+1])

    def hhv_arr(arr, i, window):
        start = max(0, i - window + 1)
        return max(arr[start:i+1])

    def ref_arr(arr, i, offset):
        pos = i - offset
        return arr[pos] if pos >= 0 else arr[0]

    # Step 3: 第1轮过滤(S级)
    低保留S_arr = np.zeros(n, dtype=int)
    for i in range(n):
        if 局部低点预选C[i] == -1:
            dgt = 距前高天[i]
            dlt = 距前低天[i]
            dgt_prev = ref_arr(距前高天, i, 1)
            dlt_prev = ref_arr(距前低天, i, 1)
            aa = False
            if dgt_prev > dlt_prev:
                if i > dgt and llv_arr(L, i, dgt+1) < llv_arr(L, i-1, dgt+1):
                    aa = True
            ab = dgt_prev <= dlt_prev
            if (aa or ab) and L[i] < ref_arr(H, i, dgt+1):
                低保留S_arr[i] = -1

    高保留_arr = np.zeros(n, dtype=int)
    for i in range(n):
        if 局部高点预选C[i] == 1:
            dgt = 距前高天[i]
            dlt = 距前低天[i]
            dgt_prev = ref_arr(距前高天, i, 1)
            dlt_prev = ref_arr(距前低天, i, 1)
            yu = (dlt < 4) or (ref_arr(低保留S_arr, i, dlt) != -1)
            pd_ = False
            if dlt_prev <= dgt_prev and yu:
                if (大值周期[i] > ref_arr(小值周期, i, dlt+1) and
                    大值周期[i] > ref_arr(小值周期, i, dlt) and
                    大值周期[i] > ref_arr(大值周期, i, dgt)):
                    pd_ = True
            ga = False
            if dlt_prev > dgt_prev:
                if i > dlt and hhv_arr(H, i, dlt+1) > hhv_arr(H, i-1, dlt+1):
                    ga = True
            gb = False
            if dlt_prev <= dgt_prev:
                if ref_arr(低保留S_arr, i, dlt) == -1 and dlt >= 4:
                    gb = True
            if (ga or gb or pd_) and H[i] > ref_arr(L, i, dlt+1):
                高保留_arr[i] = 1

    低保留_arr = np.zeros(n, dtype=int)
    for i in range(n):
        if 局部低点预选C[i] == -1:
            dgt = 距前高天[i]
            dlt = 距前低天[i]
            dgt_prev = ref_arr(距前高天, i, 1)
            dlt_prev = ref_arr(距前低天, i, 1)
            yua = (dgt < 4) or (ref_arr(高保留_arr, i, dgt) != 1)
            pda = False
            if dgt_prev <= dlt_prev and yua:
                if (小值周期[i] > ref_arr(大值周期, i, dgt+1) and
                    小值周期[i] > ref_arr(大值周期, i, dgt) and
                    小值周期[i] > ref_arr(小值周期, i, dlt)):
                    pda = True
            da = False
            if dgt_prev > dlt_prev:
                if i > dgt and llv_arr(L, i, dgt+1) < llv_arr(L, i-1, dgt+1):
                    da = True
            db = False
            if dgt_prev <= dlt_prev:
                if dgt >= 4 or pda:
                    db = True
            if (da or db) and L[i] < ref_arr(H, i, dgt+1):
                低保留_arr[i] = -1

    # Step 4: 第2轮过滤(X级)
    距前高天A = np.zeros(n, dtype=int)
    距前低天A = np.zeros(n, dtype=int)
    last_ha = -1
    last_la = -1
    for i in range(n):
        if 高保留_arr[i] == 1:
            last_ha = i
        if 低保留_arr[i] == -1:
            last_la = i
        距前高天A[i] = i - last_ha if last_ha >= 0 else i + 1
        距前低天A[i] = i - last_la if last_la >= 0 else i + 1

    高保留X_arr = np.zeros(n, dtype=int)
    for i in range(n):
        if 局部高点预选C[i] == 1:
            dgta = 距前高天A[i]
            dlta = 距前低天A[i]
            dgta_prev = ref_arr(距前高天A, i, 1)
            dlta_prev = ref_arr(距前低天A, i, 1)
            yux = (dlta < 4) or (ref_arr(低保留_arr, i, dlta) != -1)
            pdx = False
            if dlta_prev <= dgta_prev and yux:
                if (大值周期[i] > ref_arr(小值周期, i, dlta+1) and
                    大值周期[i] > ref_arr(小值周期, i, dlta) and
                    大值周期[i] > ref_arr(大值周期, i, dgta)):
                    pdx = True
            gxa = False
            if dlta_prev > dgta_prev:
                if i > dlta and hhv_arr(H, i, dlta+1) > hhv_arr(H, i-1, dlta+1):
                    gxa = True
            gxb = False
            if dlta_prev <= dgta_prev:
                if ref_arr(低保留_arr, i, dlta) == -1 and dlta >= 4:
                    gxb = True
            if (gxa or gxb or pdx) and H[i] > ref_arr(L, i, dlta+1):
                高保留X_arr[i] = 1

    低保留X_arr = np.zeros(n, dtype=int)
    for i in range(n):
        if 局部低点预选C[i] == -1:
            dgta = 距前高天A[i]
            dlta = 距前低天A[i]
            dgta_prev = ref_arr(距前高天A, i, 1)
            dlta_prev = ref_arr(距前低天A, i, 1)
            yuxa = (dgta < 4) or (ref_arr(高保留X_arr, i, dgta) != 1)
            pdxa = False
            if dgta_prev <= dlta_prev and yuxa:
                if (小值周期[i] > ref_arr(大值周期, i, dgta+1) and
                    小值周期[i] > ref_arr(大值周期, i, dgta) and
                    小值周期[i] > ref_arr(小值周期, i, dlta)):
                    pdxa = True
            dxa = False
            if dgta_prev > dlta_prev:
                if i > dgta and llv_arr(L, i, dgta+1) < llv_arr(L, i-1, dgta+1):
                    dxa = True
            dxb = False
            if dgta_prev <= dlta_prev:
                if dgta >= 4 or pdxa:
                    dxb = True
            if (dxa or dxb) and L[i] < ref_arr(H, i, dgta+1):
                低保留X_arr[i] = -1

    # Step 5: 第3轮过滤(YA级)
    距前高天YA = np.zeros(n, dtype=int)
    距前低天YA = np.zeros(n, dtype=int)
    last_hya = -1
    last_lya = -1
    for i in range(n):
        if 高保留X_arr[i] == 1:
            last_hya = i
        if 低保留X_arr[i] == -1:
            last_lya = i
        距前高天YA[i] = i - last_hya if last_hya >= 0 else i + 1
        距前低天YA[i] = i - last_lya if last_lya >= 0 else i + 1

    高保留YX_arr = np.zeros(n, dtype=int)
    for i in range(n):
        if 局部高点预选C[i] == 1:
            dgtya = 距前高天YA[i]
            dltya = 距前低天YA[i]
            dgtya_prev = ref_arr(距前高天YA, i, 1)
            dltya_prev = ref_arr(距前低天YA, i, 1)
            yuyx = (dltya < 4) or (ref_arr(低保留X_arr, i, dltya) != -1)
            pdyx = False
            if dltya_prev <= dgtya_prev and yuyx:
                if (大值周期[i] > ref_arr(小值周期, i, dltya+1) and
                    大值周期[i] > ref_arr(小值周期, i, dltya) and
                    大值周期[i] > ref_arr(大值周期, i, dgtya)):
                    pdyx = True
            gyxa = False
            if dltya_prev > dgtya_prev:
                if i > dltya and hhv_arr(H, i, dltya+1) > hhv_arr(H, i-1, dltya+1):
                    gyxa = True
            gyxb = False
            if dltya_prev <= dgtya_prev:
                if ref_arr(低保留X_arr, i, dltya) == -1 and dltya >= 4:
                    gyxb = True
            if (gyxa or gyxb or pdyx) and H[i] > ref_arr(L, i, dltya+1):
                高保留YX_arr[i] = 1

    低保留YX_arr = np.zeros(n, dtype=int)
    for i in range(n):
        if 局部低点预选C[i] == -1:
            dgtya = 距前高天YA[i]
            dltya = 距前低天YA[i]
            dgtya_prev = ref_arr(距前高天YA, i, 1)
            dltya_prev = ref_arr(距前低天YA, i, 1)
            yuyxa = (dgtya < 4) or (ref_arr(高保留YX_arr, i, dgtya) != 1)
            pdyxa = False
            if dgtya_prev <= dltya_prev and yuyxa:
                if (小值周期[i] > ref_arr(大值周期, i, dgtya+1) and
                    小值周期[i] > ref_arr(大值周期, i, dgtya) and
                    小值周期[i] > ref_arr(小值周期, i, dltya)):
                    pdyxa = True
            dyxa = False
            if dgtya_prev > dltya_prev:
                if i > dgtya and llv_arr(L, i, dgtya+1) < llv_arr(L, i-1, dgtya+1):
                    dyxa = True
            dyxb = False
            if dgtya_prev <= dltya_prev:
                if dgtya >= 4 or pdyxa:
                    dyxb = True
            if (dyxa or dyxb) and L[i] < ref_arr(H, i, dgtya+1):
                低保留YX_arr[i] = -1

    # Step 6: AAAD最终判断
    for i in range(n):
        if 高保留YX_arr[i] == 1 and 低保留YX_arr[i] == -1:
            dgtya_prev = ref_arr(距前高天YA, i, 1)
            dltya_prev = ref_arr(距前低天YA, i, 1)
            if H[i] > ref_arr(H, i, dgtya_prev + 2):
                极点保留[i] = 1
            elif L[i] < ref_arr(L, i, dltya_prev + 2):
                极点保留[i] = -1
            else:
                极点保留[i] = 高保留YX_arr[i] + 低保留YX_arr[i]
        else:
            极点保留[i] = 高保留YX_arr[i] + 低保留YX_arr[i]

    df["极点保留"] = 极点保留
    return df


# ============== 金钻趋势指标 ==============

def calc_jinzuan_signal(df):
    """金钻趋势信号"""
    H = df["high"]
    L = df["low"]
    C = df["close"]
    O = df["open"]
    V = df.get("volume", pd.Series(0, index=df.index))

    xma_h25 = xma(xma(H, 25), 25)
    xma_l25 = xma(xma(L, 25), 25)
    通道宽度 = xma_h25 - xma_l25
    金钻趋势 = xma_l25 - 通道宽度
    金牛 = xma_h25 + 通道宽度

    df["金钻趋势"] = 金钻趋势
    df["金牛"] = 金牛

    # 黄柱: 金钻趋势>HIGH
    df["黄柱"] = 金钻趋势 > H

    # 金钻起涨
    VAR23 = 100 * xma(xma(C - ref(C, 1), 6), 6) / xma(xma(abs(C - ref(C, 1)), 6), 6)
    回调买 = (llv(VAR23, 2) == llv(VAR23, 7)) & \
            (VAR23.rolling(2).apply(lambda x: (x < 0).sum()) >= 1) & \
            cross(VAR23, ma(VAR23, 2))

    if "volume" in df.columns and V.sum() > 0:
        JJ = (H + L + C) / 3
        QJ0 = V / np.where(H == L, 4, H - L)
        QJ1 = QJ0 * (JJ - np.minimum(C, O))
        QJ2 = QJ0 * (np.minimum(O, C) - L)
        QJ3 = QJ0 * (H - np.maximum(O, C))
        QJ4 = QJ0 * (np.maximum(C, O) - JJ)
        DDX = (QJ1 + QJ2 - QJ3 - QJ4) / 10000
        V2 = sma_tdx(pd.Series(np.where(C >= ref(C, 1), DDX, -DDX/100), index=df.index), 2, 1)
        DY = (np.arange(len(df)) == len(df) - 1) & (C < ref(C, 1))
        DY2 = ref(V2, 1) - pd.Series(DY, index=df.index, dtype=float)
        XG2 = (C > O) & (DY2 < 0.02) & (ma(C, 5) > ma(C, 60)) & \
              (C / ref(C, 1) >= 1.02) & (H < 金牛)
        金钻起涨 = XG2 & (L < 金钻趋势)
    else:
        金钻起涨 = pd.Series(False, index=df.index)

    df["金钻起涨"] = 金钻起涨
    return df


# ============== 四量图指标 ==============

def calc_siliang_signal(df):
    """四量图机构信号 - 精确版"""
    C = df["close"]
    O = df["open"]
    H = df["high"]
    L = df["low"]

    MID9 = (3 * C + L + O + H) / 6
    牛线1 = calc_wma20(MID9)
    马线1 = ma(牛线1, 6)

    df["机构变红"] = C > 牛线1
    df["牛线1"] = 牛线1
    df["马线1"] = 马线1
    return df


# ============== 上涨趋势预警选股指标 ==============

def calc_uptrend_signal(df):
    """
    上涨趋势预警选股
    逻辑忠实翻译自通达信公式(作者: 抖音/B站 - 爱炒股的大灰狼):
      条件1: 均线多头排列(稳健上升趋势)
      条件2: 中期趋势+金叉启动(趋势反转起爆)
      条件3: 主升浪强势(加速拉升段)
      条件4: 风控过滤(剔除停牌/无效数据)
    返回: df 增加 '上涨趋势_条件1'~'上涨趋势_条件4' '上涨趋势'
    """
    C = df["close"]
    V = df.get("volume", pd.Series(0, index=df.index))

    MA5 = ma(C, 5)
    MA10 = ma(C, 10)
    MA20 = ma(C, 20)
    MA60 = ma(C, 60)

    MAV5 = ma(V, 5)
    MAV10 = ma(V, 10)

    # 条件1: 均线多头排列(稳健上升趋势)
    多头排列 = MA5 > MA10
    多头排列 = 多头排列 & (MA10 > MA20)
    多头排列 = 多头排列 & (MA20 > MA60)
    趋势向上 = MA5 > ref(MA5, 1)
    趋势向上 = 趋势向上 & (MA10 > ref(MA10, 1))
    条件1 = 多头排列 & 趋势向上

    # 条件2: 中期趋势+金叉启动
    中期打底 = MA60 > ref(MA60, 1)
    中期打底 = 中期打底 & (C > MA60)
    金叉突破 = cross(MA5, MA20)
    量能确认 = V > ref(V, 1) * 1.3
    条件2 = 中期打底 & 金叉突破 & 量能确认

    # 条件3: 主升浪强势
    价格强势 = C > MA5
    量价健康 = V > MAV5
    量价健康 = 量价健康 & (MAV5 > MAV10)
    条件3 = 多头排列 & 价格强势 & 量价健康

    # 条件4: 风控过滤(剔除停牌及无效数据)
    H = df.get("high", pd.Series(0, index=df.index))
    L = df.get("low", pd.Series(0, index=df.index))
    剔除停牌 = (C > 0) & (V > 0) & (H > L)
    风控通过 = 剔除停牌

    # 综合选股信号
    选股信号 = (条件1 | 条件2 | 条件3) & 风控通过

    df["上涨趋势_条件1"] = 条件1.fillna(False)
    df["上涨趋势_条件2"] = 条件2.fillna(False)
    df["上涨趋势_条件3"] = 条件3.fillna(False)
    df["上涨趋势_条件4"] = 风控通过.fillna(False)
    df["上涨趋势"] = 选股信号.fillna(False)

    return df


# ============== RSI & 信号评分 ==============

def calc_rsi(close_series, period=14):
    """计算RSI指标(SMA方式)"""
    delta = close_series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_signal_score(signal_count, rsi_val, turnover_rate):
    """信号评分：信号数x3为基准，RSI>70扣1分，换手>3%加0.5分"""
    base = signal_count * 3
    if rsi_val and rsi_val > 70:
        base -= 1
    if turnover_rate and turnover_rate > 3:
        base += 0.5
    return round(max(0, base), 1)


# ============== 交易日历辅助 ==============

_trade_dates_cache = None

def _load_trade_dates():
    """加载A股交易日历(缓存)"""
    global _trade_dates_cache
    if _trade_dates_cache is not None:
        return _trade_dates_cache
    try:
        import akshare as ak
        cal = ak.tool_trade_date_hist_sina()
        _trade_dates_cache = sorted(cal["trade_date"].tolist())
    except Exception:
        _trade_dates_cache = []
    return _trade_dates_cache

def get_trade_date_n_days_ago(n):
    """获取n个交易日前的日期(YYYY-MM-DD格式)"""
    dates = _load_trade_dates()
    if not dates:
        return None
    today_str = datetime.now().strftime("%Y%m%d")
    idx = None
    for i, d in enumerate(dates):
        d_str = str(d).replace("-", "")[:8]  # 兼容 datetime.date/str 类型
        if d_str > today_str:
            idx = i
            break
    if idx is None:
        return None
    target_idx = idx - 1 - n
    if target_idx < 0:
        return None
    from datetime import date as _date
    raw = dates[target_idx]
    if isinstance(raw, _date):
        return raw.strftime("%Y-%m-%d")
    return datetime.strptime(str(raw)[:8], "%Y%m%d").strftime("%Y-%m-%d")

def calc_pct_chg_n(df, n=20):
    """用交易日历计算近N日涨幅；失败时fallback到K线近似"""
    target_date = get_trade_date_n_days_ago(n)
    if target_date and "date" in df.columns:
        # 统一转为字符串比较(兼容多种日期类型)
        try:
            df_dates = df["date"].apply(lambda x: str(x)[:10])
            mask = df_dates <= target_date
            if mask.any():
                ref_close = float(df[mask].iloc[-1]["close"])
                current_close = float(df.iloc[-1]["close"])
                return round((current_close / ref_close - 1) * 100, 2)
        except Exception:
            pass
    # fallback: K线近似
    if len(df) >= n + 2:
        return round((float(df.iloc[-1]["close"]) / float(df.iloc[-(n+2)]["close"]) - 1) * 100, 2)
    return 0


# ============== 三重数据源: mootdx → BaoStock → 东方财富 ==============

# 数据源统计
_data_source_stats = {"mootdx": 0, "baostock": 0, "eastmoney": 0, "efinance": 0, "qq": 0, "fail": 0}
_bs_consecutive_fails = 0    # BaoStock 连续失败计数
_BS_FAIL_SKIP_THRESHOLD = 3  # 连续失败 N 次后跳过后续所有 baostock 查询

# ============== 港股硬编码池(API断连时的抢救兜底) ==============
# 当 eastmoney/efinance 列表 API 都不可用时，使用此固定池
# westock-data 可批量查这些股票，按成交额动态排序取 Top N
_HK_FALLBACK_POOL = [
    # 互联网/科技 (9只)
    ("00700", "腾讯控股"), ("09988", "阿里巴巴-W"), ("03690", "美团-W"),
    ("09618", "京东集团-SW"), ("09999", "网易-S"), ("09888", "百度集团-SW"),
    ("01024", "快手-W"), ("09626", "哔哩哔哩-W"), ("01810", "小米集团-W"),
    # 金融 (12只)
    ("00005", "汇丰控股"), ("01299", "友邦保险"), ("00388", "香港交易所"),
    ("00939", "建设银行"), ("01398", "工商银行"), ("03988", "中国银行"),
    ("01288", "农业银行"), ("03968", "招商银行"), ("03328", "交通银行"),
    ("02318", "中国平安"), ("02628", "中国人寿"), ("02601", "中国太保"),
    # 能源 (3只)
    ("00883", "中国海洋石油"), ("00857", "中国石油股份"), ("00386", "中国石油化工"),
    # 汽车 (5只)
    ("01211", "比亚迪股份"), ("00175", "吉利汽车"), ("02015", "理想汽车-W"),
    ("09866", "蔚来-SW"), ("09868", "小鹏汽车-W"),
    # 消费 (7只)
    ("02319", "蒙牛乳业"), ("09633", "农夫山泉"), ("00291", "华润啤酒"),
    ("02020", "安踏体育"), ("02331", "李宁"), ("06862", "海底捞"),
    ("09987", "百胜中国"),
    # 电讯 (3只)
    ("00941", "中国移动"), ("00728", "中国电信"), ("00762", "中国联通"),
    # 医药 (8只)
    ("02269", "药明生物"), ("01177", "中国生物制药"), ("01093", "石药集团"),
    ("02359", "药明康德"), ("06160", "百济神州"), ("06618", "京东健康"),
    ("01833", "平安好医生"), ("01209", "华润万象生活"),
    # 地产 (5只)
    ("01109", "华润置地"), ("00016", "新鸿基地产"), ("00012", "恒基地产"),
    ("00017", "新世界发展"), ("00083", "信和置业"),
    # 博彩/综合 (8只)
    ("00027", "银河娱乐"), ("01928", "金沙中国有限公司"), ("02282", "美高梅中国"),
    ("00001", "长和"), ("00002", "中电控股"), ("00003", "香港中华煤气"),
    ("00006", "电能实业"), ("00267", "中信股份"),
    # 芯片/科技硬件 (4只)
    ("00981", "中芯国际"), ("01347", "华虹半导体"), ("02382", "舜宇光学科技"),
    ("02018", "瑞声科技"),
    # 新经济/金融科技 (6只)
    ("09961", "携程集团-S"), ("06690", "海尔智家"), ("02057", "中通快递-W"),
    ("03888", "金山软件"), ("09926", "康方生物"), ("03896", "金山云"),
    # 金融扩展 (5只)
    ("00011", "恒生银行"), ("02388", "中银香港"), ("06030", "中信证券"),
    ("06881", "中国银河"), ("01776", "广发证券"),
    # 更多蓝筹 (7只)
    ("00066", "港铁公司"), ("00288", "万洲国际"), ("00669", "创科实业"),
    ("01876", "百威亚太"), ("01929", "周大福"), ("02688", "新奥能源"),
    ("02899", "紫金矿业"),
    # 新能源/材料 (5只)
    ("01258", "中国有色矿业"), ("01898", "中煤能源"), ("00968", "信义玻璃"),
    ("00868", "信义光能"), ("02333", "长城汽车"),
    # 其他热门 (5只)
    ("06098", "碧桂园服务"), ("01818", "招金矿业"), ("09660", "地平线机器人"),
    ("01378", "中国宏桥"), ("00135", "昆仑能源"),
]

# mootdx 单例客户端
_tdx_client = None

def _fetch_eastmoney_batch_details(codes):
    """批量从东方财富获取换手率(f8)和总市值(f20) — 用于弥补mootdx缺失字段
    
    Args:
        codes: list of 6-digit stock codes like ["002006", "600000"]
    
    Returns:
        dict: {code: {"turnover_rate": float, "total_mv": float}}
    """
    if not codes:
        return {}
    
    result = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    
    for i in range(0, len(codes), 80):
        batch = codes[i:i+80]
        secids = []
        for c in batch:
            if c.startswith("6") or c.startswith("688"):
                secids.append(f"1.{c}")
            else:
                secids.append(f"0.{c}")
        
        # 重试3次
        for attempt in range(3):
            try:
                url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
                params = {
                    "fltt": 2,
                    "invt": 2,
                    "fields": "f12,f8,f20",
                    "secids": ",".join(secids),
                }
                r = requests.get(url, params=params, headers=headers, timeout=15)
                if r.status_code != 200:
                    print(f"    [东财] HTTP {r.status_code}, 重试({attempt+1}/3)")
                    time.sleep(0.5)
                    continue
                data = r.json().get("data", {})
                items = data.get("diff", [])
                for item in items:
                    code = str(item.get("f12", "")).zfill(6)
                    result[code] = {
                        "turnover_rate": item.get("f8", 0) or 0,
                        "total_mv": item.get("f20", 0) or 0,
                    }
                break  # 成功，跳出重试
            except Exception as e:
                print(f"    [东财] 批次{i//80+1}获取失败({attempt+1}/3): {e}")
                time.sleep(0.5)
        time.sleep(0.1)
    
    return result


def _get_tdx_client():
    """获取mootdx客户端(单例, 自动选最快服务器)"""
    global _tdx_client
    if _tdx_client is None:
        try:
            from mootdx.quotes import Quotes
            _tdx_client = Quotes.factory(market='std')
            print("[数据源] mootdx 通达信直连 - 已连接")
        except Exception as e:
            print(f"[数据源] mootdx 连接失败: {e}")
    return _tdx_client


# BaoStock 单例
_bs_logged_in = False

def _bs_login():
    """BaoStock登录(单次)"""
    global _bs_logged_in
    if not _bs_logged_in:
        try:
            import baostock as bs
            lg = bs.login()
            _bs_logged_in = (lg.error_code == '0')
            if _bs_logged_in:
                print("[数据源] BaoStock 证券宝 - 已连接")
            else:
                print(f"[数据源] BaoStock 登录失败: {lg.error_msg}")
        except Exception as e:
            print(f"[数据源] BaoStock 导入失败: {e}")

def _bs_logout():
    """BaoStock登出"""
    global _bs_logged_in
    if _bs_logged_in:
        try:
            import baostock as bs
            bs.logout()
            _bs_logged_in = False
        except:
            pass


# ============== 股票列表获取(成交量排序) ==============

def _fetch_board_top_mootdx(market_id, code_prefixes, board_label, top_n):
    """mootdx方式: 获取某板块成交量Top N (需本地排序)"""
    client = _get_tdx_client()
    if client is None:
        return []

    try:
        # 获取该市场所有股票代码
        all_stocks = client.stocks(market=market_id)
        if all_stocks is None or len(all_stocks) == 0:
            return []

        # 过滤出目标板块的股票代码
        target_codes = []
        target_names = {}
        for _, row in all_stocks.iterrows():
            code = str(row['code']).zfill(6)
            name = str(row.get('name', '')).replace('\x00', '').strip()
            # 过滤: 只保留目标前缀 + 排除指数/债券/ETF
            if not any(code.startswith(p) for p in code_prefixes):
                continue
            if name and name.startswith(('N', 'ST', '*ST', '退')):
                continue
            # 排除非股票
            if any(x in name for x in ['指数', 'Ａ股', 'Ｂ股', '基金', 'ETF', '债券', '转债', '回购']):
                continue
            target_codes.append(code)
            target_names[code] = name

        if not target_codes:
            return []

        # 批量获取实时行情(mootdx每次最多约80只)
        BATCH_SIZE = 80
        all_quotes = []
        for i in range(0, len(target_codes), BATCH_SIZE):
            batch = target_codes[i:i+BATCH_SIZE]
            try:
                df = client.quotes(symbol=batch)
                if df is not None and len(df) > 0:
                    all_quotes.append(df)
                time.sleep(0.05)
            except:
                continue

        if not all_quotes:
            return []

        quotes_df = pd.concat(all_quotes, ignore_index=True)

        # 过滤停牌(price=0) + 排序
        quotes_df = quotes_df[quotes_df['price'] > 0].copy()
        quotes_df = quotes_df.sort_values('amount', ascending=False)

        stocks = []
        count = 0
        for _, row in quotes_df.iterrows():
            code = str(row['code']).zfill(6)
            name = target_names.get(code, str(row.get('code', '')).replace('\x00', '').strip())
            if not name or name == code:
                continue
            # 再次过滤ST等
            if name.startswith(('N', 'ST', '*ST', '退', 'C')):
                continue

            price = float(row.get('price', 0))
            if price <= 0:
                continue

            volume_amount = float(row.get('amount', 0))  # 成交额(元)
            vol = float(row.get('volume', 0))  # 成交量(手)
            last_close = float(row.get('last_close', 0))

            market = "sh" if market_id == 1 else "sz"
            if code.startswith("688"):
                market = "sh"

            # 占位: 换手率和市值稍后从东财批量补充
            stocks.append((code, name, market, board_label, volume_amount, 0, 0, "混合"))
            count += 1
            if count >= top_n:
                break

        # === 批量从东财补充换手率&总市值（弥补mootdx不足） ===
        if stocks:
            codes_to_fetch = [s[0] for s in stocks]
            em_data = _fetch_eastmoney_batch_details(codes_to_fetch)
            if em_data:
                updated_stocks = []
                for s in stocks:
                    code, name, market, board_label, volume_amount, _, _, fund_type = s
                    em = em_data.get(code, {})
                    turnover_rate = float(em.get("turnover_rate", 0) or 0)
                    total_mv = float(em.get("total_mv", 0) or 0)
                    mv_yi = total_mv / 1e8 if total_mv > 0 else 0
                    
                    # 根据换手率+市值重新判定资金类型
                    if mv_yi > 500 and turnover_rate and turnover_rate < 3:
                        fund_type = "机构"
                    elif mv_yi < 200 and turnover_rate and turnover_rate > 5:
                        fund_type = "游资"
                    elif mv_yi > 1000:
                        fund_type = "机构"
                    else:
                        fund_type = "混合"
                    
                    updated_stocks.append((code, name, market, board_label, volume_amount, turnover_rate, mv_yi, fund_type))
                stocks = updated_stocks
                print(f"    [东财补全] {board_label}: {len([s for s in updated_stocks if s[5] > 0])}/{len(updated_stocks)} 只有效换手率")

        return stocks
    except Exception as e:
        print(f"[WARN] mootdx获取{board_label}列表失败: {e}")
        return []


def _fetch_board_top(board_fs, board_label, top_n, fid="f6"):
    """通用: 获取某板块按字段排序的Top N (东方财富兜底)"""
    try:
        url = "https://82.push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1, "pz": top_n + 50, "po": 1, "np": 1,
            "fltt": 2, "invt": 2, "fid": fid,
            "fs": board_fs,
            "fields": "f12,f14,f2,f3,f6,f8,f20,f21"
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json().get("data", {})
        diff = data.get("diff", [])

        stocks = []
        count = 0
        for item in diff:
            code = str(item.get("f12", "")).zfill(6)
            name = str(item.get("f14", "")).replace('\x00', '').strip()
            if not code or not name:
                continue
            if name.startswith(("N", "ST", "*ST", "退", "C")):
                continue
            price = item.get("f2", "-")
            if price == "-" or price <= 0:
                continue
            volume_amount = item.get("f6", 0)
            turnover_rate = item.get("f8", 0)
            total_mv = item.get("f20", 0)

            market = "sh" if code.startswith("6") or code.startswith("688") else "sz"
            if code.startswith("688"):
                market = "sh"

            mv_yi = (total_mv / 1e8) if total_mv and total_mv > 0 else 0
            if mv_yi > 500 and turnover_rate and turnover_rate < 3:
                fund_type = "机构"
            elif mv_yi < 200 and turnover_rate and turnover_rate > 5:
                fund_type = "游资"
            elif mv_yi > 1000:
                fund_type = "机构"
            else:
                fund_type = "混合"

            stocks.append((code, name, market, board_label, volume_amount, turnover_rate, mv_yi, fund_type))
            count += 1
            if count >= top_n:
                break
        return stocks
    except Exception as e:
        print(f"[WARN] 东方财富获取{board_label}列表失败: {e}")
        return []


def fetch_volume_top_stocks(top_cy=None, top_kc=None, top_zb=None, top_hk=None):
    """获取按成交量排序的活跃股池(三重源: mootdx → 东方财富)"""
    top_cy = top_cy or VOLUME_TOP_CY
    top_kc = top_kc or VOLUME_TOP_KC
    top_zb = top_zb or VOLUME_TOP_ZB
    top_hk = top_hk or VOLUME_TOP_HK

    all_stocks = []

    # ---- 创业板 ----
    print("  获取创业板成交量Top{}...".format(top_cy))
    cy = _fetch_board_top_mootdx(0, ["300"], "创业板", top_cy)
    if not cy:
        print("    mootdx失败, 尝试东方财富...")
        cy = _fetch_board_top("m:0+t:80", "创业板", top_cy)
    print(f"    创业板: {len(cy)} 只")
    all_stocks.extend(cy)

    # ---- 科创板 ----
    print("  获取科创板成交量Top{}...".format(top_kc))
    kc = _fetch_board_top_mootdx(1, ["688"], "科创板", top_kc)
    if not kc:
        print("    mootdx失败, 尝试东方财富...")
        kc = _fetch_board_top("m:1+t:23", "科创板", top_kc)
    print(f"    科创板: {len(kc)} 只")
    all_stocks.extend(kc)

    # ---- 主板 ----
    print("  获取主板成交量Top{}...".format(top_zb))
    zb_sz = _fetch_board_top_mootdx(0, ["000", "001", "002", "003"], "主板", top_zb // 2 + 20)
    zb_sh = _fetch_board_top_mootdx(1, ["600", "601", "603", "605"], "主板", top_zb // 2 + 20)
    if not zb_sz and not zb_sh:
        print("    mootdx失败, 尝试东方财富...")
        zb1 = _fetch_board_top("m:0+t:6", "主板", top_zb // 2 + 20)
        zb2 = _fetch_board_top("m:1+t:2", "主板", top_zb // 2 + 20)
        zb_sz = zb1
        zb_sh = zb2
    # 合并主板，去重，按成交额排序取Top
    zb_dict = {}
    for s in zb_sz + zb_sh:
        key = s[0]
        if key not in zb_dict or s[4] > zb_dict[key][4]:
            zb_dict[key] = s
    zb = sorted(zb_dict.values(), key=lambda x: -(x[4] or 0))[:top_zb]
    print(f"    主板: {len(zb)} 只")
    all_stocks.extend(zb)

    # ---- 港股 ----
    print("  获取港股成交量Top{}...".format(top_hk))
    hk = _fetch_hk_volume_top(top_hk)
    print(f"    港股: {len(hk)} 只")
    all_stocks.extend(hk)

    # 汇总
    boards = {}
    for s in all_stocks:
        b = s[3]
        boards[b] = boards.get(b, 0) + 1

    print(f"\n  股池汇总: {len(all_stocks)} 只")
    for b, c in boards.items():
        print(f"    {b}: {c} 只")

    # ── 合并投行研报关注池（30天内有出现）──
    _wl_file = os.path.join(DATA_DIR, "guanlan_watchlist.json")
    if os.path.exists(_wl_file):
        try:
            with open(_wl_file, "r", encoding="utf-8") as f:
                _wl = json.load(f)
            _cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            _added = 0
            _skipped = 0
            _existing_codes = {s[0] for s in all_stocks}
            for _fc, _stock in _wl.get("stocks", {}).items():
                _last = _stock.get("last_seen", "")
                if _last and _last >= _cutoff:
                    _code = _stock.get("code", _fc)
                    if _code not in _existing_codes:
                        _name = _stock.get("name", "")
                        # 正确区分A股/港股市场
                        _stock_market = _stock.get("market", "")
                        _full_code = _stock.get("full_code", "")
                        if _stock_market == "港股" or _full_code.startswith("HK"):
                            _mkt = "hk"
                        elif _code.startswith("6") or _code.startswith("688"):
                            _mkt = "sh"
                        else:
                            _mkt = "sz"
                        # 验证代码格式（缺前导零的代码会卡死扫描器）
                        _ok, _reason = _validate_stock_code(str(_code), _mkt)
                        if not _ok:
                            _skipped += 1
                            continue
                        # (code, name, market, board_label, volume_amount, turnover_rate, mv_yi, fund_type)
                        all_stocks.append((_code, _name, _mkt, "投行关注池", 0, 0, 0, "混合"))
                        _existing_codes.add(_code)
                        _added += 1
            print(f"    投行研报关注池(30天): +{_added} 只")
            if _skipped > 0:
                print(f"    [跳过] {_skipped} 只代码格式不合法")
        except Exception as e:
            print(f"  [投行研报] 读取关注池失败: {e}")

    return all_stocks


def _fetch_hk_volume_top_westock(top_n):
    """用 westock-data (腾讯自选股) 获取港股成交量 Top N（按成交额实时排序）
    
    原理：对大池港股批量查询实时行情，按 amount（成交额）降序取 Top N。
    这是最准确的"成交量前50"，因为 westock-data 直连腾讯自选股数据。
    """
    try:
        # 延迟导入 shared 目录
        _shared_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared")
        if _shared_dir not in sys.path:
            sys.path.insert(0, _shared_dir)
        from westock_helper import get_quote
    except Exception as e:
        print(f"  [westock] 导入失败: {e}")
        return []
    
    BATCH_SIZE = 30  # 每批最多30只
    all_rows = []
    
    for i in range(0, len(_HK_FALLBACK_POOL), BATCH_SIZE):
        batch = _HK_FALLBACK_POOL[i:i+BATCH_SIZE]
        codes = ",".join([f"hk{code}" for code, _ in batch])
        try:
            rows = get_quote(codes)
            if rows:
                all_rows.extend(rows)
            print(f"    westock 批次 {i//BATCH_SIZE+1}: {len(rows)} 只")
        except Exception as e:
            print(f"    [westock] 批次 {i//BATCH_SIZE+1} 失败: {e}")
        time.sleep(0.3)
    
    if not all_rows:
        print("  [westock] 所有批次均失败")
        return []
    
    # 按成交额降序排序
    for r in all_rows:
        try:
            r['_amount'] = float(r.get('amount', 0) or 0)
        except (ValueError, TypeError):
            r['_amount'] = 0
    
    all_rows.sort(key=lambda x: -x['_amount'])
    
    stocks = []
    count = 0
    for r in all_rows:
        code = r.get('code', '').replace('hk', '')
        name = str(r.get('name', '')).replace('\x00', '').strip()
        if not code or not name:
            continue
        try:
            price = float(r.get('price', 0) or 0)
        except (ValueError, TypeError):
            price = 0
        if price <= 0:
            continue
        
        amount = r['_amount']
        try:
            total_mv = float(r.get('total_market_cap', 0) or 0)
        except (ValueError, TypeError):
            total_mv = 0
        mv_yi = total_mv / 1e8 if total_mv > 0 else 0
        
        stocks.append((code, name, "hk", "港股", amount, 0, mv_yi, "港股"))
        count += 1
        if count >= top_n:
            break
    
    if stocks:
        _data_source_stats["qq"] += 1  # 标记为腾讯自选股来源
    
    return stocks


def _fetch_hk_volume_top(top_n):
    """获取港股成交量Top N (westock → efinance → 东方财富 → 硬编码抢救池)
    
    四层抢救：
    1. westock-data (腾讯自选股，实时成交量排序，最准确 ✅)
    2. efinance (兜底)
    3. 东方财富 push2 API (次兜底)
    4. 硬编码池 (最终抢救 — API全断时用，按固定顺序)
    """
    # 源1: westock-data (最高优先级 — 实时成交量排序)
    stocks = _fetch_hk_volume_top_westock(top_n)
    if stocks:
        return stocks
    
    # 源2: efinance (带重试)
    for attempt in range(MAX_RETRIES):
        try:
            import efinance as ef
            df = ef.stock.get_realtime_quotes()
            if df is not None and len(df) > 0:
                # efinance返回港股数据，筛选
                # 按成交额排序
                if '成交额' in df.columns:
                    df = df.sort_values('成交额', ascending=False)
                stocks = []
                count = 0
                for _, row in df.head(top_n + 50).iterrows():
                    code = str(row.get('股票代码', '')).zfill(5)
                    name = str(row.get('股票名称', '')).replace('\x00', '').strip()
                    if not code or not name:
                        continue
                    if any(x in name for x in ["优先", "信托", "ETF", "REIT", "基金", "衍"]):
                        continue
                    price = row.get('最新价', 0)
                    if not price or float(price) <= 0:
                        continue
                    volume_amount = row.get('成交额', 0)
                    try:
                        volume_amount = float(volume_amount)
                    except:
                        volume_amount = 0
                    stocks.append((code, name, "hk", "港股", volume_amount, 0, 0, "港股"))
                    count += 1
                    if count >= top_n:
                        break
                if stocks:
                    _data_source_stats["efinance"] += 1
                    return stocks
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  [重试] efinance港股列表 第{attempt+2}次...")
                time.sleep(1.5 * (attempt + 1))
            else:
                print(f"[WARN] efinance港股列表失败(已重试{MAX_RETRIES}次): {e}")

    # 源3: 东方财富 (带重试)
    for attempt in range(MAX_RETRIES):
        try:
            url = "https://82.push2.eastmoney.com/api/qt/clist/get"
            params = {
                "pn": 1, "pz": top_n + 50, "po": 1, "np": 1,
                "fltt": 2, "invt": 2, "fid": "f6",
                "fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2",
                "fields": "f12,f14,f2,f3,f6,f8,f20,f21"
            }
            r = requests.get(url, params=params, timeout=15)
            data = r.json().get("data", {})
            diff = data.get("diff", [])
            if not diff:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue

            stocks = []
            count = 0
            for item in diff:
                code = str(item.get("f12", "")).zfill(5)
                name = str(item.get("f14", "")).replace('\x00', '').strip()
                if not code or not name:
                    continue
                if any(x in name for x in ["优先", "信托", "ETF", "REIT", "基金", "衍"]):
                    continue
                price = item.get("f2", "-")
                if price == "-" or price <= 0:
                    continue
                volume_amount = item.get("f6", 0)
                total_mv = item.get("f20", 0)
                mv_yi = (total_mv / 1e8) if total_mv and total_mv > 0 else 0
                stocks.append((code, name, "hk", "港股", volume_amount, 0, mv_yi, "港股"))
                count += 1
                if count >= top_n:
                    break
            if stocks:
                _data_source_stats["eastmoney"] += 1
            return stocks
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  [重试] 东方财富港股列表 第{attempt+2}次...")
                time.sleep(1.5 * (attempt + 1))
            else:
                print(f"[WARN] 东方财富港股列表失败(已重试{MAX_RETRIES}次): {e}")

    # 源4: 硬编码抢救池 (最终兜底)
    print(f"[抢救] API全断，使用硬编码港股池 {len(_HK_FALLBACK_POOL)} 只")
    stocks = []
    for code, name in _HK_FALLBACK_POOL[:top_n]:
        stocks.append((code, name, "hk", "港股", 0, 0, 0, "港股"))
    return stocks


# 保留旧接口兼容(gold pool等)
def fetch_a_stock_list():
    """兼容旧接口: 返回全量A股(按成交量排序取前300+金股池)"""
    stocks = fetch_volume_top_stocks()
    return [(s[0], s[1], s[2]) for s in stocks]


def fetch_hk_stock_list():
    """兼容旧接口"""
    hk = _fetch_hk_volume_top(VOLUME_TOP_HK)
    return [(s[0], s[1], s[2]) for s in hk]


# ============== K线数据获取(三重源) ==============

def fetch_a_daily(code, bars=None):
    """获取A股日K数据 - 三重源: mootdx → BaoStock → 东方财富"""
    global _bs_consecutive_fails, _data_source_stats
    if bars is None:
        bars = DAILY_BARS

    # 源1: mootdx (通达信直连, 无调用限制)
    try:
        client = _get_tdx_client()
        if client is not None:
            df = client.bars(symbol=code, category=9, offset=bars)
            if df is not None and len(df) >= 60:
                result = pd.DataFrame({
                    "date": df.index.strftime("%Y-%m-%d"),
                    "open": df["open"].astype(float),
                    "close": df["close"].astype(float),
                    "high": df["high"].astype(float),
                    "low": df["low"].astype(float),
                    "volume": df["vol"].astype(float),
                    "pct_chg": 0.0,
                }).reset_index(drop=True)
                if len(result) > 1:
                    result["pct_chg"] = ((result["close"] / result["close"].shift(1) - 1) * 100).round(2)
                _data_source_stats["mootdx"] += 1
                return result
    except Exception:
        pass

    # 源2: BaoStock (证券宝, 免费稳定)
    # 连续失败过多时跳过，避免拖慢整体扫描
    if _bs_consecutive_fails < _BS_FAIL_SKIP_THRESHOLD:
        try:
            _bs_login()
            import baostock as bs
            # BaoStock代码格式: sh.600000 / sz.000001
            if code.startswith("6") or code.startswith("688"):
                bs_code = f"sh.{code}"
            else:
                bs_code = f"sz.{code}"
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=bars * 2)).strftime("%Y-%m-%d")

            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,turn,pctChg",
                start_date=start_date, end_date=end_date,
                frequency="d", adjustflag="2"
            )
            rows = []
            while (rs.error_code == '0') and rs.next():
                rows.append(rs.get_row_data())

            if rows:
                kdf = pd.DataFrame(rows, columns=rs.fields)
                kdf = kdf[kdf['close'].astype(str) != '']
                if len(kdf) >= 60:
                    result = pd.DataFrame({
                        "date": kdf["date"],
                        "open": kdf["open"].astype(float),
                        "close": kdf["close"].astype(float),
                        "high": kdf["high"].astype(float),
                        "low": kdf["low"].astype(float),
                        "volume": kdf["volume"].astype(float),
                        "pct_chg": kdf["pctChg"].astype(float) if "pctChg" in kdf.columns else 0.0,
                    }).reset_index(drop=True)
                    _data_source_stats["baostock"] += 1
                    _bs_consecutive_fails = 0
                    return result
            # 无有效数据也算失败
            _bs_consecutive_fails += 1
        except Exception:
            _bs_consecutive_fails += 1
            pass

    # 源3: 东方财富 (兜底)
    for attempt in range(MAX_RETRIES):
        try:
            if code.startswith("6"):
                secid = f"1.{code}"
            else:
                secid = f"0.{code}"

            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "secid": secid,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
                "klt": 101, "fqt": 1,
                "beg": "0", "end": "20500101",
                "lmt": bars,
            }
            r = requests.get(url, params=params, timeout=5)
            data = r.json().get("data", {})
            klines = data.get("klines", [])
            if not klines:
                return None

            rows = []
            for line in klines:
                parts = line.split(",")
                if len(parts) >= 7:
                    rows.append({
                        "date": parts[0],
                        "open": float(parts[1]),
                        "close": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "volume": float(parts[5]),
                        "pct_chg": 0.0,
                    })

            df = pd.DataFrame(rows)
            if len(df) > 1:
                df["pct_chg"] = ((df["close"] / df["close"].shift(1) - 1) * 100).round(2)
            else:
                df["pct_chg"] = 0.0
            _data_source_stats["eastmoney"] += 1
            return df.reset_index(drop=True)
        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(0.5 * (attempt + 1))
            continue

    _data_source_stats["fail"] += 1
    return None


def fetch_hk_daily(code, bars=None):
    """获取港股日K数据 - efinance → 东方财富 → QQ财付通(抢救)

    三层抢救：
    1. efinance (优先)
    2. 东方财富 push2his (兜底，已验证可用)
    3.     QQ/腾讯财付通 API (最终抢救)
    """
    if bars is None:
        bars = DAILY_BARS

    # 源1: efinance
    try:
        import efinance as ef
        # efinance用代码获取K线
        df = ef.stock.get_quote_history(code)
        if df is not None and len(df) >= 60:
            result = pd.DataFrame({
                "date": df["日期"].astype(str),
                "open": df["开盘"].astype(float),
                "close": df["收盘"].astype(float),
                "high": df["最高"].astype(float),
                "low": df["最低"].astype(float),
                "volume": df["成交量"].astype(float),
                "pct_chg": df.get("涨跌幅", pd.Series(0, index=df.index)).astype(float),
            }).tail(bars).reset_index(drop=True)
            _data_source_stats["efinance"] += 1
            return result
    except Exception:
        pass

    # 源2: 东方财富 (兜底)
    for attempt in range(MAX_RETRIES):
        try:
            secid = f"116.{code}"
            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "secid": secid,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
                "klt": 101, "fqt": 1,
                "beg": "0", "end": "20500101",
                "lmt": bars,
            }
            r = requests.get(url, params=params, timeout=5)
            data = r.json().get("data", {})
            klines = data.get("klines", [])
            if not klines:
                return None

            rows = []
            for line in klines:
                parts = line.split(",")
                if len(parts) >= 7:
                    rows.append({
                        "date": parts[0],
                        "open": float(parts[1]),
                        "close": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "volume": float(parts[5]),
                        "pct_chg": 0.0,
                    })

            df = pd.DataFrame(rows)
            if len(df) > 1:
                df["pct_chg"] = ((df["close"] / df["close"].shift(1) - 1) * 100).round(2)
            else:
                df["pct_chg"] = 0.0
            _data_source_stats["eastmoney"] += 1
            return df.reset_index(drop=True)
        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(0.5 * (attempt + 1))
            continue

    # 源3: QQ/腾讯财付通 (最终抢救)
    try:
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        params = {"param": f"hk{code},day,,,{bars},qfq"}
        r = requests.get(url, params=params, timeout=10)
        d = r.json()
        stock_data = d.get("data", {}).get(f"hk{code}", {})
        days = stock_data.get("qfqday", stock_data.get("day", []))
        if not days or len(days) < 30:
            return None

        rows = []
        for day in days:
            rows.append({
                "date": day[0],
                "open": float(day[1]),
                "close": float(day[2]),
                "high": float(day[3]),
                "low": float(day[4]),
                "volume": float(day[5]),
                "pct_chg": 0.0,
            })

        df = pd.DataFrame(rows)
        if len(df) > 1:
            df["pct_chg"] = ((df["close"] / df["close"].shift(1) - 1) * 100).round(2)
        else:
            df["pct_chg"] = 0.0
        _data_source_stats["qq"] += 1
        return df.reset_index(drop=True)
    except Exception:
        pass

    _data_source_stats["fail"] += 1
    return None


# ============== 信号检测 ==============

def check_stock_signals(code, name, market="sh", board_label="", volume_amount=0, turnover_rate=0, mv_yi=0, fund_type=""):
    """
    检测个股三线共振信号(仅日K)
    返回: dict 含信号详情
    """
    # 获取日K数据
    if market == "hk":
        df = fetch_hk_daily(code)
    else:
        df = fetch_a_daily(code)
    
    if df is None or len(df) < 60:
        return None

    try:
        # 缠论买字(日K)
        df = calc_chanlun_signal(df)
        recent = df.tail(3)
        缠论买 = bool((recent["极点保留"] == -1).any())

        # 金钻趋势
        df = calc_jinzuan_signal(df)
        last = df.iloc[-1]
        黄柱 = bool(last.get("黄柱", False))
        金钻起涨 = bool(last.get("金钻起涨", False))
        金钻信号 = 黄柱 or 金钻起涨

        # 四量图机构变红
        df = calc_siliang_signal(df)
        last = df.iloc[-1]
        机构变红 = bool(last.get("机构变红", False))

        # 上涨趋势预警选股(日K)
        df = calc_uptrend_signal(df)
        last = df.iloc[-1]
        上涨趋势_条件1 = bool(last.get("上涨趋势_条件1", False))
        上涨趋势_条件2 = bool(last.get("上涨趋势_条件2", False))
        上涨趋势_条件3 = bool(last.get("上涨趋势_条件3", False))
        上涨趋势_条件4 = bool(last.get("上涨趋势_条件4", False))
        上涨趋势 = bool(last.get("上涨趋势", False))

        # ===== 次日开盘确认（摘星阁逻辑）=====
        try:
            prev = df.iloc[-2]  # 前一根完整K线
            prev_close = float(prev["close"])
            今开 = float(last.get("open", last["close"]))
            今收 = float(last["close"])
            今高 = float(last.get("high", 今收))
            今低 = float(last.get("low", 今收))
            振幅 = (今高 - 今低) / prev_close if prev_close > 0 else 0
            开盘_高开 = 今开 > prev_close
            开盘_低开 = 今开 < prev_close
            开盘_阳线 = 今收 > 今开
            开盘_阴线 = 今收 < 今开
            开盘_长腿 = 振幅 > 0.03
            # 组合标签
            if 开盘_高开 and 开盘_阳线:
                开盘_标签 = "🔥高开高走"
            elif 开盘_高开 and 开盘_阴线:
                开盘_标签 = "⚠️高开低走"
            elif 开盘_低开 and 开盘_阳线:
                开盘_标签 = "⚡低开高走"
            elif 开盘_低开 and 开盘_阴线:
                开盘_标签 = "📉低开低走"
            elif 开盘_高开:
                开盘_标签 = "📈高开"
            elif 开盘_低开:
                开盘_标签 = "📉低开"
            else:
                开盘_标签 = "➖平开"
            if 开盘_长腿 and 开盘_阳线:
                开盘_标签 = "🦵长腿收阳 " + 开盘_标签
            elif 开盘_长腿 and 开盘_阴线:
                开盘_标签 = "🦵长腿收阴 " + 开盘_标签
        except Exception:
            开盘_标签 = "—"
            开盘_高开 = 开盘_低开 = 开盘_阳线 = 开盘_阴线 = 开盘_长腿 = False

        # 信号统计
        signal_count = sum([缠论买, 金钻信号, 机构变红, 上涨趋势])
        # 三线共振：四个信号中满足任意三种
        三线共振 = signal_count >= 3
        # 三足鼎立：四信号全满足（最难出现）
        三足鼎立 = signal_count == 4

        # RSI(14) — 用于风控和评分
        try:
            rsi_series = calc_rsi(df["close"], 14)
            current_rsi = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50.0
        except Exception:
            current_rsi = 50.0

        # 信号评分(信号质量: RSI>70扣分, 换手>3%加分)
        signal_score = calc_signal_score(signal_count, current_rsi, turnover_rate)

        # 涨跌幅
        pct = float(last.get("pct_chg", 0)) if "pct_chg" in df.columns else 0
        close_price = float(last["close"])

        # 近5日缠论买字次数(信号强度)
        recent5 = df.tail(5)
        缠论买次数 = int((recent5["极点保留"] == -1).sum())

        # 成交额格式化
        if volume_amount and volume_amount > 0:
            if volume_amount >= 1e8:
                volume_str = f"{volume_amount/1e8:.1f}亿"
            elif volume_amount >= 1e4:
                volume_str = f"{volume_amount/1e4:.0f}万"
            else:
                volume_str = f"{volume_amount:.0f}"
        else:
            volume_str = "-"

        return {
            "code": code,
            "name": name,
            "market": market,
            "market_label": "港股" if market == "hk" else ("沪" if code.startswith("6") else "深"),
            "board_label": board_label or ("港股" if market == "hk" else ("科创板" if code.startswith("688") else ("创业板" if code.startswith("300") else "主板"))),
            "close": round(close_price, 2),
            "pct_chg": round(pct, 2),
            "pct_chg_20d": calc_pct_chg_n(df, 20),
            "volume_str": volume_str,
            "turnover_rate": round(turnover_rate, 2) if turnover_rate else 0,
            "mv_yi": round(mv_yi, 1) if mv_yi else 0,
            "rsi_14": round(current_rsi, 1),
            "signal_score": signal_score,
            "fund_type": fund_type or "混合",
            "缠论买_日K": 缠论买,
            "缠论买_次数": 缠论买次数,
            "金钻_黄柱": 黄柱,
            "金钻_起涨": 金钻起涨,
            "四量图_机构变红": 机构变红,
            "上涨趋势_条件1": 上涨趋势_条件1,
            "上涨趋势_条件2": 上涨趋势_条件2,
            "上涨趋势_条件3": 上涨趋势_条件3,
            "上涨趋势_条件4": 上涨趋势_条件4,
            "上涨趋势": 上涨趋势,
            "三线共振": 三线共振,
            "三足鼎立": 三足鼎立,
            "signal_count": signal_count,
            "开盘_标签": 开盘_标签,
            "开盘_高开": 开盘_高开,
            "开盘_低开": 开盘_低开,
            "开盘_阳线": 开盘_阳线,
            "开盘_阴线": 开盘_阴线,
            "开盘_长腿": 开盘_长腿,
            "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            # latest 副本（供 dashboard JS 直接使用，无需嵌套判断）
            "latest": {
                "close": round(close_price, 2),
                "pct_chg": round(pct, 2),
                "pct_chg_20d": calc_pct_chg_n(df, 20),
                "rsi_14": round(current_rsi, 1),
                "signal_score": signal_score,
                "turnover_rate": round(turnover_rate, 2) if turnover_rate else 0,
                "缠论买_日K": 缠论买,
                "缠论买_次数": 缠论买次数,
                "金钻_黄柱": 黄柱,
                "金钻_起涨": 金钻起涨,
                "四量图_机构变红": 机构变红,
                "上涨趋势_条件1": 上涨趋势_条件1,
                "上涨趋势_条件2": 上涨趋势_条件2,
                "上涨趋势_条件3": 上涨趋势_条件3,
                "上涨趋势_条件4": 上涨趋势_条件4,
                "上涨趋势": 上涨趋势,
                "三线共振": 三线共振,
                "三足鼎立": 三足鼎立,
                "signal_count": signal_count,
                "开盘_标签": 开盘_标签,
                "开盘_高开": 开盘_高开,
                "开盘_低开": 开盘_低开,
                "开盘_阳线": 开盘_阳线,
                "开盘_阴线": 开盘_阴线,
            },
        }
    except Exception as e:
        print(f"    [ERR] {code} {name} 指标计算失败: {e}")
        return None


# ============== 金股池管理 ==============

def load_gold_pool():
    """加载金股池"""
    if not os.path.exists(GOLD_POOL_JSON):
        return {"stocks": {}, "last_update": None}
    try:
        with open(GOLD_POOL_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"stocks": {}, "last_update": None}


def save_gold_pool(pool):
    """保存金股池"""
    with open(GOLD_POOL_JSON, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)


# 股票名称修复白名单
_GUANLAN_NAME_WHITELIST = {'和林微纳', '和而泰', '和顺石油', '和晶科技', '和远气体', '和邦生物',
                           '和辉光电', '和佳医疗', '和金科技', '和元生物'}


def _repair_guanlan_name(name: str) -> str:
    """修复 guanlan 提取的垃圾股票名称"""
    if not name or len(name) < 2:
        return name

    # 白名单保护
    if name in _GUANLAN_NAME_WHITELIST:
        return name

    # 1. 去掉句子前缀
    garbage_prefixes = ['我们给予', '新客户包括', '但随着', '其次是',
                        '新增', '带动', '包括', '给予', '及', '和']
    for p in sorted(garbage_prefixes, key=len, reverse=True):
        if name.startswith(p) and len(name) > len(p) + 1:
            candidate = name[len(p):]
            if candidate in _GUANLAN_NAME_WHITELIST:
                continue
            name = candidate
            break

    # 2. 截断描述性后缀
    tail_markers = ['主要依靠', '近期与', '的风险', '首选']
    for m in tail_markers:
        idx = name.find(m)
        if idx >= 2:
            name = name[:idx]
            break

    # 3. 去末尾未闭合括号
    name = re.sub(r'[（(][^）)]*$', '', name)

    # 4. 去末尾「X有限公司」
    name = re.sub(r'(科技|股份|有限|投资|控股|集团|实业|证券)有限公司$', '', name)

    return name.strip('，,。.、；;：:（）()·')


def _convert_guanlan_to_pool_entry(gl_stock, today):
    """将投行研报股票转换为金股池条目格式"""
    code = str(gl_stock.get("code", ""))
    market_raw = gl_stock.get("market", "")
    full_code = gl_stock.get("full_code", "")
    raw_name = gl_stock.get("name", "")

    # 代码标准化：港股补前导零到5位，A股补到6位，防止脏数据再入
    if market_raw == "港股":
        code = code.zfill(5)
    else:
        code = code.zfill(6)

    # 名称清洗：修复 guanlan 解析错误
    name = _repair_guanlan_name(raw_name)

    # 如果修复后名称仍然含垃圾关键词，跳过
    bad_keywords = ['我们的', '首选', '给予', '带动', '新增', '包括', '主要依靠',
                    '的风险', '近期与', '成立']
    if any(kw in name for kw in bad_keywords) and name not in _GUANLAN_NAME_WHITELIST:
        return None  # 返回 None 表示跳过此条目

    # 市场映射
    if market_raw == "港股":
        market = "hk"
        board_label = "港股"
    elif "SH" in full_code.upper() or code.startswith("6"):
        market = "sh"
        board_label = "科创板" if code.startswith("688") else "主板"
    elif "SZ" in full_code.upper() or code.startswith(("0", "3")):
        market = "sz"
        board_label = "创业板" if code.startswith("300") else "主板"
    else:
        market = "sh"
        board_label = ""

    return {
        "code": code,
        "name": name,
        "market": market,
        "board_label": board_label,
        "fund_type": "",
        "first_date": today,
        "first_signal": 0,
        "max_signal": 0,
        "history": [],
        "sources": ["投行研报"],
    }


def update_gold_pool_from_scan(output):
    """盘后扫描后更新金股池(合并近3天信号股 + 投行研报推荐)"""
    pool = load_gold_pool()
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = get_n_trade_days_ago(GOLD_POOL_DAYS)

    # 清理过期股票（投行研报来源的不过期，它们没有first_date限制）
    expired_keys = [k for k, v in pool["stocks"].items()
                    if v.get("first_date", "") < cutoff
                    and "投行研报" not in v.get("sources", [])]
    for k in expired_keys:
        del pool["stocks"][k]

    # 添加/更新本次扫描中有信号的股票
    for s in output.get("all_results", []):
        if s.get("signal_count", 0) >= 1:
            key = f"{s['market']}_{s['code']}"
            if key not in pool["stocks"]:
                pool["stocks"][key] = {
                    "code": s["code"],
                    "name": s["name"],
                    "market": s["market"],
                    "board_label": s.get("board_label", ""),
                    "fund_type": s.get("fund_type", ""),
                    "first_date": today,
                    "first_signal": s["signal_count"],
                    "max_signal": s["signal_count"],
                    "history": [],
                    "sources": ["三足鼎立"],
                }
            else:
                pool["stocks"][key]["max_signal"] = max(
                    pool["stocks"][key]["max_signal"], s["signal_count"]
                )
                # 更新板块/资金类型
                pool["stocks"][key]["board_label"] = s.get("board_label", pool["stocks"][key].get("board_label", ""))
                pool["stocks"][key]["fund_type"] = s.get("fund_type", pool["stocks"][key].get("fund_type", ""))
                # 确保sources列表存在，添加三足鼎立来源
                if "sources" not in pool["stocks"][key]:
                    pool["stocks"][key]["sources"] = ["三足鼎立"]
                elif "三足鼎立" not in pool["stocks"][key]["sources"]:
                    pool["stocks"][key]["sources"].append("三足鼎立")

            # 记录每日信号
            history_entry = {
                "date": today,
                "signal_count": s["signal_count"],
                "close": s["close"],
                "pct_chg": s["pct_chg"],
                "缠论买_日K": s.get("缠论买_日K", False),
                "金钻_黄柱": s.get("金钻_黄柱", False),
                "金钻_起涨": s.get("金钻_起涨", False),
                "四量图_机构变红": s.get("四量图_机构变红", False),
                "上涨趋势_条件1": s.get("上涨趋势_条件1", False),
                "上涨趋势_条件2": s.get("上涨趋势_条件2", False),
                "上涨趋势_条件3": s.get("上涨趋势_条件3", False),
                "上涨趋势_条件4": s.get("上涨趋势_条件4", False),
                "上涨趋势": s.get("上涨趋势", False),
                "三线共振": s.get("三线共振", False),
                # latest 副本（供 dashboard JS 直接使用）
                "latest": {
                    "缠论买_日K": s.get("缠论买_日K", False),
                    "金钻_黄柱": s.get("金钻_黄柱", False),
                    "金钻_起涨": s.get("金钻_起涨", False),
                    "四量图_机构变红": s.get("四量图_机构变红", False),
                    "上涨趋势_条件1": s.get("上涨趋势_条件1", False),
                    "上涨趋势_条件2": s.get("上涨趋势_条件2", False),
                    "上涨趋势_条件3": s.get("上涨趋势_条件3", False),
                    "上涨趋势_条件4": s.get("上涨趋势_条件4", False),
                    "上涨趋势": s.get("上涨趋势", False),
                    "signal_count": s["signal_count"],
                },
            }
            pool["stocks"][key]["history"].append(history_entry)
            # 更新名称(可能有变化)
            pool["stocks"][key]["name"] = s["name"]

    # 合并投行研报推荐股票到金股池
    guanlan_count = 0
    try:
        from guanlan_extractor import load_watchlist
        wl = load_watchlist()
        for fc, gl_stock in wl.get("stocks", {}).items():
            entry = _convert_guanlan_to_pool_entry(gl_stock, today)
            if entry is None or not entry["code"]:
                continue
            key = f"{entry['market']}_{entry['code']}"
            if key not in pool["stocks"]:
                pool["stocks"][key] = entry
                guanlan_count += 1
            else:
                # 已存在的股票，追加投行研报来源
                if "sources" not in pool["stocks"][key]:
                    pool["stocks"][key]["sources"] = []
                if "投行研报" not in pool["stocks"][key]["sources"]:
                    pool["stocks"][key]["sources"].append("投行研报")
    except ImportError:
        pass

    pool["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pool["total_count"] = len(pool["stocks"])

    save_gold_pool(pool)
    print(f"  金股池已更新: {pool['total_count']} 只")
    print(f"    三足鼎立信号股 + 投行研报 {guanlan_count} 只 (保留{GOLD_POOL_DAYS}个交易日)")
    return pool


def update_gold_pool_from_watch(watch_output):
    """盘中精监后更新金股池"""
    pool = load_gold_pool()
    today = datetime.now().strftime("%Y-%m-%d")

    for s in watch_output.get("all_results", []):
        key = f"{s['market']}_{s['code']}"
        if key in pool["stocks"]:
            # 更新已有股票的今日信号
            pool["stocks"][key]["history"] = [
                h for h in pool["stocks"][key]["history"] if h["date"] != today
            ]
            pool["stocks"][key]["history"].append({
                "date": today,
                "signal_count": s["signal_count"],
                "close": s["close"],
                "pct_chg": s["pct_chg"],
                "缠论买_日K": s.get("缠论买_日K", False),
                "金钻_黄柱": s.get("金钻_黄柱", False),
                "金钻_起涨": s.get("金钻_起涨", False),
                "四量图_机构变红": s.get("四量图_机构变红", False),
                "上涨趋势_条件1": s.get("上涨趋势_条件1", False),
                "上涨趋势_条件2": s.get("上涨趋势_条件2", False),
                "上涨趋势_条件3": s.get("上涨趋势_条件3", False),
                "上涨趋势_条件4": s.get("上涨趋势_条件4", False),
                "上涨趋势": s.get("上涨趋势", False),
                "三线共振": s.get("三线共振", False),
            })
            pool["stocks"][key]["max_signal"] = max(
                pool["stocks"][key]["max_signal"], s["signal_count"]
            )
            # 更新板块/资金类型
            pool["stocks"][key]["board_label"] = s.get("board_label", pool["stocks"][key].get("board_label", ""))
            pool["stocks"][key]["fund_type"] = s.get("fund_type", pool["stocks"][key].get("fund_type", ""))
        elif s.get("signal_count", 0) >= 2:
            # 盘中新发现双线以上，加入金股池
            pool["stocks"][key] = {
                "code": s["code"],
                "name": s["name"],
                "market": s["market"],
                "board_label": s.get("board_label", ""),
                "fund_type": s.get("fund_type", ""),
                "first_date": today,
                "first_signal": s["signal_count"],
                "max_signal": s["signal_count"],
                "sources": ["三足鼎立"],
                "history": [{
                    "date": today,
                    "signal_count": s["signal_count"],
                    "close": s["close"],
                    "pct_chg": s["pct_chg"],
                    "缠论买_日K": s.get("缠论买_日K", False),
                    "金钻_黄柱": s.get("金钻_黄柱", False),
                    "金钻_起涨": s.get("金钻_起涨", False),
                    "四量图_机构变红": s.get("四量图_机构变红", False),
                "三线共振": s.get("三线共振", False),
                "上涨趋势_条件1": s.get("上涨趋势_条件1", False),
                "上涨趋势_条件2": s.get("上涨趋势_条件2", False),
                "上涨趋势_条件3": s.get("上涨趋势_条件3", False),
                "上涨趋势_条件4": s.get("上涨趋势_条件4", False),
                "上涨趋势": s.get("上涨趋势", False),
            }]
            }

    pool["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pool["total_count"] = len(pool["stocks"])

    save_gold_pool(pool)
    return pool


# ============== 信号复核（回测验证）==============

def calc_signal_backtest():
    """
    信号复核：对金股池中每只股票做回测验证
    对比入池价 vs 最新价，计算胜率、平均收益、分布
    输出 signal_backtest.json
    """
    pool = load_gold_pool()
    stocks = pool.get("stocks", {})
    if not stocks:
        print("[复核] 金股池为空，跳过")
        return {"total": 0, "win_rate": 0, "results": []}

    results = []
    win = 0
    loss = 0
    total_ret = 0.0

    for key, entry in stocks.items():
        history = entry.get("history", [])
        if len(history) < 1:
            continue

        # 入池价 = 第一天收盘价
        entry_price = history[0].get("close", 0) or 0
        # 最新价 = 最后一天收盘价
        latest_price = history[-1].get("close", 0) or 0
        if entry_price <= 0:
            continue

        ret_pct = (latest_price - entry_price) / entry_price * 100
        is_win = ret_pct > 0
        if is_win:
            win += 1
        else:
            loss += 1
        total_ret += ret_pct

        results.append({
            "code": entry.get("code", ""),
            "name": entry.get("name", ""),
            "market": entry.get("market", ""),
            "board_label": entry.get("board_label", ""),
            "signal_count": entry.get("max_signal", 0),
            "entry_date": entry.get("first_date", ""),
            "entry_price": round(entry_price, 2),
            "latest_price": round(latest_price, 2),
            "return_pct": round(ret_pct, 2),
            "is_win": is_win,
            "days_in_pool": len(history),
            "sources": entry.get("sources", []),
        })

    total_count = len(results)
    win_rate = round(win / total_count * 100, 1) if total_count > 0 else 0
    avg_ret = round(total_ret / total_count, 2) if total_count > 0 else 0

    # 按收益排序
    results_sorted = sorted(results, key=lambda x: -x["return_pct"])

    backtest = {
        "calc_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_count": total_count,
        "win_count": win,
        "loss_count": loss,
        "win_rate": win_rate,
        "avg_return": avg_ret,
        "best3": results_sorted[:3],
        "worst3": results_sorted[-3:] if len(results_sorted) >= 3 else [],
        "results": results_sorted,
    }

    with open(SIGNAL_BACKTEST_JSON, "w", encoding="utf-8") as f:
        json.dump(backtest, f, ensure_ascii=False, indent=2)

    print(f"[复核] 信号复核完成: 共{total_count}只 | 胜率{win_rate}% | 平均收益{avg_ret:+.2f}%")
    print(f"      盈利:{win}只 | 亏损:{loss}只")
    return backtest




def _validate_stock_code(code, market):
    """验证股票代码格式，返回 (valid, reason)
    
    规则: A股6位数字, 港股5位数字 (前导零)
    不合法代码会直接导致数据源卡死，必须提前过滤
    """
    digits = code.replace('.', '').replace('-', '').strip()
    if not digits.isdigit():
        return False, f"含非数字字符: {code}"
    if market == 'hk':
        if len(digits) != 5:
            return False, f"港股需5位数字, 实际{len(digits)}: {code}"
    else:
        if len(digits) != 6:
            return False, f"A股需6位数字, 实际{len(digits)}: {code}"
    return True, ""


def _scan_one_stock(args):
    """单只股票扫描(用于多线程)"""
    stock, _preload_stocks = args
    code, name, market = stock[0], stock[1], stock[2]
    board_label = stock[3] if len(stock) > 3 else ""
    volume_amount = stock[4] if len(stock) > 4 else 0
    turnover_rate = stock[5] if len(stock) > 5 else 0
    mv_yi = stock[6] if len(stock) > 6 else 0
    fund_type = stock[7] if len(stock) > 7 else ""

    try:
        result = check_stock_signals(code, name, market, board_label, volume_amount, turnover_rate, mv_yi, fund_type)
        if result is not None:
            pool_key = f"{market}_{code}"
            result["sources"] = _preload_stocks.get(pool_key, {}).get("sources", ["三足鼎立"])
        return (result, None)
    except Exception as e:
        return (None, {
            "code": code, "name": name, "market": market,
            "source": "mootdx/baostock",
            "reason": f"{type(e).__name__}: {str(e)[:80]}",
        })

def scan_market(scan_a=True, scan_hk=True, max_stocks=None, resume=False):
    """盘后扫描(成交量排序活跃股池), 支持断点续扫 + 多线程并行"""
    global _error_details, _bs_consecutive_fails
    _error_details = []
    _bs_consecutive_fails = 0  # 每次扫描重置 BaoStock 失败计数
    print(f"\n{'='*60}")
    print(f"选股观测台 - 盘后扫描(活跃股池) {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # 获取成交量排序股池
    print("[1/3] 获取活跃股池(按成交量排序)...")
    all_stocks = fetch_volume_top_stocks()

    if max_stocks and len(all_stocks) > max_stocks:
        all_stocks = all_stocks[:max_stocks]

    print(f"  股池总计: {len(all_stocks)} 只")

    # 断点续扫: 加载已有进度
    results = []
    三线共振_list = []
    双线共振_list = []
    errors = 0
    start_idx = 0

    if resume and os.path.exists(PROGRESS_JSON):
        try:
            with open(PROGRESS_JSON, "r", encoding="utf-8") as f:
                progress = json.load(f)
            results = progress.get("results", [])
            三线共振_list = progress.get("triple", [])
            双线共振_list = progress.get("double", [])
            errors = progress.get("errors", 0)
            start_idx = progress.get("next_idx", 0)
            print(f"  断点续扫: 从第{start_idx+1}只开始 (已完成{start_idx}只)")
        except:
            start_idx = 0

    print(f"\n[3/3] 开始扫描 {len(all_stocks)} 只股票 (从第{start_idx+1}只开始)...")

    # 预加载金股池，用于交叉引用来源标签
    _preload_pool = load_gold_pool()
    _preload_stocks = _preload_pool.get("stocks", {})

    save_interval = 100 # 每100只保存一次进度 (减少I/O)
    scan_start_time = time.time()

    # 多线程并行扫描 (mootdx本地直连无调用限制)
    MAX_WORKERS = 48
    STOCK_TIMEOUT = 30  # 单只股票最大30秒，超时跳过防卡死
    batch = all_stocks[start_idx:]
    total = len(all_stocks)
    
    # 预过滤：跳过代码格式不合法的股票（缺前导零等会直接卡死）
    valid_batch = []
    skipped_codes = []
    for stock in batch:
        code, name, market = stock[0], stock[1], stock[2]
        ok, reason = _validate_stock_code(str(code), market)
        if ok:
            valid_batch.append(stock)
        else:
            skipped_codes.append({"code": str(code), "name": name, "reason": reason})
            errors += 1
            _error_details.append({
                "code": str(code), "name": name, "market": market,
                "source": "code_validation",
                "reason": reason,
            })
    if skipped_codes:
        print(f"\n  [跳过] {len(skipped_codes)} 只代码格式不合法:")
        for s in skipped_codes[:10]:
            print(f"    {s['code']} {s['name'][:20]} → {s['reason']}")
        if len(skipped_codes) > 10:
            print(f"    ... 还有 {len(skipped_codes)-10} 只")
    
    batch = valid_batch

    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        futures = {}
        for idx_rel, stock in enumerate(batch):
            idx = start_idx + idx_rel
            future = executor.submit(_scan_one_stock, (stock, _preload_stocks))
            futures[future] = idx

        completed = 0
        timed_out = 0
        # wait() 替代 as_completed()，加整体超时防港股数据源永久阻塞
        pending = set(futures.keys())
        batch_deadline = time.time() + 30 + len(pending) * STOCK_TIMEOUT // 3
        while pending and time.time() < batch_deadline:
            done, pending = wait(pending, timeout=STOCK_TIMEOUT, return_when=FIRST_COMPLETED)
            if not done:
                # 所有剩余线程卡死，跳过
                for f in list(pending):
                    idx = futures[f]
                    stock = all_stocks[idx]
                    timed_out += 1; errors += 1
                    _error_details.append({
                        "code": str(stock[0]), "name": stock[1], "market": stock[2],
                        "source": "timeout",
                        "reason": f"超时({STOCK_TIMEOUT}s)无响应",
                    })
                break
            for future in done:
                idx = futures[future]
                completed += 1
                try:
                    result, err = future.result(timeout=0)
                except Exception as e:
                    result = None
                    err = {"reason": str(e)[:80]}

                stock = all_stocks[idx]
                code, name, market = stock[0], stock[1], stock[2]
                board_label = stock[3] if len(stock) > 3 else ""

                pct_done = completed / len(batch) * 100
                board_short = board_label[:2] if board_label else ""
                print(f"\r  [{completed}/{len(batch)}] {pct_done:.1f}% - [{board_short}] {code} {name}        ", end="", flush=True)

                if err:
                    errors += 1
                    _error_details.append(err)
                elif result is not None:
                    results.append(result)
                    if result["三线共振"]:
                        三线共振_list.append(result)
                        print(f"\n    >>> 三线共振! {code} {name} [{board_label}] <<<")
                    elif result["signal_count"] >= 2:
                        双线共振_list.append(result)

                # 交叉审核: 仅对信号>=2的股票全量验证, 减少采样 (提速)
                if result is not None and market != "hk" and result.get("close_price"):
                    should_verify = result.get("signal_count", 0) >= 2
                    if should_verify:
                        try:
                            verify_df = pd.DataFrame([{"close": result["close_price"]}])
                            diff, status = _cross_verify(code, verify_df, "mootdx")
                            _audit_stats["total"] += 1
                            if status == "OK":
                                _audit_stats["ok"] += 1
                            elif status == "SUSPECT":
                                _audit_stats["suspect"] += 1
                                _audit_results.append({
                                    "code": code, "name": name,
                                    "diff_pct": round(diff, 4) if diff else None,
                                    "status": status,
                                })
                            else:
                                _audit_stats["no_verify"] += 1
                        except Exception:
                            _audit_stats["no_verify"] += 1

                # 定期保存进度
                if completed % save_interval == 0:
                    progress = {
                        "results": results,
                        "triple": 三线共振_list,
                        "double": 双线共振_list,
                        "errors": errors,
                        "next_idx": start_idx + completed,
                        "total": total,
                    }
                    with open(PROGRESS_JSON, "w", encoding="utf-8") as f:
                        json.dump(progress, f, ensure_ascii=False)
    finally:
        # shutdown(wait=False): 不等卡死的线程，带现有结果继续
        # 不能用 with ThreadPoolExecutor — __exit__ 会强制 wait=True 覆盖这个
        executor.shutdown(wait=False)

    scan_elapsed = time.time() - scan_start_time
    print(f"\n\n扫描完成! 用时 {scan_elapsed:.1f} 秒")
    print(f"  成功: {len(results)}, 错误: {errors}")
    if timed_out > 0:
        print(f"  超时跳过: {timed_out} 只")
    print(f"  三线共振: {len(三线共振_list)} 只")
    print(f"  双线共振: {len(双线共振_list)} 只")
    print(f"  数据源: mootdx={_data_source_stats['mootdx']} baostock={_data_source_stats['baostock']} eastmoney={_data_source_stats['eastmoney']} efinance={_data_source_stats['efinance']} qq={_data_source_stats['qq']} fail={_data_source_stats['fail']}")
    if _bs_consecutive_fails >= _BS_FAIL_SKIP_THRESHOLD:
        print(f"  注: BaoStock 连续失败 {_bs_consecutive_fails} 次后已自动跳过")

    # 投行研报扫描
    guanlan_data = None
    try:
        from guanlan_extractor import get_watchlist_for_dashboard, load_watchlist
        wl = load_watchlist()
        stocks_list = get_watchlist_for_dashboard()
        guanlan_data = {
            "updated": wl.get("updated", ""),
            "total": wl.get("total", 0),
            "stocks": stocks_list,
        }
        print(f"  观澜关注池: {len(stocks_list)} 只")
    except ImportError:
        pass

    # 排序: 信号数降序 → 涨跌幅降序
    results.sort(key=lambda x: (-x["signal_count"], -x.get("pct_chg", 0)))

    # 交叉关联投行研报股票到扫描结果
    if guanlan_data and guanlan_data.get("stocks"):
        gl_codes = set()
        for gl_stock in guanlan_data["stocks"]:
            code = gl_stock.get("code", "")
            # 去掉 SH/SZ/HK. 前缀
            for prefix in ["SH", "SZ", "HK.", "HK"]:
                if code.startswith(prefix):
                    code = code[len(prefix):]
                    break
            gl_codes.add(code)
        for stock_list in [results, 三线共振_list, 双线共振_list]:
            for s in stock_list:
                scan_code = s.get("code", "")
                code_variants = [scan_code]
                if "." in scan_code:
                    code_variants.append(scan_code.split(".")[0])
                if any(cv in gl_codes for cv in code_variants):
                    sources = s.get("sources", [])
                    if "投行研报" not in sources:
                        sources.append("投行研报")
                        s["sources"] = sources
        print(f"  投行研报关联完成")

    # 输出JSON
    output = {
        "scan_mode": "full",
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_scanned": len(results),
        "total_errors": errors,
        "triple_count": len(三线共振_list),
        "double_count": len(双线共振_list),
        "pool_summary": {
            "创业板": len([s for s in all_stocks if s[3] == "创业板"]),
            "科创板": len([s for s in all_stocks if s[3] == "科创板"]),
            "主板": len([s for s in all_stocks if s[3] == "主板"]),
            "港股": len([s for s in all_stocks if s[3] == "港股"]),
        },
        "data_source_stats": dict(_data_source_stats),
        "error_details": _error_details,
        "audit": {
            "total_verified": _audit_stats["total"],
            "pass": _audit_stats["ok"],
            "suspect": _audit_stats["suspect"],
            "no_verify": _audit_stats["no_verify"],
            "suspicious": _audit_results[-20:],
        },
        "triple_signals": 三线共振_list,
        "double_signals": 双线共振_list,
        "all_results": results,
        "guanlan": guanlan_data,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  结果已保存: {OUTPUT_JSON}")

    # 清理进度文件
    if os.path.exists(PROGRESS_JSON):
        os.remove(PROGRESS_JSON)

    # 更新金股池
    update_gold_pool_from_scan(output)

    # 清理BaoStock连接
    _bs_logout()

    # 超时跳过时，shutdown(wait=False) 已释放主线程，
    # 但 Python 退进程时仍会等非 daemon 线程。os._exit 强制退出避卡。
    if timed_out > 0:
        os._exit(0)

    return output


def watch_gold_pool():
    """盘中精监金股池"""
    pool = load_gold_pool()

    if not pool.get("stocks"):
        print("[WARN] 金股池为空，请先执行盘后全扫(full)")
        return None

    print(f"\n{'='*60}")
    print(f"选股观测台 - 盘中精监 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"  金股池: {pool['total_count']} 只")

    results = []
    三线共振_list = []
    双线共振_list = []
    new_triple = []  # 新增三线共振
    errors = 0

    stocks_list = list(pool["stocks"].values())
    total = len(stocks_list)

    for idx, stock_info in enumerate(stocks_list):
        code = stock_info["code"]
        name = stock_info["name"]
        market = stock_info["market"]

        pct_done = (idx + 1) / total * 100
        print(f"\r  [{idx+1}/{total}] {pct_done:.1f}% - {code} {name}        ", end="", flush=True)

        try:
            result = check_stock_signals(code, name, market)
            if result is not None:
                # 注入来源标签(从金股池读取)
                result["sources"] = stock_info.get("sources", ["三足鼎立"])
                results.append(result)
                if result["三线共振"]:
                    三线共振_list.append(result)
                    # 判断是否新增三线共振(之前max_signal < 3)
                    if stock_info.get("max_signal", 0) < 3:
                        new_triple.append(result)
                        print(f"\n    >>> 新增三线共振! {code} {name} <<<")
                elif result["signal_count"] >= 2:
                    双线共振_list.append(result)
        except Exception as e:
            errors += 1
            _error_details.append({
                "code": code, "name": name, "market": market,
                "source": "watch_mootdx",
                "reason": f"{type(e).__name__}: {str(e)[:80]}",
            })

        time.sleep(RATE_LIMIT_WATCH)

    print(f"\n\n精监完成!")
    print(f"  扫描: {len(results)}, 错误: {errors}")
    print(f"  三线共振: {len(三线共振_list)} 只")
    print(f"  双线共振: {len(双线共振_list)} 只")
    if new_triple:
        print(f"  新增三线共振: {len(new_triple)} 只!")
        for s in new_triple:
            print(f"    ★ {s['code']} {s['name']} ({s['market_label']}) {s['close']} {s['pct_chg']:+.2f}%")

    # 排序
    results.sort(key=lambda x: (-x["signal_count"], -x.get("pct_chg", 0)))

    # 输出精监结果
    output = {
        "scan_mode": "watch",
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_scanned": len(results),
        "total_errors": errors,
        "error_details": _error_details,
        "triple_count": len(三线共振_list),
        "double_count": len(双线共振_list),
        "new_triple_count": len(new_triple),
        "triple_signals": 三线共振_list,
        "double_signals": 双线共振_list,
        "new_triple_signals": new_triple,
        "all_results": results,
        "gold_pool_total": pool["total_count"],
    }

    with open(WATCH_RESULT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  精监结果已保存: {WATCH_RESULT_JSON}")

    # 更新金股池
    update_gold_pool_from_watch(output)

    # 清理BaoStock连接
    _bs_logout()

    return output


# ============== 机游共振分析（龙虎榜） ==============

LHB_SEATS_PATH = os.path.join(DATA_DIR, "lhb_seats.json")
LHB_RESULT_PATH = os.path.join(DATA_DIR, "lhb_result.json")

def _load_lhb_seats():
    """加载席位定性知识库"""
    if os.path.exists(LHB_SEATS_PATH):
        with open(LHB_SEATS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seats": {"游资": [], "量化": [], "股东_关联方": []}, "patterns": {}}

def _classify_seat(seat_name, seats_db):
    """定性单个席位：机构专用/游资/量化/北向/本地"""
    seat = seat_name.strip()
    # 机构专用
    if "机构专用" in seat:
        return "机构专用"
    # 北向资金
    if "深股通" in seat or "沪股通" in seat:
        return "北向资金"
    # 精确匹配已知游资
    for yz in seats_db.get("seats", {}).get("游资", []):
        if yz in seat or seat in yz:
            return "游资"
    # 精确匹配已知量化
    for lh in seats_db.get("seats", {}).get("量化", []):
        if lh in seat or seat in lh:
            return "量化"
    # 精确匹配股东/关联方
    for gd in seats_db.get("seats", {}).get("股东_关联方", []):
        if gd in seat or seat in gd:
            return "股东_关联方"
    # 模式匹配：游资模式
    for pat in seats_db.get("patterns", {}).get("游资", []):
        if pat in seat:
            return "游资"
    # 模式匹配：量化模式
    for pat in seats_db.get("patterns", {}).get("量化", []):
        if pat in seat:
            return "量化"
    # 未知席位 → 本地（默认）
    return "本地"


def _get_stock_seat_details(stock_code, trade_date, seats_db):
    """
    获取单只股票在指定日期的龙虎榜席位明细（买入+卖出），
    对每个席位定性，返回游资买入额、游资卖出额。
    
    Returns:
        dict: {"游资买入": float, "游资卖出": float, "席位明细": [list]}
    """
    result = {"游资买入": 0.0, "游资卖出": 0.0, "席位明细": []}
    import akshare as ak

    try:
        dates_df = ak.stock_lhb_stock_detail_date_em(symbol=stock_code)
        trade_date_obj = datetime.strptime(trade_date, "%Y%m%d").date()
        valid_dates = [d['交易日'] if isinstance(d, dict) else d for d in dates_df['交易日']]
        valid_dates = [d.date() if isinstance(d, datetime) else d for d in valid_dates]
        if trade_date_obj not in valid_dates:
            return result
        date_str = trade_date_obj.strftime("%Y%m%d")
    except Exception:
        return result

    all_seats = {}
    for flag in ["买入", "卖出"]:
        try:
            df = ak.stock_lhb_stock_detail_em(symbol=stock_code, date=date_str, flag=flag)
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                seat_name = str(row.get("交易营业部名称", "")).strip()
                if not seat_name:
                    continue
                buy_amt = float(row.get("买入金额", 0) or 0)
                sell_amt = float(row.get("卖出金额", 0) or 0)
                reason = str(row.get("类型", "") or "")
                seat_type = _classify_seat(seat_name, seats_db)
                if seat_name not in all_seats:
                    all_seats[seat_name] = {"名称": seat_name, "类型": seat_type, "买入金额": 0.0, "卖出金额": 0.0, "净额": 0.0, "上榜原因": reason}
                all_seats[seat_name]["买入金额"] = max(all_seats[seat_name]["买入金额"], buy_amt)
                all_seats[seat_name]["卖出金额"] = max(all_seats[seat_name]["卖出金额"], sell_amt)
                all_seats[seat_name]["净额"] = all_seats[seat_name]["买入金额"] - all_seats[seat_name]["卖出金额"]
                if reason and not all_seats[seat_name]["上榜原因"]:
                    all_seats[seat_name]["上榜原因"] = reason
        except Exception:
            continue

    yz_buy = yz_sell = 0.0
    seat_details = []
    for info in all_seats.values():
        seat_details.append(info)
        if info["类型"] == "游资":
            yz_buy += info["买入金额"]
            yz_sell += info["卖出金额"]

    result["游资买入"] = yz_buy
    result["游资卖出"] = yz_sell
    result["席位明细"] = seat_details
    return result


def calc_jy共振_single(code, date=None):
    """
    计算单只股票的机游共振指标（含游资席位解析）。
    返回: dict 含 机构净买入/游资净买入/分类/席位明细
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    seats_db = _load_lhb_seats()
    result = {
        "code": code,
        "date": date,
        "机构净买入": 0.0,
        "游资净买入": 0.0,
        "机构买入": 0.0,
        "机构卖出": 0.0,
        "游资买入": 0.0,
        "游资卖出": 0.0,
        "分类": "无数据",
        "席位明细": [],
        "error": None,
    }

    try:
        import akshare as ak
        df = ak.stock_lhb_jgmmtj_em(start_date=date, end_date=date)
        if df is None or df.empty:
            result["error"] = "龙虎榜无数据"
            return result

        code_col = "代码"
        stock_df = df[df[code_col].astype(str).str.contains(code)]
        if stock_df.empty:
            result["error"] = "该股未上龙虎榜"
            return result

        row = stock_df.iloc[0]
        result["机构净买入"] = float(row.get("机构买入净额", 0))
        result["机构买入"] = float(row.get("机构买入总额", 0))
        result["机构卖出"] = float(row.get("机构卖出总额", 0))

        # 游资席位解析
        seat_result = _get_stock_seat_details(code, date, seats_db)
        result["游资买入"] = seat_result["游资买入"]
        result["游资卖出"] = seat_result["游资卖出"]
        result["游资净买入"] = seat_result["游资买入"] - seat_result["游资卖出"]
        result["席位明细"] = seat_result["席位明细"]

        # 分类判定
        jg_net = result["机构净买入"]
        yz_net = result["游资净买入"]
        if jg_net > 80_000_000 and yz_net > 80_000_000:
            result["分类"] = "纯共振"
        elif jg_net > 80_000_000 and yz_net < 0:
            result["分类"] = "标X"
        else:
            result["分类"] = "不达标"
        return result

    except ImportError:
        result["error"] = "akshare 未安装"
        return result
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:80]}"
        return result


def scan_jy共振(target_date=None):
    """
    扫描当日所有龙虎榜标的，计算机游共振（含游资席位解析）。
    返回: dict 含纯共振列表/标X列表/不达标列表
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y%m%d")

    seats_db = _load_lhb_seats()
    print(f"\n{'='*60}")
    print(f"机游共振扫描 — {target_date}")
    print(f"{'='*60}")

    try:
        import akshare as ak
        df = ak.stock_lhb_jgmmtj_em(start_date=target_date, end_date=target_date)
        # 防御：接口可能返回 None
        if df is None:
            print("  ⚠️ 龙虎榜接口返回 None（非交易日或无数据）")
            return {"date": target_date, "stocks": [], "pure_resonance": [], "mark_x": [], "summary": "接口返回None"}
        if df.empty:
            print("  当日无龙虎榜数据")
            return {"date": target_date, "stocks": [], "pure_resonance": [], "mark_x": [], "summary": "无数据"}

        # 收集唯一股票
        unique_codes = []
        seen = set()
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).zfill(6)
            if code not in seen:
                seen.add(code)
                unique_codes.append(code)

        # 逐只解析游资席位（带进度显示）
        print(f"  龙虎榜{len(df)}条记录, {len(unique_codes)}只唯一股票")
        yz_data = {}  # {code: {游资买入, 游资卖出, 席位明细}}
        total = len(unique_codes)
        for idx, code in enumerate(unique_codes):
            print(f"\r  [席位解析 {idx+1}/{total}] {code}...", end="", flush=True)
            seat_result = _get_stock_seat_details(code, target_date, seats_db)
            yz_data[code] = {
                "游资买入": seat_result["游资买入"],
                "游资卖出": seat_result["游资卖出"],
                "游资净买入": seat_result["游资买入"] - seat_result["游资卖出"],
                "席位明细": seat_result["席位明细"],
            }
            time.sleep(0.25)
        print(f"\r  ✓ 完成 {total} 只股票席位解析" + " " * 30)

        # 构建每只上榜股票条目
        stocks = []
        pure_resonance = []
        mark_x = []
        seen_pure = set()
        seen_mark = set()

        for _, row in df.iterrows():
            code = str(row.get("代码", "")).zfill(6)
            name = str(row.get("名称", ""))
            jg_net = float(row.get("机构买入净额", 0) or 0)
            jg_buy = float(row.get("机构买入总额", 0) or 0)
            jg_sell = float(row.get("机构卖出总额", 0) or 0)

            yz = yz_data.get(code, {"游资买入": 0, "游资卖出": 0, "游资净买入": 0, "席位明细": []})
            yz_net = yz["游资净买入"]

            entry = {
                "code": code,
                "name": name,
                "机构净买入_万": round(jg_net / 10000, 2),
                "机构买入_万": round(jg_buy / 10000, 2),
                "机构卖出_万": round(jg_sell / 10000, 2),
                "游资净买入_万": round(yz_net / 10000, 2),
                "游资买入_万": round(yz["游资买入"] / 10000, 2),
                "游资卖出_万": round(yz["游资卖出"] / 10000, 2),
                "分类": "不达标",
                "上榜原因": str(row.get("上榜原因", "")),
            }

            # 分类判定
            if jg_net > 8000_0000 and yz_net > 8000_0000:
                entry["分类"] = "纯共振"
                if code not in seen_pure:
                    pure_resonance.append(entry)
                    seen_pure.add(code)
            elif jg_net > 8000_0000 and yz_net < 0:
                entry["分类"] = "标X"
                if code not in seen_mark:
                    mark_x.append(entry)
                    seen_mark.add(code)

            stocks.append(entry)

            label = entry["分类"]
            print(f"  {code} {name:10s} 机构净:{jg_net/10000:>8.0f}万 游资净:{yz_net/10000:>8.0f}万 → {label}")

        output = {
            "date": target_date,
            "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_stocks": len(stocks),
            "stocks": stocks,
            "pure_resonance": pure_resonance,
            "mark_x": mark_x,
            "summary": f"龙虎榜{len(stocks)}只 | 纯共振{len(pure_resonance)}只 | 标X{len(mark_x)}只",
        }

        # 连续共振天数追踪
        try:
            if os.path.exists(LHB_RESULT_PATH):
                with open(LHB_RESULT_PATH, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                old_map = {s["code"]: s.get("连续天数", 0) for s in old_data.get("stocks", [])}
            else:
                old_map = {}
            for s in stocks:
                if s["code"] in old_map and old_map[s["code"]] > 0:
                    s["连续天数"] = old_map[s["code"]] + 1
                else:
                    s["连续天数"] = 1
        except Exception:
            for s in stocks:
                s["连续天数"] = 1

        with open(LHB_RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"\n  结果已保存: {LHB_RESULT_PATH}")
        print(f"  纯共振 {len(pure_resonance)} 只 | 标X {len(mark_x)} 只")
        return output

    except ImportError:
        print("  akshare 未安装")
        return {"date": target_date, "error": "akshare 未安装"}
    except Exception as e:
        print(f"  扫描失败: {e}")
        return {"date": target_date, "error": str(e)}

# ============== 入口 ==============

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "full":
            # 盘后扫描活跃股池(创业板Top100+科创板Top100+主板Top100+港股Top50)
            scan_market()
        elif cmd == "quick":
            # 盘中极速扫描(只要60天K线, 速度加倍)
            import __main__
            __main__.DAILY_BARS = 60
            scan_market()
        elif cmd == "a":
            scan_market(scan_a=True, scan_hk=False)
        elif cmd == "hk":
            scan_market(scan_a=False, scan_hk=True)
        elif cmd == "resume":
            scan_market(resume=True)
        elif cmd == "watch":
            # 盘中精监金股池
            watch_gold_pool()
        elif cmd == "pool":
            # 查看金股池
            pool = load_gold_pool()
            print(f"\n金股池 ({pool.get('total_count', 0)} 只, 更新: {pool.get('last_update', '-')})")
            for key, s in sorted(pool.get("stocks", {}).items(), key=lambda x: -x[1].get("max_signal", 0)):
                hist = s.get("history", [])
                latest = hist[-1] if hist else {}
                board = s.get("board_label", "")
                fund = s.get("fund_type", "")
                print(f"  {s['code']} {s['name']:8s} [{board}][{fund}] 峰值:{s.get('max_signal',0)}线 今日:{latest.get('signal_count','-')}线")
        elif cmd == "test":
            # 测试扫描(仅30只)
            all_stocks = fetch_volume_top_stocks(top_cy=15, top_kc=5, top_zb=10, top_hk=0)
            print(f"\n测试股池: {len(all_stocks)} 只")
            results = []
            for idx, stock in enumerate(all_stocks):
                code, name, market = stock[0], stock[1], stock[2]
                board_label = stock[3] if len(stock) > 3 else ""
                volume_amount = stock[4] if len(stock) > 4 else 0
                turnover_rate = stock[5] if len(stock) > 5 else 0
                mv_yi = stock[6] if len(stock) > 6 else 0
                fund_type = stock[7] if len(stock) > 7 else ""
                pct_done = (idx + 1) / len(all_stocks) * 100
                print(f"\r  [{idx+1}/{len(all_stocks)}] {pct_done:.1f}% - [{board_label}] {code} {name}        ", end="", flush=True)
                try:
                    result = check_stock_signals(code, name, market, board_label, volume_amount, turnover_rate, mv_yi, fund_type)
                    if result:
                        results.append(result)
                except:
                    pass
                time.sleep(RATE_LIMIT_FULL)
            print(f"\n\n测试完成: {len(results)} 只有结果")
            for r in sorted(results, key=lambda x: -x["signal_count"]):
                signals = []
                if r["缠论买_日K"]: signals.append("缠论")
                if r["金钻_黄柱"] or r["金钻_起涨"]: signals.append("金钻")
                if r["四量图_机构变红"]: signals.append("机构")
                print(f"  {r['code']} {r['name']:8s} [{r.get('board_label','')}] {r['signal_count']}线({'+'.join(signals)}) {r['close']} {r['pct_chg']:+.2f}%")
        elif cmd == "single":
            code = sys.argv[2] if len(sys.argv) > 2 else "000001"
            name = sys.argv[3] if len(sys.argv) > 3 else "test"
            market = sys.argv[4] if len(sys.argv) > 4 else "sh"
            result = check_stock_signals(code, name, market)
            if result:
                for k, v in result.items():
                    print(f"  {k}: {v}")
            else:
                print("  数据不足或获取失败")
        elif cmd == "lhb":
            date = sys.argv[2] if len(sys.argv) > 2 else datetime.now().strftime("%Y%m%d")
            result = scan_jy共振(date)
            print(f"\n机游共振扫描完成: {result.get('summary', '')}")
            if result.get("pure_resonance"):
                print(f"  纯共振: {len(result['pure_resonance'])} 只")
            if result.get("mark_x"):
                print(f"  标X: {len(result['mark_x'])} 只")
    else:
        print("选股观测台 - 三线共振扫描 v4.0 (三重数据源: mootdx+BaoStock+东方财富)")
        print("用法:")
        print("  python scanner.py full   - 盘后扫描活跃股池(创业板100+科创板100+主板100+港股50)")
        print("  python scanner.py a      - 仅A股")
        print("  python scanner.py hk     - 仅港股")
        print("  python scanner.py resume - 断点续扫")
        print("  python scanner.py watch  - 盘中精监金股池")
        print("  python scanner.py pool   - 查看金股池")
        print("  python scanner.py test   - 测试(少量股票)")
        print("  python scanner.py single 000001 平安银行 sh  - 单只股票")
        print("  python scanner.py lhb [20260602]           - 机游共振扫描")
