#!/usr/bin/env python3
"""
sync_check.py — 部署前双机同步检查 + 坚果云冲突清理
确保两台电脑都使用最新代码，防止旧版覆盖新版

用法：
  python sync_check.py          # 检查并同步
  python sync_check.py --force  # 强制 git pull（忽略本地冲突）

集成：在 batch_update.py 所有 deploy 步骤之前调用
"""

import os
import sys
import subprocess
import glob
import json
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# ─────────── 关键代码标记（不匹配 = 旧版） ───────────
SAFETY_MARKERS = {
    "index_master.html": [
        "typeof CLOSED_SET !== 'undefined'",  # CLOSED_SET 防御检查
    ],
    "fetch_sector_fund_flow.py": [
        "neodata流入+流出完整",              # neodata 双查询修复
        "流入TOP10",
        "流出TOP10",
    ],
    "generate_triple_resonance_history.py": [
        "scan_result] 刷新:",                # _tracking_latest 价格刷新
    ],
    "update_data_v2.py": [
        "verify_runtime_smoke",              # 运行时冒烟测试
    ],
}

# ─────────── 满意版 index_master.html MD5 锁定 ───────────
# 坚果云同步可能覆盖满意版 → 部署前校验 MD5，不匹配则阻断并回退
INDEX_MASTER_MD5 = "37fbe6ff63cecbcf6a4972a7a442e783"  # 满意版 MD5
INDEX_MASTER_MD5_FILE = os.path.join(PROJECT_ROOT, ".index_master_md5_lock")


def run(cmd, cwd=None):
    """执行命令并返回 CompletedProcess"""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=cwd or PROJECT_ROOT)


def clean_conflict_files():
    """清理坚果云冲突残余文件"""
    patterns = [
        os.path.join(PROJECT_ROOT, "**", "*冲突*"),
        os.path.join(PROJECT_ROOT, "**", "*conflict*"),
    ]
    cleaned = 0
    for pattern in patterns:
        for f in glob.glob(pattern, recursive=True):
            try:
                os.remove(f)
                print(f"  🧹 清理冲突文件: {os.path.relpath(f, PROJECT_ROOT)}")
                cleaned += 1
            except Exception as e:
                print(f"  ⚠️ 清理失败: {f} ({e})")
    if cleaned:
        print(f"  ✅ 清理了 {cleaned} 个冲突文件")


def check_version_markers():
    """检查关键代码是否包含最新版本的标记"""
    all_ok = True
    for fname, markers in SAFETY_MARKERS.items():
        fpath = os.path.join(PROJECT_ROOT, fname)
        if not os.path.exists(fpath):
            print(f"  ⚠️ {fname} 不存在，跳过检查")
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        missing = [m for m in markers if m not in content]
        if missing:
            all_ok = False
            print(f"  ❌ {fname} 缺少关键代码标记: {missing}")
            print(f"     该文件可能是旧版！坚果云同步可能未完成！")
        else:
            print(f"  ✓ {fname} 版本标记通过")
    return all_ok


def git_sync(force=False):
    """从 GitHub 强制同步最新代码"""
    print("  🔄 从 GitHub 同步最新代码...")
    
    # 先检查是否有未合并文件（合并冲突状态），有则重置
    r_status = run("git status --porcelain")
    if r_status.returncode == 0:
        unmerged = [l for l in r_status.stdout.split('\n') if l[:2] in ('UU', 'AA', 'DD', 'AU', 'UA', 'DU', 'UD')]
        if unmerged:
            print(f"  ⚠️ 检测到未合并文件（合并冲突），执行 git reset --hard origin/main")
            r_reset = run("git reset --hard origin/main")
            if r_reset.returncode != 0:
                print(f"  ❌ git reset --hard 失败: {r_reset.stderr.strip()[:200]}")
                return False
            print(f"  ✓ 已重置到 origin/main，冲突已清理")
            # 重置后直接 pull
            r = run("git pull --rebase origin main")
            if r.returncode != 0:
                err = r.stderr.strip()[:200] if r.stderr else r.stdout.strip()[:200]
                print(f"  ❌ git pull 失败: {err}")
                return False
            print(f"  ✓ 代码已同步")
            return True
    
    # 先 stash 本地修改
    r = run("git stash -u -m 'sync-check-stash'")
    stashed = r.returncode == 0 and "No local changes" not in r.stdout
    
    # git pull
    r = run("git pull --rebase origin main")
    if r.returncode != 0:
        err = r.stderr.strip()[:200] if r.stderr else r.stdout.strip()[:200]
        print(f"  ❌ git pull 失败: {err}")
        if not force:
            if stashed:
                run("git stash pop")
            return False
        print(f"  ⚠️ --force 模式，继续执行")
    
    # 恢复 stash
    if stashed:
        r_pop = run("git stash pop")
        if r_pop.returncode != 0:
            print(f"  ⚠️ git stash pop 有冲突，可能需手动处理")
    
    print(f"  ✓ 代码已同步")
    return True


def check_nutstore_lag():
    """检查坚果云同步延迟：比较本地文件修改时间和 git HEAD 时间"""
    key_files = ["index_master.html", "update_data_v2.py", "deploy_now.py"]
    issues = []
    
    for fname in key_files:
        fpath = os.path.join(PROJECT_ROOT, fname)
        if not os.path.exists(fpath):
            continue
        
        # 本地文件修改时间
        local_mtime = os.path.getmtime(fpath)
        
        # git HEAD 版本时间
        try:
            r = run(f'git log -1 --format="%at" -- {fname}')
            git_mtime = int(r.stdout.strip()) if r.stdout.strip() else 0
        except:
            git_mtime = 0
        
        lag_seconds = local_mtime - git_mtime
        if abs(lag_seconds) > 300:  # 超过5分钟差异
            issues.append(f"{fname}: 本地与git HEAD差 {lag_seconds:.0f}秒")
    
    if issues:
        print(f"  ⚠️ 坚果云可能延迟同步: {issues}")
        return False
    else:
        print(f"  ✓ 关键文件时间戳一致")
        return True


def check_index_master_lock():
    """检查 index_master.html 是否被坚果云覆盖为旧版（MD5 锁定）
    
    坚果云同步可能把家里电脑的旧版 index_master.html 覆盖到本地。
    本机存储满意版的 MD5 校验值，每次部署前对比。
    不匹配 → 阻断部署并自动从 Git 回退到满意版。
    """
    fpath = os.path.join(PROJECT_ROOT, "index_master.html")
    if not os.path.exists(fpath):
        print(f"  ❌ index_master.html 不存在！")
        return False
    
    import hashlib
    with open(fpath, "rb") as f:
        actual_md5 = hashlib.md5(f.read()).hexdigest()
    
    # 从锁定文件中读取期望 MD5，没有则使用代码中的常量
    expected_md5 = INDEX_MASTER_MD5
    if os.path.exists(INDEX_MASTER_MD5_FILE):
        with open(INDEX_MASTER_MD5_FILE, "r") as f:
            locked = f.read().strip()
            if locked:
                expected_md5 = locked
    
    if actual_md5 != expected_md5:
        print(f"  🚨 index_master.html 被坚果云覆盖为旧版！")
        print(f"     期望 MD5: {expected_md5[:16]}...")
        print(f"     实际 MD5: {actual_md5[:16]}...")
        print(f"     → 自动执行 git checkout HEAD -- index_master.html 回退")
        r = run("git checkout HEAD -- index_master.html")
        if r.returncode == 0:
            # 重新验证
            with open(fpath, "rb") as f:
                restored_md5 = hashlib.md5(f.read()).hexdigest()
            if restored_md5 == expected_md5:
                print(f"  ✓ 已回退到满意版")
                return True
            else:
                print(f"  ❌ git checkout 回退失败，MD5 仍不匹配，阻断部署")
                return False
        else:
            print(f"  ❌ git checkout 执行失败: {r.stderr.strip()[:200]}")
            return False
    else:
        print(f"  ✓ index_master.html 满意版锁定通过 (MD5: {actual_md5[:16]}...)")
        return True


def update_index_master_lock():
    """更新 index_master.html 的 MD5 锁定值（手动调用，确认当前版本为满意版后执行）"""
    import hashlib
    fpath = os.path.join(PROJECT_ROOT, "index_master.html")
    if not os.path.exists(fpath):
        print(f"  ❌ index_master.html 不存在")
        return False
    with open(fpath, "rb") as f:
        new_md5 = hashlib.md5(f.read()).hexdigest()
    with open(INDEX_MASTER_MD5_FILE, "w") as f:
        f.write(new_md5)
    print(f"  ✓ 已锁定 index_master.html 满意版 MD5: {new_md5[:16]}...")
    return True


def main():
    force = "--force" in sys.argv
    lock_cmd = "--lock" in sys.argv
    
    # 手动锁定当前版本为满意版
    if lock_cmd:
        update_index_master_lock()
        return 0
    
    print(f"\n{'='*55}")
    print(f"🔍 部署前同步检查 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*55}")
    
    # 1. 清理冲突文件
    print("\n[1/5] 清理坚果云冲突文件...")
    clean_conflict_files()
    
    # 2. Git 同步
    print("\n[2/5] Git 同步...")
    sync_ok = git_sync(force=force)
    
    # 3. 版本标记检查
    print("\n[3/5] 版本标记检查...")
    version_ok = check_version_markers()
    
    # 4. 坚果云延迟检查
    print("\n[4/5] 坚果云同步检查...")
    nutstore_ok = check_nutstore_lag()
    
    # 5. 满意版 MD5 锁定检查（最强防线：坚果云覆盖自动回退）
    print("\n[5/5] index_master.html 满意版锁定...")
    master_ok = check_index_master_lock()
    
    # 汇总
    print(f"\n{'='*55}")
    if sync_ok and version_ok and master_ok:
        print(f"✅ 同步检查通过，满意版锁定正常，可以安全部署")
        print(f"{'='*55}\n")
        return 0
    else:
        if not sync_ok:
            print(f"❌ Git 同步失败！请手动 git pull 后重试")
        if not version_ok:
            print(f"❌ 关键代码版本标记不匹配！")
            print(f"   可能原因：坚果云未同步最新代码")
            print(f"   解决方法：1) 等坚果云同步完成 2) 手动 git pull")
        if not master_ok:
            print(f"❌ index_master.html 被覆盖或锁定失败！")
            print(f"   可能原因：坚果云同步了旧版 index_master.html")
            print(f"   解决方法：检查 .nutstoreignore 是否排除 .git/ 目录")
        print(f"{'='*55}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
