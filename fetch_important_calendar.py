import requests
import json
from datetime import datetime, timedelta
import os

def fetch_financial_reports():
    """抓取财报日历，获取未来90天内的A股财报披露日期（使用akshare）"""
    try:
        import akshare as ak
        import pandas as pd

        today = datetime.now()
        current_year = today.year

        all_reports = []

        # akshare的stock_report_disclosure只支持已过报告期
        # 我们需要获取近期的报告期，然后过滤披露日期在未来90天内
        periods_to_try = []

        # 构建可能的报告期列表
        valid_periods = []
        for y in range(current_year - 2, current_year + 1):
            for p in ['年报', '一季报', '中报', '三季报']:
                valid_periods.append(f"{y}{p}")

        # 只尝试当前日期之前的报告期
        for period in valid_periods:
            year = int(period[:4])
            type_ = period[4:]

            # 判断该报告期的披露截止日
            report_end_month = {
                '年报': 4,   # 次年4月
                '一季报': 4,  # 当年4月
                '中报': 8,    # 当年8月
                '三季报': 10  # 当年10月
            }
            end_year = year + 1 if type_ == '年报' else year
            end_month = report_end_month.get(type_, 12)

            # 如果该报告期的披露截止日已经过了，就可以获取数据
            if end_year < current_year or (end_year == current_year and end_month < today.month):
                periods_to_try.append(period)

        print(f"  尝试获取报告期: {periods_to_try}")

        for period in periods_to_try:
            try:
                df = ak.stock_report_disclosure(market='沪深京', period=period)
                future_date = today + timedelta(days=90)

                for _, row in df.iterrows():
                    first_date = row['首次预约']
                    actual_date = row['实际披露']

                    # 优先使用实际披露日期，否则使用首次预约
                    report_date = actual_date if pd.notna(actual_date) else first_date

                    if pd.notna(report_date):
                        report_date_str = report_date.strftime('%Y-%m-%d')
                        # 只保留未来且90天内的
                        if today.strftime('%Y-%m-%d') <= report_date_str <= future_date.strftime('%Y-%m-%d'):
                            all_reports.append({
                                'code': row['股票代码'],
                                'name': row['股票简称'],
                                'period': period,
                                'report_date': report_date_str,
                                'first_appointment': first_date.strftime('%Y-%m-%d') if pd.notna(first_date) else None,
                                'actual_date': actual_date.strftime('%Y-%m-%d') if pd.notna(actual_date) else None
                            })
            except Exception as e:
                print(f"  获取{period}数据失败: {e}")
                continue

        # 去重
        seen = set()
        unique_reports = []
        for r in all_reports:
            key = (r['code'], r['period'])
            if key not in seen:
                seen.add(key)
                unique_reports.append(r)

        print(f"  获取到{len(unique_reports)}条财报披露日期")
        return unique_reports
    except Exception as e:
        print(f"抓取财报日历失败: {e}")
        return []

def fetch_holidays():
    """抓取中国法定假期及调休安排（使用apihubs稳定接口）"""
    holidays = {}
    adjusted_workdays = {}
    
    # 尝试从缓存文件读取
    cache_file = os.path.join(os.path.dirname(__file__), 'data', 'important_calendar.json')
    cached_holidays = {}
    cached_adjusted = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                cached_holidays = cached_data.get('holidays', {})
                cached_adjusted = cached_data.get('adjusted_workdays', {})
                if cached_holidays:
                    print(f"  找到缓存的假期数据: {len(cached_holidays)}天假期")
        except:
            pass
    
    try:
        current_year = datetime.now().year
        success = False
        for year in [current_year, current_year + 1]:
            url = f"https://api.apihubs.cn/holiday/get?year={year}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            print(f"假期接口({year})状态码: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"  返回code: {data.get('code')}, msg: {data.get('msg', '')}")
                if data.get('code') == 0 and 'data' in data and 'list' in data['data']:
                    for day_info in data['data']['list']:
                        date_str = str(day_info['date'])
                        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                        if day_info.get('holiday_today') == 2:
                            holidays[formatted_date] = {
                                'name': '法定假期',
                                'wage': day_info.get('holiday_legal', 1)
                            }
                        if day_info.get('workday') == 2:
                            adjusted_workdays[formatted_date] = {
                                'name': '调休上班',
                                'wage': 1
                            }
                    success = True
                else:
                    print(f"  API返回错误: {data.get('msg', '未知错误')}")
            else:
                print(f"  请求失败: HTTP {response.status_code}")
        
        # 如果API调用失败，使用缓存数据
        if not success or (len(holidays) == 0 and len(adjusted_workdays) == 0):
            print("  API调用失败或被限频，使用缓存数据")
            holidays = cached_holidays
            adjusted_workdays = cached_adjusted
        
        # 手动补充假期名称（基于国务院通知，2026年）
        holiday_names = {
            '2026-01-01': '元旦', '2026-01-02': '元旦', '2026-01-03': '元旦',
            '2026-02-15': '春节', '2026-02-16': '春节', '2026-02-17': '春节',
            '2026-02-18': '春节', '2026-02-19': '春节', '2026-02-20': '春节',
            '2026-02-21': '春节', '2026-02-22': '春节', '2026-02-23': '春节',
            '2026-04-04': '清明节', '2026-04-05': '清明节', '2026-04-06': '清明节',
            '2026-05-01': '劳动节', '2026-05-02': '劳动节', '2026-05-03': '劳动节',
            '2026-05-04': '劳动节', '2026-05-05': '劳动节',
            '2026-06-19': '端午节', '2026-06-20': '端午节', '2026-06-21': '端午节',
            '2026-09-25': '中秋节', '2026-09-26': '中秋节', '2026-09-27': '中秋节',
            '2026-10-01': '国庆节', '2026-10-02': '国庆节', '2026-10-03': '国庆节',
            '2026-10-04': '国庆节', '2026-10-05': '国庆节', '2026-10-06': '国庆节',
            '2026-10-07': '国庆节',
            '2027-01-01': '元旦', '2027-01-02': '元旦', '2027-01-03': '元旦',
            '2027-02-14': '春节', '2027-02-15': '春节', '2027-02-16': '春节',
            '2027-02-17': '春节', '2027-02-18': '春节', '2027-02-19': '春节',
            '2027-02-20': '春节',
        }
        for date in holidays:
            if date in holiday_names:
                holidays[date]['name'] = holiday_names[date]
        return {'holidays': holidays, 'adjusted_workdays': adjusted_workdays}
    except Exception as e:
        print(f"抓取假期安排失败: {e}")
        return {'holidays': {}, 'adjusted_workdays': {}}

def fetch_economic_events():
    """抓取重要经济事件（预置重要事件）"""
    events = []

    # 预置的重要经济事件（2026年6月-9月）
    preset_events = [
        # 美联储FOMC会议（2026年8次，使用公告日=第二天）
        {'date': '2026-01-28', 'country': '美国', 'event': '美联储FOMC会议(1.27-28)', 'importance': 3},
        {'date': '2026-03-18', 'country': '美国', 'event': '美联储FOMC会议(3.17-18)', 'importance': 3},
        {'date': '2026-04-29', 'country': '美国', 'event': '美联储FOMC会议(4.28-29)', 'importance': 3},
        {'date': '2026-06-17', 'country': '美国', 'event': '美联储FOMC会议(6.16-17)', 'importance': 3},
        {'date': '2026-07-29', 'country': '美国', 'event': '美联储FOMC会议(7.28-29)', 'importance': 3},
        {'date': '2026-09-16', 'country': '美国', 'event': '美联储FOMC会议(9.15-16)', 'importance': 3},
        {'date': '2026-10-28', 'country': '美国', 'event': '美联储FOMC会议(10.27-28)', 'importance': 3},
        {'date': '2026-12-09', 'country': '美国', 'event': '美联储FOMC会议(12.8-9)', 'importance': 3},
        # 中国重要经济数据发布
        {'date': '2026-07-15', 'country': '中国', 'event': '中国Q2 GDP数据发布', 'importance': 3},
        {'date': '2026-10-18', 'country': '中国', 'event': '中国Q3 GDP数据发布', 'importance': 3},
        # 中国LPR利率公布日（每月20日）
        {'date': '2026-06-20', 'country': '中国', 'event': 'LPR利率公布', 'importance': 2},
        {'date': '2026-07-20', 'country': '中国', 'event': 'LPR利率公布', 'importance': 2},
        {'date': '2026-08-20', 'country': '中国', 'event': 'LPR利率公布', 'importance': 2},
        {'date': '2026-09-20', 'country': '中国', 'event': 'LPR利率公布', 'importance': 2},
        {'date': '2026-10-20', 'country': '中国', 'event': 'LPR利率公布', 'importance': 2},
        {'date': '2026-11-20', 'country': '中国', 'event': 'LPR利率公布', 'importance': 2},
        {'date': '2026-12-20', 'country': '中国', 'event': 'LPR利率公布', 'importance': 2},
        # A股财报披露截止日
        {'date': '2026-08-31', 'country': '中国', 'event': 'A股中报披露截止', 'importance': 2},
        {'date': '2026-10-31', 'country': '中国', 'event': 'A股三季报披露截止', 'importance': 2},
    ]

    # 过滤出未来90天内的事件
    today = datetime.now()
    future_date = today + timedelta(days=90)
    for evt in preset_events:
        evt_date = datetime.strptime(evt['date'], '%Y-%m-%d')
        if today <= evt_date <= future_date:
            events.append(evt)

    return events

def main():
    print("开始抓取重要日历数据...")
    financial_reports = fetch_financial_reports()
    holiday_info = fetch_holidays()
    economic_events = fetch_economic_events()

    calendar_data = {
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'financial_reports': financial_reports,
        'holidays': holiday_info['holidays'],
        'adjusted_workdays': holiday_info['adjusted_workdays'],
        'economic_events': economic_events
    }

    # 保存到data目录
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(data_dir, exist_ok=True)
    data_path = os.path.join(data_dir, 'important_calendar.json')
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(calendar_data, f, ensure_ascii=False, indent=2)
    print(f"✅ 日历数据已保存到: {data_path}")
    print(f"   - 财报日历: {len(financial_reports)}条")
    print(f"   - 假期安排: {len(holiday_info['holidays'])}天假期, {len(holiday_info['adjusted_workdays'])}天调休")
    print(f"   - 经济事件: {len(economic_events)}条")

    # 复制到dist目录
    dist_dir = os.path.join(os.path.dirname(__file__), 'dist')
    os.makedirs(dist_dir, exist_ok=True)
    dist_path = os.path.join(dist_dir, 'important_calendar.json')
    with open(dist_path, 'w', encoding='utf-8') as f:
        json.dump(calendar_data, f, ensure_ascii=False, indent=2)
    print(f"✅ 日历数据已复制到dist目录: {dist_path}")

if __name__ == '__main__':
    main()
