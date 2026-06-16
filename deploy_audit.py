#!/usr/bin/env python3
"""
deploy_audit.py - 四台仪表盘数据健康审计
审计：选股观测台、观澜台、国家队动向台、全球股市/产业链观测台
检查数据完整性、接口可用性、文件生成状态
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path(__file__).parent
DATA_DIR = WORKSPACE / "data"
DIST_DIR = WORKSPACE / "dist"
DIST_DATA_DIR = DIST_DIR / "data"

NOW = time.time()
NOW_DT = datetime.now()

# 阈值（秒）
STALE_24H = 24 * 3600
STALE_48H = 48 * 3600
STALE_72H = 72 * 3600

results = []


def log(level, dashboard, check, message):
    icon = {"OK": "✅", "WARN": "⚠️", "ERROR": "❌", "INFO": "ℹ️"}.get(level, "  ")
    results.append({"level": level, "dashboard": dashboard, "check": check, "message": message})
    print(f"  {icon} [{dashboard}] {check}: {message}")


def file_age_seconds(filepath):
    if not filepath.exists():
        return None
    return NOW - filepath.stat().st_mtime


def file_age_str(filepath):
    age = file_age_seconds(filepath)
    if age is None:
        return "不存在"
    hours = age / 3600
    if hours < 1:
        return f"{int(age/60)}分钟前"
    return f"{hours:.1f}小时前"


def check_file_freshness(filepath, max_age, dashboard, check_name):
    age = file_age_seconds(filepath)
    if age is None:
        log("ERROR", dashboard, check_name, f"文件不存在: {filepath.name}")
        return False
    if age > max_age:
        hours = age / 3600
        log("WARN", dashboard, check_name, f"文件已老化 {hours:.1f}h（阈值 {max_age/3600:.0f}h）")
        return False
    log("OK", dashboard, check_name, f"文件新鲜（{file_age_str(filepath)}）")
    return True


def check_json_valid(filepath, dashboard, check_name):
    if not filepath.exists():
        log("ERROR", dashboard, check_name, f"文件不存在: {filepath.name}")
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        log("OK", dashboard, check_name, "JSON格式有效")
        return data
    except json.JSONDecodeError as e:
        log("ERROR", dashboard, check_name, f"JSON解析失败: {e}")
        return None
    except Exception as e:
        log("ERROR", dashboard, check_name, f"读取失败: {e}")
        return None


def check_json_non_empty(data, dashboard, check_name, key="results"):
    if data is None:
        return
    if isinstance(data, list):
        if len(data) == 0:
            log("WARN", dashboard, check_name, "数据为空数组")
        else:
            log("OK", dashboard, check_name, f"数据条数: {len(data)}")
    elif isinstance(data, dict):
        if key in data:
            val = data[key]
            if isinstance(val, list):
                if len(val) == 0:
                    log("WARN", dashboard, check_name, f"字段'{key}'为空数组")
                else:
                    log("OK", dashboard, check_name, f"字段'{key}'条数: {len(val)}")
            else:
                log("INFO", dashboard, check_name, f"字段'{key}'类型: {type(val).__name__}")
        else:
            log("INFO", dashboard, check_name, f"JSON字段: {list(data.keys())[:10]}")


def check_dist_sync(src_file, dashboard, check_name):
    """检查 data/ 和 dist/data/ 是否同步——仅源文件新鲜时严查"""
    if not src_file.exists():
        return
    dist_file = DIST_DATA_DIR / src_file.name
    if not dist_file.exists():
        log("WARN", dashboard, f"{check_name}(部署)", f"dist/data/ 中缺少 {src_file.name}")
        return
    src_mtime = src_file.stat().st_mtime
    dist_mtime = dist_file.stat().st_mtime
    src_age_h = (NOW - src_mtime) / 3600
    dist_age_h = (NOW - dist_mtime) / 3600
    diff = abs(src_mtime - dist_mtime)
    # 仅当源文件新鲜(<2h)且dist显著落后(>6h)时才警告，减少正常盘中延迟误报
    if src_age_h < 2 and dist_age_h > 6:
        log("WARN", dashboard, f"{check_name}(同步)",
            f"源文件({src_age_h:.1f}h前) 与 部署文件({dist_age_h:.1f}h前) 不同步——可能漏跑 update_data_v2")
    elif diff > 60:
        log("INFO", dashboard, f"{check_name}(同步)",
            f"源文件({src_age_h:.1f}h前) 部署文件({dist_age_h:.1f}h前) — 正常盘中差异")
    else:
        log("OK", dashboard, f"{check_name}(同步)", "源文件与部署文件同步")


def audit_scanner():
    """审计 选股观测台"""
    print("\n" + "="*60)
    print("📊 审计：选股观测台")
    print("="*60)

    # 1. scan_result.json（新格式：无 results 字段，改用 triple_count/double_count 等）
    f = DATA_DIR / "scan_result.json"
    age_ok = check_file_freshness(f, STALE_48H, "选股观测台", "scan_result.json 新鲜度")
    data = check_json_valid(f, "选股观测台", "scan_result.json 格式")
    if data is not None:
        scan_mode = data.get("scan_mode", "N/A")
        total_scanned = data.get("total_scanned", "N/A")
        triple_count = data.get("triple_count", "N/A")
        double_count = data.get("double_count", "N/A")
        total_errors = data.get("total_errors", "N/A")
        if total_scanned == 0 or total_scanned == "N/A":
            log("ERROR", "选股观测台", "scan_result.json 数据",
                f"total_scanned={total_scanned}, 疑似无扫描结果")
        elif total_errors and total_errors > total_scanned * 0.5:
            log("WARN", "选股观测台", "scan_result.json 数据",
                f"扫描{total_scanned}只，错误{total_errors}条，错误率较高")
        else:
            log("OK", "选股观测台", "scan_result.json 数据",
                f"模式={scan_mode}, 扫描{total_scanned}只, 三重{ triple_count}/双重{double_count}, 错误{total_errors}")
    check_dist_sync(f, "选股观测台", "scan_result.json")

    # 2. watch_result.json（新格式：无 results 字段）
    f = DATA_DIR / "watch_result.json"
    check_file_freshness(f, STALE_48H, "选股观测台", "watch_result.json 新鲜度")
    data = check_json_valid(f, "选股观测台", "watch_result.json 格式")
    if data is not None:
        scan_mode = data.get("scan_mode", "N/A")
        total_scanned = data.get("total_scanned", "N/A")
        triple_count = data.get("triple_count", 0)
        double_count = data.get("double_count", 0)
        triple_signals = data.get("triple_signals", [])
        double_signals = data.get("double_signals", [])
        all_results = data.get("all_results", [])
        gold_pool_total = data.get("gold_pool_total", "N/A")
        log("INFO", "选股观测台", "watch_result.json 数据",
            f"模式={scan_mode}, 三重{triple_count}(信号{len(triple_signals)}), "
            f"双重{double_count}(信号{len(double_signals)}), 全部{len(all_results)}只, 池{gold_pool_total}")
        if len(all_results) == 0 and triple_count == 0 and double_count == 0:
            log("WARN", "选股观测台", "watch_result.json 数据", "关注池和信号均为空")
    check_dist_sync(f, "选股观测台", "watch_result.json")

    # 3. stock_names.json
    f = DATA_DIR / "stock_names.json"
    age_ok = check_file_freshness(f, STALE_72H, "选股观测台", "stock_names.json 新鲜度")
    data = check_json_valid(f, "选股观测台", "stock_names.json 格式")
    if data is not None:
        if isinstance(data, list):
            count = len(data)
        elif isinstance(data, dict):
            count = len(data)
        else:
            count = 0
        if count == 0:
            log("WARN", "选股观测台", "stock_names.json 数据", "股票名称库为空")
        else:
            log("OK", "选股观测台", "stock_names.json 数据", f"名称库条数: {count}")
    check_dist_sync(f, "选股观测台", "stock_names.json")

    # 4. signal_backtest.json
    f = DATA_DIR / "signal_backtest.json"
    check_file_freshness(f, STALE_72H, "选股观测台", "signal_backtest.json 新鲜度")
    data = check_json_valid(f, "选股观测台", "signal_backtest.json 格式")
    if data is not None:
        check_json_non_empty(data, "选股观测台", "signal_backtest.json 内容")
    check_dist_sync(f, "选股观测台", "signal_backtest.json")

    # 5. lhb_result.json
    f = DATA_DIR / "lhb_result.json"
    check_file_freshness(f, STALE_48H, "选股观测台", "lhb_result.json 新鲜度")
    data = check_json_valid(f, "选股观测台", "lhb_result.json 格式")
    if data is not None:
        check_json_non_empty(data, "选股观测台", "lhb_result.json 内容")
    check_dist_sync(f, "选股观测台", "lhb_result.json")

    # 6. industry_map.json
    f = DATA_DIR / "industry_map.json"
    check_file_freshness(f, STALE_72H * 7, "选股观测台", "industry_map.json 新鲜度")
    data = check_json_valid(f, "选股观测台", "industry_map.json 格式")
    if data is not None:
        count = len(data) if isinstance(data, dict) else 0
        log("INFO", "选股观测台", "industry_map.json 数据", f"行业映射条数: {count}")
    check_dist_sync(f, "选股观测台", "industry_map.json")

    # 7. scan_progress.json（运行时临时文件，缺失正常，降级为WARN）
    f = DATA_DIR / "scan_progress.json"
    if f.exists():
        check_file_freshness(f, STALE_48H, "选股观测台", "scan_progress.json 新鲜度")
        data = check_json_valid(f, "选股观测台", "scan_progress.json 格式")
        check_dist_sync(f, "选股观测台", "scan_progress.json")
    else:
        log("INFO", "选股观测台", "scan_progress.json", "文件不存在（运行时临时文件，非关键）")

    # 8. dist/index_master.html 是否存在
    idx = DIST_DIR / "index_master.html"
    if idx.exists():
        log("OK", "选股观测台", "部署文件", "index_master.html 存在")
    else:
        log("ERROR", "选股观测台", "部署文件", "index_master.html 不存在！")


def audit_guanlan():
    """审计 观澜台"""
    print("\n" + "="*60)
    print("📡 审计：观澜台")
    print("="*60)

    # 1. guanlan_reports.json
    f = DATA_DIR / "guanlan_reports.json"
    check_file_freshness(f, STALE_48H, "观澜台", "guanlan_reports.json 新鲜度")
    data = check_json_valid(f, "观澜台", "guanlan_reports.json 格式")
    if data is not None:
        count = len(data) if isinstance(data, list) else 0
        if count == 0:
            log("WARN", "观澜台", "guanlan_reports.json 数据", "研报数据为空，可能 guanlan_extractor.py 未运行")
        else:
            log("OK", "观澜台", "guanlan_reports.json 数据", f"研报条数: {count}")
    check_dist_sync(f, "观澜台", "guanlan_reports.json")

    # 2. recommend.json
    f = DATA_DIR / "recommend.json"
    check_file_freshness(f, STALE_48H, "观澜台", "recommend.json 新鲜度")
    data = check_json_valid(f, "观澜台", "recommend.json 格式")
    if data is not None:
        count = len(data) if isinstance(data, list) else 0
        log("INFO", "观澜台", "recommend.json 数据", f"推荐标的数: {count}")
    check_dist_sync(f, "观澜台", "recommend.json")

    # 3. guanlan_watchlist.json
    f = DATA_DIR / "guanlan_watchlist.json"
    check_file_freshness(f, STALE_72H, "观澜台", "guanlan_watchlist.json 新鲜度")
    data = check_json_valid(f, "观澜台", "guanlan_watchlist.json 格式")
    if data is not None:
        count = len(data) if isinstance(data, list) else 0
        log("INFO", "观澜台", "guanlan_watchlist.json 数据", f"关注列表条数: {count}")
        # 检查港股代码前导零
        if isinstance(data, list):
            bad_codes = []
            for item in data:
                code = item.get("code", "")
                if code.startswith("HK."):
                    num = code[3:]
                    if len(num) < 5:
                        bad_codes.append(code)
            if bad_codes:
                log("ERROR", "观澜台", "guanlan_watchlist.json 代码格式",
                    f"发现 {len(bad_codes)} 个港股代码缺前导零: {bad_codes[:5]}")
            else:
                log("OK", "观澜台", "guanlan_watchlist.json 代码格式", "港股代码前导零正常")
    check_dist_sync(f, "观澜台", "guanlan_watchlist.json")

    # 4. 检查 guanlan_extractor.py 是否存在
    extractor = WORKSPACE / "guanlan_extractor.py"
    if extractor.exists():
        log("OK", "观澜台", "脚本检查", "guanlan_extractor.py 存在")
    else:
        log("ERROR", "观澜台", "脚本检查", "guanlan_extractor.py 不存在！")


def audit_national_team():
    """审计 国家队动向台"""
    print("\n" + "="*60)
    print("🏛️ 审计：国家队动向台")
    print("="*60)

    # 1. nt_data.json
    f = DATA_DIR / "nt_data.json"
    check_file_freshness(f, STALE_48H, "国家队动向台", "nt_data.json 新鲜度")
    data = check_json_valid(f, "国家队动向台", "nt_data.json 格式")
    if data is not None:
        if isinstance(data, dict):
            keys = list(data.keys())
            log("INFO", "国家队动向台", "nt_data.json 字段", f"字段: {keys}")
            # 检查是否包含沪深港通字段
            expected_fields = ["north_bound", "hk_holdings", "sh_holdings"]
            missing = [f for f in expected_fields if f not in data]
            if missing:
                log("INFO", "国家队动向台", "nt_data.json 字段完整性",
                    f"缺少字段: {missing}（数据源可能不支持）")
            else:
                log("OK", "国家队动向台", "nt_data.json 字段完整性", "沪深港通字段完整")
        elif isinstance(data, list):
            log("INFO", "国家队动向台", "nt_data.json 数据", f"数据条数: {len(data)}")
    check_dist_sync(f, "国家队动向台", "nt_data.json")

    # 2. 检查 fetch_nt_data.py 是否存在
    fetcher = WORKSPACE / "fetch_nt_data.py"
    if fetcher.exists():
        log("OK", "国家队动向台", "脚本检查", "fetch_nt_data.py 存在")
    else:
        log("ERROR", "国家队动向台", "脚本检查", "fetch_nt_data.py 不存在！")


def audit_global_market():
    """审计 全球股市/产业链观测台"""
    print("\n" + "="*60)
    print("🌍 审计：全球股市/产业链观测台")
    print("="*60)

    # 1. triple_resonance_history.json
    f = DATA_DIR / "triple_resonance_history.json"
    check_file_freshness(f, STALE_48H, "全球股市台", "triple_resonance_history.json 新鲜度")
    data = check_json_valid(f, "全球股市台", "triple_resonance_history.json 格式")
    if data is not None:
        count = len(data) if isinstance(data, list) else 0
        log("INFO", "全球股市台", "triple_resonance_history.json 数据", f"历史记录条数: {count}")
    check_dist_sync(f, "全球股市台", "triple_resonance_history.json")

    # 2. industry_map.json（与选股观测台共用）
    f = DATA_DIR / "industry_map.json"
    check_file_freshness(f, STALE_72H * 7, "全球股市台", "industry_map.json 新鲜度")
    check_dist_sync(f, "全球股市台", "industry_map.json")

    # 3. resonance_history.json
    f = DATA_DIR / "resonance_history.json"
    if f.exists():
        check_file_freshness(f, STALE_48H, "全球股市台", "resonance_history.json 新鲜度")
        data = check_json_valid(f, "全球股市台", "resonance_history.json 格式")
        if data is not None:
            check_json_non_empty(data, "全球股市台", "resonance_history.json 内容")
        check_dist_sync(f, "全球股市台", "resonance_history.json")
    else:
        log("INFO", "全球股市台", "resonance_history.json", "文件不存在（可选）")

    # 4. 检查 dist/ 下是否有 triple_resonance 相关 HTML
    html_files = list(DIST_DIR.glob("triple_resonance*.html"))
    if html_files:
        for hf in html_files:
            log("OK", "全球股市台", "部署文件", f"{hf.name} 存在")
    else:
        log("WARN", "全球股市台", "部署文件", "未找到 triple_resonance*.html")

    # 5. update_triple_resonance_daily.py
    updater = WORKSPACE / "update_triple_resonance_daily.py"
    if updater.exists():
        log("OK", "全球股市台", "脚本检查", "update_triple_resonance_daily.py 存在")
    else:
        log("WARN", "全球股市台", "脚本检查", "update_triple_resonance_daily.py 不存在")


def audit_dist_data_completeness():
    """审计 dist/data/ 文件完整性"""
    print("\n" + "="*60)
    print("📦 审计：dist/data/ 部署文件完整性")
    print("="*60)

    if not DIST_DATA_DIR.exists():
        log("ERROR", "部署", "dist/data目录", "dist/data/ 目录不存在！")
        return

    data_files = [f for f in DATA_DIR.glob("*.json")
                  if f.name not in ("audit_summary.json", "signal_log.json")
                  and "冲突" not in f.name]  # 排除审计自身文件、调试日志、git冲突文件
    dist_data_files = list(DIST_DATA_DIR.glob("*.json"))

    log("INFO", "部署", "文件统计",
        f"data/ JSON文件: {len(data_files)} 个, dist/data/ JSON文件: {len(dist_data_files)} 个")

    # 检查 data/ 中有但 dist/data/ 中没有的文件
    data_names = {f.name for f in data_files}
    dist_names = {f.name for f in dist_data_files}
    missing_in_dist = data_names - dist_names
    if missing_in_dist:
        for name in sorted(missing_in_dist):
            log("WARN", "部署", "dist/data完整性", f"data/ 有但 dist/data/ 缺少: {name}")
    else:
        log("OK", "部署", "dist/data完整性", "所有 data/*.json 已部署到 dist/data/")


def print_summary():
    """打印审计摘要"""
    print("\n" + "="*60)
    print("📋 审计摘要")
    print("="*60)

    errors = [r for r in results if r["level"] == "ERROR"]
    warns = [r for r in results if r["level"] == "WARN"]
    oks = [r for r in results if r["level"] == "OK"]

    print(f"  ✅ 正常: {len(oks)} 项")
    print(f"  ⚠️  警告: {len(warns)} 项")
    print(f"  ❌ 错误: {len(errors)} 项")
    print()

    if errors:
        print("  ❌ 错误详情：")
        for r in errors:
            print(f"    - [{r['dashboard']}] {r['check']}: {r['message']}")
        print()

    if warns:
        print("  ⚠️  警告详情：")
        for r in warns:
            print(f"    - [{r['dashboard']}] {r['check']}: {r['message']}")
        print()

    if not errors and not warns:
        print("  🎉 所有检查通过，数据健康！")
        print()

    # 输出机器可读的摘要（供自动化读取）
    summary = {
        "timestamp": NOW_DT.isoformat(),
        "errors": len(errors),
        "warnings": len(warns),
        "ok": len(oks),
        "details": {
            "errors": [{"dashboard": r["dashboard"], "check": r["check"], "message": r["message"]} for r in errors],
            "warnings": [{"dashboard": r["dashboard"], "check": r["check"], "message": r["message"]} for r in warns],
        }
    }

    summary_path = WORKSPACE / "data" / "audit_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"  审计摘要已保存至: {summary_path}")


if __name__ == "__main__":
    print("="*60)
    print(f"  🔍 四台仪表盘数据健康审计")
    print(f"  时间: {NOW_DT.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    audit_scanner()
    audit_guanlan()
    audit_national_team()
    audit_global_market()
    audit_dist_data_completeness()
    print_summary()
