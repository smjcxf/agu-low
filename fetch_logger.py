#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch 脚本统一日志记录器 — 每个 fetch 脚本结束时调用 record_success/record_failure
写入 data/.fetch_log.json，供 verify_data_vs_website.py 读取审计。

用法（在 fetch 脚本末尾）：
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
"""
import json
import os
from datetime import datetime

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", ".fetch_log.json")


def _load_log():
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_log(log_data):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)


def record_success(script_path_or_name):
    """记录 fetch 脚本执行成功"""
    log = _load_log()
    key = _script_key(script_path_or_name)
    entry = log.get(key, {"consecutive_failures": 0})
    entry["last_success"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry["consecutive_failures"] = 0
    entry["last_error"] = None
    log[key] = entry
    _save_log(log)


def record_failure(script_path_or_name, error_msg=""):
    """记录 fetch 脚本执行失败"""
    log = _load_log()
    key = _script_key(script_path_or_name)
    entry = log.get(key, {"consecutive_failures": 0})
    entry["last_failure"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1
    entry["last_error"] = str(error_msg)[:200]
    log[key] = entry
    _save_log(log)


def _script_key(script_path_or_name):
    """从脚本路径提取简短名称"""
    name = os.path.basename(script_path_or_name) if os.path.sep in str(script_path_or_name) else script_path_or_name
    # 去掉 .py 后缀
    if name.endswith(".py"):
        name = name[:-3]
    return name


def get_log():
    """读取当前日志"""
    return _load_log()
