"""
宏观观测数据采集脚本
三板块：货币政策 / 经济基本面 / 全球宏观
数据源：akshare + 东方财富API

月度指标发布日程（用于前端⭐标记）:
  - LPR: 每月20日(最近一个工作日)
  - PMI: 月末/次月初(通常1-3日)
  - CPI/PPI: 次月10日左右
  - 社融: 次月1-10日
  - M2: 次月12日左右
  - 出口: 次月7日左右
  - 新增投资者: 次月中旬
"""

import json
import os
import sys
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

# ════════════════════════════════════════
#  月度指标发布日程配置
#  expected_day: 预期每月发布日期（用于⭐判断）
#  tolerance_days: 容差天数（发布日后N天内都算"本月已更新"）
# ════════════════════════════════════════
MONTHLY_INDICATOR_SCHEDULE = {
    # 货币政策
    'lpr':            {'name': 'LPR利率',        'expected_day': 20, 'tolerance_days': 5},
    'm2_yoy':         {'name': 'M2同比',          'expected_day': 12, 'tolerance_days': 5},
    # 经济基本面
    'pmi':            {'name': '制造业PMI',       'expected_day': 1,  'tolerance_days': 10},   # 月末/月初
    'cpi':            {'name': 'CPI同比',         'expected_day': 10, 'tolerance_days': 5},
    'ppi':            {'name': 'PPI同比',         'expected_day': 10, 'tolerance_days': 5},
    'social_financing':{'name': '社融规模',        'expected_day': 10, 'tolerance_days': 8},   # 1-10日
    'export_yoy':     {'name': '出口增速',        'expected_day': 7,  'tolerance_days': 5},
    # 市场情绪
    'new_investors':  {'name': '新增投资者',      'expected_day': 15, 'tolerance_days': 10},
}


def safe_call(fn, name, default=None):
    """安全调用，失败返回默认值"""
    try:
        return fn()
    except Exception as e:
        print(f"  [WARN] {name} 获取失败: {e}")
        return default


def fetch_macro_data():
    """采集全部宏观数据"""
    import akshare as ak
    import requests

    now = datetime.now()
    result = {
        'update_time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'monetary': {},      # 货币政策
        'economy': {},       # 经济基本面
        'market_sentiment': {},  # 市场情绪（新增）
        'global_macro': {},  # 全球宏观
        # 新增：月度指标更新状态（用于前端⭐标记）
        'indicator_status': {},
    }

    def mark_updated(indicator_key, data_dict):
        """标记某指标已更新，记录到indicator_status"""
        today = datetime.now().strftime('%Y-%m-%d')
        sched = MONTHLY_INDICATOR_SCHEDULE.get(indicator_key)
        if sched:
            exp_day = sched['expected_day']
            tol = sched['tolerance_days']
            # 计算本月预期发布日
            try:
                current_day = now.day
                expected_date = now.replace(day=min(exp_day, 28))  # 避免超过当月天数
                days_since = (now - expected_date).days
                is_fresh = -2 <= days_since <= tol  # 发布日前2天到容差期内都算新鲜
            except ValueError:
                is_fresh = True
            result['indicator_status'][indicator_key] = {
                'last_updated': today,
                'is_fresh': is_fresh,
                'name': sched['name'],
            }

    # ========== 1. 货币政策 ==========
    print("=== 货币政策 ===")

    # 1a. 10年期国债收益率（中+美）
    print("  10Y国债收益率...")
    df = safe_call(lambda: ak.bond_zh_us_rate(), "国债收益率")
    if df is not None and len(df) > 0:
        cn = df[['日期', '中国国债收益率10年']].dropna()
        us = df[['日期', '美国国债收益率10年']].dropna()
        if len(cn) > 0:
            cl = cn.iloc[-1]
            result['monetary']['cn_bond_10y'] = {
                'value': round(float(cl['中国国债收益率10年']), 4),
                'date': str(cl['日期'])[:10],
            }
        if len(us) > 0:
            ul = us.iloc[-1]
            result['monetary']['us_bond_10y'] = {
                'value': round(float(ul['美国国债收益率10年']), 4),
                'date': str(ul['日期'])[:10],
            }
        # 中美利差
        if 'cn_bond_10y' in result['monetary'] and 'us_bond_10y' in result['monetary']:
            spread = result['monetary']['cn_bond_10y']['value'] - result['monetary']['us_bond_10y']['value']
            result['monetary']['cn_us_spread'] = {'value': round(spread, 2)}

    # 1b. LPR利率
    print("  LPR利率...")
    df_lpr = safe_call(lambda: ak.macro_china_lpr(), "LPR")
    if df_lpr is not None and len(df_lpr) > 0:
        lpr_last = df_lpr.iloc[-1]
        result['monetary']['lpr'] = {
            'lpr_1y': float(lpr_last['LPR1Y']),
            'lpr_5y': float(lpr_last['LPR5Y']),
            'date': str(lpr_last['TRADE_DATE'])[:10],
        }
        mark_updated('lpr', result['monetary']['lpr'])

    # 1c. Shibor（替代逆回购，每日更新）
    print("  Shibor利率...")
    df_shibor = safe_call(lambda: ak.macro_china_shibor_all(), "Shibor")
    if df_shibor is not None and len(df_shibor) > 0:
        sh = df_shibor.iloc[-1]
        result['monetary']['shibor'] = {
            'on': float(sh.get('O/N-定价', 0)),
            'w1': float(sh.get('1W-定价', 0)),
            'm1': float(sh.get('1M-定价', 0)),
            'm3': float(sh.get('3M-定价', 0)),
            'date': str(sh.get('日期', ''))[:10],
        }

    # 1d. M2/M1货币供应（用年度数据）
    print("  M2/M1货币供应...")
    df_m2 = safe_call(lambda: ak.macro_china_m2_yearly(), "M2年度")
    if df_m2 is not None and len(df_m2) > 0:
        m2_row = df_m2[df_m2['商品'].str.contains('M2', na=False)].tail(1)
        if len(m2_row) > 0:
            m2_val = m2_row.iloc[0]['今值']
            result['monetary']['m2_yoy'] = {
                'value': float(m2_val) if str(m2_val) != 'nan' else None,
                'date': str(m2_row.iloc[0]['日期'])[:10],
            }
            if result['monetary']['m2_yoy']['value'] is not None:
                mark_updated('m2_yoy', result['monetary']['m2_yoy'])

    # 1e. 央行公开市场操作（OMO）— 东方财富API（每日）
    print("  央行公开市场操作(OMO)...")
    try:
        r = requests.get(
            'https://push2his.eastmoney.com/api/qt/stock/kline/get',
            params={
                'secid': '1.000001',  # 用逆回购利率隐含
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
                'klt': '101', 'fqt': '1', 'end': '20500101', 'lmt': 5,
            },
            timeout=10
        )
        # 改用更直接的央行公开市场操作接口
        r2 = requests.get('https://datacenter-web.eastmoney.com/api/data/v1/get', params={
            'reportName': 'RPT_MARKET_OPENOPERATIONNETINVEST',
            'columns': 'REPORT_DATE,NET_INVEST_AMOUNT',
            '(pageNumber)': '1', '(pageSize)': '1',
            'sortColumns': 'REPORT_DATE', 'sortTypes': '-1',
        }, timeout=10)
        omo_result = r2.json()
        if omo_result.get('result') and omo_result['result'].get('data'):
            d = omo_result['result']['data'][0]
            net_val = d.get('NET_INVEST_AMOUNT', 0)
            result['monetary']['open_market_operation'] = {
                'net_inflow': round(float(net_val), 1) if net_val else 0,
                'date': str(d.get('REPORT_DATE', ''))[:10],
            }
            print(f"    OMO净投放: {net_val}亿")
        else:
            # fallback: 给一个默认值标记为暂无
            result['monetary']['open_market_operation'] = {
                'net_inflow': None,
                'date': datetime.now().strftime('%Y-%m-%d'),
            }
    except Exception as e:
        print(f"  [WARN] OMO获取失败: {e}")
        result['monetary']['open_market_operation'] = {'net_inflow': None, 'date': datetime.now().strftime('%Y-%m-%d')}

    # ========== 2. 经济基本面 ==========
    print("\n=== 经济基本面 ===")

    # 2a. 制造业PMI
    print("  PMI...")
    df_pmi = safe_call(lambda: ak.macro_china_pmi_yearly(), "PMI")
    if df_pmi is not None and len(df_pmi) > 0:
        pmi_row = df_pmi[df_pmi['商品'].str.contains('制造业')].tail(1)
        if len(pmi_row) > 0:
            r = pmi_row.iloc[0]
            val = r['今值']
            result['economy']['pmi'] = {
                'value': float(val) if str(val) != 'nan' else None,
                'forecast': float(r['预测值']) if str(r['预测值']) != 'nan' else None,
                'previous': float(r['前值']) if str(r['前值']) != 'nan' else None,
                'date': str(r['日期'])[:10],
            }
            if result['economy']['pmi']['value'] is not None:
                mark_updated('pmi', result['economy']['pmi'])

    # 2b. CPI
    print("  CPI...")
    df_cpi = safe_call(lambda: ak.macro_china_cpi_monthly(), "CPI")
    if df_cpi is not None and len(df_cpi) > 0:
        cpi_rows = df_cpi[df_cpi['商品'].str.contains('CPI')]
        if len(cpi_rows) > 0:
            cpi_last = cpi_rows.tail(1).iloc[0]
            val = cpi_last.get('今值')
            result['economy']['cpi'] = {
                'value': float(val) if str(val) != 'nan' else None,
                'previous': float(cpi_last.get('前值')) if str(cpi_last.get('前值')) != 'nan' else None,
                'date': str(cpi_last['日期'])[:10],
            }
            if result['economy']['cpi']['value'] is not None:
                mark_updated('cpi', result['economy']['cpi'])

    # 2c. PPI
    print("  PPI...")
    df_ppi = safe_call(lambda: ak.macro_china_ppi_yearly(), "PPI")
    if df_ppi is not None and len(df_ppi) > 0:
        ppi_last = df_ppi.tail(1).iloc[0]
        val = ppi_last.get('今值')
        result['economy']['ppi'] = {
            'value': float(val) if str(val) != 'nan' else None,
            'previous': float(ppi_last.get('前值')) if str(ppi_last.get('前值')) != 'nan' else None,
            'date': str(ppi_last['日期'])[:10],
        }
        if result['economy']['ppi']['value'] is not None:
            mark_updated('ppi', result['economy']['ppi'])

    # 2d. 社融规模
    print("  社融规模...")
    df_szr = safe_call(lambda: ak.macro_china_bank_financing(), "社融")
    if df_szr is not None and len(df_szr) > 0:
        szr_last = df_szr.tail(1).iloc[0]
        result['economy']['social_financing'] = {
            'value': int(szr_last['最新值']) if szr_last.get('最新值') else None,
            'change_pct': round(float(szr_last['涨跌幅']), 1),
            'date': str(szr_last['日期'])[:10],
        }
        if result['economy']['social_financing']['value'] is not None:
            mark_updated('social_financing', result['economy']['social_financing'])

    # 2e. 出口增速
    print("  出口增速...")
    df_export = safe_call(lambda: ak.macro_china_exports_yoy(), "出口")
    if df_export is not None and len(df_export) > 0:
        export_last = df_export[df_export['今值'].notna()].tail(1)
        if len(export_last) > 0:
            ex = export_last.iloc[0]
            result['economy']['export_yoy'] = {
                'value': float(ex['今值']),
                'previous': float(ex['前值']) if str(ex['前值']) != 'nan' else None,
                'date': str(ex['日期'])[:10],
            }
            mark_updated('export_yoy', result['economy']['export_yoy'])

    # 2f. IPO数量/募资额（周度）— akshare
    print("  IPO数据...")
    try:
        df_ipo = safe_call(lambda: ak.stock_ipo_info(), "IPO信息")
        if df_ipo is not None and len(df_ipo) > 0:
            # 取最近有数据的记录
            ipo_recent = df_ipo.tail(10)
            ipo_count = len(ipo_recent)
            ipo_amount = 0
            # 尝试获取募资金段
            for col in ['募集总额(万元)', '募资总额', '募集资金(亿)', '发行总额']:
                if col in ipo_recent.columns:
                    try:
                        ipo_amount = float(ipo_recent[col].iloc[-1]) if str(ipo_recent[col].iloc[-1]) != 'nan' else 0
                        if '万' in col or '万元' in col:
                            ipo_amount = round(ipo_amount / 10000, 1)  # 转亿
                        break
                    except (ValueError, TypeError):
                        continue
            result['economy']['ipo'] = {
                'count': ipo_count,
                'amount': ipo_amount,
                'date': datetime.now().strftime('%Y-%m-%d'),
            }
            print(f"    近期IPO: {ipo_count}只, 募资约{ipo_amount}亿")
        else:
            result['economy']['ipo'] = {'count': 0, 'amount': 0, 'date': datetime.now().strftime('%Y-%m-%d')}
    except Exception as e:
        print(f"  [WARN] IPO获取失败: {e}")
        result['economy']['ipo'] = {'count': 0, 'amount': 0, 'date': datetime.now().strftime('%Y-%m-%d')}

    # ========== 4. 市场情绪（新增板块） ==========
    print("\n=== 市场情绪 ===")

    # 4a. 新增投资者人数（月度）— 东方财富/akshare
    print("  新增投资者人数...")
    try:
        df_inv = safe_call(lambda: ak.stock_account_statistics_em(), "投资者人数")
        if df_inv is not None and len(df_inv) > 0:
            inv_last = df_inv.tail(1).iloc[0]
            # 尝试不同可能的字段名
            new_val = None
            change_val = None
            for val_col in ['新增投资者-数量', '新增投资者数量', '新增投资者(万)', 'NEW_INVESTOR']:
                if val_col in df_inv.columns:
                    new_val = inv_last.get(val_col)
                    break
            for chg_col in ['新增投资者-环比', '环比变化', 'CHANGE']:
                if chg_col in df_inv.columns:
                    change_val = inv_last.get(chg_col)
                    break
            if new_val is None:
                # 尝试数值列
                numeric_cols = df_inv.select_dtypes(include=['number']).columns.tolist()
                if numeric_cols:
                    new_val = inv_last.get(numeric_cols[-1])
            result['market_sentiment']['new_investors'] = {
                'value': round(float(new_val), 2) if str(new_val) != 'nan' and new_val is not None else None,
                'change': round(float(change_val), 2) if change_val is not None and str(change_val) != 'nan' else None,
                'date': str(inv_last.get('日期', datetime.now().strftime('%Y-%m-%d')))[:10],
            }
            if result['market_sentiment']['new_investors']['value'] is not None:
                mark_updated('new_investors', result['market_sentiment']['new_investors'])
            print(f"    新增: {new_val}万")
        else:
            result['market_sentiment']['new_investors'] = {'value': None, 'change': None, 'date': ''}
    except Exception as e:
        print(f"  [WARN] 投资者人数获取失败: {e}")
        result['market_sentiment']['new_investors'] = {'value': None, 'change': None, 'date': ''}

    # ========== 3. 全球宏观 ==========
    print("\n=== 全球宏观 ===")

    # 3a. VIX恐慌指数
    print("  VIX...")
    df_vix = safe_call(lambda: ak.futures_foreign_hist(symbol='VX'), "VIX")
    if df_vix is not None and len(df_vix) > 0:
        vix_last = df_vix.tail(1).iloc[0]
        result['global_macro']['vix'] = {
            'value': round(float(vix_last['close']), 2),
            'date': str(vix_last['date'])[:10],
        }

    # 3b. 离岸人民币汇率（Sina实时外汇行情）
    print("  离岸人民币汇率...")
    try:
        import urllib.request as _ureq
        url = 'http://hq.sinajs.cn/list=fx_susdcnh'
        headers = {'Referer': 'https://finance.sina.com.cn'}
        req = _ureq.Request(url, headers=headers)
        resp = _ureq.urlopen(req, timeout=10)
        raw = resp.read().decode('gbk')
        # 格式: var hq_str_fx_susdcnh="time,open,昨收,?,vol,现价,高,低,price,名称,...";
        # 字段: 1=昨收(prev_close), 5=现价, 17=日期
        if '=' in raw:
            parts = raw.split('"')[1].split(',')
            price = float(parts[5]) if len(parts) > 5 else None
            prev_close = float(parts[1]) if len(parts) > 1 else None  # 昨收
            trade_date = parts[17] if len(parts) > 17 else datetime.now().strftime('%Y-%m-%d')
            result['global_macro']['usdcnh'] = {
                'price': round(price, 4) if price else None,
                'prev_close': round(prev_close, 4) if prev_close else None,
                'date': trade_date,
                'source': 'Sina实时'
            }
            print(f"    USDCNH(Sina): {price:.4f} (昨收: {prev_close:.4f})")
    except Exception as e_fx:
        print(f"  [WARN] Sina USDCNH获取失败: {e_fx}, 尝试中行汇率...")
        # 降级：中行汇率
        try:
            df_boc = ak.currency_boc_sina()
            if df_boc is not None and len(df_boc) > 0:
                latest = df_boc.tail(1).iloc[0]
                price = float(latest['中行钞卖价/汇卖价']) / 100
                prev = float(latest['中行钞买价/汇买价']) / 100 if '中行钞买价/汇买价' in latest else None
                result['global_macro']['usdcnh'] = {
                    'price': round(price, 4),
                    'prev_close': round(prev, 4) if prev else None,
                    'date': str(latest['日期'])[:10],
                    'source': '中行汇率'
                }
                print(f"    USDCNH(中行): {round(price, 4)}")
        except Exception as e_boc:
            print(f"  [WARN] 中行USDCNH获取失败: {e_boc}")

    # 3c. 美元指数DXY（期货）
    print("  美元指数...")
    df_dxy = safe_call(lambda: ak.futures_foreign_hist(symbol='DX'), "DXY")
    if df_dxy is not None and len(df_dxy) > 0:
        dxy_last = df_dxy.tail(1).iloc[0]
        result['global_macro']['dxy'] = {
            'value': round(float(dxy_last['close']), 2),
            'date': str(dxy_last['date'])[:10],
        }

    # ========== 3d. 大宗商品观测 ==========
    print("\n=== 大宗商品观测 ===")
    commodities = result['global_macro']['commodities'] = {}

    # 黄金 (COMEX GC)
    print("  黄金...")
    df_gc = safe_call(lambda: ak.futures_foreign_hist(symbol='GC'), "GC黄金")
    if df_gc is not None and len(df_gc) > 0:
        gc_last = df_gc.tail(1).iloc[0]
        commodities['gold'] = {
            'value': round(float(gc_last['close']), 2),
            'unit': '美元/盎司',
            'date': str(gc_last['date'])[:10],
        }

    # 白银 (COMEX SI)
    print("  白银...")
    df_si = safe_call(lambda: ak.futures_foreign_hist(symbol='SI'), "SI白银")
    if df_si is not None and len(df_si) > 0:
        si_last = df_si.tail(1).iloc[0]
        commodities['silver'] = {
            'value': round(float(si_last['close']), 2),
            'unit': '美元/盎司',
            'date': str(si_last['date'])[:10],
        }

    # 铜 (COMEX HG, akshare返回美分/磅，需除以100)
    print("  铜...")
    df_hg = safe_call(lambda: ak.futures_foreign_hist(symbol='HG'), "HG铜")
    if df_hg is not None and len(df_hg) > 0:
        hg_last = df_hg.tail(1).iloc[0]
        commodities['copper'] = {
            'value': round(float(hg_last['close']) / 100, 4),
            'unit': '美元/磅',
            'date': str(hg_last['date'])[:10],
        }

    # 原油 (NYMEX CL)
    print("  原油...")
    df_cl = safe_call(lambda: ak.futures_foreign_hist(symbol='CL'), "CL原油")
    if df_cl is not None and len(df_cl) > 0:
        cl_last = df_cl.tail(1).iloc[0]
        commodities['oil'] = {
            'value': round(float(cl_last['close']), 2),
            'unit': '美元/桶',
            'date': str(cl_last['date'])[:10],
        }

    # 比特币 (Binance公开API → CoinGecko备用)
    print("  比特币...")
    try:
        import urllib.request as _req2
        # 优先用Binance API（国内可直连）
        btc_price = None
        btc_change = None
        try:
            binance_url = 'https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT'
            bnb_req = _req2.Request(binance_url, headers={'User-Agent': 'Mozilla/5.0'})
            bnb_resp = _req2.urlopen(bnb_req, timeout=10)
            bnb_data = json.loads(bnb_resp.read().decode('utf-8'))
            btc_price = float(bnb_data.get('lastPrice', 0))
            btc_change = float(bnb_data.get('priceChangePercent', 0))
            print(f"    BTC(Binance): ${btc_price:,.0f} (24h: {btc_change:.1f}%)")
        except Exception as e_bnb:
            print(f"    [INFO] Binance API失败, 改用CoinGecko... ({e_bnb})")
        # 备用: CoinGecko
        if btc_price is None:
            try:
                cg_url = 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true'
                cg_req = _req2.Request(cg_url, headers={'User-Agent': 'Mozilla/5.0'})
                cg_resp = _req2.urlopen(cg_req, timeout=15)
                cg_data = json.loads(cg_resp.read().decode('utf-8'))
                if 'bitcoin' in cg_data:
                    btc = cg_data['bitcoin']
                    btc_price = btc.get('usd')
                    btc_change = btc.get('usd_24h_change')
                    print(f"    BTC(CoinGecko): ${btc_price:,.0f} (24h: {btc_change:.1f}%)")
            except Exception as e_cg:
                print(f"    [WARN] CoinGecko也失败: {e_cg}")
        # 有结果就写入
        if btc_price is not None:
            commodities['bitcoin'] = {
                'value': btc_price,
                'unit': '美元/BTC',
                'change_24h': btc_change if btc_change is not None else 0,
                'date': datetime.now().strftime('%Y-%m-%d'),
            }
    except Exception as e_btc:
        print(f"  [WARN] BTC全部API获取失败: {e_btc}")

    return result


def main():
    print("=" * 50)
    print("宏观观测数据采集开始")
    print("=" * 50)

    data = fetch_macro_data()

    # 保存
    os.makedirs(DATA_DIR, exist_ok=True)
    output_path = os.path.join(DATA_DIR, 'macro_data.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 50)
    print(f"已保存: {output_path}")
    
    # 打印摘要
    print("\n--- 数据摘要 ---")
    for section, items in [
        ('货币政策', data.get('monetary', {})),
        ('经济基本面', data.get('economy', {})),
        ('市场情绪', data.get('market_sentiment', {})),
        ('全球宏观', data.get('global_macro', {})),
    ]:
        print(f"\n【{section}】")
        for k, v in items.items():
            if isinstance(v, dict):
                val_str = f"{v.get('value', '--')}%"
                date_str = v.get('date', '')
                print(f"  {k}: {val_str} ({date_str})")

    # 打印月度指标更新状态
    status = data.get('indicator_status', {})
    if status:
        print(f"\n⭐ 月度指标更新状态:")
        for key, info in status.items():
            star = "⭐" if info.get('is_fresh') else "☆"
            print(f"  {star} {info['name']}: 更新于 {info['last_updated']}")
        fresh_count = sum(1 for s in status.values() if s.get('is_fresh'))
        print(f"  → 本月已更新: {fresh_count}/{len(status)} 项")


fetch_all = fetch_macro_data
if __name__ == '__main__':
    main()
