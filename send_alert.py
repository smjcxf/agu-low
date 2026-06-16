#!/usr/bin/env python3
"""心跳告警邮件发送器 - QQ邮箱SMTP"""
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import sys
from datetime import datetime

def send_alert(subject, body):
    """发送告警邮件到 2814546@qq.com"""
    sender = "2814546@qq.com"
    receiver = "2814546@qq.com"
    auth_code = "sceornygysatcaig"
    
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = sender
    msg["To"] = receiver

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15)
        server.login(sender, auth_code)
        server.sendmail(sender, [receiver], msg.as_string())
        server.quit()
        print(f"[{datetime.now()}] 告警已发送: {subject}")
        return True
    except Exception as e:
        print(f"[{datetime.now()}] 发送失败: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        send_alert(sys.argv[1], sys.argv[2])
    else:
        # 自检
        send_alert("九宝量化-自检邮件", "心跳邮件功能正常")
