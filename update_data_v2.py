#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新数据块脚本 — 处理 index_master.html 和 lhb_calendar.html
不碰密码页、不碰 JS、不碰任何其他内容
输出: index.html、lhb_calendar.html（可部署）

数据文件来源对照表：
  scan_result.json      → scanner.py (每日09:15/09:45/11:00/13:45/14:30/20:30)
  watch_result.json     → scanner.py (同上)
  gold_pool.json        → scanner.py (同上)
  stock_names.json      → fetch_stock_names.py (股票名称映射)
  lhb_result.json       → fetch_lhb.py (每日17:00)
  lhb_history.json      → fetch_lhb.py (同上)
  recommend.json        → scanner.py (每日09:15/09:45/11:00/13:45/14:30/20:30)
  sh_index_fib.json     → scanner.py (上证指数斐波那契)
  sector_fund_flow.json → fetch_sector_fund_flow.py (每日09:15/09:45/11:00/13:45/14:30/20:30)
  sh_sz_history.json    → scanner.py (上证深证历史)
  nt_data.json          → fetch_nt_data.py (每日09:25/17:00)
  concept_ranking.json  → fetch_concept_ranking.py (每日09:15/09:45/11:00/13:45/14:30/20:30)
  market_alerts.json    → fetch_market_alerts.py (每日09:15/09:45/11:00/13:45/14:30/20:30)
  update_schedule.json  → 手动创建 (不更新)
  guanlan_watchlist.json → guanlan_extractor.py (每日09:25/17:00)
"""
import os, sys, json
try:
    import requests
except ImportError:
    requests = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
MASTER_PATH = os.path.join(BASE_DIR, "index_master.html")  # 直接读根目录模板，避免dist/不同步
OUTPUT_PATH = os.path.join(DIST_DIR, "index.html")
OUTPUT_PATH_MASTER = os.path.join(DIST_DIR, "index_master.html")  # 双文件输出，保持一致
DATA_DIR = os.path.join(BASE_DIR, "data")

def load_json(path, default=None):
    if default is None: default = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"  ⚠️ 加载失败 {os.path.basename(path)}: {e}")
    return default

def fetch_stock_concepts(code, market="sh"):
    """获取个股所属概念列表 (East Money API)"""
    if market == "hk":
        return []
    if requests is None:
        return []
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_THEME_CONCEPT",
            "columns": "SECURITY_CODE,THEME_NAME",
            "filter": "(SECURITY_CODE=='{}')".format(code),
            "pageNumber": 1,
            "pageSize": 100,
        }
        resp = requests.get(url, params=params, timeout=8)
        data = resp.json()
        concepts = []
        if data.get("data") and data["data"].get("data"):
            for item in data["data"]["data"]:
                name = item.get("THEME_NAME", "")
                if name:
                    concepts.append(name)
        return concepts
    except Exception as e:
        print("  [WARN] 获取 {} 概念失败: {}".format(code, e))
        return []

def find_block_end(content, marker_start, open_ch, close_ch):
    """精确查找 JS 数据块的边界：(start_pos, end_pos)"""
    start = content.find(marker_start)
    if start < 0:
        return -1, -1
    i = start + len(marker_start)
    # 跳过空格到 open_ch
    while i < len(content) and content[i] != open_ch:
        i += 1
    if i >= len(content):
        return -1, -1
    # 括号计数法精确找到匹配的 close_ch
    count = 1
    i += 1
    while i < len(content) and count > 0:
        if content[i] == open_ch:
            count += 1
        elif content[i] == close_ch:
            count -= 1
        i += 1
    # 跳过后面的空格/分号
    end = i
    while end < len(content) and content[end] in ' ;\n\r\t':
        end += 1
    return start, end

def verify_data(content):
    """用 Node.js 验证数据块 JS 语法"""
    import tempfile, subprocess
    js_code = r'''
const fs = require("fs");
const c = fs.readFileSync(process.argv[1], "utf8");
const r = s => { try { new Function("return " + s); return "OK"; } catch(e) { return "ERR: " + e.message; } };
const m1 = c.match(/window\.SCAN_DATA = ({[\s\S]*?};)/);
const m2 = c.match(/window\.WATCH_DATA = ({[\s\S]*?};)/);
const m3 = c.match(/window\.GOLD_POOL = ({[\s\S]*?};)/);
const m4 = c.match(/window\.STOCK_LIST = (\[[\s\S]*?\];)/);
console.log("SCAN_DATA:", m1 ? r(m1[1]) : "NOT FOUND");
console.log("WATCH_DATA:", m2 ? r(m2[1]) : "NOT FOUND");
console.log("GOLD_POOL:", m3 ? r(m3[1]) : "NOT FOUND");
console.log("STOCK_LIST:", m4 ? r(m4[1]) : "NOT FOUND");
const m5 = c.match(/window\.NT_DATA = ({[\s\S]*?};)/);console.log("NT_DATA:", m5 ? r(m5[1]) : "NOT FOUND");'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
        f.write(js_code)
        tmp_path = f.name
    try:
        node_path = os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries", "node", "versions", "22.22.2", "node.exe")
        r = subprocess.run(
            [node_path, "-e", js_code, OUTPUT_PATH],
            capture_output=True, text=True, timeout=30
        )
        return r.stdout.strip()
    finally:
        try: os.unlink(tmp_path)
        except: pass


def verify_all_js(content):
    """全量 JS 语法检查，捕获括号不配、非法 return 等低级错误"""
    import re, subprocess, tempfile
    scripts = re.findall(r'<script\b[^>]*>(.*?)</script>', content, re.DOTALL)
    checked = 0
    errors = 0
    for i, js in enumerate(scripts):
        js = js.strip()
        if len(js) < 50:
            continue
        # 跳过宏观渲染注入
        if 'var el = document.getElementById("macroUpdateTime")' in js[:300]:
            continue
        checked += 1
        try:
            # 写入临时文件避免命令行长度限制
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
                f.write("try{new Function(" + repr(js) + ");console.log('OK')}catch(e){console.log('ERR:'+e.message)}")
                tmp_path = f.name
            node_path = os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries", "node", "versions", "22.22.2", "node.exe")
            r = subprocess.run(
                [node_path, tmp_path],
                capture_output=True, text=True, timeout=15
            )
            out = r.stdout.strip()
            if "ERR:" in out:
                print(f"    ⚠️ 脚本块{i}: {out}")
                errors += 1
            else:
                print(f"    ✓ 脚本块{i}")
        except Exception as e:
            print(f"    ⚠️ 脚本块{i}: 检查异常 - {e}")
            errors += 1
        finally:
            try: os.unlink(tmp_path)
            except: pass
    print(f"    检查 {checked} 个脚本块，{errors} 个错误")
    return errors == 0


# ============ 宏观观测表格渲染JS（整合自 inject_macro.py RENDER_JS）============
def get_macro_render_js():
    """返回填充宏观观测表格的JS脚本字符串（幂等，重复注入不重复执行）"""
    return """<script>
(function(){
  if(typeof window.MACRO_DATA === "undefined") return;
  const m = window.MACRO_DATA;
  var el = document.getElementById("macroUpdateTime");
  if(el && m.update_time) { var ft = (typeof fmtDataTime === 'function') ? fmtDataTime(m.update_time) : {text: (m.update_time||'').slice(0,16)}; el.textContent = '更新于 ' + ft.text; }
  var leg = document.getElementById("macroStarLegend");
  if(leg) {
    var st = m.indicator_status || {};
    var monthlyKeys = ["lpr","m2_yoy","pmi","cpi","ppi","social_financing","export_yoy","new_investors"];
    var total = monthlyKeys.length;
    var fresh = 0;
    for(var i=0; i<monthlyKeys.length; i++) {
      var sti = st[monthlyKeys[i]];
      if(sti && sti.is_fresh) fresh++;
    }
    leg.innerHTML = "⭐ 已更新 " + fresh + "/" + total + " &nbsp; ☆ 待更新";
  }
  function v(id,val,color){var e=document.getElementById(id); if(!e)return; e.innerHTML=val||"--"; if(color)e.style.color=color;}
  function note(id, level, text) {
    if(!text) return;
    var e = document.getElementById(id);
    if(!e || !e.parentNode) return;
    var td = e.parentNode.children[2];
    if(!td || td.dataset.noted) return;
    var icon = level>=2 ? "🔴 " : (level>=1 ? "🟡 " : "");
    if(icon) {
      td.innerHTML = icon + text;
      td.style.color = level>=2 ? "#f44336" : "#ff9800";
    }
    td.dataset.noted = "1";
  }
  /* ===== ⭐ 月度指标标记渲染 ===== */
  function star(id, key){
    var e=document.getElementById(id); if(!e)return;
    var st = m.indicator_status && m.indicator_status[key];
    if(st && st.is_fresh){ e.innerHTML = "⭐ 月度"; e.style.color = "#FFD700"; }
    else { e.innerHTML = "☆ 月度"; e.style.color = "#999"; }
  }
  star("upd-lpr", "lpr");
  star("upd-m2", "m2_yoy");
  star("upd-pmi", "pmi");
  star("upd-cpi", "cpi");
  star("upd-ppi", "ppi");
  star("upd-szr", "social_financing");
  star("upd-export", "export_yoy");
  star("upd-investors", "new_investors");

  /* ===== 数值渲染（异常说明写入第3列） ===== */
  var mon = m.monetary || {};
  if(mon.cn_bond_10y) { var cb=mon.cn_bond_10y.value; var cbLv=cb<1.8?2:(cb<2.0?1:0); v("m-cn-bond", cb+"%", "#4fc3f7"); note("m-cn-bond", cbLv, cb<1.8?"利率极低，流动性泛滥":(cb<2.0?"利率偏低":"")); }
  if(mon.us_bond_10y) { var ub=mon.us_bond_10y.value; var ubLv=ub>=5?2:(ub>=4.5?1:0); v("m-us-bond", ub+"%", "#ff9800"); note("m-us-bond", ubLv, ub>=5?"高利率压制全球资产":(ub>=4.5?"利率偏高":"正常区间")); }
  if(mon.shibor) { var so=mon.shibor.on; var sLv=so>3?2:(so>2?1:0); v("m-shibor", so+"% / "+mon.shibor.w1+"%", "#b0bec5"); note("m-shibor", sLv, so>3?"资金面紧张":(so>2?"偏紧":"")); }
  if(mon.cn_us_spread){var s=mon.cn_us_spread.value; var spLv=s<-2.5?2:(s<-1.5?1:0); v("m-spread", s+"%", s<0?"#f44336":"#4caf50"); note("m-spread", spLv, s<-2.5?"利差严重倒挂，资本外流压力大":(s<-1?"利差倒挂":"正常"));}
  if(mon.lpr) v("m-lpr", mon.lpr.lpr_1y+"% / "+mon.lpr.lpr_5y+"%", "#81c784");
  if(mon.m2_yoy && mon.m2_yoy.value!==null) { var m2v=mon.m2_yoy.value; var m2Lv=m2v>10?2:(m2v>8?1:(m2v<0?2:0)); v("m-m1m2", m2v+"%", m2v>8?"#f44336":"#4caf50"); note("m-m1m2", m2Lv, m2v>8?"货币供应偏快":(m2v<0?"货币收缩":"正常")); }
  if(mon.open_market_operation){var omo=mon.open_market_operation; v("m-omo", (omo.net_inflow>=0?"+":"")+omo.net_inflow+"亿", omo.net_inflow>=0?"#4caf50":"#f44336");}
  var eco = m.economy || {};
  if(eco.pmi){var p=eco.pmi.value; var pCol=p>=50?"#4caf50":"#f44336"; var pLv=p<49?2:(p<50?1:0); v("e-pmi", p+(eco.pmi.forecast?" (预:"+eco.pmi.forecast+")":""), pCol); note("e-pmi", pLv, p<49?"PMI收缩，经济下行压力":(p<50?"PMI偏弱，景气度不足":"PMI扩张，经济向好"));}
  if(eco.cpi){var cv=eco.cpi.value; var cStr=cv!==null&&cv!==undefined?cv+"%":(eco.cpi.previous?eco.cpi.previous+"%(前值)":"--"); v("e-cpi", cStr, undefined); if(cv!==null&&cv!==undefined){ var cLv=cv<0?2:(cv>3?2:(cv<1?1:0)); note("e-cpi", cLv, cv<0?"通缩风险":(cv>3?"通胀压力":(cv<1?"偏低":""))); } }
  if(eco.ppi){var pp=eco.ppi.value; var ppStr=pp!==null&&pp!==undefined?pp+"%":(eco.ppi.previous?eco.ppi.previous+"%(前值)":"--"); v("e-ppi", ppStr, undefined); if(pp!==null&&pp!==undefined){ var ppLv=pp<-3?2:(pp<-2?1:0); note("e-ppi", ppLv, pp<-3?"通缩压力严重":"正常"); } }
  if(eco.social_financing) { var sz=eco.social_financing; var szLv=sz.change_pct<-15?2:(sz.change_pct<-5?1:0); v("e-szr", sz.value+"亿 "+(sz.change_pct>0?"↑":"↓")+Math.abs(sz.change_pct)+"%", sz.change_pct<0?"#f44336":"#4caf50"); note("e-szr", szLv, sz.change_pct<-10?"社融大幅回落":(sz.change_pct<0?"社融回落":"")); }
  if(eco.export_yoy){var ex=eco.export_yoy.value; var exStr=ex+"%"+(eco.export_yoy.previous?" (前:"+eco.export_yoy.previous+"%)":""); var exCol=ex>0?"#4caf50":"#f44336"; var exLv=ex<-5?2:(ex<0?1:0); v("e-export", exStr, exCol); note("e-export", exLv, ex<-5?"出口大幅下滑":"正常");}
  if(eco.ipo){ var ipo=eco.ipo; var ipoLv=ipo.count>20?2:(ipo.count>10?1:0); v("e-ipo", ipo.count+"只 / "+ipo.amount+"亿", "#90caf9"); note("e-ipo", ipoLv, ipo.count>20?"IPO供给压力大":"正常");}
  var mt = m.market_sentiment || {};
  if(mt.new_investors){ var ni=mt.new_investors; var invStr=ni.value+"万"+(ni.change?" ("+(ni.change>=0?"+":"")+ni.change+"万)":""); var invCol=ni.change>0?"#ef5350":"#4caf50"; var niLv=ni.value>150?2:(ni.value>100?1:(ni.value<30?2:0)); v("mt-investors", invStr, invCol); note("mt-investors", niLv, ni.value>150?"散户过热，警惕":(ni.value<30?"人气极端低迷":"正常"));}
  var g = m.global_macro || {};
  if(g.vix){var vx=g.vix.value; var vxCol=vx<20?"#4caf50":(vx<30?"#ff9800":"#f44336"); var vxLv=vx>30?2:(vx>25?1:0); v("g-vix", vx, vxCol); note("g-vix", vxLv, vx>30?"极度恐慌":(vx>25?"恐慌上升":"低波动"));}
  if(g.dxy) { var dx=g.dxy.value; var dxLv=dx>105?2:(dx>100?1:0); v("g-dxy", dx, "#90caf9"); note("g-dxy", dxLv, dx>105?"强美元，新兴市场承压":(dx>100?"美元偏强":"")); }
  if(g.usdcnh){var price=g.usdcnh.price; var usdStr=price?price.toFixed(4)+(g.usdcnh.prev_close?" (昨:"+g.usdcnh.prev_close+")":""):"暂无数据"; var usdCol=price>7.2?"#f44336":"#4caf50"; var usdLv=price>7.3?2:(price>7.2?1:0); v("g-usdcnh", usdStr, usdCol); note("g-usdcnh", usdLv, price>7.3?"贬值压力大，北向流出风险":(price>7.2?"轻微贬值":"正常"));}
  else v("g-usdcnh", "暂无数据", "#666");
})();
</script>"""



# ============ 宏观异动速报HTML生成（整合自 inject_macro.py）============
def generate_macro_alert_html(macro_data):
    """根据 macro_data 字典生成分析结论HTML，返回 (html_string, update_time, count) —— 仅异常数据才显示"""
    mon = macro_data.get('monetary', {})
    eco = macro_data.get('economy', {})
    mt  = macro_data.get('market_sentiment', {})
    g   = macro_data.get('global_macro', {})

    analyses = []

    # 流动性（10Y国债）— 仅极端值显示
    cn_bond = mon.get('cn_bond_10y')
    if cn_bond and cn_bond.get('value'):
        v = cn_bond['value']
        if v < 1.5:
            analyses.append(('流动性', f'10年期国债收益率降至{v:.2f}%，流动性极度宽松，利好A股估值修复。', '#4caf50'))
        elif v > 3.0:
            analyses.append(('流动性', f'10年期国债收益率升至{v:.2f}%，利率上行压力显著。', '#e65100'))

    # 中美利差 — 仅明显倒挂时显示
    spread = mon.get('cn_us_spread')
    if spread and spread.get('value') is not None:
        s = spread['value']
        if s < -2.5:
            analyses.append(('利差', f'中美利差倒挂达{s:.1f}%，严重倒挂，人民币汇率及外资均承压。', '#d06b82'))
        elif s < -1.5:
            analyses.append(('利差', f'中美利差倒挂{s:.1f}%，资本外流压力需持续关注。', '#ff9800'))

    # VIX恐慌指数 — 仅极端时显示（正常15-25不显示）
    vix = g.get('vix')
    if vix and vix.get('value'):
        vx = vix['value']
        if vx < 15:
            analyses.append(('风险偏好', f'VIX指数仅{vx:.0f}，全球风险偏好极高。', '#4caf50'))
        elif vx > 25:
            analyses.append(('风险偏好', f'VIX指数飙至{vx:.0f}，全球恐慌情绪升温，注意控制仓位。', '#d06b82'))

    # 离岸人民币 — 仅贬值压力时显示（正常<7.2不显示）
    usdcnh = g.get('usdcnh')
    if usdcnh and usdcnh.get('price') is not None:
        price = usdcnh['price']
        if price > 7.3:
            analyses.append(('汇率', f'离岸人民币跌破7.30关口，贬值压力加大，北向资金可能承压。', '#d06b82'))
        elif price > 7.2:
            analyses.append(('汇率', f'离岸人民币{price:.2f}，汇率压力值得关注。', '#ff9800'))

    # PMI — 仅明显偏离荣枯线时显示
    pmi = eco.get('pmi')
    if pmi and pmi.get('value') is not None:
        pv = pmi['value']
        if pv < 49:
            analyses.append(('经济景气', f'制造业PMI仅{pv:.1f}（显著低于荣枯线），经济下行压力较大。', '#d06b82'))
        elif pv > 52:
            analyses.append(('经济景气', f'制造业PMI{pv:.1f}，明显扩张，经济动能增强。', '#4caf50'))

    # 社融 — 仅大幅波动时显示
    sf = eco.get('social_financing')
    if sf and sf.get('value') is not None:
        sv, sc = sf['value'], sf.get('change_pct', 0)
        if sc < -10:
            analyses.append(('信用扩张', f'社融规模{sv:.0f}亿（同比回落{abs(sc):.0f}%），信贷需求走弱。', '#d06b82'))
        elif sc > 20:
            analyses.append(('信用扩张', f'社融规模{sv:.0f}亿（同比+{sc:.0f}%），融资需求强劲回暖。', '#4caf50'))

    # 生成HTML
    h = '<div style="font-size:13px;line-height:2.2;">'
    if not analyses:
        h += '<div style="color:#999;padding:8px 0;">当前宏观经济指标均在正常区间，无异常异动。</div>'
    else:
        for cat, text, color in analyses:
            h += '<div style="margin-bottom:4px;padding:2px 0;">'
            h += f'<span style="color:{color};font-weight:600;">【{cat}】</span> '
            h += f'<span style="color:#444;">{text}</span></div>'
    h += '</div>'

    update_time = macro_data.get('update_time', '')
    return h, '更新时间：' + update_time if update_time else '', len(analyses)
def main():
    fast_mode = "--fast" in sys.argv
    if fast_mode:
        print("=" * 60)
        print("更新数据块 — 快速模式(跳过宏观采集+概念查询+JS验证)")
        print("=" * 60)
    else:
        print("=" * 60)
        print("更新数据块 — 基于 index_master.html（密码页已内置）")
        print("=" * 60)

    if not os.path.exists(MASTER_PATH):
        print(f"❌ 找不到母版: {MASTER_PATH}")
        return False

    with open(MASTER_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    master_content = content  # 保存原始母版内容，用于保留 calendar

    print(f"  母版: {len(content):,} 字符")

    # 加载数据
    scan_data   = load_json(os.path.join(DATA_DIR, "scan_result.json"))
    watch_data  = load_json(os.path.join(DATA_DIR, "watch_result.json"))
    gold_pool   = load_json(os.path.join(DATA_DIR, "gold_pool.json"))
    stock_names = load_json(os.path.join(DATA_DIR, "stock_names.json"), [])

    # 精监数据中的新增三线合并到 scan_data（全扫不计算新增，精监才计算）
    if watch_data.get("new_triple_count", 0) > 0:
        scan_data["new_triple_count"] = watch_data["new_triple_count"]
        scan_data["new_triple_signals"] = watch_data.get("new_triple_signals", [])
    else:
        scan_data.setdefault("new_triple_count", 0)
        scan_data.setdefault("new_triple_signals", [])

    # 【数据一致性】watch 覆盖 scan，但仅当 watch 不旧于 scan
    wt = watch_data.get("scan_time", "")
    st = scan_data.get("scan_time", "")
    if wt and (not st or wt >= st):
        scan_data["triple_count"] = watch_data.get("triple_count", 0)
        scan_data["triple_signals"] = watch_data.get("triple_signals", [])
        scan_data["double_count"] = watch_data.get("double_count", 0)
        scan_data["double_signals"] = watch_data.get("double_signals", [])
        scan_data["scan_time"] = wt
        # 持久化写回，防后续脚本读到旧数据
        try:
            scan_json_path = os.path.join(DATA_DIR, "scan_result.json")
            with open(scan_json_path, "w", encoding="utf-8") as f:
                json.dump(scan_data, f, ensure_ascii=False)
        except:
            pass

    # 加载推荐数据（在提取 triple_signals 之前，因为推荐可能含港股）
    recommend   = load_json(os.path.join(DATA_DIR, "recommend.json"), [])

    # 【统一标准】金股池是唯一权威数据源 — 从中提取三线共振
    # 这样无论 scan/watch/recommend 各自有多少，所有页面始终显示同一份数据
    triple_from_pool = []
    double_from_pool = []
    for key, stock in gold_pool.get("stocks", {}).items():
        hist = stock.get("history", [])
        if not hist:
            continue
        latest = hist[-1]
        sc = latest.get("signal_count", 0)
        if sc >= 3:
            triple_from_pool.append({
                "code": stock["code"],
                "name": stock["name"],
                "market": stock.get("market", ""),
                "signal_count": sc,
                "close": latest.get("close", 0),
                "pct_chg": latest.get("pct_chg", 0),
                "缠论买_日K": latest.get("缠论买_日K", False),
                "金钻_起涨": latest.get("金钻_起涨", False),
                "金钻_黄柱": latest.get("金钻_黄柱", False),
                "四量图_机构变红": latest.get("四量图_机构变红", False),
                "上涨趋势": latest.get("上涨趋势", False),
                "三线共振": True,
            })
        elif sc >= 2:
            double_from_pool.append({"code": stock["code"], "name": stock["name"], "signal_count": sc})

    if triple_from_pool:
        scan_data["triple_signals"] = triple_from_pool
        scan_data["triple_count"] = len(triple_from_pool)
        scan_data["double_signals"] = double_from_pool
        scan_data["double_count"] = len(double_from_pool)
        print(f"  ✓ 金股池统一: triple={len(triple_from_pool)}, double={len(double_from_pool)}")
    elif not scan_data.get("triple_signals"):
        scan_data["triple_signals"] = []
        scan_data["triple_count"] = 0

    # 从 results 中提取 triple_signals 和 quad_signals（前端依赖这些字段）
    if "results" in scan_data and "triple_signals" not in scan_data:
        triple = [s for s in scan_data["results"] if s.get("signal_count", 0) >= 3]

        # 合并推荐/精监中 signal_count >= 3 的股票（包括港股）
        if isinstance(recommend, list):
            for s in recommend:
                sig = s.get("sig_count", s.get("signal_count", 0))
                if sig >= 3:
                    # 确保不重复
                    code = s.get("code", "")
                    if code and not any(t.get("code") == code for t in triple):
                        triple.append({
                            "code": code,
                            "name": s.get("name", ""),
                            "signal_count": sig,
                            "close": s.get("close", 0),
                            "pct_chg": s.get("pct_chg", 0),
                            "board": s.get("board", "港股"),
                            "action": s.get("action", ""),
                        })

        scan_data["triple_signals"] = triple
        scan_data["triple_count"] = len(triple)
        quad = [s for s in triple if s.get("signal_count", 0) >= 4]
        scan_data["quad_signals"] = quad
        scan_data["quad_count"] = len(quad)
        print(f"  ✓ 合并后 triple_signals: {len(triple)} 只（含港股推荐 {len(triple) - len([s for s in scan_data['results'] if s.get('signal_count',0)>=3])} 只）")

        # 持久化：把港股三线共振写回 scan_result.json，后续任何脚本读它都统一
        scan_json_path = os.path.join(DATA_DIR, "scan_result.json")
        try:
            with open(scan_json_path, "w", encoding="utf-8") as f:
                json.dump(scan_data, f, ensure_ascii=False)
            print(f"  ✓ 已持久化到 scan_result.json（triple_signals={len(triple)}只，含港股）")
        except Exception as e:
            print(f"  ⚠️ 持久化 scan_result.json 失败: {e}")

    stock_list = [{"code": s["code"], "name": s["name"]}
                  for s in stock_names if "code" in s and "name" in s]
    # 加载上证指数斐波那契数据
    sh_fib      = load_json(os.path.join(DATA_DIR, "sh_index_fib.json"))
    # 加载深证成指斐波那契数据
    sz_fib      = load_json(os.path.join(DATA_DIR, "sz_index_fib.json"))
    # 加载板块资金流向数据
    sector_flow = load_json(os.path.join(DATA_DIR, "sector_fund_flow.json"))
    # 加载上证深证历史数据
    sh_sz_history = load_json(os.path.join(DATA_DIR, "sh_sz_history.json"))
    # 加载国家队ETF数据
    nt_data = load_json(os.path.join(DATA_DIR, "nt_data.json"))
    # 加载概念涨跌幅排名
    concept_ranking = load_json(os.path.join(DATA_DIR, "concept_ranking.json"))
    # 加载市场异动数据
    market_alerts = load_json(os.path.join(DATA_DIR, "market_alerts.json"))
    margin_data  = load_json(os.path.join(DATA_DIR, "margin_data.json"), {"sh": [], "sz": [], "update_time": ""})
    etf_subscription = load_json(os.path.join(DATA_DIR, "etf_subscription.json"), {"sh": [], "update_time": ""})
    macro_data   = load_json(os.path.join(DATA_DIR, "macro_data.json"), {"update_time": "", "monetary": {}, "economy": {}, "market_sentiment": {}, "global_macro": {}})
    herding_data = load_json(os.path.join(DATA_DIR, "herding_data.json"), {"update_time": ""})
    # 计算龙虎榜连续买入天数（依赖 lhb_history.json）
    try:
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "compute_lhb_consecutive.py")],
                       capture_output=True, timeout=30)
    except Exception as e:
        print(f"  [WARN] LHB连续天数计算跳过: {e}")
    lhb_data     = load_json(os.path.join(DATA_DIR, "lhb_result.json"), {"stocks": [], "scan_time": ""})
    main_stock   = load_json(os.path.join(DATA_DIR, "main_stock.json"), {"update_time": ""})
    main_week    = load_json(os.path.join(DATA_DIR, "main_week.json"), {"update_time": "", "buy_top5": [], "sell_top5": []})
    north_fund   = load_json(os.path.join(DATA_DIR, "north_fund.json"), {"update_time": ""})
    suspension_alert = load_json(os.path.join(DATA_DIR, "suspension_alert.json"), {"update_time": "", "suspended": [], "near_trigger": []})
    stock_deviation = load_json(os.path.join(DATA_DIR, "stock_deviation.json"), {"update_time": "", "stocks": {}})
    mahoro_sig   = load_json(os.path.join(DATA_DIR, "mahoro_signals.json"), {"gold_pool_matches": []})
    fomc_summary = load_json(os.path.join(DATA_DIR, "fomc_summary.json"), {})
    # 构建投行覆盖映射: code -> stance
    mahoro_coverage = {}
    for m in mahoro_sig.get("gold_pool_matches", []):
        code = m.get("code", "")
        stance = m.get("stance", "")
        if code and stance:
            mahoro_coverage[code] = stance
    if mahoro_coverage:
        print(f"  ▸ 投行覆盖: {len(mahoro_coverage)} 只")

    if not fast_mode:
        # 自动采集最新宏观数据
        print("  ▸ 正在刷新宏观数据...")
        try:
            import importlib, fetch_macro_data as fmd
            importlib.reload(fmd)
            new_macro = fmd.fetch_all()
            if new_macro and new_macro.get('update_time'):
                macro_data = new_macro
                save_json(os.path.join(DATA_DIR, 'macro_data.json'), new_macro)
                print(f"    ✓ 宏观数据已更新: {new_macro['update_time']}")
            else:
                print("    ℹ️ 宏观数据无更新，使用缓存")
        except Exception as e:
            print(f"    ⚠️ 宏观数据采集异常({e})，使用缓存")

        # 自动采集最新宏观数据（合并 fetch_macro_data 功能）
        try:
            import importlib, fetch_macro_data as fmd
            importlib.reload(fmd)
            print("  ▸ 正在采集最新宏观数据...")
            macro_data = fmd.fetch_all()
            if macro_data:
                save_json(os.path.join(DATA_DIR, "macro_data.json"), macro_data)
                print(f"    ✓ 宏观数据已更新: {macro_data.get('update_time','')}")
            else:
                print("    ℹ️ 宏观数据采集失败，使用缓存")
                macro_data = load_json(os.path.join(DATA_DIR, "macro_data.json"), {"update_time": "", "monetary": {}, "economy": {}, "market_sentiment": {}, "global_macro": {}})
        except Exception as e:
            print(f"    ⚠️ 宏观数据采集异常: {e}，使用缓存")

        # 自动刷新宏观数据（先采集最新数据再使用）
        print("  ▸ 刷新宏观数据...")
        try:
            import subprocess
            _r = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "fetch_macro_data.py")],
                               capture_output=True, text=True, timeout=180)
            if _r.returncode == 0:
                # 重新加载更新后的数据
                macro_data = load_json(os.path.join(DATA_DIR, "macro_data.json"), macro_data)
                print("    ✓ 宏观数据已刷新")
            else:
                print(f"    ⚠ 宏观数据刷新失败，沿用旧数据: {_r.stderr[-100:] if _r.stderr else ''}")
        except Exception as _e:
            print(f"    ⚠ 宏观数据跳过: {_e}")
    else:
        print("  ▸ 快速模式：跳过宏观数据刷新")

    print(f"\n  数据:")
    print(f"  ▸ SCAN_DATA:  {len(scan_data.get('all_results',[]))} 条, time={scan_data.get('scan_time','N/A')}")
    print(f"  ▸ WATCH_DATA: {len(watch_data.get('all_results',[]))} 条")
    print(f"  ▸ GOLD_POOL:  {len(gold_pool.get('stocks',{}))} 只")
    print(f"  ▸ STOCK_LIST: {len(stock_list)} 只")
    print(f"  ▸ RECOMMEND:  {len(recommend)} 条推荐")
    print(f"  ▸ SH_FIB:     {len(sh_fib.get('windows',[]))} 个窗口")
    print(f"  ▸ SECTOR_FLOW:{len(sector_flow.get('top_list',[]))} 个板块")
    print(f"  ▸ SH_SZ_HIST: {len(sh_sz_history.get('amount_history',[]))} 天历史")
    print(f"  ▸ MARKET_ALERTS: {'有' if market_alerts.get('summary') else '无'}数据")
    print(f"  ▸ MARGIN_DATA: {len(margin_data.get('sh',[]))} 天两融数据")
    print(f"  ▸ ETF_SUB: {len(etf_subscription.get('sh',[]))} 天ETF数据")
    print(f"  ▸ MACRO_DATA: 更新={macro_data.get('update_time','N/A')}")
    print(f"  ▸ FOMC: {'有' if fomc_summary.get('meeting_date') else '无'}速览 (会议={fomc_summary.get('meeting_date','N/A')})")

    if not fast_mode:
        # 获取三线共振股票概念
        if scan_data and "triple_signals" in scan_data:
            print("  ⚡ 获取三线共振股票概念...")
            for stock in scan_data["triple_signals"]:
                code = stock["code"]
                # 从recommend合并来的港股可能没有market字段
                market = stock.get("market", stock.get("board_label", ""))
                if not market or market == "港股":
                    # 港股代码前缀
                    if code.startswith("0") and len(code) == 5:
                        market = "hk"
                    elif code.startswith("0"):
                        market = "sz"
                    elif code.startswith("6"):
                        market = "sh"
                    elif code.startswith("3"):
                        market = "sz"
                    else:
                        market = "sh"
                concepts = fetch_stock_concepts(code, market)
                stock["concepts"] = concepts
                if concepts:
                    print(f"    {code} {stock['name']}: {', '.join(concepts[:3])}" + ("..." if len(concepts) > 3 else ""))
    else:
        print("  ▸ 快速模式：跳过概念查询")

    # 查找并替换数据块（13个块）
    markers = [
        ("SCAN_DATA",      "window.SCAN_DATA = ",      "{", "}"),
        ("WATCH_DATA",     "window.WATCH_DATA = ",     "{", "}"),
        ("GOLD_POOL",      "window.GOLD_POOL = ",      "{", "}"),
        ("STOCK_LIST",     "window.STOCK_LIST = ",    "[", "]"),
        ("RECOMMEND",      "var RECOMMEND = window.RECOMMEND = ",      "[", "]"),
        ("SH_FIB",         "var SH_FIB = window.SH_FIB = ",         "{", "}"),
        ("SZ_FIB",         "var SZ_FIB = window.SZ_FIB = ",         "{", "}"),
        ("SECTOR_FUND_FLOW", "window.SECTOR_FUND_FLOW = ", "{", "}"),
        ("SH_SZ_HISTORY",  "var SH_SZ_HISTORY = window.SH_SZ_HISTORY = ",  "{", "}"),
        ("NT_DATA",        "window.NT_DATA = ",        "{", "}"),
        ("CONCEPT_RANKING", "var CONCEPT_RANKING = window.CONCEPT_RANKING = ", "{", "}"),
        ("MARKET_ALERTS",  "var MARKET_ALERTS = window.MARKET_ALERTS = ",  "{", "}"),
        ("MARGIN_DATA",     "var MARGIN_DATA = window.MARGIN_DATA = ",     "{", "}"),
        ("ETF_SUBSCRIPTION", "var ETF_SUBSCRIPTION = window.ETF_SUBSCRIPTION = ", "{", "}"),
        ("MACRO_DATA",      "window.MACRO_DATA = ",    "{", "}"),
        ("HERRING_DATA",   "window.HERRING_DATA = ",  "{", "}"),
        ("LHB_DATA",       "window.LHB_DATA = ",      "{", "}"),
        ("MAIN_STOCK",     "var MAIN_STOCK_DATA = window.MAIN_STOCK_DATA = ","{", "}"),
        ("MAIN_WEEK",      "window.MAIN_WEEK_DATA = ",  "{", "}"),
        ("NORTH_FUND",     "window.NORTH_FUND_DATA = ",  "{", "}"),
        ("MAHORO_COVERAGE", "var MAHORO_COVERAGE = window.MAHORO_COVERAGE = ","{", "}"),
        ("SUSPENSION_ALERT", "window.SUSPENSION_ALERT = ",  "{", "}"),
        ("STOCK_DEVIATION", "var STOCK_DEVIATION = window.STOCK_DEVIATION = ", "{", "}"),
        ("FOMC_SUMMARY",   "window.FOMC_SUMMARY = ",  "{", "}"),
    ]
    data_objs = [scan_data, watch_data, gold_pool, stock_list, recommend,
                 sh_fib, sz_fib, sector_flow, sh_sz_history, nt_data,
                 concept_ranking, market_alerts, margin_data, etf_subscription, macro_data,                  herding_data,
                 lhb_data, main_stock, main_week, north_fund, mahoro_coverage, suspension_alert, stock_deviation, fomc_summary]
    replacements = []

    for (name, marker, open_ch, close_ch), data in zip(markers, data_objs):
        s, e = find_block_end(content, marker, open_ch, close_ch)
        if s < 0:
            print(f"  ⚠️  找不到 {name}，跳过")
            continue
        # 校验数据有效性：如果数据为空（无update_time/scan_time/有效列表），保留旧数据
        is_empty = False
        if isinstance(data, dict) and name in ("MAIN_STOCK", "HERRING_DATA", "LHB_DATA"):
            if not data.get("update_time") and not data.get("scan_time"):
                is_empty = True
        # 额外检查：即使有update_time，如果核心数据数组全空，也视为无效（防止API空结果覆盖已有数据）
        if not is_empty and isinstance(data, dict):
            if name == "HERRING_DATA":
                clusters = data.get("current_clusters") or []
                high_prob = data.get("high_prob") or []
                if len(clusters) == 0 and len(high_prob) == 0:
                    is_empty = True
                    print(f"  ⚠️  {name} 数据全空 (clusters=0, high_prob=0)，跳过替换")
            elif name == "MAIN_STOCK":
                top_in = data.get("top_main_in") or []
                top_out = data.get("top_main_out") or []
                if len(top_in) == 0 and len(top_out) == 0:
                    is_empty = True
                    print(f"  ⚠️  {name} 数据全空 (top_in=0, top_out=0)，跳过替换")
        if isinstance(data, dict) and name == "LHB_DATA":
            if not data.get("stocks") and not data.get("update_time") and not data.get("scan_time"):
                is_empty = True
        if isinstance(data, dict) and name in ("MARGIN_DATA", "NORTH_FUND", "ETF_SUBSCRIPTION", "FOMC_SUMMARY"):
            if not data.get("update_time") and not data.get("available", True):
                is_empty = True
                print(f"  ⚠️  {name} 无新数据且不可用，跳过替换")
        if is_empty:
            print(f"  ⚠️  {name} 数据为空，跳过替换（保留旧数据）")
            continue
        new_json = json.dumps(data, ensure_ascii=False, indent=0)
        new_block = marker + new_json + ";"
        replacements.append((s, e, new_block))
        print(f"  ✓ {name}: {e-s:,} → {len(new_block):,} 字符")

    # 从后往前替换
    replacements.sort(key=lambda x: x[0], reverse=True)
    for s, e, new_block in replacements:
        content = content[:s] + new_block + content[e:]

    # ===== 注入 NT_DATA.calendar（使用最新 fetch_nt_data.py 生成的日历）=====
    nt_json_path = os.path.join(BASE_DIR, "data", "nt_data.json")
    fresh_calendar = []
    if os.path.exists(nt_json_path):
        try:
            with open(nt_json_path, "r", encoding="utf-8") as f:
                nt_fresh = json.load(f)
            fresh_calendar = nt_fresh.get("calendar", [])
            if isinstance(fresh_calendar, dict) and "events" in fresh_calendar:
                fresh_calendar = fresh_calendar["events"]
        except Exception as e:
            print(f"  ⚠️ 读取 nt_data.json 失败: {e}")

    if fresh_calendar and isinstance(fresh_calendar, list) and len(fresh_calendar) > 0:
        dist_nt_s, dist_nt_e = find_block_end(content, "window.NT_DATA = ", "{", "}")
        if dist_nt_s >= 0:
            try:
                dist_nt_json = content[dist_nt_s:dist_nt_e][len("window.NT_DATA = "):].strip().rstrip(";").strip()
                dist_nt = json.loads(dist_nt_json)
                dist_nt["calendar"] = fresh_calendar
                new_nt_json = json.dumps(dist_nt, ensure_ascii=False, indent=0)
                new_nt_block = "window.NT_DATA = " + new_nt_json + ";"
                content = content[:dist_nt_s] + new_nt_block + content[dist_nt_e:]
                print(f"  ✓ NT_DATA.calendar 已注入最新数据 ({len(fresh_calendar)} 条，含华为HDC、苹果WWDC等)")
            except Exception as e:
                print(f"  ⚠️ 注入 calendar 失败: {e}")
    else:
        print(f"  ⚠️ nt_data.json 无有效日历数据")

    # 验证密码页还在
    if 'id="pwdOverlay"' not in content:
        print("  ❌ 密码页丢失！母版可能被破坏")
        return False
    print("  ✓ 密码页完好")

    # ===== 注入宏观观测表格渲染JS（幂等）=====
    render_js = get_macro_render_js()
    # 强制重新注入（从母版生成，不存在重复）
    _BODY = "</body>"
    content = content.replace(_BODY, render_js + "\n" + _BODY)
    print('  ✓ 宏观观测表格渲染JS已注入')

    # 注入三线共振历史数据到 triple_resonance.html
    # 先自动生成最新历史数据（一劳永逸，不会漏掉）
    resonance_generator = os.path.join(BASE_DIR, "generate_triple_resonance_history.py")
    if os.path.exists(resonance_generator):
        try:
            subprocess.run([sys.executable, resonance_generator],
                capture_output=True, encoding='utf-8', errors='replace',
                timeout=120, cwd=BASE_DIR)
        except Exception:
            pass  # 生成失败也不阻塞部署

    resonance_html_path = os.path.join(BASE_DIR, "triple_resonance.html")  # 根目录模板
    resonance_out_path = os.path.join(DIST_DIR, "triple_resonance.html")   # 输出到 dist
    resonance_json_path = os.path.join(DATA_DIR, "triple_resonance_history.json")
    if os.path.exists(resonance_html_path) and os.path.exists(resonance_json_path):
        try:
            with open(resonance_json_path, "r", encoding="utf-8") as f:
                resonance_data = json.load(f)
            # 注入到 triple_resonance.html
            with open(resonance_html_path, "r", encoding="utf-8") as f:
                rh = f.read()
            embedded = json.dumps(resonance_data, ensure_ascii=False)
            # 清除旧数据并注入新数据
            import re as _re
            if 'EMBEDDED_HISTORY_DATA' in rh:
                rh = _re.sub(
                    r'<script>\s*\n\s*var EMBEDDED_HISTORY_DATA\s*=.*?\n\s*</script>',
                    '', rh, flags=_re.DOTALL
                )
            rh = rh.replace('</head>',
                f'<script>\nvar EMBEDDED_HISTORY_DATA = {embedded};\n</script>\n</head>')
            with open(resonance_out_path, "w", encoding="utf-8") as f:
                f.write(rh)
            print(f"  ✓ triple_resonance.html 已嵌入历史数据")
            # 不再注入到主页面（历史追踪已恢复为独立页面）
        except Exception as e:
            print(f"  ⚠️ triple_resonance 注入失败: {e}")

    # 保存（双文件输出：index.html + index_master.html）
    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    with open(OUTPUT_PATH_MASTER, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"  ✓ 已保存: index.html + index_master.html ({len(content):,} 字符)")

    # 注入真实密码（替换源码 __PWD__ / __GUEST_PWD__ 占位符）
    REAL_PWD = os.environ.get("QB_PWD", "cat999")
    REAL_GUEST_PWD = os.environ.get("QB_GUEST_PWD", "hjd666")
    for fpath in [OUTPUT_PATH, OUTPUT_PATH_MASTER]:
        for attempt in range(3):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    c = f.read()
                break
            except PermissionError:
                if attempt < 2:
                    time.sleep(0.3)
                else:
                    raise
        n = c.count("__PWD__")
        m = c.count("__GUEST_PWD__")
        if n > 0:
            c = c.replace("__PWD__", REAL_PWD)
        if m > 0:
            c = c.replace("__GUEST_PWD__", REAL_GUEST_PWD)
        if n > 0 or m > 0:
            for attempt in range(3):
                try:
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(c)
                    break
                except PermissionError:
                    if attempt < 2:
                        time.sleep(0.3)
                    else:
                        raise
            print(f"  ✓ 密码已注入 {os.path.basename(fpath)} (admin:{n} 处, guest:{m} 处)")

    # 验证 JS 语法（无论模式，必须执行）
    print("\n  JS 语法验证:")
    verify_out = verify_data(content)
    print(f"  {verify_out}")
    if "ERR" in verify_out or "NOT FOUND" in verify_out:
        print("  ❌ 数据块 JS 语法异常！")
        return False

    # 全量 JS 语法检查（防止括号不配等低级错误上线）
    print("  全量JS检查:")
    full_ok = verify_all_js(content)
    if not full_ok:
        print("  ❌ 全量JS语法异常，已拦截！")
        return False

    # 保存（双文件输出）
    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    with open(OUTPUT_PATH_MASTER, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"\n  ✓ 已保存: index.html + index_master.html ({len(content):,} 字符)")

    # 同步 data/*.json → dist/data/（保证 JSON 文件与 HTML 内嵌数据一致）
    import shutil
    dist_data = os.path.join(os.path.dirname(OUTPUT_PATH), "data")
    os.makedirs(dist_data, exist_ok=True)
    SKIP_FILES = {"zsxq_token.json", ".mahoro_cookies.txt", "mahoro_signals.json"}  # 凭据或隐藏数据不同步
    for fname in os.listdir(DATA_DIR):
        if fname.endswith(".json") and fname not in SKIP_FILES:
            src = os.path.join(DATA_DIR, fname)
            dst = os.path.join(dist_data, fname)
            shutil.copy2(src, dst)
    # 清理 dist/data 中的凭据文件
    for sf in SKIP_FILES:
        sf_path = os.path.join(dist_data, sf)
        if os.path.exists(sf_path):
            os.remove(sf_path)
    print(f"  ✓ 已同步 data/*.json → dist/data/")

    print(f"\n✅ 数据块更新成功！")
    print(f"   部署: python deploy_now.py")
    print(f"   网址: https://ah-quant999.github.io/quant-scanner-v6/")
    return True
if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
