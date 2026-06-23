#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据新鲜度检查 + NeoData 故障邮件告警
检查所有数据文件的 update_time，超48小时无更新的发送邮件告警
用法: python check_data_freshness.py [--email]
"""
import os, sys, json, datetime, smtplib
from email.mime.text import MIMEText
from email.header import Header

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# ===== 邮件配置 =====
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
SMTP_USER = "2814546@qq.com"          # 发件人
SMTP_TO = "2814546@qq.com"            # 收件人
# QQ邮箱授权码 — 在QQ邮箱设置→账户→POP3/SMTP服务中生成
# 请替换为实际授权码，或通过环境变量 QQ_SMTP_PASS 传入
SMTP_PASS = os.environ.get("QQ_SMTP_PASS", "")

# 数据文件 → 显示名称 映射
DATA_SOURCES = {
    "scan_result.json":       ("全量扫描", "🔴"),
    "gold_pool.json":         ("金股池", "⭐"),
    "lhb_result.json":        ("龙虎榜", "🐉"),
    "herding_data.json":      ("资金抱团预判", "🔥"),
    "main_stock.json":        ("主力个股动向", "💪"),
    "macro_data.json":        ("宏观数据", "🌍"),
    "margin_data.json":       ("两融数据", "📊"),
    "etf_subscription.json":  ("ETF份额", "💰"),
    "sector_fund_flow.json":  ("板块资金流向", "🚀"),
    "concept_ranking.json":   ("概念涨跌榜", "📈"),
    "market_alerts.json":     ("市场异动", "⚡"),
    "cffex_holdings.json":    ("中信期货持仓", "📊"),
    "inst_trade.json":        ("机构买卖统计", "🏦"),
    "fomc_summary.json":      ("FOMC速览", "🏛️"),
    "north_fund.json":        ("北向资金", "🌏"),
}


def load_update_time(filename):
    """从数据文件中提取 update_time"""
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return open(path, "r", encoding="utf-8").read()[:200], None
    ts = data.get("update_time") or data.get("scan_time") or ""
    # 也检查 data 嵌套字段
    if not ts and "data" in data:
        ts = data["data"].get("update_time", "")
    return ts, os.path.getmtime(path)


def check_all():
    """检查所有数据源的新鲜度"""
    now = datetime.datetime.now()
    print("=" * 55)
    print(f"  数据新鲜度检查 — {now.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)

    stale_sources = []  # 超过48小时
    warn_sources = []   # 超过24小时但不到48小时
    ok_count = 0

    for filename, (label, icon) in DATA_SOURCES.items():
        ts, file_mtime = load_update_time(filename)
        if not ts:
            if file_mtime:
                # 文件存在但无update_time字段
                file_dt = datetime.datetime.fromtimestamp(file_mtime)
                diff = now - file_dt
                hours = diff.total_seconds() / 3600
                status = f"⚠️ 无时间戳 | 文件{diff.days}天前"
                if hours > 48:
                    stale_sources.append((label, icon, status))
                else:
                    warn_sources.append((label, icon, status))
                print(f"  {icon} {label:12s}  {status}")
            else:
                print(f"  {icon} {label:12s}  ❌ 文件缺失")
                stale_sources.append((label, icon, "文件缺失"))
            continue

        try:
            dt = datetime.datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        except:
            try:
                dt = datetime.datetime.strptime(ts[:16], "%Y-%m-%d %H:%M")
            except:
                print(f"  {icon} {label:12s}  ❓ 无法解析: {ts[:30]}")
                continue

        diff = now - dt
        hours = diff.total_seconds() / 3600
        days = diff.days

        if hours > 48:
            stale_sources.append((label, icon, f"{days}天前 ({ts[:16]})"))
            print(f"  {icon} {label:12s}  ❌ {days}天前  ({ts[:16]})")
        elif hours > 24:
            warn_sources.append((label, icon, f"{int(hours)}小时前 ({ts[:16]})"))
            print(f"  {icon} {label:12s}  ⚠️ {int(hours)}小时前 ({ts[:16]})")
        else:
            ok_count += 1
            ago = f"{int(hours)}小时前" if hours >= 1 else f"{int(hours*60)}分钟前"
            print(f"  {icon} {label:12s}  ✅ {ago}")

    print(f"\n  结果: {ok_count} 正常 | {len(warn_sources)} 预警 | {len(stale_sources)} 过期")
    return stale_sources, warn_sources


def send_email(stale_sources, warn_sources):
    """发送告警邮件"""
    if not stale_sources and not warn_sources:
        print("\n  所有数据正常，无需发送告警")
        return True

    if not SMTP_PASS:
        print("\n  ⚠️ SMTP密码未配置，跳过邮件发送")
        print("  请设置环境变量 QQ_SMTP_PASS=你的QQ邮箱授权码")
        print("  (QQ邮箱 → 设置 → 账户 → POP3/SMTP服务 → 生成授权码)")
        return False

    now = datetime.datetime.now().strftime("%m-%d %H:%M")
    subject = f"🔴 九宝量化数据告警 - {now}"

    body_lines = ["【九宝量化 v6.0 数据新鲜度告警】\n"]
    if stale_sources:
        body_lines.append("❌ 超过48小时未更新（紧急）:")
        for label, icon, detail in stale_sources:
            body_lines.append(f"  {icon} {label}: {detail}")
    if warn_sources:
        body_lines.append("\n⚠️ 超过24小时未更新（预警）:")
        for label, icon, detail in warn_sources:
            body_lines.append(f"  {icon} {label}: {detail}")

    body_lines.append(f"\n---\n自动发送 | {now}")
    body = "\n".join(body_lines)

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = SMTP_USER
        msg["To"] = SMTP_TO

        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [SMTP_TO], msg.as_string())
        server.quit()
        print(f"\n  ✅ 告警邮件已发送至 {SMTP_TO}")
        return True
    except Exception as e:
        print(f"\n  ❌ 邮件发送失败: {e}")
        return False


if __name__ == "__main__":
    stale, warn = check_all()
    if "--email" in sys.argv:
        send_email(stale, warn)
