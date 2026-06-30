#!/usr/bin/env python3
"""获取 A 股 + 港股全量股票名称列表（每周更新一次即可）"""

import json, os, time
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT = os.path.join(DATA_DIR, "stock_names.json")

def _fetch_a_share_via_eastmoney():
    """东方财富全量 A 股代码→名称（akshare stock_zh_a_spot_em 经常超时丢数据时的兜底）"""
    import requests
    url = "https://push2.eastmoney.com/api/qianlong/clist/get?pn=1&pz=10000&po=1&np=1&fltt=2&invt=2&fs=m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2&fields=f12,f14"
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json().get("data") or {}
        diff = data.get("diff") or []
        result = []
        for item in diff:
            code = str(item.get("f12", "")).strip()
            name = str(item.get("f14", "")).strip()
            if not code or not name:
                continue
            if not (code.startswith(("0", "3", "6")) and len(code) == 6):
                continue
            prefix = "sz" if code.startswith(("0", "3")) else "sh"
            result.append({"code": code, "name": name, "full_code": prefix + code})
        return result
    except Exception as e:
        print(f"  ⚠️ 东方财富 A股接口失败: {e}")
        return []

def _fetch_a_share_via_sina():
    """新浪全量 A 股代码→名称（分页拉沪A/深A/北A，更稳定的兜底）"""
    import requests, json
    result = []
    nodes = [
        ("sh", "sh_a", 2500),   # 沪A (沪市主板+科创板)
        ("sz", "sz_a", 3000),   # 深A (深市主板+中小板+创业板)
        ("bj", "hs_a", 300),    # 北A (北交所)
    ]
    for prefix, node, total in nodes:
        for offset in range(0, total, 80):
            try:
                url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?node={node}&sort=symbol&asc=1&num=80&page={offset//80 + 1}&_s_r_a=page"
                r = requests.get(url, timeout=15, headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://vip.stock.finance.sina.com.cn/"
                })
                txt = r.text.strip()
                if not txt.startswith("["):
                    break
                items = json.loads(txt)
                if not items:
                    break
                for item in items:
                    code = str(item.get("symbol", "")).strip()
                    name = str(item.get("name", "")).strip()
                    if not code or not name:
                        continue
                    # 取纯 6 位代码
                    code6 = code[2:] if len(code) > 6 else code
                    if not (code6.startswith(("0", "3", "6")) and len(code6) == 6):
                        continue
                    result.append({"code": code6, "name": name, "full_code": prefix + code6})
            except Exception as e:
                print(f"  ⚠️ 新浪 {node} 第{offset//80+1}页失败: {e}")
                break
    return result

def main():
    print("=" * 50)
    print("  A 股 + 港股全量股票名称列表更新")
    print("=" * 50)

    all_stocks = []

    # ── A 股（新浪优先，东财次之，akshare 最后）──
    a_stocks = _fetch_a_share_via_sina()
    if not a_stocks:
        a_stocks = _fetch_a_share_via_eastmoney()
    if not a_stocks:
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("代码", "")).strip()
                    name = str(row.get("名称", "")).strip()
                    if not code or not name:
                        continue
                    prefix = "sz" if code.startswith(("0", "3")) else "sh"
                    a_stocks.append({"code": code, "name": name, "full_code": prefix + code})
        except Exception as e:
            print(f"  ⚠️ A股获取失败: {e}")

    if a_stocks:
        all_stocks.extend(a_stocks)
        print(f"  ✅ A股: {len(a_stocks)} 只")
    else:
        print("  ⚠️ A股全失败，跳过")

    # ── 港股 ──
    try:
        import akshare as ak
        time.sleep(1)  # 避免请求过于密集
        df_hk = ak.stock_hk_spot_em()
        if df_hk is None or df_hk.empty:
            print("  ⚠️ 港股无数据")
        else:
            hk_count = 0
            for _, row in df_hk.iterrows():
                code = str(row.get("代码", "")).strip()
                name = str(row.get("名称", "")).strip()
                if not code or not name:
                    continue
                # 去重：跳过已在A股列表中的相同code
                if any(s["code"] == code for s in all_stocks):
                    continue
                all_stocks.append({
                    "code": code,
                    "name": name,
                    "full_code": "hk" + code,
                })
                hk_count += 1
            print(f"  ✅ 港股: {hk_count} 只")
    except Exception as e:
        print(f"  ⚠️ 港股获取失败: {e}")

    if len(all_stocks) < 4000:
        print(f"  ⚠️ 总数 {len(all_stocks)} 不足（预期>4000），保留旧文件")
        return

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(all_stocks, f, ensure_ascii=False, indent=0)

    print(f"  ✅ 总计 {len(all_stocks)} 只 → {OUTPUT}")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
