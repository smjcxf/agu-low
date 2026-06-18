#!/usr/bin/env python3
"""
生成异动提醒 + ETF资金流向 + 重要日历 数据
- alerts: 异动提醒（ETF大涨大跌）
- etfFlow: 国家队ETF监测
- calendar: 重要市场日历（直到2027-12-31）

用法：
  python fetch_nt_data.py              # 生成全部
  python fetch_nt_data.py --etf-only   # 只生成ETF数据
  python fetch_nt_data.py --calendar-only  # 只生成日历数据
"""

import json
import sys
import os
from datetime import datetime, timedelta
import calendar
import argparse

# 尝试导入中国节假日库
try:
    from chinese_calendar import is_workday, is_holiday
    HAS_CH_CAL = True
except ImportError:
    HAS_CH_CAL = False
    print("⚠️ chinese_calendar not installed, using manual holiday list")

# 添加父目录到路径，以便导入akshare
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import akshare as ak
    HAS_AK = True
except ImportError:
    HAS_AK = False
    print("⚠️  akshare not installed, using mock data")

# ─────────────────────────────────────────
# 1. ETF监控列表（12只国家队ETF）
# ─────────────────────────────────────────
ETF_LIST = [
    {"code": "510300", "name": "华泰柏瑞沪深300ETF", "type": "宽基"},
    {"code": "510310", "name": "易方达沪深300ETF",   "type": "宽基"},
    {"code": "159919", "name": "嘉实沪深300ETF",     "type": "宽基"},
    {"code": "510330", "name": "华夏沪深300ETF",     "type": "宽基"},
    {"code": "510050", "name": "华夏上证50ETF",      "type": "宽基"},
    {"code": "510500", "name": "南方中证500ETF",      "type": "宽基"},
    {"code": "159845", "name": "华夏中证1000ETF",    "type": "宽基"},
    {"code": "588000", "name": "华夏科创50ETF",      "type": "宽基"},
    {"code": "512690", "name": "酒ETF",               "type": "行业"},
    {"code": "515050", "name": "5G通信ETF",           "type": "行业"},
    {"code": "159995", "name": "芯片ETF",              "type": "行业"},
    {"code": "512010", "name": "医药ETF",              "type": "行业"},
]

# ─────────────────────────────────────────
# 2. 获取ETF实时行情
# ─────────────────────────────────────────
def fetch_etf_realtime():
    """获取12只ETF的实时行情"""
    etf_data = []
    alerts = []

    if not HAS_AK:
        # 模拟数据
        import random
        for etf in ETF_LIST:
            change_pct = round(random.uniform(-3, 3), 2)
            price = round(random.uniform(1, 10), 3)
            amount = round(random.uniform(1e8, 5e9), 2)
            etf_data.append({
                "code": etf["code"],
                "name": etf["name"],
                "type": etf["type"],
                "price": price,
                "change_pct": change_pct,
                "volume": int(random.uniform(1e6, 1e8)),
                "amount": amount,
                "amplitude": round(random.uniform(1, 5), 2),
            })
            if abs(change_pct) >= 3:
                alerts.append({
                    "type": "etf",
                    "severity": "high" if abs(change_pct) >= 5 else "medium",
                    "message": f"{etf['name']} {'大涨' if change_pct > 0 else '大跌'} {abs(change_pct):.2f}%",
                    "time": datetime.now().strftime("%H:%M"),
                })
        return etf_data, alerts

    try:
        # 获取ETF实时行情
        df = ak.fund_etf_spot_em()
        now_str = datetime.now().strftime("%H:%M")

        for etf in ETF_LIST:
            try:
                row = df[df['代码'] == etf['code']]
                if row.empty:
                    continue
                row = row.iloc[0]
                price = float(row.get('最新价', 0) or 0)
                change_pct = float(row.get('涨跌幅', 0) or 0)
                volume = float(row.get('成交量', 0) or 0)
                amount = float(row.get('成交额', 0) or 0)
                amplitude = float(row.get('振幅', 0) or 0)

                etf_data.append({
                    "code": etf["code"],
                    "name": etf["name"],
                    "type": etf["type"],
                    "price": price,
                    "change_pct": change_pct,
                    "volume": volume,
                    "amount": amount,
                    "amplitude": amplitude,
                })

                # 异动提醒：涨跌超过3%
                if abs(change_pct) >= 3:
                    alerts.append({
                        "type": "etf",
                        "severity": "high" if abs(change_pct) >= 5 else "medium",
                        "message": f"{etf['name']} {'大涨' if change_pct > 0 else '大跌'} {abs(change_pct):.2f}%",
                        "time": now_str,
                    })
            except Exception as e:
                print(f"  ⚠️  {etf['name']} 获取失败: {e}")
                continue

    except Exception as e:
        print(f"⚠️  ETF行情获取失败: {e}")

    return etf_data, alerts


# ─────────────────────────────────────────
# 3. 生成重要市场日历（直到2027-12-31）
# ─────────────────────────────────────────
def generate_calendar():
    """
    生成重要市场日历
    包含：
    - 中国宏观经济数据（CPI/PPI、PMI、出口、GDP等）
    - 美国非农、CPI、美联储议息
    - 期权交割日（每月第四个周三）
    - 股指期货交割日（每月第三个周五）
    - A50交割日（每月倒数第二个交易日）
    - MLF操作（每月15日）
    - LPR报价（每月20日）
    - 重要会议（两会、中央经济工作会议等）
    """
    calendar_events = []
    today = datetime.now()
    end_date = datetime(2027, 12, 31)

    # 辅助：获取某月最后一个工作日
    def last_workday(y, m):
        last_day = calendar.monthrange(y, m)[1]
        d = datetime(y, m, last_day)
        while d.weekday() >= 5:  # 周六=5, 周日=6
            d -= timedelta(days=1)
        return d

    # 辅助：获取某月第N个周X
    def nth_weekday(y, m, n, weekday):
        """返回y年m月第n个weekday（0=周一，6=周日）"""
        first_day = datetime(y, m, 1)
        days_until = (weekday - first_day.weekday()) % 7
        first_match = first_day + timedelta(days=days_until)
        return first_match + timedelta(weeks=n-1)

    # 辅助：获取某月倒数第N个交易日
    def nth_last_workday(y, m, n):
        """返回y年m月倒数第n个工作日"""
        last_day = calendar.monthrange(y, m)[1]
        d = datetime(y, m, last_day)
        count = 0
        while True:
            if d.weekday() < 5:  # 工作日
                count += 1
                if count == n:
                    return d
            d -= timedelta(days=1)

    # 手动假期日期集合（2026-2027）
    _holiday_set = set()
    # 2026
    for dd in [19,20,21]: _holiday_set.add(f"2026-06-{dd:02d}")  # 端午
    for dd in range(15,24): _holiday_set.add(f"2026-02-{dd:02d}")  # 春节
    for dd in [25,26,27]: _holiday_set.add(f"2026-09-{dd:02d}")  # 中秋
    for dd in range(1,8): _holiday_set.add(f"2026-10-{dd:02d}")  # 国庆
    _holiday_set.add("2026-01-01")  # 元旦
    # 2027
    for dd in [8,9,10]: _holiday_set.add(f"2027-06-{dd:02d}")  # 端午
    for dd in range(14,21): _holiday_set.add(f"2027-02-{dd:02d}")  # 春节
    for dd in [15,16,17]: _holiday_set.add(f"2027-09-{dd:02d}")  # 中秋
    for dd in range(1,8): _holiday_set.add(f"2027-10-{dd:02d}")  # 国庆
    _holiday_set.add("2027-01-01")  # 元旦

    # 辅助：顺延到下一个交易日（遇节假日/周末自动跳过）
    def to_workday(d):
        """如果当天是节假日或周末，顺延到下一个交易日"""
        for _ in range(60):
            if HAS_CH_CAL:
                if is_workday(d) and not is_holiday(d):
                    return d
            else:
                ds = d.strftime("%Y-%m-%d")
                if d.weekday() < 5 and ds not in _holiday_set:
                    return d
            d += timedelta(days=1)
        return d

    y, m = today.year, 1  # 从当年1月开始迭代，确保全年节假日都能生成
    while (y, m) <= (end_date.year, end_date.month):
        ym_str = f"{y}-{m:02d}"

        # ── 中国宏观经济数据 ──

        # CPI/PPI：通常每月9-10日（遇节假日顺延）
        cpi_day = to_workday(datetime(y, m, 9))
        calendar_events.append({
            "date": cpi_day.strftime("%Y-%m-%d"),
            "title": "CPI/PPI",
            "type": "data"
        })

        # 中国PMI：每月最后一天
        pm_day = last_workday(y, m)
        calendar_events.append({
            "date": pm_day.strftime("%Y-%m-%d"),
            "title": "中国PMI",
            "type": "data"
        })

        # 中国出口数据：每月7-8日（遇节假日顺延）
        exp_day = to_workday(datetime(y, m, 7))
        calendar_events.append({
            "date": exp_day.strftime("%Y-%m-%d"),
            "title": "中国出口",
            "type": "data"
        })

        # 中国社会消费品零售：每月15日（遇节假日顺延）
        # 中国社会消费品零售：每月15日（遇节假日顺延）
        retail_day = to_workday(datetime(y, m, 15))
        calendar_events.append({
            "date": retail_day.strftime("%Y-%m-%d"),
            "title": "社会消费品零售",
            "type": "data"
        })

        # 中国GDP：每季度16日（1月、4月、7月、10月）
        if m in [1, 4, 7, 10]:
            gdp_day = 16 if m == 1 else 15
            gdp_dt = to_workday(datetime(y, m, gdp_day))
            calendar_events.append({
                "date": gdp_dt.strftime("%Y-%m-%d"),
                "title": "GDP",
                "type": "data"
            })

        # ── 美国数据 ──

        # 美国非农：每月第一个周五
        nfp_day = nth_weekday(y, m, 1, 4)  # 周五=4
        calendar_events.append({
            "date": nfp_day.strftime("%Y-%m-%d"),
            "title": "美国非农",
            "type": "data"
        })

        # 美国CPI：每月中旬（通常10-13日）
        calendar_events.append({
            "date": f"{y}-{m:02d}-13",
            "title": "美国CPI",
            "type": "data"
        })

        # ── 交割日 ──

        # 期权交割：每月第四个周三（遇节假日顺延）
        opt_day = nth_weekday(y, m, 4, 2)  # 周三=2
        opt_day = to_workday(opt_day)
        calendar_events.append({
            "date": opt_day.strftime("%Y-%m-%d"),
            "title": "期权交割",
            "type": "option"
        })

        # 股指期货交割：每月第三个周五（遇节假日顺延）
        fut_day = nth_weekday(y, m, 3, 4)  # 周五=4
        fut_day = to_workday(fut_day)
        calendar_events.append({
            "date": fut_day.strftime("%Y-%m-%d"),
            "title": "股指期货交割",
            "type": "futures"
        })

        # A50交割：每月倒数第二个交易日（遇节假日顺延）
        a50_day = nth_last_workday(y, m, 2)
        a50_day = to_workday(a50_day)
        calendar_events.append({
            "date": a50_day.strftime("%Y-%m-%d"),
            "title": "A50交割",
            "type": "a50"
        })

        # ── 央行操作 ──

        # MLF操作：每月15日（遇节假日顺延）
        mlf_day = to_workday(datetime(y, m, 15))
        calendar_events.append({
            "date": mlf_day.strftime("%Y-%m-%d"),
            "title": "MLF操作",
            "type": "central_bank"
        })

        # LPR报价：每月20日（遇节假日顺延）
        lpr_day = to_workday(datetime(y, m, 20))
        calendar_events.append({
            "date": lpr_day.strftime("%Y-%m-%d"),
            "title": "LPR报价",
            "type": "central_bank"
        })

        # ── 特殊事件 ──

        # 两会（每年3月5日开幕，遇节假日顺延）
        if m == 3:
            lianghui = to_workday(datetime(y, m, 5))
            calendar_events.append({
                "date": lianghui.strftime("%Y-%m-%d"),
                "title": "两会开幕",
                "type": "policy"
            })

        # 中央经济工作会议（每年12月中旬，遇节假日顺延）
        if m == 12:
            jjy = to_workday(datetime(y, m, 15))
            calendar_events.append({
                "date": jjy.strftime("%Y-%m-%d"),
                "title": "中央经济工作会议",
                "type": "policy"
            })

        # 上市公司财报披露截止日
        # 年报：4月30日
        if m == 4:
            calendar_events.append({
                "date": f"{y}-{m:02d}-30",
                "title": "年报披露截止",
                "type": "earnings"
            })
        # 一季报+中报：8月31日
        if m == 8:
            calendar_events.append({
                "date": f"{y}-{m:02d}-31",
                "title": "中报披露截止",
                "type": "earnings"
            })
        # 三季报：10月31日
        if m == 10:
            calendar_events.append({
                "date": f"{y}-{m:02d}-31",
                "title": "三季报披露截止",
                "type": "earnings"
            })

        # 美联储议息会议（通常每年8次，大约每6周一次）
        # 2026-2027年议息会议日期（大致估算）
        fomc_2026 = [
            "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
            "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"
        ]
        fomc_2027 = [
            "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-16",
            "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08"
        ]
        fomc_dates = fomc_2026 + fomc_2027
        for d in fomc_dates:
            if d.startswith(ym_str):
                calendar_events.append({
                    "date": d,
                    "title": "美联储议息",
                    "type": "fomc"
                })

        # ── 美股七姐妹财报 ──
        # 财报季度：Q4(1-2月) Q1(4月) Q2(7月) Q3(10-11月)
        magnificent7 = [
            # Apple
            ('2026-01-28', '苹果Q1财报'),
            ('2026-04-29', '苹果Q2财报'),
            ('2026-07-29', '苹果Q3财报'),
            ('2026-10-28', '苹果Q4财报'),
            ('2027-01-27', '苹果Q1财报'),
            ('2027-04-28', '苹果Q2财报'),
            ('2027-07-28', '苹果Q3财报'),
            # Microsoft
            ('2026-01-27', '微软Q2财报'),
            ('2026-04-29', '微软Q3财报'),
            ('2026-07-29', '微软Q4财报'),
            ('2026-10-27', '微软Q1财报'),
            ('2027-01-26', '微软Q2财报'),
            ('2027-04-28', '微软Q3财报'),
            ('2027-07-28', '微软Q4财报'),
            # Alphabet/Google
            ('2026-02-03', '谷歌Q4财报'),
            ('2026-04-28', '谷歌Q1财报'),
            ('2026-07-28', '谷歌Q2财报'),
            ('2026-10-27', '谷歌Q3财报'),
            ('2027-02-02', '谷歌Q4财报'),
            ('2027-04-27', '谷歌Q1财报'),
            ('2027-07-27', '谷歌Q2财报'),
            # Amazon
            ('2026-01-29', '亚马逊Q4财报'),
            ('2026-04-29', '亚马逊Q1财报'),
            ('2026-07-30', '亚马逊Q2财报'),
            ('2026-10-28', '亚马逊Q3财报'),
            ('2027-01-28', '亚马逊Q4财报'),
            ('2027-04-28', '亚马逊Q1财报'),
            ('2027-07-29', '亚马逊Q2财报'),
            # Meta
            ('2026-01-28', 'Meta Q4财报'),
            ('2026-04-29', 'Meta Q1财报'),
            ('2026-07-29', 'Meta Q2财报'),
            ('2026-10-28', 'Meta Q3财报'),
            ('2027-01-27', 'Meta Q4财报'),
            ('2027-04-28', 'Meta Q1财报'),
            ('2027-07-28', 'Meta Q2财报'),
            # Tesla
            ('2026-01-27', '特斯拉Q4财报'),
            ('2026-04-21', '特斯拉Q1财报'),
            ('2026-07-21', '特斯拉Q2财报'),
            ('2026-10-20', '特斯拉Q3财报'),
            ('2027-01-26', '特斯拉Q4财报'),
            ('2027-04-20', '特斯拉Q1财报'),
            ('2027-07-20', '特斯拉Q2财报'),
        ]
        for nd, ntitle in magnificent7:
            if nd.startswith(ym_str):
                calendar_events.append({'date': nd, 'title': ntitle, 'type': 'earnings_calendar'})

        # ── 韩国：三星 + SK海力士财报 ──
        korea_earnings = [
            ('2026-01-27', '三星Q4财报'),
            ('2026-04-28', '三星Q1财报'),
            ('2026-07-28', '三星Q2财报'),
            ('2026-10-27', '三星Q3财报'),
            ('2027-01-26', '三星Q4财报'),
            ('2027-04-27', '三星Q1财报'),
            ('2027-07-27', '三星Q2财报'),
            ('2026-01-28', 'SK海力士Q4财报'),
            ('2026-04-29', 'SK海力士Q1财报'),
            ('2026-07-29', 'SK海力士Q2财报'),
            ('2026-10-28', 'SK海力士Q3财报'),
            ('2027-01-27', 'SK海力士Q4财报'),
            ('2027-04-28', 'SK海力士Q1财报'),
            ('2027-07-28', 'SK海力士Q2财报'),
        ]
        for nd, ntitle in korea_earnings:
            if nd.startswith(ym_str):
                calendar_events.append({'date': nd, 'title': ntitle, 'type': 'earnings_korea'})

        # ── 台湾台积电财报 ──
        tsmc_earnings = [
            ('2026-01-15', '台积电Q4财报'),
            ('2026-04-16', '台积电Q1财报'),
            ('2026-07-16', '台积电Q2财报'),
            ('2026-10-15', '台积电Q3财报'),
            ('2027-01-14', '台积电Q4财报'),
            ('2027-04-15', '台积电Q1财报'),
            ('2027-07-15', '台积电Q2财报'),
        ]
        for nd, ntitle in tsmc_earnings:
            if nd.startswith(ym_str):
                calendar_events.append({'date': nd, 'title': ntitle, 'type': 'earnings_taiwan'})

        # ── 中国法定节假日（必须在递增月份之前） ──
        # 2026年端午节：6月19日（周五，农历五月初五），连休3天
        if y == 2026 and m == 6:
            for dd in [19, 20, 21]:
                calendar_events.append({'date': f'2026-06-{dd:02d}', 'title': '端午节假期', 'type': 'holiday'})
        # 2027年端午节：6月8日（周二），连休3天（预计6-10）
        if y == 2027 and m == 6:
            for dd in [8, 9, 10]:
                calendar_events.append({'date': f'2027-06-{dd:02d}', 'title': '端午节假期', 'type': 'holiday'})
        # 元旦
        if m == 1:
            calendar_events.append({'date': f'{y}-01-01', 'title': '元旦假期', 'type': 'holiday'})
        # 春节（2026: 2月15-23, 2027: 2月14-20 预测）
        if y == 2026 and m == 2:
            for dd in range(15, 24):
                calendar_events.append({'date': f'2026-02-{dd:02d}', 'title': '春节假期', 'type': 'holiday'})
        if y == 2027 and m == 2:
            for dd in range(14, 21):
                calendar_events.append({'date': f'2027-02-{dd:02d}', 'title': '春节假期', 'type': 'holiday'})
        # 中秋（2026: 9月25-27, 2027: 9月15-17）
        if y == 2026 and m == 9:
            for dd in [25, 26, 27]:
                calendar_events.append({'date': f'2026-09-{dd:02d}', 'title': '中秋节假期', 'type': 'holiday'})
        if y == 2027 and m == 9:
            for dd in [15, 16, 17]:
                calendar_events.append({'date': f'2027-09-{dd:02d}', 'title': '中秋节假期', 'type': 'holiday'})
        # 国庆（10月1-7日）
        if m == 10:
            for dd in range(1, 8):
                calendar_events.append({'date': f'{y}-10-{dd:02d}', 'title': '国庆节假期', 'type': 'holiday'})

        # 递增月份
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1

        # ── 华为重要事件 ──
        huawei_events = [
            (2026, 3, 20, '华为P系列发布会'),
            (2026, 6, 12, '华为开发者大会HDC·Day1'),
            (2026, 6, 13, '华为开发者大会HDC·Day2'),
            (2026, 6, 14, '华为开发者大会HDC·Day3'),
            (2026, 9, 10, '华为Mate系列发布会'),
            (2027, 3, 20, '华为P系列发布会'),
            (2027, 6, 12, '华为开发者大会HDC·Day1'),
            (2027, 6, 13, '华为开发者大会HDC·Day2'),
            (2027, 6, 14, '华为开发者大会HDC·Day3'),
            (2027, 9, 10, '华为Mate系列发布会'),
        ]
        for hy, hm, hd, htitle in huawei_events:
            date_str = f'{hy}-{hm:02d}-{hd:02d}'
            if date_str.startswith(ym_str):
                calendar_events.append({'date': date_str, 'title': htitle, 'type': 'product_launch'})

        # ── 英伟达财报 + 业绩指引 ──
        nvidia_events = [
            ('2026-02-25', '英伟达Q4财报'),
            ('2026-05-21', '英伟达Q1财报+指引'),
            ('2026-08-20', '英伟达Q2财报+指引'),
            ('2026-11-18', '英伟达Q3财报+指引'),
            ('2027-02-24', '英伟达Q4财报'),
            ('2027-05-19', '英伟达Q1财报+指引'),
            ('2027-08-18', '英伟达Q2财报+指引'),
            ('2027-11-17', '英伟达Q3财报+指引'),
        ]
        for nd, ntitle in nvidia_events:
            if nd.startswith(ym_str):
                calendar_events.append({'date': nd, 'title': ntitle, 'type': 'earnings_calendar'})

        # ── 苹果重要事件 ──
        apple_events = [
            ('2026-06-09', '苹果WWDC·Day1'),
            ('2026-06-10', '苹果WWDC·Day2'),
            ('2026-06-11', '苹果WWDC·Day3'),
            ('2026-09-08', '苹果秋季发布会'),
            ('2027-06-07', '苹果WWDC·Day1'),
            ('2027-06-08', '苹果WWDC·Day2'),
            ('2027-06-09', '苹果WWDC·Day3'),
            ('2027-09-07', '苹果秋季发布会'),
        ]
        for nd, ntitle in apple_events:
            if nd.startswith(ym_str):
                calendar_events.append({'date': nd, 'title': ntitle, 'type': 'product_launch'})

        # ── 重大IPO/市场事件 ──
        ipo_events = [
            ('2026-06-12', 'SpaceX IPO'),
        ]
        for nd, ntitle in ipo_events:
            if nd.startswith(ym_str):
                calendar_events.append({'date': nd, 'title': ntitle, 'type': 'product_launch'})

    # 去重并按日期排序
    seen = set()
    unique_events = []
    for e in sorted(calendar_events, key=lambda x: x["date"]):
        key = (e["date"], e["title"])
        if key not in seen:
            seen.add(key)
            unique_events.append(e)

    return unique_events


# ─────────────────────────────────────────
# 4. 主函数
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='生成ETF数据和重要日历')
    parser.add_argument('--etf-only', action='store_true', help='只生成ETF数据')
    parser.add_argument('--calendar-only', action='store_true', help='只生成日历数据')
    args = parser.parse_args()

    print("=" * 40)
    if args.etf_only:
        print("  生成 NT_DATA（ETF数据仅）")
    elif args.calendar_only:
        print("  生成 NT_DATA（重要日历仅）")
    else:
        print("  生成 NT_DATA（异动提醒 + ETF + 日历）")
    print("=" * 40)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    short_time = datetime.now().strftime("%H:%M")
    print(f"更新时间: {now_str}")

    # 初始化
    etf_list, etf_alerts = [], []
    calendar_events = []

    # 1. 获取ETF数据
    if not args.calendar_only:
        print("")
        print("正在获取ETF行情...")
        etf_list, etf_alerts = fetch_etf_realtime()
        print(f"  获取 {len(etf_list)} 只ETF数据")
        print(f"  异动提醒 {len(etf_alerts)} 条")

    # 2. 生成日历
    if not args.etf_only:
        print("")
        print("正在生成重要市场日历...")
        calendar_events = generate_calendar()
        print(f"  生成 {len(calendar_events)} 条日历事件")

    # 3. 汇总异动提醒
    alerts = []
    if not args.calendar_only:
        alerts.extend(etf_alerts)
        up_count = sum(1 for e in etf_list if e["change_pct"] > 0)
        down_count = len(etf_list) - up_count
        alerts.insert(0, {
            "type": "summary",
            "severity": "medium" if down_count > up_count else "low",
            "message": f"ETF监测中，{up_count}涨{down_count}跌",
            "time": short_time,
        })
    else:
        up_count, down_count = 0, 0

    # 4. 组装数据
    nt_data = {
        "update_time": now_str,
        "alerts": alerts,
        "etfFlow": {
            "etfs": etf_list,
            "summary": {
                "total": len(ETF_LIST),
                "valid": len(etf_list),
                "up": up_count,
                "down": down_count,
                "alerts_count": len(etf_alerts),
            }
        } if not args.calendar_only else {"etfs": [], "summary": {}},
        "calendar": calendar_events if not args.etf_only else [],
    }

    # 5. 保存
    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "nt_data.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)

    # 如果是部分更新，先读取已有数据，合并
    if args.etf_only or args.calendar_only:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            if args.etf_only:
                nt_data["calendar"] = old_data.get("calendar", [])
            if args.calendar_only:
                nt_data["etfFlow"] = old_data.get("etfFlow", {})
                nt_data["alerts"] = old_data.get("alerts", [])

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(nt_data, f, ensure_ascii=False, indent=2)
    print(f"")
    print(f"数据已保存: {out_file}")

    # 6. 打印摘要
    print("=" * 40)
    print("  摘要")
    print("=" * 40)
    if not args.calendar_only:
        print(f"  异动提醒: {len(alerts)} 条")
        print(f"  ETF监测: {len(etf_list)} 只 ({up_count}涨 {down_count}跌)")
    if not args.etf_only:
        print(f"  重要日历: {len(calendar_events)} 条事件 (至2027-12-31)")
    print(f"  更新时间: {now_str}")


if __name__ == "__main__":
    main()
