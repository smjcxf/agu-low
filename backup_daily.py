#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日自动备份脚本
用法: python backup_daily.py
备份内容: index_master.html + data/ + *.py 到 backup_YYYYMMDD/
保留策略: 最近 7 天，超期自动清理
"""
import os, shutil, datetime, re

BASE = os.path.dirname(os.path.abspath(__file__))
today = datetime.datetime.now().strftime('%Y%m%d')
backup_dir = os.path.join(BASE, f'backup_{today}')

if os.path.exists(backup_dir):
    shutil.rmtree(backup_dir)
os.makedirs(backup_dir, exist_ok=True)

# 备份文件列表
files = ['index_master.html']
for f in files:
    src = os.path.join(BASE, 'dist', f)
    if os.path.exists(src):
        shutil.copy2(src, backup_dir)

# 备份数据目录
data_src = os.path.join(BASE, 'data')
data_dst = os.path.join(backup_dir, 'data')
if os.path.exists(data_src):
    shutil.copytree(data_src, data_dst)

# 备份脚本
for f in os.listdir(BASE):
    if f.endswith('.py'):
        shutil.copy2(os.path.join(BASE, f), backup_dir)

size = sum(os.path.getsize(os.path.join(dp, f)) for dp, dn, fn in os.walk(backup_dir) for f in fn)
print(f'✅ 备份完成: {backup_dir} ({size/1024/1024:.1f}MB)')

# 清理 7 天前的日备
cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
for item in os.listdir(BASE):
    item_path = os.path.join(BASE, item)
    if not os.path.isdir(item_path):
        continue
    m = re.match(r'backup_(\d{8})$', item)
    if not m:
        continue
    try:
        d = datetime.datetime.strptime(m.group(1), '%Y%m%d')
        if d < cutoff:
            shutil.rmtree(item_path)
            print(f'🗑️  已删除过期日备: {item}')
    except:
        pass
