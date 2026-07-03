#!/usr/bin/env python3
"""
fetch_etf_subscription.py
抓取上交所宽基ETF 份额数据，通过日环比计算申购赎回
筛选逻辑：匹配宽基指数关键词（300/500/1000/50/180/科创50/A500/创业板/综指），排除行业/主题ETF
输出: data/etf_subscription.json
"""
import akshare as ak
import json
import os
import re
from datetime import datetime, timedelta
import time

DATA_DIR = 'data'
os.makedirs(DATA_DIR, exist_ok=True)

# 行业/主题 ETF 排除关键词
SECTOR_KEYWORDS = [
    '半导体', '芯片', '医药', '医疗', '券商', '银行', '煤炭', '通信',
    '消费', '军工', '电池', '新能源', '光伏', '有色', '化工',
    '物联网', '云计算', '互联', '科技', '传媒', '地产', '基建',
    '食品', '汽车', '钢铁', '建材', '农业', '环保', '旅游',
    '教育', '港股', '恒生', 'H股', '德国', '日本', '法国',
    '印度', '越南', '黄金', '原油', '豆粕', '能源', '商品',
    '货币', '债券', '国债', '国开', '政金', '城投', '信用',
    '短融', '存单', '理财', '标普', '纳斯达克', 'MSCI', '富时',
    '央企', '国企', '产业', '畜牧', '养殖', '种植', '渔业',
    '种业', '化肥', '农药', '服装', '家电', '家电',
    '造纸', '包装', '石油', '天然气', '电力', '水务', '燃气',
    '供热', '固废', '污水', '风电', '核电', '水电', '储能',
    '氢能', '生物质', '充电桩', '换电', '锂电', '钠电',
    '固态', '燃料电池', '电机', '电控', '轨道交通', '航空航天',
    '船舶', '港口', '机场', '公路', '铁路', '物流', '快递',
    '仓储', '供应链', '贸易', '零售', '电商', '免税', '餐饮',
    '酒店', '演艺', '会展', '体育', '游戏', '动漫', '影视',
    '音乐', '广告', '营销', '家政', '共享', '租赁', '卫星',
    '火箭', '基因', '干细胞', '机器人', '无人机', '虚拟',
    '增强', '量子', '纳米', '石墨烯', '超导', '核聚变',
    '信创', '电子', '电信', '物联网', '5G', '6G', 'AI',
    '智能制造', '工业',
]

def is_broad_based(name):
    """判断是否为宽基指数ETF（沪深300/中证500/中证1000/创业板/上证50/科创50/A500等）"""
    name = name.strip()
    # 排除行业/主题ETF
    for kw in SECTOR_KEYWORDS:
        if kw in name:
            return False
    # 宽基指数关键词（正则模式）
    broad_patterns = [
        r'(?:沪深)?300(?:ETF|指数|基金|[A-Z]|增|价值|成长|质量|ESG|红利|指增|增强)?$',
        r'^(?:HS)?300(?:ETF|增|价值|成长|质量|ESG|红利|增强)?$',
        r'^(?:[^\x00-\x7f]*?)300(?:ETF|增|价值|成长|质量|ESG|红利|增强|指数)?$',
        r'(?:中证)?500(?:ETF|指数|基金|质量|低波|价值|成长|增强)?$',
        r'^(?:ZZ)?500(?:ETF|基金|指数|[A-Z])?$',
        r'(?:中证)?1000(?:ETF|指数|基金|价值|成长|增强)?$',
        r'^(?:ZZ)?1000$',
        r'(?:上证)?50(?:ETF|指数|基金|[A-Z])?$',
        r'^(?:SZ|SH)?50(?:ETF)?(?:\s|$)',
        r'^(?:上证)?180(?:ETF|指数|基金|[A-Z])?$',
        r'^创业板(?:ETF|指数|50)?$',
        r'^创50(?:ETF)?$',
        r'^(?:科创板|科创)(?:50|100|200)(?:ETF|指数|基金|[A-Za-z])?$',
        r'^(?:中证)?A500(?:ETF|基金|指数|龙头|添富|富国|华宝|中金|申万|银河|红利|增强|[A-Z])?$',
        r'^A500[EF]?$',
        r'^综指ETF$',
        r'^(?:上证|沪深|中证)综合(?:ETF|指数)?$',
        r'(?:中证)?科创(?:50|100|200)(?:ETF|指数|基金|[A-Za-z])?$',
        r'^AH300ETF$',
        r'^AH500ETF$',
        r'^(?:天弘|广发|华夏|平安|国寿|方正|博时|易方达|华泰|添富|兴业|招商|民生|工银|中金|泰康|国联|国泰|永赢)(?:300|500|1000|50|180)$',
        r'^(?:天弘|广发|华夏|平安|国寿|方正|博时|易方达|华泰|添富|兴业|招商|民生|工银|中金|泰康|国联|国泰|永赢)(?:300|500|1000|50|180)(?:ETF|指数|基金|增|价值|成长|质量|低波|红利|增强)?$',
        r'^MSCIA50$',
        r'^(?:港股通50|中国A50)$',
        r'^A50(?:中证|指数|基金|龙头|博时|新华)?$',
        r'^双创50(?:ETF)?$',
        r'^A50ETF$',
    ]
    for p in broad_patterns:
        if re.search(p, name):
            return True
    return False

def get_recent_trade_dates(n=60):
    dates = []
    d = datetime.now()
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.strftime('%Y%m%d'))
        d -= timedelta(days=1)
    return list(reversed(dates))

def main():
    dates = get_recent_trade_dates(60)
    print('🔵 抓取上交所宽基ETF 份额数据（' + str(len(dates)) + ' 个交易日）...')
    result = {'sh': [], 'sh_all': [], 'update_time': ''}
    prev_total = None
    prev_total_all = None

    for d in dates:
        try:
            df = ak.fund_etf_scale_sse(date=d)
            if df is None or len(df) == 0:
                continue
            
            # 宽基ETF筛选
            df_broad = df[df['基金简称'].apply(is_broad_based)]
            broad_count = len(df_broad)
            all_count = len(df)
            
            # 宽基ETF统计
            broad_shares = df_broad['基金份额'].sum() if broad_count > 0 else 0
            broad_bil = round(broad_shares / 1e8, 2)
            
            # 所有ETF统计（保留用于对照）
            all_shares = df['基金份额'].sum()
            all_bil = round(all_shares / 1e8, 2)
            
            dt_fmt = str(int(d[4:6])) + '/' + str(int(d[6:8]))
            dt_raw = d[:4] + '-' + d[4:6] + '-' + d[6:]

            # 宽基ETF entry
            entry = {
                'date': dt_fmt,
                'date_raw': dt_raw,
                'total_shares_bil': broad_bil,
                'net_subscribe_bil': 0.0
            }
            if prev_total is not None:
                net = round((broad_shares - prev_total) / 1e8, 2)
                entry['net_subscribe_bil'] = net
            result['sh'].append(entry)
            prev_total = broad_shares
            
            # 所有ETF entry（对照用）
            entry_all = {
                'date': dt_fmt,
                'date_raw': dt_raw,
                'total_shares_bil': all_bil,
                'net_subscribe_bil': 0.0
            }
            if prev_total_all is not None:
                net_all = round((all_shares - prev_total_all) / 1e8, 2)
                entry_all['net_subscribe_bil'] = net_all
            result['sh_all'].append(entry_all)
            prev_total_all = all_shares

            print('  ' + dt_fmt + '：宽基ETF ' + str(broad_count) + '/' + str(all_count) + '只，净申购 ' + str(entry['net_subscribe_bil']) + ' 亿份')
        except Exception as e:
            pass
        time.sleep(0.3)

    result['update_time'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    out = os.path.join(DATA_DIR, 'etf_subscription.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print('  ✅ 已保存：' + out + '（' + str(len(result['sh'])) + ' 条）')

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise

