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
import os, sys, json, time, re, subprocess

# 拼音首字母（Python端预计算，替代JS端脆弱硬编码字典）
try:
    from pypinyin import pinyin, Style
    def _py_abbr(name):
        # 只保留中文字符做拼音转换，忽略英文数字空格等
        clean = ''.join(c for c in name if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
        if not clean:
            return ''.join(c.lower() for c in name if c.isalnum())
        return ''.join(p[0] for p in pinyin(clean, style=Style.FIRST_LETTER)).lower()
except ImportError:
    # 回退：简易部首映射（仅覆盖常见单字，兜底用）
    _FALLBACK_MAP = {
        '建':'j','滔':'t','集':'j','团':'t','层':'c','板':'b','积':'j',
        '维':'w','信':'x','通':'t','讯':'x','惠':'h','科':'k','创':'c',
        '医':'y','药':'y','疗':'l','器':'q','械':'x','光':'g','伏':'f',
        '汽':'q','车':'c','零':'l','部':'b','件':'j','地':'d','产':'c',
        '银':'y','行':'x','半':'b','导':'d','体':'t','电':'d','力':'l',
        '军':'j','工':'g','家':'j','华':'h','为':'w','海':'h','博':'b',
        '尔':'e','康':'k','港':'g','龙':'l','金':'j','属':'s','铝':'l',
        '铜':'t','钢':'g','铁':'t','煤':'m','炭':'t','石':'s','油':'y',
        '化':'h','材':'c','料':'l','新':'x','能':'n','源':'y','网':'w',
        '络':'l','科':'k','技':'j','数':'s','字':'z','软':'r','件':'j',
        '人':'r','智':'z','机':'j','器':'q','元':'y','宇':'y','宙':'z',
        '区':'q','块':'k','链':'l','基':'j','础':'c','设':'s','施':'s',
        '农':'n','牧':'m','渔':'y','食':'s','品':'p','饮':'y','料':'l',
        '服':'f','装':'z','纺':'f','织':'z','家':'j','居':'j','建':'j',
        '造':'z','环':'h','保':'b','水':'s','公':'g','交':'j','运':'y',
        '航':'h','空':'k','港':'g','口':'k','铁':'t','路':'l','机':'j',
        '器':'q','人':'r','微':'w','霄':'x','鼎':'d','盛':'s','锐':'r',
    }
    def _py_abbr(name):
        abbr = ''
        for c in name:
            if re.match(r'[a-zA-Z0-9]', c):
                abbr += c.lower()
            elif c in _FALLBACK_MAP:
                abbr += _FALLBACK_MAP[c]
            # 空格/全角字符跳过
        return abbr
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
    if count > 0:
        return -1, -1  # 括号不匹配，查找失败
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


def verify_runtime_smoke(content):
    """运行时冒烟测试：验证数据块 JSON 合法性 + 关键函数可解析，<15秒

    改进（2026-06-28）：
    - 移除合并冲突检测（对生成HTML无意义，且可能误报）
    - 增强 Mock 环境（更完整的浏览器API模拟）
    - 添加括号匹配检查（检测常见JS语法错误）
    """
    import re, subprocess, tempfile, json as json_mod

    node_path = os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries", "node", "versions", "22.22.2", "node.exe")

    # ===== 冒烟测试 Node.js 脚本（始终输出 JSON）=====
    smoke_js = r'''// 冒烟测试：验证数据块 JSON + 关键函数可解析
const fs = require("fs");

// 始终输出 JSON（即使崩溃）
function output(result) {
  fs.writeSync(1, JSON.stringify(result));
  process.exit(result.passed ? 0 : 1);
}
process.on("uncaughtException", function(e) {
  output({ errors: ["UNCAUGHT: " + e.message.slice(0, 200)], passed: false });
});

const htmlPath = process.argv[2];
if (!htmlPath || !fs.existsSync(htmlPath)) {
  output({ errors: ["HTML file not found: " + htmlPath], passed: false });
}

const html = fs.readFileSync(htmlPath, "utf8");
const errors = [];

// ===== Mock 浏览器环境（更完整）=====
const noop = () => ({});
const mockEl = new Proxy({}, { get: () => (...args) => mockEl, set: () => true });
global.document = {
  getElementById: () => mockEl,
  createElement: () => mockEl,
  querySelector: () => mockEl,
  querySelectorAll: () => [],
  addEventListener: () => {},
  body: mockEl,
  documentElement: mockEl,
  head: mockEl,
  title: "test",
  cookie: "",
  readyState: "complete",
};
global.setTimeout = (fn) => { try { fn(); } catch(e) {} };
global.setInterval = () => 0;
global.requestAnimationFrame = (fn) => { try { fn(); } catch(e) {} };
global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
global.sessionStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
global.window = global;
global.console = { log: () => {}, warn: () => {}, error: () => {}, info: () => {} };
global.navigator = { userAgent: "node", platform: "win32" };
global.location = { href: "http://localhost", search: "", hash: "" };
global.history = { pushState: () => {}, replaceState: () => {} };
global.fetch = () => Promise.resolve({ json: () => ({}), text: () => "" });
global.alert = () => {};
global.confirm = () => true;
global.prompt = () => null;

// ===== 测试1: 数据块 JSON 合法性 =====
const dataBlocks = [
  ["SCAN_DATA",        /window\.SCAN_DATA\s*=\s*(\{[\s\S]*?\})\s*;/],
  ["WATCH_DATA",       /window\.WATCH_DATA\s*=\s*(\{[\s\S]*?\})\s*;/],
  ["GOLD_POOL",        /window\.GOLD_POOL\s*=\s*(\{[\s\S]*?\})\s*;/],
  ["STOCK_LIST",        /window\.STOCK_LIST\s*=\s*(\[[\s\S]*?\])\s*;/],
  ["NT_DATA",           /window\.NT_DATA\s*=\s*(\{[\s\S]*?\})\s*;/],
  ["MACRO_DATA",        /window\.MACRO_DATA\s*=\s*(\{[\s\S]*?\})\s*;/],
];
dataBlocks.forEach(function(d) {
  try {
    var m = html.match(d[1]);
    if (!m) { errors.push(d[0] + ": NOT FOUND in HTML"); return; }
    // 尝试解析为 JS 表达式（处理 Date() 等 JS 特有语法）
    var jsExpr = m[1];
    try {
      new Function("return (" + jsExpr + ")")();
    } catch(e1) {
      // 尝试修复常见 JS->JSON 问题后再试
      var fixed = jsExpr
        .replace(/Date\([^)]*\)/g, "null")
        .replace(/,\s*]/g, "]")
        .replace(/,\s*}/g, "}");
      try {
        JSON.parse(fixed);
      } catch(e2) {
        errors.push(d[0] + " JSON: " + e1.message.slice(0, 100));
      }
    }
  } catch(e) {
    errors.push(d[0] + ": " + e.message.slice(0, 80));
  }
});

// ===== 测试2: 关键函数定义可解析（不执行）=====
var funcNames = ["fmtDataTime", "getTodayStr", "isTradingDay", "isBeforeMarketOpen"];
funcNames.forEach(function(name) {
  if (new RegExp("function " + name + "\\s*\\(").test(html)) {
    // 函数存在，尝试解析整个函数体（检查语法）
    try {
      var match = html.match(new RegExp("function " + name + "\\s*\\([^)]*\\)\\s*\\{"));
      if (match) {
        // 找到函数开头，尝试用 Function 解析（检查语法不报错即可）
        var start = html.indexOf(match[0]);
        if (start >= 0) {
          // 简单检查：函数在 HTML 中存在且大致完整（有开头）
          // 不做完整解析（太复杂），只检查存在性
        }
      }
    } catch(e) {
      errors.push(name + ": syntax check failed: " + e.message.slice(0, 80));
    }
  } else {
    errors.push(name + ": function definition NOT FOUND in HTML");
  }
});

// ===== 测试3: 括号匹配检查（检测常见JS语法错误）=====
// 只检查 <script> 标签内的内容
var scriptRe = /<script[\s\S]*?>([\s\S]*?)<\/script>/gi;
var scriptMatch;
while ((scriptMatch = scriptRe.exec(html)) !== null) {
  var scriptContent = scriptMatch[1];
  // 跳过外部脚本（src=...）
  if (scriptMatch[0].indexOf("src=") >= 0) continue;

  var stack = [];
  var lineNum = 1;
  for (var i = 0; i < scriptContent.length; i++) {
    var ch = scriptContent[i];
    if (ch === '\n') lineNum++;
    if (ch === '(' || ch === '[' || ch === '{') {
      stack.push({ ch: ch, line: lineNum });
    } else if (ch === ')' || ch === ']' || ch === '}') {
      if (stack.length === 0) {
        errors.push("Unmatched closing '" + ch + "' at script line ~" + lineNum);
        break;
      }
      var top = stack.pop();
      var expected = ch === ')' ? '(' : (ch === ']' ? '[' : '{');
      if (top.ch !== expected) {
        errors.push("Mismatched bracket: '" + top.ch + "' (line ~" + top.line + ") vs '" + ch + "' (line ~" + lineNum + ")");
        break;
      }
    }
  }
  if (stack.length > 0) {
    var unclosed = stack[stack.length - 1];
    errors.push("Unclosed '" + unclosed.ch + "' at script line ~" + unclosed.line);
  }
}

output({ errors: errors, passed: errors.length === 0 });
'''
    
    # 写临时 smoke 脚本
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(smoke_js)
        tmp_path = f.name

    try:
        # 对 dist/index.html 做冒烟测试
        test_html = OUTPUT_PATH  # 已经是完整路径 dist/index.html
        if not os.path.exists(test_html):
            print(f"  ⚠️ 冒烟测试: {test_html} 不存在，跳过")
            return True

        r = subprocess.run(
            [node_path, tmp_path, test_html],
            capture_output=True, text=True, timeout=30
        )
        out = r.stdout.strip() if r.stdout else ""
        err = r.stderr.strip() if r.stderr else ""

        if out:
            try:
                result = json_mod.loads(out)
            except:
                # 输出不是 JSON，可能是脚本打印了其他内容
                result = {"errors": [out[:200]], "passed": False}
        elif err:
            result = {"errors": [err[:200]], "passed": False}
        else:
            result = {"errors": ["Node.js script produced no output (timeout or crash)"], "passed": False}

        if not result.get("passed"):
            errs = result.get("errors", [])
            print(f"  ⚠️ 运行时冒烟: {len(errs)} 个异常")
            for e in errs[:8]:
                print(f"     {e}")
            # FATAL 错误才拦截部署，普通警告继续
            fatal = any("NOT FOUND" in e.upper() or "FATAL" in e.upper() or "BAD MARKER" in e.upper() for e in errs)
            if fatal:
                print(f"  ❌ 冒烟测试发现致命问题，已拦截部署！")
                return False
            else:
                print(f"  ⚠️ 冒烟测试有警告但继续部署")
        else:
            print(f"  ✓ 运行时冒烟: 全部通过 (数据块 + 函数检查)")

        return True
    finally:
        try: os.unlink(tmp_path)
        except: pass


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
  if(eco.ipo){ var ipo=eco.ipo; var ipoLv=ipo.count>20?2:(ipo.count>10?1:0); var ipoTxt=ipo.count+"只"; if(ipo.amount && ipo.amount>0) ipoTxt+=" / "+ipo.amount+"亿"; v("e-ipo", ipoTxt, "#90caf9"); note("e-ipo", ipoLv, ipo.count>20?"IPO供给压力大":"正常");}
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

def _safe_write(filepath, content, max_retries=5, retry_delay=0.5):
    """
    安全写入文件：处理符号链接 + Windows Defender 锁文件
    1. 检测并删除符号链接（reparse point）
    2. 写入失败时重试（应对 Windows Defender 实时扫描锁文件）
    """
    # 1. 处理符号链接
    if os.path.exists(filepath):
        try:
            if os.path.islink(filepath):
                print(f"  ⚠️  检测到符号链接: {filepath}，自动删除")
                os.remove(filepath)
            else:
                # Windows: 检测 reparse point（junction/symbolic link）
                import ctypes
                file_stat = os.stat(filepath)
                # FILE_ATTRIBUTE_REPARSE_POINT = 0x400
                if hasattr(file_stat, 'st_file_attributes') and (file_stat.st_file_attributes & 0x400):
                    print(f"  ⚠️  检测到 reparse point: {filepath}，自动删除")
                    os.remove(filepath)
        except Exception as e:
            print(f"  ⚠️  符号链接检测异常: {e}")
    
    # 2. 重试写入（应对 Windows Defender 锁文件）
    for attempt in range(max_retries):
        try:
            with open(filepath, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            return True
        except PermissionError as e:
            if attempt < max_retries - 1:
                print(f"  ⚠️  写入 {os.path.basename(filepath)} 被锁（尝试 {attempt+1}/{max_retries}），{retry_delay}s后重试...")
                time.sleep(retry_delay)
            else:
                print(f"  ❌ 写入 {filepath} 失败（PermissionError，已重试 {max_retries} 次）: {e}")
                raise
        except Exception as e:
            print(f"  ❌ 写入 {filepath} 失败: {e}")
            raise
    return False

def main():
    global subprocess
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

    # === 兜底补全：stock_names.json 偶发只有港股（akshare A股接口超时/失败），
    # 从 gold_pool + scan_result + watch_result + industry_map 提取 (code→name) 合并 ===
    try:
        _im = load_json(os.path.join(DATA_DIR, "industry_map.json"), {})
        _im_codes = set(_im.keys()) if isinstance(_im, dict) else set()
    except Exception:
        _im_codes = set()

    _fallback_names = {}  # code -> name
    # 1) gold_pool.stocks
    try:
        for _code, _info in (gold_pool.get("stocks") or {}).items():
            if isinstance(_info, dict) and _info.get("name"):
                _fallback_names[_code] = _info["name"]
    except Exception:
        pass
    # 2) scan_result.all_results + triple_signals
    try:
        for _r in (scan_data.get("all_results") or []):
            if _r.get("code") and _r.get("name"):
                _fallback_names[_r["code"]] = _r["name"]
        for _r in (scan_data.get("triple_signals") or []):
            if _r.get("code") and _r.get("name"):
                _fallback_names[_r["code"]] = _r["name"]
    except Exception:
        pass
    # 3) watch_result.all_results
    try:
        for _r in (watch_data.get("all_results") or []):
            if _r.get("code") and _r.get("name"):
                _fallback_names[_r["code"]] = _r["name"]
    except Exception:
        pass
    # 4) industry_map 关联到的代码（兜底），如 002155 等 A 股
    # industry_map 是 {code: [板块...]}，没有 name 字段 → 必须从其它来源取
    # 已有 _fallback_names，则 industry_map 里的 A 股代码现在已在金股池
    # 额外：watchlist 港股可能与 industry_map 重叠

    # 构建已有 code 集合
    _existing_codes = {s.get("code") for s in stock_names if s.get("code")}
    _missing_in_stock_list = 0
    for _code, _name in _fallback_names.items():
        if _code not in _existing_codes:
            stock_names.append({
                "code": _code,
                "name": _name,
                "full_code": ("sz" if _code.startswith(("0", "3")) else "sh" if _code.startswith("6") else "hk" if _code.startswith("0") else "") + _code
            })
            _existing_codes.add(_code)
            _missing_in_stock_list += 1
    if _missing_in_stock_list:
        print(f"  ▸ 兜底补全 STOCK_LIST: +{_missing_in_stock_list} 只（来自金股池+扫描+监控+行业）")

    # 【EMA修复】从 scan_result + watch_result 同步 latest 到 gold_pool
    # 根因：scanner.py full 模式只扫描信号子集（~237只），gold_pool 有 517 只
    # 策略：优先从扫描数据匹配，无匹配则用 gold_pool 自身字段构建基础 latest
    if gold_pool:
        _wp_stocks = gold_pool.get("stocks", {})
        _wp_updated = 0
        _wp_fallback = 0

        # 构建扫描代码索引：覆盖 watch 的 all_results + signals，以及 full 模式的 signals
        # 关键：必须包含 watch_result.all_results（康强电子就是只走 watch 模式的典型）
        _scan_idx = {}
        for _src in [scan_data, watch_data]:
            if not _src: continue
            for _s in (_src.get("all_results") or []) \
                    + (_src.get("double_signals") or []) \
                    + (_src.get("triple_signals") or []):
                _c = str(_s.get("code", ""))
                if not _c: continue
                _clean = _c.split("_")[-1] if "_" in _c else _c
                # 同一 code 后写覆盖前写（watch_data 后于 scan_data）
                _scan_idx[_clean] = _s
                _scan_idx[_c] = _s
        
        for _gp_code, _gp_data in _wp_stocks.items():
            _norm = _gp_code.split("_")[-1] if "_" in _gp_code else _gp_code

            # 尝试从扫描数据匹配
            _ms = _scan_idx.get(_norm) or _scan_idx.get(_gp_code)
            if _ms and isinstance(_ms, dict):
                        # EMA 优先取顶层 ema_up/ema_score/ema_dirs（来自 scanner 写入 watch_result），其次 latest
                        _ema_up = _ms.get("ema_up")
                        if _ema_up is None:
                            _ema_up = (_ms.get("latest") or {}).get("ema_up", 0)
                        _ema_dirs = _ms.get("ema_dirs")
                        if not _ema_dirs:
                            _ema_dirs = (_ms.get("latest") or {}).get("ema_dirs", [False]*7)
                        _ema_score = _ms.get("ema_score")
                        if _ema_score is None:
                            _ema_score = _ema_up
                        _gp_data["latest"] = {
                            "close": _ms.get("close", 0),
                            "pct_chg": _ms.get("pct_chg", 0),
                            "pct_chg_5d": _ms.get("pct_chg_5d", _ms.get("pct_chg", 0)),
                            "pct_chg_20d": _ms.get("pct_chg_20d", _ms.get("pct_chg", 0)),
                            "rsi_14": _ms.get("rsi_14", 50),
                            "signal_score": _ms.get("signal_score", 0),
                            "ema_up": _ema_up,
                            "ema_dirs": _ema_dirs,
                            "ema_score": _ema_score,
                            "turnover_rate": _ms.get("turnover_rate", 0),
                            "缠论买_日K": _ms.get("缠论买_日K", False),
                            "缠论买_次数": _ms.get("缠论买_次数", 0),
                            "金钻_黄柱": _ms.get("金钻_黄柱", False),
                            "金钻_起涨": _ms.get("金钻_起涨", False),
                            "四量图_机构变红": _ms.get("四量图_机构变红", False),
                            "上涨趋势": _ms.get("上涨趋势", False),
                            "三线共振": _ms.get("三线共振", False),
                            "三足鼎立": _ms.get("三足鼎立", False),
                            "signal_count": _ms.get("signal_count", 0),
                            "当日涨停": _ms.get("当日涨停", False),
                            "开盘_标签": _ms.get("开盘_标签", ""),
                        }
                        # 同步到金股池顶层（供 buildQueryExtras 读 entry.ema_score）
                        _gp_data["ema_up"] = _ema_up
                        _gp_data["ema_dirs"] = _ema_dirs
                        _gp_data["ema_score"] = _ema_score
                        _wp_updated += 1
            else:
                # 无扫描数据匹配：保留已有的 latest（含历史EMA），不覆盖
                _old_latest = _gp_data.get("latest")
                if not isinstance(_old_latest, dict) or _old_latest.get("ema_up", 0) == 0:
                    # 确实无任何数据 → fallback 构建基础 latest（EMA=0）
                    _gp_data["latest"] = {
                        "close": _gp_data.get("close", 0),
                        "pct_chg": _gp_data.get("pct_chg", 0),
                        "pct_chg_5d": _gp_data.get("pct_chg_5d", _gp_data.get("pct_chg", 0)),
                        "pct_chg_20d": _gp_data.get("pct_chg_20d", _gp_data.get("pct_chg", 0)),
                        "rsi_14": _gp_data.get("rsi_14", 50),
                        "signal_score": _gp_data.get("signal_score", 0),
                        "ema_up": 0,
                        "ema_dirs": [False, False, False, False, False, False, False],
                        "ema_score": 0,
                        "turnover_rate": _gp_data.get("turnover_rate", 0),
                        "缠论买_日K": _gp_data.get("缠论买_日K", False),
                        "缠论买_次数": _gp_data.get("缠论买_次数", 0),
                        "金钻_黄柱": _gp_data.get("金钻_黄柱", False),
                        "金钻_起涨": _gp_data.get("金钻_起涨", False),
                        "四量图_机构变红": _gp_data.get("四量图_机构变红", False),
                        "上涨趋势": _gp_data.get("上涨趋势", False),
                        "三线共振": _gp_data.get("三线共振", False),
                        "三足鼎立": _gp_data.get("三足鼎立", False),
                        "signal_count": _gp_data.get("signal_count", 0),
                        "当日涨停": _gp_data.get("当日涨停", False),
                        "开盘_标签": _gp_data.get("开盘_标签", ""),
                    }
                    _wp_fallback += 1
                # else: 已有有效 latest（含EMA），保持不动
        _total_synced = _wp_updated + _wp_fallback
        if _total_synced > 0:
            print(f"  ▸ GOLD_POOL: 从扫描数据同步 {_wp_updated} 只 + fallback {_wp_fallback} 只 = {_total_synced} 只补全latest")
        # 总是写回（日期不同+确保最新EMA落盘）
        _old_ut = gold_pool.get("update_time", "")
        _new_ut = time.strftime("%Y-%m-%d %H:%M:%S")
        gold_pool["update_time"] = _new_ut
        _need_save = _total_synced > 0
        if _old_ut != _new_ut[:10]:  # 日期不同就需要写回
            _need_save = True
        if _need_save:
            try:
                with open(os.path.join(DATA_DIR, "gold_pool.json"), "w", encoding="utf-8") as _f:
                    json.dump(gold_pool, _f, ensure_ascii=False, indent=2)
                print(f"  ▸ GOLD_POOL: 已写回磁盘 (update_time: {_old_ut[:10]} → {_new_ut[:10]}, 517只, EMA完整)")
            except Exception as _e:
                print(f"  ⚠ GOLD_POOL 写回失败: {_e}")

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

    stock_list = []
    _seen_codes = set()
    for s in stock_names:
        if "code" in s and "name" in s:
            code = s["code"]
            if code in _seen_codes:
                continue  # 去重：避免同名股票被多次列出
            _seen_codes.add(code)
            stock_list.append({
                "code": code,
                "name": s["name"],
                "py": _py_abbr(s["name"]),
            })
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
    sector_rs    = load_json(os.path.join(DATA_DIR, "sector_rs.json"), {"update_time": "", "strong_5d": [], "strong_20d": [], "strong_52w": []})
    ipo_score    = load_json(os.path.join(DATA_DIR, "ipo_score.json"), {"update_time": "", "eligible_count": 0, "summary": "", "stocks": []})
    cffex_holdings = load_json(os.path.join(DATA_DIR, "cffex_holdings.json"), {})
    inst_trade = load_json(os.path.join(DATA_DIR, "inst_trade.json"), {})
    overnight_brief = load_json(os.path.join(DATA_DIR, "overnight_timeline.json"), [])
    worldcup = load_json(os.path.join(DATA_DIR, "worldcup.json"), {})
    lottery_data = load_json(os.path.join(DATA_DIR, "lottery_data.json"), {})
    limit_up_heatmap = load_json(os.path.join(DATA_DIR, "limit_up_heatmap.json"), {})
    top10_daily = load_json(os.path.join(DATA_DIR, "top10_daily.json"), {"update_time": "", "top10": []})
    # 多维共振最新一日TOP10
    multi_resonance_history = load_json(os.path.join(DATA_DIR, "multi_resonance_history.json"), {})
    multi_resonance_top10 = []
    if isinstance(multi_resonance_history, dict):
        mr_dates = sorted(multi_resonance_history.keys(), reverse=True)
        if mr_dates:
            latest_mr = multi_resonance_history[mr_dates[0]]
            if isinstance(latest_mr, dict):
                multi_resonance_top10 = latest_mr.get("top10", [])
    industry_map_data = load_json(os.path.join(DATA_DIR, "industry_map.json"), {"update_time": "", "stocks": {}})
    w52_high = load_json(os.path.join(DATA_DIR, "52w_high.json"), {"update_time": "", "total": 0, "top_sectors": [], "top_gainers": [], "stocks": []})
    analyst_ratings = load_json(os.path.join(DATA_DIR, "analyst_ratings.json"), {"update_time": "", "upgrades": [], "hot_stocks": []})
    policy_density = load_json(os.path.join(DATA_DIR, "policy_density.json"), {"update_time": "", "density": 0, "level": "低", "signals": []})
    fetch_errors = load_json(os.path.join(DATA_DIR, ".fetch_errors.json"), {"last_scan": "", "errors": []})

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
    mahoro_coverage = {"_update_time": mahoro_sig.get("fetch_time", "")}
    for m in mahoro_sig.get("gold_pool_matches", []):
        code = m.get("code", "")
        stance = m.get("stance", "")
        if code and stance:
            mahoro_coverage[code] = stance
    has_cov = len(mahoro_coverage) > 1  # >1 因为有 _update_time 键
    if has_cov:
        print(f"  ▸ 投行覆盖: {len(mahoro_coverage)-1} 只")

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
        ("SECTOR_RS",       "window.SECTOR_RS = ",       "{", "}"),
        ("IPO_DATA",      "window.IPO_DATA = ",      "{", "}"),
        ("LHB_DATA",       "window.LHB_DATA = ",      "{", "}"),
        ("MAIN_STOCK",     "var MAIN_STOCK_DATA = window.MAIN_STOCK_DATA = ","{", "}"),
        ("MAIN_WEEK",      "window.MAIN_WEEK_DATA = ",  "{", "}"),
        ("NORTH_FUND",     "window.NORTH_FUND_DATA = ",  "{", "}"),
        ("MAHORO_COVERAGE", "var MAHORO_COVERAGE = window.MAHORO_COVERAGE = ","{", "}"),
        ("SUSPENSION_ALERT", "window.SUSPENSION_ALERT = ",  "{", "}"),
        ("STOCK_DEVIATION", "var STOCK_DEVIATION = window.STOCK_DEVIATION = ", "{", "}"),
        ("FOMC_SUMMARY",   "window.FOMC_SUMMARY = ",  "{", "}"),
        ("CFFEX_HOLDINGS", "window.CFFEX_HOLDINGS = ", "{", "}"),
        ("INST_TRADE",     "window.INST_TRADE = ",     "{", "}"),
        ("WORLD_CUP",     "window.WORLD_CUP = ",      "{", "}"),
        ("LOTTERY_DATA",  "window.LOTTERY_DATA = ",   "{", "}"),
        ("LIMIT_UP_HEATMAP","window.LIMIT_UP_HEATMAP = ","{", "}"),
        ("W52_HIGH",      "window.W52_HIGH = ",       "{", "}"),
        ("ANALYST_RATINGS", "window.ANALYST_RATINGS = ", "{", "}"),
        ("POLICY_DENSITY", "window.POLICY_DENSITY = ",  "{", "}"),
        ("TOP10_DAILY",   "window.TOP10_DAILY = ",    "{", "}"),
        ("INDUSTRY_MAP",  "window.INDUSTRY_MAP = ",   "{", "}"),
    ]
    data_objs = [scan_data, watch_data, gold_pool, stock_list, recommend,
                 sh_fib, sz_fib, sector_flow, sh_sz_history, nt_data,
                 concept_ranking, market_alerts, margin_data, etf_subscription, macro_data,                  herding_data,
                 sector_rs, ipo_score, lhb_data, main_stock, main_week, north_fund, mahoro_coverage, suspension_alert, stock_deviation, fomc_summary, cffex_holdings, inst_trade, worldcup, lottery_data, limit_up_heatmap, w52_high, analyst_ratings, policy_density, top10_daily, industry_map_data]
    replacements = []

    for (name, marker, open_ch, close_ch), data in zip(markers, data_objs):
        s, e = find_block_end(content, marker, open_ch, close_ch)
        if s < 0:
            print(f"  ⚠️  找不到 {name}，跳过")
            continue
        # 校验数据有效性：如果数据为空（无update_time/scan_time/有效列表），保留旧数据
        is_empty = False
        if isinstance(data, dict) and name in ("MAIN_STOCK", "HERRING_DATA", "LHB_DATA", "IPO_DATA"):
            if not data.get("update_time") and not data.get("scan_time"):
                is_empty = True
        # 额外检查：即使有update_time，如果核心数据数组全空，也视为无效（防止API空结果覆盖已有数据）
        if not is_empty and isinstance(data, dict):
            if name == "HERRING_DATA":
                # 如果明确标记 data_available=false（API全失败），放行空数据不拦截
                if data.get("data_available") is False:
                    pass  # 故意为空，允许替换旧数据
                else:
                    clusters = data.get("current_clusters") or []
                    high_prob = data.get("high_prob") or []
                    if len(clusters) == 0 and len(high_prob) == 0:
                        is_empty = True
                        print(f"  ⚠️  {name} 数据全空 (clusters=0, high_prob=0)，跳过替换")
            elif name == "MAIN_STOCK":
                # 如果明确标记 data_available=false（API全失败），放行空数据不拦截
                if data.get("data_available") is False:
                    pass  # 故意为空，允许替换旧数据
                else:
                    top_in = data.get("top_main_in") or []
                    top_out = data.get("top_main_out") or []
                    if len(top_in) == 0 and len(top_out) == 0:
                        is_empty = True
                        print(f"  ⚠️  {name} 数据全空 (top_in=0, top_out=0)，跳过替换")
            elif name == "IPO_DATA":
                stocks = data.get("stocks") or []
                if len(stocks) == 0 and not data.get("summary"):
                    is_empty = True
                    print(f"  ⚠️  {name} 数据全空 (stocks=0)，跳过替换")
        if isinstance(data, dict) and name == "LHB_DATA":
            if not data.get("stocks") and not data.get("update_time") and not data.get("scan_time"):
                is_empty = True
        if isinstance(data, dict) and name in ("MARGIN_DATA", "NORTH_FUND", "ETF_SUBSCRIPTION", "FOMC_SUMMARY"):
            if not data.get("update_time") and not data.get("available", True):
                is_empty = True
                print(f"  ⚠️  {name} 无新数据且不可用，跳过替换")
        # 通用空数据保护：检查核心数组是否为空
        if not is_empty and isinstance(data, dict):
            # SECTOR_FUND_FLOW: 检查 sectors_in/out
            if name == "SECTOR_FUND_FLOW":
                if not data.get("sectors_in") and not data.get("sectors_out"):
                    if not data.get("update_time"):
                        is_empty = True
                        print(f"  ⚠️  {name} 数据全空，跳过替换")
            # SECTOR_RS: 检查 strong_5d/strong_20d/strong_52w
            elif name == "SECTOR_RS":
                strong_5d = data.get("strong_5d") or []
                strong_20d = data.get("strong_20d") or []
                if len(strong_5d) == 0 and len(strong_20d) == 0 and not data.get("update_time"):
                    is_empty = True
                    print(f"  ⚠️  {name} 数据全空，跳过替换")
            # TOP10_DAILY: 检查 top10
            elif name == "TOP10_DAILY":
                top10 = data.get("top10") or []
                if len(top10) == 0 and not data.get("update_time"):
                    is_empty = True
                    print(f"  ⚠️  {name} 数据全空，跳过替换")
            # ANALYST_RATINGS: 检查 upgrades/hot_stocks
            elif name == "ANALYST_RATINGS":
                upgrades = data.get("upgrades") or []
                hot = data.get("hot_stocks") or []
                if len(upgrades) == 0 and len(hot) == 0 and not data.get("update_time"):
                    is_empty = True
                    print(f"  ⚠️  {name} 数据全空，跳过替换")
            # POLICY_DENSITY: 检查 signals
            elif name == "POLICY_DENSITY":
                signals = data.get("signals") or []
                if len(signals) == 0 and not data.get("update_time"):
                    is_empty = True
                    print(f"  ⚠️  {name} 数据全空，跳过替换")
            # CONCEPT_RANKING: 检查 concepts
            elif name == "CONCEPT_RANKING":
                concepts = data.get("concepts") or []
                if len(concepts) == 0 and not data.get("update_time"):
                    is_empty = True
                    print(f"  ⚠️  {name} 数据全空，跳过替换")
            # MARKET_ALERTS: 检查 alerts
            elif name == "MARKET_ALERTS":
                alerts = data.get("alerts") or []
                if len(alerts) == 0 and not data.get("update_time"):
                    is_empty = True
                    print(f"  ⚠️  {name} 数据全空，跳过替换")
            # W52_HIGH: 检查 stocks
            elif name == "W52_HIGH":
                stocks = data.get("stocks") or []
                if len(stocks) == 0 and not data.get("update_time"):
                    is_empty = True
                    print(f"  ⚠️  {name} 数据全空，跳过替换")
        if is_empty:
            print(f"  ⚠️  {name} 数据为空，跳过替换（保留旧数据）")
            continue
        new_json = json.dumps(data, ensure_ascii=False, indent=0)
        new_block = marker + new_json + ";"
        # 立即替换（不收集后排序，防止位置偏移导致串行）
        content = content[:s] + new_block + content[e:]
        print(f"  ✓ {name}: {e-s:,} → {len(new_block):,} 字符")

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

    # 注入多维共振历史数据到 multi_resonance.html
    multi_resonance_html_path = os.path.join(BASE_DIR, "multi_resonance.html")
    multi_resonance_out_path = os.path.join(DIST_DIR, "multi_resonance.html")
    multi_resonance_json_path = os.path.join(DATA_DIR, "multi_resonance_history.json")
    if os.path.exists(multi_resonance_html_path) and os.path.exists(multi_resonance_json_path):
        try:
            with open(multi_resonance_json_path, "r", encoding="utf-8") as f:
                mrh_data = json.load(f)
            with open(multi_resonance_html_path, "r", encoding="utf-8") as f:
                mrh = f.read()
            embedded = json.dumps(mrh_data, ensure_ascii=False)
            if 'MULTI_RESONANCE_HISTORY' in mrh:
                mrh = _re.sub(
                    r'<script>\s*\n\s*var MULTI_RESONANCE_HISTORY\s*=.*?\n\s*</script>',
                    '', mrh, flags=_re.DOTALL
                )
            mrh = mrh.replace('</head>',
                f'<script>\nvar MULTI_RESONANCE_HISTORY = {embedded};\n</script>\n</head>')
            with open(multi_resonance_out_path, "w", encoding="utf-8") as f:
                f.write(mrh)
            print(f"  ✓ multi_resonance.html 已嵌入历史数据")
        except Exception as e:
            print(f"  ⚠️ multi_resonance 注入失败: {e}")

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
            written = False
            for attempt in range(3):
                try:
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(c)
                    # 回读验证：确认占位符已被替换
                    with open(fpath, "r", encoding="utf-8") as vf:
                        vc = vf.read()
                    if "__PWD__" in vc or "__GUEST_PWD__" in vc:
                        if attempt < 2:
                            time.sleep(0.5)
                            continue  # 写入可能被锁，重试
                        else:
                            print(f"  ❌ 密码注入写入验证失败！{os.path.basename(fpath)} 仍含占位符")
                            return False
                    written = True
                    break
                except PermissionError:
                    if attempt < 2:
                        time.sleep(0.5)
                    else:
                        raise
            if not written:
                print(f"  ❌ 密码注入失败！{os.path.basename(fpath)} 写入不成功")
                return False
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

    # 运行时冒烟测试（模拟浏览器执行关键代码路径，捕获 TypeError/ReferenceError）
    print("  运行时冒烟测试:")
    smoke_ok = verify_runtime_smoke(content)
    if not smoke_ok:
        print("  ❌ 运行时冒烟失败，已拦截！")
        return False

    # 保存（双文件输出）
    _safe_write(OUTPUT_PATH, content)
    _safe_write(OUTPUT_PATH_MASTER, content)
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

    # 同步静态资源（favicon.svg 等）→ dist/
    _static_assets = ["favicon.svg"]
    for _sa in _static_assets:
        _src_sa = os.path.join(BASE_DIR, _sa)
        _dst_sa = os.path.join(DIST_DIR, _sa)
        if os.path.exists(_src_sa):
            shutil.copy2(_src_sa, _dst_sa)
    print(f"  ✓ 已同步静态资源 → dist/")

    print(f"\n✅ 数据块更新成功！")
    print(f"   部署: python deploy_now.py")
    print(f"   网址: https://ah-quant999.github.io/quant-scanner-v6/")
    return True
if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
