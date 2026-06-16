#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
投行最新研报 — 知识星球研报股票提取 + 关注池管理
============================================
数据源：https://wx.zsxq.com/group/28882555515111
API：https://api.zsxq.com/v2/groups/{group_id}/topics

功能：
  1. 通过知识星球 API（zsxq_access_token）拉取全部帖子
  2. 提取股票名称、代码、推荐机构、评级
  3. 维护关注池（guanlan_watchlist.json），自动去重
  4. 输出可集成到扫描器/仪表盘的数据

机构覆盖（不限于高盛花旗）：
  高盛、花旗、摩根士丹利、摩根大通、美银美林、瑞银、瑞信、
  德意志银行、巴克莱、汇丰、野村、大和、麦格理、杰富瑞、
  中金、中信、华泰、国泰君安、招商、海通、广发等 30+ 机构
"""

import re
import json
import sys
import os
import ssl
import subprocess
import hashlib
import datetime
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import quote

# --- Selenium（可选，用于绕过 API 封锁） ---
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_OK = True
except ImportError:
    SELENIUM_OK = False

# --- 路径 ---
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
WATCHLIST_FILE = DATA_DIR / "guanlan_watchlist.json"
TOKEN_FILE = DATA_DIR / "zsxq_token.json"
ZSXQ_GROUP_ID = "28882555515111"

# --- 股票提取 ---
STOCK_PATTERN = re.compile(
    r'([\u4e00-\u9fa5a-zA-Z（）()\·]+?)\s*[\(（]\s*(\d{4,6})\s*\.\s*(HK|SS|SZ|SH)\s*[\)）]'
)

# --- 机构识别（30+ 机构） ---
INSTITUTION_PATTERNS = [
    (r'高盛|Goldman\s*Sachs', '高盛'),
    (r'花旗|Citi(group)?', '花旗'),
    (r'摩根士丹利|大摩|Morgan\s*Stanley', '摩根士丹利'),
    (r'摩根大通|小摩|J\.?\s*P\.?\s*Morgan', '摩根大通'),
    (r'美银美林|美银|美林|BofA|Bank\s*of\s*America', '美银美林'),
    (r'瑞银|UBS', '瑞银'),
    (r'瑞信|Credit\s*Suisse', '瑞信'),
    (r'德意志银行|德银|Deutsche\s*Bank', '德意志银行'),
    (r'巴克莱|Barclays', '巴克莱'),
    (r'汇丰|HSBC', '汇丰'),
    (r'野村|Nomura', '野村'),
    (r'大和|Daiwa', '大和'),
    (r'麦格理|Macquarie', '麦格理'),
    (r'杰富瑞|Jefferies', '杰富瑞'),
    (r'伯恩斯坦|Bernstein', '伯恩斯坦'),
    (r'中金公司|中金', '中金公司'),
    (r'中信证券|中信', '中信证券'),
    (r'华泰证券|华泰', '华泰证券'),
    (r'国泰君安', '国泰君安'),
    (r'招商证券|招商', '招商证券'),
    (r'海通证券|海通', '海通证券'),
    (r'广发证券|广发', '广发证券'),
    (r'申万宏源|申万', '申万宏源'),
    (r'中信建投', '中信建投'),
    (r'国信证券|国信', '国信证券'),
    (r'银河证券|银河', '银河证券'),
    (r'兴业证券|兴业', '兴业证券'),
    (r'天风证券|天风', '天风证券'),
    (r'浙商证券|浙商', '浙商证券'),
    (r'东方证券|东方', '东方证券'),
    (r'光大证券|光大', '光大证券'),
    (r'中泰证券|中泰', '中泰证券'),
]

# --- 评级识别 ---
RATING_PATTERNS = [
    (r'强烈推荐', '强烈推荐'), (r'买入|Buy', '买入'),
    (r'增持|Overweight|Outperform', '增持'),
    (r'推荐', '推荐'), (r'持有|Hold', '持有'),
    (r'中性|Neutral', '中性'), (r'减持|Underweight|Underperform', '减持'),
    (r'卖出|Sell', '卖出'), (r'回避', '回避'),
]


def extract_institution(text: str) -> str:
    for pattern, name in INSTITUTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return "未知机构"


def extract_rating(text: str) -> str:
    for pattern, name in RATING_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return "未评级"


# 已知合法的"和/及"开头股票名白名单
_WHITELIST_PREFIX = {'和林微纳', '和而泰', '和顺石油', '和晶科技', '和远气体', '和邦生物',
                     '和辉光电', '和佳医疗', '和金科技', '和元生物'}


def _repair_name(name: str) -> str:
    """从解析错误中尝试恢复真实股票名"""
    if not name:
        return name

    # 白名单保护 — 原名称命中直接返回
    if name in _WHITELIST_PREFIX:
        return name

    original = name

    # 1. 去掉常见句子前缀（按长度倒序，避免短前缀误匹配）
    garbage_prefixes = ['我们给予', '新客户包括', '但随着', '其次是',
                        '新增', '带动', '包括', '给予', '及', '和']
    for p in sorted(garbage_prefixes, key=len, reverse=True):
        if name.startswith(p) and len(name) > len(p) + 1:
            candidate = name[len(p):]
            if candidate in _WHITELIST_PREFIX:
                continue
            name = candidate
            break

    # 2. 截断后面的描述性文字（"东方电气主要依靠中国广核" → "东方电气"）
    tail_markers = ['主要依靠', '近期与', '的风险', '首选', '是']
    for m in tail_markers:
        idx = name.find(m)
        if idx >= 2:
            name = name[:idx]
            break

    # 3. 去末尾未闭合括号（"六福集团（国际" → "六福集团"）
    name = re.sub(r'[（(][^）)]*$', '', name)

    # 4. 去末尾「X有限公司」等非股票名后缀
    name = re.sub(r'(科技|股份|有限|投资|控股|集团|实业|证券)有限公司$', '', name)

    return name.strip('，,。.、；;：:（）()·')


def _clean_stock_name(name: str) -> str:
    """清洗股票名称，去除多余后缀和杂讯"""
    name = re.sub(r'[\n\r\t\s]', '', name)

    # 先尝试修复
    name = _repair_name(name)

    # 去除常见后缀
    for suffix in ['股份有限公司', '有限公司', '集团', '控股', '科技', '实业']:
        if name.endswith(suffix) and len(name) > len(suffix) + 2:
            name = name[:-len(suffix)]
    # 去除括号内的英文缩写如 （CRML）
    name = re.sub(r'[（(][A-Za-z]+[）)]', '', name)
    # 边界清理
    name = name.strip('，,。.、；;：:（）()·')
    return name


_BAD_NAME_PATTERNS = [
    # 含这些关键词的名称必然是解析错误，直接丢弃
    re.compile(r'我们的'),
    re.compile(r'首选股票是'),
    re.compile(r'其次是'),
    re.compile(r'给予'),
    re.compile(r'带动'),
    re.compile(r'新增'),
    re.compile(r'新客户包括'),
    re.compile(r'但随着'),
    re.compile(r'近期与.*成立'),
    re.compile(r'主要依靠'),
    re.compile(r'的风险'),
    # 修复：和/及 开头跟中文字符（不覆盖白名单）
    re.compile(r'^和[\u4e00-\u9fff]'),
    re.compile(r'^及[\u4e00-\u9fff]'),
    re.compile(r'^包括'),
]


def _is_bad_name(name: str) -> bool:
    """检测是否为解析错误的名称"""
    if len(name) < 2 or name.isdigit():
        return True
    if len(name) > 15:
        return True
    # 白名单保护
    if name in _WHITELIST_PREFIX:
        return False
    for pat in _BAD_NAME_PATTERNS:
        if pat.search(name):
            return True
    return False


def extract_stocks(text: str) -> list:
    """从文本中提取股票名称和代码"""
    results, seen = [], set()
    for match in STOCK_PATTERN.finditer(text):
        name = _clean_stock_name(match.group(1).strip())
        code, exchange = match.group(2), match.group(3)

        # 标准化代码
        if exchange in ('SS', 'SH'):
            full_code, market = f"SH{code}", "A股"
        elif exchange == 'SZ':
            full_code, market = f"SZ{code}", "A股"
        elif exchange == 'HK':
            # 港股代码补前导零到5位
            code = code.zfill(5)
            full_code, market = f"HK.{code}", "港股"
        else:
            full_code, market = f"{code}.{exchange}", "未知"

        # 过滤无效名称
        if _is_bad_name(name):
            continue
        if len(name) < 2 or name.isdigit():
            continue
        # 过滤纯标点、纯英文字母等
        if re.match(r'^[A-Za-z·\s]+$', name):
            continue
        if full_code not in seen:
            seen.add(full_code)
            results.append({"name": name, "code": code, "full_code": full_code,
                            "exchange": exchange, "market": market})
    return results


# --- Token 管理 ---

def load_token() -> str:
    """从配置文件加载 zsxq_access_token"""
    if TOKEN_FILE.exists():
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        return data.get("token", "")
    return ""


def save_token(token: str):
    """保存 token 到配置文件"""
    TOKEN_FILE.write_text(
        json.dumps({"token": token, "updated": datetime.datetime.now().isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# --- 知识星球 API 抓取（主力） ---

def fetch_via_api(group_id: str = ZSXQ_GROUP_ID,
                  max_pages: int = 200,
                  token: str = "") -> list:
    """
    通过知识星球 API 拉取全部帖子并提取研报。
    递归分页（cursor-based），直到没有更多或达到 max_pages。
    每页 20 条，max_pages=200 → 最多 4000 条帖子。
    """
    if not token:
        token = load_token()
    if not token:
        print("[投行最新研报] ⚠️ 未配置 zsxq_access_token", file=sys.stderr)
        return []

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {
        "Cookie": f"zsxq_access_token={token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    all_posts = []
    seen_text_hashes = set()
    end_time = None

    for page in range(max_pages):
        # 构建 URL
        url = f"https://api.zsxq.com/v2/groups/{group_id}/topics?scope=all&count=20"
        if end_time:
            url += "&end_time=" + quote(end_time, safe="")

        # 带重试的请求（API 限流时自动重试）
        for attempt in range(3):
            try:
                req = Request(url, headers=headers)
                with urlopen(req, context=ctx, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(1.5)
                else:
                    print(f"[投行最新研报] API 第{page+1}页失败(已重试): {e}", file=sys.stderr)
                    data = {}

        topics = data.get("resp_data", {}).get("topics", [])
        if not topics:
            if page > 0:
                print(f"[投行最新研报] 第{page+1}页无数据，分页终止", file=sys.stderr)
            break

        new_posts = 0
        for topic in topics:
            # 提取帖子正文（talk 类型）
            if topic.get("type") != "talk":
                continue

            talk = topic.get("talk", {})
            text = talk.get("text", "")
            if not text:
                continue

            # 去重（按文本 hash）
            text_hash = hashlib.md5(text[:200].encode()).hexdigest()
            if text_hash in seen_text_hashes:
                continue
            seen_text_hashes.add(text_hash)

            # 清理 HTML 标签
            clean = re.sub(r'<[^>]+>', ' ', text)
            clean = re.sub(r'&nbsp;', ' ', clean)
            clean = re.sub(r'\s+', ' ', clean).strip()

            stocks = extract_stocks(clean)
            if not stocks:
                continue

            institution = extract_institution(clean)
            rating = extract_rating(clean)
            create_time = topic.get("create_time", "")
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', create_time)
            date_str = date_match.group(1) if date_match else create_time[:10]

            all_posts.append({
                "institution": institution,
                "rating": rating,
                "date": date_str,
                "stocks": stocks,
                "topic_id": topic.get("topic_id"),
                "raw_text": clean[:500],
            })
            new_posts += 1

        # 更新游标（最后一条帖子的时间）
        end_time = topics[-1].get("create_time", "")

        # 每页打印进度
        print(f"[投行最新研报] 第{page+1}页: {len(topics)}条帖子 → "
              f"命中{new_posts}篇研报 | 累计{len(all_posts)}篇",
              file=sys.stderr)

        # 如果连续 3 页没命中研报，提前终止
        if new_posts == 0:
            _no_hit_streak = getattr(fetch_via_api, "_no_hit_streak", 0) + 1
            setattr(fetch_via_api, "_no_hit_streak", _no_hit_streak)
            if _no_hit_streak >= 3:
                print(f"[投行最新研报] 连续{_no_hit_streak}页无研报，终止扫描", file=sys.stderr)
                break
            continue
        else:
            setattr(fetch_via_api, "_no_hit_streak", 0)

        # 延迟防限流（每5页休息一下）
        if page % 5 == 4:
            time.sleep(0.8)

    return all_posts


# --- agent-browser 抓取（兜底方案） ---

def parse_snapshot_posts(snapshot_text: str) -> list:
    """解析 agent-browser snapshot 文本，按帖子容器分隔"""
    posts = []
    post_blocks = re.split(r'(?=generic\s+\[ref=e\d+\])', snapshot_text)
    for block in post_blocks:
        static_texts = re.findall(r'StaticText\s+\"(.+?)\"', block, re.DOTALL)
        if not static_texts:
            continue
        content = '\n'.join(static_texts)
        content = content.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')
        stocks = extract_stocks(content)
        if not stocks:
            continue
        institution = extract_institution(content)
        rating = extract_rating(content)
        date_match = re.search(r'(\d{4}/\d{1,2}/\d{1,2})', content)
        posts.append({
            "institution": institution,
            "rating": rating,
            "date": date_match.group(1) if date_match else "",
            "stocks": stocks,
            "raw_text": content[:500],
        })
    return posts


def _fetch_via_selenium(max_pages: int = 10) -> list:
    """Selenium 浏览器抓取（绕过 API 封锁，需要 Chrome + webdriver-manager）"""
    if not SELENIUM_OK:
        print("[投行最新研报] ⚠️ selenium 未安装，跳过")
        return []
    token = load_token()
    if not token:
        print("[投行最新研报] ⚠️ 未找到 zsxq token，无法认证浏览器会话")
        return []
    print("[投行最新研报] Selenium 模式：启动 Chrome（自动下载驱动）...")
    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"[投行最新研报] ⚠️ Chrome 启动失败: {e}")
        return []

    try:
        # 1. 先访问主站，注入认证 cookie
        driver.get("https://wx.zsxq.com")
        time.sleep(1)
        driver.add_cookie({
            "name": "zsxq_access_token",
            "value": token,
            "domain": ".zsxq.com",
            "path": "/",
        })
        # 2. 访问群组页面
        driver.get(f"https://wx.zsxq.com/group/{ZSXQ_GROUP_ID}")
        time.sleep(4)

        # 3. 滚动加载更多帖子
        for _ in range(min(max_pages, 8)):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

        # 4. 提取页面文本
        body_text = driver.find_element(By.TAG_NAME, "body").text
        DATA_DIR.mkdir(exist_ok=True)
        snap_file = DATA_DIR / "zsxq_selenium_snapshot.txt"
        snap_file.write_text(body_text, encoding="utf-8")

        # 5. 按日期行切割帖子，逐段解析
        posts = []
        current_block = ""
        for line in body_text.splitlines():
            if re.match(r"\d{4}/\d{1,2}/\d{1,2}", line):
                if current_block.strip():
                    stocks = extract_stocks(current_block)
                    if stocks:
                        posts.append({
                            "institution": extract_institution(current_block),
                            "rating": extract_rating(current_block),
                            "date": line[:10],
                            "stocks": stocks,
                            "raw_text": current_block[:500],
                        })
                current_block = line
            else:
                current_block += "\n" + line
        # 处理最后一段
        if current_block.strip():
            stocks = extract_stocks(current_block)
            if stocks:
                date_match = re.search(r"(\d{4}/\d{1,2}/\d{1,2})", current_block)
                posts.append({
                    "institution": extract_institution(current_block),
                    "rating": extract_rating(current_block),
                    "date": date_match.group(1) if date_match else "",
                    "stocks": stocks,
                    "raw_text": current_block[:500],
                })

        print(f"[投行最新研报] Selenium 提取到 {len(posts)} 篇研报帖子")
        return posts

    except Exception as e:
        print(f"[投行最新研报] ⚠️ Selenium 抓取异常: {e}")
        return []
    finally:
        driver.quit()


def _fetch_via_agent_browser_fallback() -> list:
    """agent-browser 兜底（公开页面预览 → 最后手段）"""
    snapshot_file = DATA_DIR / "zsxq_snapshot.txt"
    try:
        subprocess.run(["agent-browser", "open",
                        f"https://wx.zsxq.com/group/{ZSXQ_GROUP_ID}"],
                       capture_output=True, text=True, timeout=15)
        subprocess.run(["agent-browser", "wait", "--load", "networkidle"],
                       capture_output=True, text=True, timeout=20)
        result = subprocess.run(["agent-browser", "snapshot"],
                                capture_output=True, text=True, timeout=15)
        if result.stdout.strip():
            snapshot_file.write_text(result.stdout, encoding="utf-8")
            return parse_snapshot_posts(result.stdout)
    except Exception:
        pass
    if snapshot_file.exists():
        return parse_snapshot_posts(snapshot_file.read_text(encoding="utf-8"))
    return []


# --- 关注池管理 ---

def load_watchlist() -> dict:
    if WATCHLIST_FILE.exists():
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"version": "2.0", "updated": "", "total": 0, "stocks": {}}


def save_watchlist(wl: dict):
    # 最终清洗：扫描所有股票名称，剔除坏名
    bad_codes = []
    for code, info in wl.get("stocks", {}).items():
        if _is_bad_name(info.get("name", "")):
            bad_codes.append(code)
    for code in bad_codes:
        print(f"  [清洗] 丢弃坏名条目: {code} \"{wl['stocks'][code]['name']}\"")
        del wl["stocks"][code]
    wl["total"] = len(wl["stocks"])
    wl["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(wl, f, ensure_ascii=False, indent=2)


def update_watchlist(posts: list, dry_run: bool = False) -> dict:
    wl = load_watchlist()
    added, updated = [], []
    for post in posts:
        institution = post.get("institution", "未知机构")
        rating = post.get("rating", "未评级")
        date_str = post.get("date", datetime.date.today().isoformat())
        for stock in post.get("stocks", []):
            fc = stock["full_code"]
            entry = {"institution": institution, "rating": rating,
                     "date": date_str}
            if fc not in wl["stocks"]:
                wl["stocks"][fc] = {
                    "name": stock["name"], "code": stock["code"],
                    "full_code": fc, "market": stock["market"],
                    "first_seen": date_str, "last_seen": date_str,
                    "recommendations": [entry], "rec_count": 1,
                    "institutions": [institution],
                    "latest_rating": rating, "status": "active",
                }
                added.append(fc)
            else:
                ex = wl["stocks"][fc]
                ex["last_seen"] = date_str
                ex["rec_count"] += 1
                if institution not in ex["institutions"]:
                    ex["institutions"].append(institution)
                ex["latest_rating"] = rating
                ex["recommendations"].append(entry)
                if len(ex["recommendations"]) > 30:
                    ex["recommendations"] = ex["recommendations"][-30:]
                updated.append(fc)

    wl["total"] = len(wl["stocks"])
    if not dry_run:
        save_watchlist(wl)
    return {"watchlist": wl, "added": added, "updated": updated,
            "total": wl["total"]}


def scan(silent: bool = False, max_pages: int = 200) -> dict:
    """完整扫描：API 拉取 → 提取研报 → 更新关注池"""
    if not silent:
        print("[投行最新研报] 正在通过 API 拉取知识星球研报...")

    # 方法1：API 直接拉取（主力）
    token = load_token()
    posts = fetch_via_api(max_pages=max_pages, token=token) if token else []

    # 方法2：Selenium 浏览器抓取（绕过 API 封锁）
    if not posts:
        if not silent:
            print("[投行最新研报] API 被封锁，尝试 Selenium 浏览器模式...")
        posts = _fetch_via_selenium(max_pages=min(max_pages, 10))

    # 方法3：agent-browser 兜底
    if not posts:
        if not silent:
            print("[投行最新研报] Selenium 无结果，尝试 agent-browser 兜底...")
        posts = _fetch_via_agent_browser_fallback()

    if not posts:
        if not silent:
            print("[投行最新研报] ⚠️ 未提取到研报帖子")
        return {"status": "no_posts", "posts": [], "result": None}

    if not silent:
        print(f"[投行最新研报] 提取到 {len(posts)} 篇研报帖子")
        for i, p in enumerate(posts[:10]):
            names = [s["name"] for s in p["stocks"]]
            print(f"  {i+1}. [{p['institution']}] {', '.join(names)} — {p.get('rating','?')}")
        if len(posts) > 10:
            print(f"  ... 还有 {len(posts)-10} 篇")

    result = update_watchlist(posts, dry_run=False)
    if not silent:
        print(f"[投行最新研报] 新增 {len(result['added'])} 只, "
              f"更新 {len(result['updated'])} 只, "
              f"关注池总计 {result['total']} 只")
    return {"status": "ok", "posts": posts, "result": result}


def get_watchlist_for_dashboard() -> list:
    wl = load_watchlist()
    return sorted(
        [{"full_code": fc, "name": i["name"], "code": i["code"],
          "market": i["market"], "first_seen": i.get("first_seen", ""),
          "last_seen": i.get("last_seen", ""),
          "rec_count": i.get("rec_count", 0),
          "institutions": i.get("institutions", []),
          "latest_rating": i.get("latest_rating", ""),
          "status": i.get("status", "active")}
         for fc, i in wl["stocks"].items()],
        key=lambda x: x["rec_count"], reverse=True)


# --- CLI ---
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="投行最新研报研报提取器")
    p.add_argument("action", nargs="?", default="scan",
                   choices=["scan", "list", "export", "test", "set-token"])
    p.add_argument("--silent", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--max-pages", type=int, default=200,
                   help="API 最大翻页数（默认200页=4000条帖子）")
    p.add_argument("--token", type=str, default="",
                   help="设置/更新 zsxq_access_token")
    args = p.parse_args()

    if args.action == "set-token":
        if args.token:
            save_token(args.token)
            print(f"[投行最新研报] Token 已保存")
        else:
            print("[投行最新研报] 请通过 --token 参数提供 token 值")

    elif args.action == "scan":
        r = scan(silent=args.silent, max_pages=args.max_pages)
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))

    elif args.action == "list":
        stocks = get_watchlist_for_dashboard()
        if args.json:
            print(json.dumps(stocks, ensure_ascii=False, indent=2))
        else:
            print(f"\n{'代码':<12} {'名称':<10} {'市场':<6} {'推荐':>4} {'机构':<24} {'评级':<8}")
            print("-" * 72)
            for s in stocks:
                insts = ", ".join(s["institutions"][:4])
                print(f"{s['full_code']:<12} {s['name']:<10} {s['market']:<6} "
                      f"{s['rec_count']:>4} {insts:<24} {s['latest_rating']:<8}")

    elif args.action == "export":
        stocks = get_watchlist_for_dashboard()
        out = DATA_DIR / f"guanlan_export_{datetime.date.today()}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(stocks, f, ensure_ascii=False, indent=2)
        print(f"[投行最新研报] 已导出 {len(stocks)} 只股票到 {out}")

    elif args.action == "test":
        tests = [
            "高盛\n\n中芯国际 (0981.HK)：AI 推动需求上升；买入",
            "花旗\n\n中国巨石 (600176.SS)\n上调目标价；重申买入评级",
            "摩根士丹利\n\n宁德时代 (300750.SZ)：全球电池龙头，维持增持评级",
            "中金公司\n\n贵州茅台 (600519.SH)：高端白酒龙头，强烈推荐",
            "瑞银\n\n腾讯控股 (0700.HK)：维持买入，目标价上调",
        ]
        for t in tests:
            inst = extract_institution(t)
            rating = extract_rating(t)
            stocks = extract_stocks(t)
            print(f"\n机构: {inst} | 评级: {rating}")
            for s in stocks:
                print(f"  → {s['name']} ({s['full_code']}) [{s['market']}]")
