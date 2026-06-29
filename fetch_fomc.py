#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FOMC 美联储议息数据采集
从 akshare 宏观数据接口拉取最近一次 FOMC 会议概要
"""
import json
import os
import sys
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(PROJECT_ROOT, "data", "fomc_summary.json")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def fetch_fomc():
    """获取 FOMC 最新数据"""
    try:
        import akshare as ak
        # 美联储利率决议历史
        df = ak.macro_bank_usa_interest_rate()
        if df is None or len(df) == 0:
            log("未获取到美联储利率数据")
            return None
        
        # 取最新一条
        latest = df.iloc[-1]
        meeting_date_raw = str(latest.get('日期', ''))
        
        # 格式化日期
        meeting_date = meeting_date_raw.replace('年', '-').replace('月', '-').replace('日', '')
        
        result = {
            "meeting_date": meeting_date,
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": ""
        }
        
        # 构建摘要
        rate_before = latest.get('调整前', '') or latest.get('前值', '')
        rate_after = latest.get('调整后', '') or latest.get('现值', '')
        if rate_before and rate_after:
            if rate_before == rate_after:
                result["summary"] = f"维持利率 {rate_after} 不变"
            else:
                result["summary"] = f"利率从 {rate_before} 调整为 {rate_after}"
        
        log(f"最新FOMC: {meeting_date} {result['summary']}")
        return result
        
    except Exception as e:
        log(f"FOMC数据获取失败: {e}")
        return None

def main():
    log("=" * 40)
    log("FOMC 数据采集")
    
    data = fetch_fomc()
    if data and data["summary"]:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log(f"✅ 已保存: {DATA_FILE}")
    else:
        log("⚠️ 未获取到有效FOMC数据，保留现有文件")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
