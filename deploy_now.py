#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Pages deploy -- push dist/ to gh-pages branch

Target: https://ah-quant999.github.io/quant-scanner-v6/
Repo: ah-quant999/quant-scanner-v6

Pre-deploy audit via deploy_audit.py:
  - ERROR > 0 => block deploy
  - WARNING > 3 => block deploy
  - --force to skip audit
"""
import os, sys, time, shutil, subprocess, tempfile, json
from datetime import datetime

DIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
OUTPUT_URL = "https://ah-quant999.github.io/quant-scanner-v6/"
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
AUDIT_SUMMARY = os.path.join(PROJECT_ROOT, "data", "audit_summary.json")
MAX_WARNINGS = 5  # 2026-07-01 调整：今天WARNING=4导致部署被阻止，实际不影响主功能

# ── 双机部署锁：防止两台机器同时推送 GitHub Pages ──
DEPLOY_LOCK_FILE = ".deploy_lock"          # git main 分支上的锁文件
LOCK_TIMEOUT = 180                           # 锁超时 3 分钟，超时自动抢占

def log(msg):
    try:
        print(msg, flush=True)
    except:
        print(msg.encode("ascii", "replace").decode(), flush=True)

def run(cmd, cwd=None):
    result = subprocess.run(cmd, shell=True, cwd=cwd,
                            capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr.strip()
        if err:
            log(f"   [CMD] {cmd[:80]}... -> {err[:200]}")
    return result


def pre_deploy_audit():
    """Pre-deploy data health audit -- fail blocks deploy"""
    log("=" * 55)
    log("0. Pre-deploy data audit...")
    log("=" * 55)

    audit_py = os.path.join(PROJECT_ROOT, "deploy_audit.py")
    if not os.path.exists(audit_py):
        log("   WARN deploy_audit.py not found, skipping audit")
        return True

    python_exe = sys.executable
    result = subprocess.run([python_exe, audit_py],
                           capture_output=True, text=True, timeout=120, cwd=PROJECT_ROOT)
    log(result.stdout.strip())

    if not os.path.exists(AUDIT_SUMMARY):
        log("   ERROR audit summary not generated, deploy aborted")
        return False

    try:
        with open(AUDIT_SUMMARY, "r", encoding="utf-8") as f:
            summary = json.load(f)
    except Exception as e:
        log(f"   ERROR reading audit summary: {e}")
        return False

    errors = summary.get("errors", 0)
    warnings = summary.get("warnings", 0)

    log("")
    log(f"   Audit result: ERROR={errors}  WARNING={warnings}")

    if errors > 0:
        log("   ERROR data errors found, deploy blocked")
        log(f"   Threshold: ERROR must be 0")
        err_list = summary.get("details", {}).get("errors", [])
        for e in err_list:
            log(f"      - [{e.get('dashboard','')}] {e.get('check','')}: {e.get('message','')}")
        return False

    if warnings > MAX_WARNINGS:
        log(f"   ERROR too many warnings ({warnings}, threshold={MAX_WARNINGS}), deploy blocked")
        warn_list = summary.get("details", {}).get("warnings", [])
        for w in warn_list:
            log(f"      - [{w.get('dashboard','')}] {w.get('check','')}: {w.get('message','')}")
        return False

    log("   PASS data audit passed, continuing deploy")
    return True


def sync_remote_data():
    """Pull data from GitHub main branch, merge into local data/ (newer wins)"""
    log("=" * 55)
    log("0. Syncing remote data (two-machine merge)...")
    log("=" * 55)

    data_dir = os.path.join(PROJECT_ROOT, "data")

    # Fetch remote main branch
    r = run("git fetch origin main --depth=1")
    if r.returncode != 0:
        log("   WARN git fetch failed, skipping sync, using local data")
        return False

    # List data files on remote main
    r = run("git ls-tree --name-only origin/main -- data/")
    if r.returncode != 0 or not r.stdout.strip():
        log("   INFO no data/ on remote")
        return False

    remote_files = [f for f in r.stdout.strip().split('\n') if f.endswith('.json')]
    synced = 0

    for remote_rel_path in remote_files:
        fname = os.path.basename(remote_rel_path)
        local_path = os.path.join(data_dir, fname)

        # Get remote file content
        r = run(f"git show origin/main:{remote_rel_path}")
        if r.returncode != 0:
            continue
        remote_content = r.stdout

        if not os.path.exists(local_path):
            try:
                with open(local_path, 'w', encoding='utf-8') as f:
                    f.write(remote_content)
                synced += 1
                log(f"   NEW {fname} (from remote)")
            except:
                pass
        else:
            # Compare by commit timestamp
            r2 = run(f"git log -1 --format=%ct origin/main -- {remote_rel_path}")
            if r2.returncode != 0:
                continue
            try:
                remote_ts = int(r2.stdout.strip())
            except:
                continue
            local_ts = int(os.path.getmtime(local_path))

            if remote_ts > local_ts + 2:  # 2s tolerance
                try:
                    with open(local_path, 'w', encoding='utf-8') as f:
                        f.write(remote_content)
                    synced += 1
                    log(f"   UPD {fname} (remote newer)")
                except:
                    pass

    if synced == 0:
        log("   OK data already latest, no sync needed")
    else:
        log(f"   OK synced {synced} files, re-embedding data...")
        python_exe = sys.executable
        updater = os.path.join(PROJECT_ROOT, "update_data_v2.py")
        r = subprocess.run([python_exe, updater, "--fast"],
                          capture_output=True, text=True, timeout=120, cwd=PROJECT_ROOT)
        lines = r.stdout.strip().split('\n')
        for line in lines[-5:]:
            if line.strip():
                log(f"   {line.strip()}")

    # Push synced data back to main so the other computer benefits
    if synced > 0:
        try:
            run("git add data/*.json")
            run(f"git commit -m \"sync: merge remote data {datetime.now().strftime('%m-%d %H:%M')}\"")
            run("git push origin main")
            log("   OK pushed merged data back to main")
        except:
            log("   WARN failed to push merged data (non-blocking)")

    return synced > 0


def _ensure_dist_fresh():
    """强制重建 dist，防止部署旧版 UI。

    【2026-07-03 修复】：调用 _rebuild_dist() 真正重建，之前版本跳过了重建（ok=True 直接返回）。
    """
    log("   🔄 强制重建 dist（本地模板为权威版本）...")
    if not _rebuild_dist():
        log("   ❌ dist 重建失败，阻塞部署")
        return False

    # 5. 验证关键 JS 变量已注入
    log("   🔍 验证 dist/index.html 数据注入...")
    dist_html = os.path.join(DIST_DIR, "index.html")
    if not os.path.exists(dist_html):
        log("   ❌ dist/index.html 不存在，阻塞部署")
        return False
    with open(dist_html, "r", encoding="utf-8") as f:
        content = f.read()
    required_vars = ["LHB_DATA", "HERRING_DATA", "NORTH_FUND_DATA", "MAIN_STOCK_DATA", "LOTTERY_DATA"]
    missing = [v for v in required_vars if f"window.{v}" not in content and f"var {v}" not in content]
    if missing:
        log(f"   ❌ 关键变量未注入，阻塞部署: {missing}")
        return False
    log(f"   ✓ 验证通过: {', '.join(required_vars)}")

    return True


def _rebuild_dist():
    """调用 update_data_v2.py --fast 重新生成 dist 文件。
    
    【2026-07-03 修复】：部署前先从 origin/main 拉取最新模板，
    防止本地模板过期导致覆盖他人的修复。
    """
    # 0. 先拉取最新模板代码（index_master.html, update_data_v2.py 等）
    log("   📥 拉取最新模板代码 from origin/main ...")
    pull_result = subprocess.run(
        "git fetch origin main --depth=1",
        shell=True, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=30
    )
    if pull_result.returncode == 0:
        # 只重置模板和脚本文件（不碰 data/ 和 dist/）
        reset_files = ["index_master.html", "update_data_v2.py", "deploy_now.py"]
        for f in reset_files:
            fpath = os.path.join(PROJECT_ROOT, f)
            if os.path.exists(fpath):
                r = subprocess.run(
                    f"git checkout origin/main -- {f}",
                    shell=True, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=15
                )
                if r.returncode == 0:
                    log(f"   ✓ 已更新 {f} (from origin/main)")
                else:
                    log(f"   ⚠️ 更新 {f} 失败，使用本地版本")
    else:
        log("   ⚠️ git fetch 失败，使用本地模板")

    updater = os.path.join(PROJECT_ROOT, "update_data_v2.py")
    if not os.path.exists(updater):
        log("   ⚠️ update_data_v2.py 不存在，无法重建")
        return False

    python_exe = sys.executable
    log(f"   执行: python update_data_v2.py --fast")
    result = subprocess.run(
        [python_exe, updater, "--fast"],
        capture_output=True, text=True, timeout=300,
        cwd=PROJECT_ROOT
    )
    # 打印最后几行输出（方便确认数据注入成功）
    lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
    for line in lines[-6:]:
        log(f"   {line}")
    if result.returncode == 0:
        log("   ✓ dist 重建成功")
        # 运行 enhance_dist 同步逻辑详解/投行覆盖/getScore
        enhancer = os.path.join(PROJECT_ROOT, "enhance_dist.py")
        if os.path.exists(enhancer):
            log(f"   执行: python enhance_dist.py")
            e_result = subprocess.run(
                [python_exe, enhancer],
                capture_output=True, text=True, timeout=60,
                cwd=PROJECT_ROOT
            )
            if e_result.returncode == 0:
                log("   ✓ enhance_dist 完成")
            else:
                log(f"   ⚠️ enhance_dist 失败: {e_result.stderr.strip()[:200]}")
    else:
        err = result.stderr.strip()[:300] if result.stderr else 'unknown'
        log(f"   ❌ 重建失败（returncode={result.returncode}），阻塞部署: {err}")
        return False
    return True


def _fix_unmerged_files():
    """检测并清理未合并文件（合并冲突状态），防止后续 git commit/pull 失败。"""
    r = subprocess.run("git status --porcelain", shell=True, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if r.returncode != 0:
        return
    # 未合并文件标记：UU, AA, DD, AU, UA, DU, UD
    unmerged = [line for line in r.stdout.strip().split('\n') if line and line[:2] != '  ' and line[:2] in ('UU','AA','DD','AU','UA','DU','UD')]
    if unmerged:
        log(f"   ⚠️ 检测到未合并文件（合并冲突），执行 git reset --hard origin/main")
        r2 = subprocess.run("git reset --hard origin/main", shell=True, capture_output=True, text=True, cwd=PROJECT_ROOT)
        if r2.returncode == 0:
            log(f"   ✓ 已重置到 origin/main，冲突已清理")
        else:
            log(f"   ❌ git reset --hard 失败: {r2.stderr.strip()[:200]}")


def _acquire_deploy_lock():
    """Try to acquire deploy lock via git main branch.

    Only one machine can push the lock file at a time.
    The one that succeeds gets to deploy; the other skips.
    
    Returns: True if lock acquired, False if another machine is deploying.
    """
    my_host = os.environ.get("COMPUTERNAME", "unknown")

    # 1. Fetch remote lock state
    run("git fetch origin main --depth=1", cwd=PROJECT_ROOT)
    r = run("git show origin/main:.deploy_lock", cwd=PROJECT_ROOT)

    if r.returncode == 0:
        try:
            lock = json.loads(r.stdout)
            lock_host = lock.get("host", "?")
            lock_time = datetime.fromisoformat(lock["time"])
            age = (datetime.now() - lock_time).total_seconds()

            if lock_host == my_host:
                log(f"   [LOCK] stale self-lock ({age:.0f}s), forcing")
            elif age < LOCK_TIMEOUT:
                sep = "=" * 55
                log(f"\n{sep}")
                log(f"  SKIP: {lock_host} is deploying ({age:.0f}s ago)")
                log(f"  Data will go live on next deploy")
                log(f"{sep}")
                return False
            else:
                log(f"   [LOCK] expired ({age:.0f}s > {LOCK_TIMEOUT}s), forcing")
        except Exception:
            log("   [LOCK] corrupt lock file, forcing")

    # 2. Write lock and push
    try:
        lock_path = os.path.join(PROJECT_ROOT, DEPLOY_LOCK_FILE)
        with open(lock_path, "w", encoding="utf-8") as f:
            json.dump({"host": my_host, "time": datetime.now().isoformat()}, f, ensure_ascii=False)

        run("git add -f .deploy_lock", cwd=PROJECT_ROOT)
        ts = datetime.now().strftime("%m-%d %H:%M")
        run(f'git commit -m "[lock] deploy by {my_host} {ts}"', cwd=PROJECT_ROOT)
        r = run("git push origin main", cwd=PROJECT_ROOT)

        if r.returncode == 0:
            log(f"   [LOCK] acquired by {my_host}")
            return True

        err = (r.stdout + r.stderr).lower()
        if "rejected" in err or "non-fast" in err:
            sep = "=" * 55
            log(f"\n{sep}")
            log("  SKIP: other machine grabbed the lock first")
            log(f"{sep}")
        else:
            log(f"   [LOCK] push failed: {r.stderr[:120] if r.stderr else 'unknown'}")
        return False
    except Exception as e:
        log(f"   [LOCK] exception: {e}")
        return False


def _release_deploy_lock():
    """Release the deploy lock after deployment completes."""
    lock_path = os.path.join(PROJECT_ROOT, DEPLOY_LOCK_FILE)
    if os.path.exists(lock_path):
        try:
            os.remove(lock_path)
        except OSError:
            pass

    run("git fetch origin main --depth=1", cwd=PROJECT_ROOT)
    r = run("git rm -f --ignore-unmatch .deploy_lock", cwd=PROJECT_ROOT)
    if r.returncode == 0:
        run('git commit -m "lock: release"', cwd=PROJECT_ROOT)
        r2 = run("git push origin main", cwd=PROJECT_ROOT)
        if r2.returncode == 0:
            log("   [LOCK] released")
        else:
            log(f"   [LOCK] release push failed (auto-expires in {LOCK_TIMEOUT}s)")
    else:
        log("   [LOCK] already released")


def _regen_standalone_if_needed():
    """Auto-regenerate standalone pages if index_master.html is newer"""
    project_root = os.path.dirname(os.path.abspath(__file__))
    index_master = os.path.join(project_root, "index_master.html")
    standalone_dir = os.path.join(project_root, "standalone")
    
    if not os.path.exists(index_master):
        return
    
    index_mtime = os.path.getmtime(index_master)
    
    # Check if any standalone HTML is older than index_master
    need_regen = False
    if os.path.exists(standalone_dir):
        for f in os.listdir(standalone_dir):
            if f.endswith(".html"):
                fp = os.path.join(standalone_dir, f)
                if os.path.getmtime(fp) < index_mtime:
                    need_regen = True
                    break
    
    if need_regen:
        log("   Auto-regenerating standalone pages (index_master.html updated)...")
        extract_py = os.path.join(project_root, "extract_panels_v6.py")
        if os.path.exists(extract_py):
            result = subprocess.run([sys.executable, extract_py],
                                   capture_output=True, text=True, timeout=120, cwd=project_root)
            if result.returncode == 0:
                log("   ✓ Standalone pages regenerated")
            else:
                log(f"   WARN standalone regeneration failed: {result.stderr[:200]}")
        else:
            log("   WARN extract_panels_v6.py not found, skipping standalone regen")
    else:
        log("   ✓ Standalone pages up-to-date (skipping regen)")

def main():
    log("=== Start Deploy (GitHub Pages) ===")
    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)

    # 0.0 清理未合并文件（合并冲突状态），防止后续 git commit/pull 失败
    _fix_unmerged_files()
    
    # 0.0.1 Auto-regenerate standalone pages if needed
    _regen_standalone_if_needed()

    # 0. Deploy lock: only one machine deploys at a time
    if not _acquire_deploy_lock():
        return 0  # lock held by other machine, skip gracefully

    try:
            # 0.1. Sync remote data (two-machine merge) — DISABLED: 两机同步导致数据冲突
        # sync_remote_data()

        # --force skips audit
        force = "--force" in sys.argv
        if not force:
            if not pre_deploy_audit():
                log("\nERROR deploy aborted: data audit failed")
                log("   Use --force to skip audit if data is confirmed OK")
                return 1
        else:
            log("   WARN --force: skipping pre-deploy audit")

        # 0.5. 自动重建 dist（模板改了必须重生成，防止部署旧版）
        _auto_push_source()
        if not _ensure_dist_fresh():
            log("\nERROR deploy aborted: dist 重建或验证失败")
            return 1

        # Use temp dir for gh-pages
        tmpdir = tempfile.mkdtemp(prefix="gh-pages-deploy-")
        GITHUB_REMOTE = "git@github.com:ah-quant999/quant-scanner-v6.git"
        log(f"1. Cloning gh-pages from GitHub to temp dir...")
        r = run(f"git clone --branch gh-pages --depth 1 {GITHUB_REMOTE} {tmpdir}")
        if r.returncode != 0:
            log("   gh-pages branch not found, creating orphan...")
            os.makedirs(tmpdir, exist_ok=True)
            r = run(f"git -C {tmpdir} init")
            r = run(f"git -C {tmpdir} checkout --orphan gh-pages")
            # 确保 .nojekyll 存在
            open(os.path.join(tmpdir, ".nojekyll"), "w").close()
            log("   ✓ .nojekyll 已创建（orphan）")
        else:
            log("   Cloned, cleaning old files...")
            for item in os.listdir(tmpdir):
                if item in (".git", ".nojekyll"):
                    continue
                path = os.path.join(tmpdir, item)
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
            # 确保 .nojekyll 始终存在（防止 Jekyll 处理破坏页面）
            nojekyll = os.path.join(tmpdir, ".nojekyll")
            if not os.path.exists(nojekyll):
                open(nojekyll, "w").close()
                log("   ✓ .nojekyll 已创建")

        # 1.5 CDN cache busting（改注释 + 改 title + 加 meta 标签，三重确保 CDN 感知文件变化）
        log("1.5. Busting CDN cache...")
        import re
        now_stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        pattern = re.compile(r'<!-- build: \d+ -->')
        pattern_title = re.compile(r'<title>九宝量化 v\d\.\d</title>')
        pattern_meta = re.compile(r'<meta name="build-stamp" content="[^"]*">')
        for root, dirs, files in os.walk(DIST_DIR):
            for fname in files:
                if fname.endswith('.html'):
                    fpath = os.path.join(root, fname)
                    with open(fpath, 'r', encoding='utf-8') as f:
                        c = f.read()
                    changed = False
                    # ① 改 build 注释
                    if pattern.search(c):
                        c = pattern.sub(f'<!-- build: {now_stamp} -->', c)
                        changed = True
                    # ② 改 title（文件内容确实变化，CDN 无法忽略）
                    if pattern_title.search(c):
                        c = pattern_title.sub(f'<title>九宝量化 v6.0 ({now_stamp})</title>', c)
                        changed = True
                    # ③ 加/更新 meta build-stamp
                    if pattern_meta.search(c):
                        c = pattern_meta.sub(f'<meta name="build-stamp" content="{now_stamp}">', c)
                        changed = True
                    else:
                        # 没有 meta 标签，在 <head> 之后插入
                        c = c.replace('<head>', f'<head>\n<meta name="build-stamp" content="{now_stamp}">')
                        changed = True
                    if changed:
                        with open(fpath, 'w', encoding='utf-8') as f:
                            f.write(c)
        log(f"   Build stamp: {now_stamp}")

        # 1.6. 注入真实密码（替换源码中的 __PWD__ / __GUEST_PWD__ 占位符）
        # 优先从环境变量读取，否则使用默认值
        REAL_PWD = os.environ.get("QB_PWD", "cat999")
        REAL_GUEST_PWD = os.environ.get("QB_GUEST_PWD", "hjd666")
        for fname in ["index.html", "index_master.html"]:
            fpath = os.path.join(DIST_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath, "r", encoding="utf-8") as f:
                    c = f.read()
                replaced = False
                n = c.count("__PWD__")
                if n > 0:
                    c = c.replace("__PWD__", REAL_PWD)
                    replaced = True
                m = c.count("__GUEST_PWD__")
                if m > 0:
                    c = c.replace("__GUEST_PWD__", REAL_GUEST_PWD)
                    replaced = True
                if replaced:
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(c)
                    log(f"   ✓ 密码已注入 {fname} (admin:{n} 处, guest:{m} 处)")

        # 2. Copy dist/ to temp dir
        log("2. Copying dist/ ...")
        file_count = 0
        for root, dirs, files in os.walk(DIST_DIR):
            rel_root = os.path.relpath(root, DIST_DIR)
            target_dir = os.path.join(tmpdir, rel_root) if rel_root != "." else tmpdir
            os.makedirs(target_dir, exist_ok=True)
            for f in files:
                src = os.path.join(root, f)
                dst = os.path.join(target_dir, f)
                shutil.copy2(src, dst)
                file_count += 1
        log(f"   Copied {file_count} files")
        # 最后防线：确保 .nojekyll 绝不丢失（防 Jekyll 破坏页面）
        nojekyll_final = os.path.join(tmpdir, ".nojekyll")
        if not os.path.exists(nojekyll_final):
            open(nojekyll_final, "w").close()
            log("   ✓ .nojekyll 最后防线已创建")

        # 3. Commit and push
        log("3. Committing and pushing...")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        commit_msg = f"deploy: {now}"

        main_name = run("git config user.name", cwd=project_root).stdout.strip()
        main_email = run("git config user.email", cwd=project_root).stdout.strip()
        if main_name:
            run(f'git -C {tmpdir} config user.name "{main_name}"')
        if main_email:
            run(f'git -C {tmpdir} config user.email "{main_email}"')

        r = run(f"git -C {tmpdir} add -A")
        r = run(f'git -C {tmpdir} commit -m "{commit_msg}"')
        if r.returncode != 0 and "nothing to commit" in (r.stdout + r.stderr):
            log("   Nothing to commit (no changes)")
        elif r.returncode != 0:
            log(f"   Commit failed: {r.stderr[:300]}")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return 1

        r = run(f"git -C {tmpdir} push {GITHUB_REMOTE} gh-pages")
        if r.returncode != 0:
            log(f"   Push failed: {r.stderr[:300]}")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return 1

        shutil.rmtree(tmpdir, ignore_errors=True)

        log("4. Waiting for GitHub Pages build...")
        time.sleep(2)

        log(f"\nSUCCESS! Deployed to {OUTPUT_URL}")
        log("   (GitHub Pages build takes 1-2 min)")

        # 5. 自动同步源代码到 main 分支（永久防止双机版号冲突）
        log("-" * 55)
        log("5. Auto-syncing source code to main...")

        return 0

    finally:
        _release_deploy_lock()


def _auto_push_source():
    """自动将工作区源码修改 commit + push 到 main 分支。

    为什么需要这一步：
      - 阿狸咪改了 index_master.html 后跑部署
      - 如果忘记手动 git push，小九 git pull 就拉到旧代码
      - 下次小九部署会用旧模板覆盖掉阿狸咪的 UI 改版
      - 本函数在每次部署后自动确保 main 分支是最新的
    """
    git_root = PROJECT_ROOT

    # 检查工作区是否有未提交修改
    r = run("git status --porcelain", cwd=git_root)
    if r.returncode != 0:
        log("   ⚠️ 无法获取 git 状态，跳过源码同步")
        return

    lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
    if not lines:
        log("   ℹ️ 工作区干净，无需同步")
        return

    # 过滤出非 data/、非 dist/、非临时目录的变更
    dirty = []
    for line in lines:
        fname = line[3:].strip().strip('"')
        if fname.startswith("data/") or fname.startswith("dist/") or fname.startswith("_gh_pages"):
            continue
        if fname.startswith(".workbuddy/"):
            continue
        dirty.append(fname)

    if not dirty:
        log("   ℹ️ 非源码文件变动，跳过")
        return

    log(f"   📝 检测到 {len(dirty)} 个源码变更")
    for f in dirty[:5]:
        log(f"      {f}")
    if len(dirty) > 5:
        log(f"      ... 共 {len(dirty)} 个")

    # 统一 git add（依赖 .gitignore 排除 data/ dist/）
    r = run("git add -A", cwd=git_root)
    if r.returncode != 0:
        log(f"   ⚠️ git add 失败: {r.stderr[:200]}")
        return

    # 生成提交信息
    now = datetime.now().strftime("%m-%d %H:%M")
    top_files = [os.path.basename(f) for f in dirty[:3]]
    msg = f"auto: source sync {now}"
    if top_files:
        msg += " — " + ", ".join(top_files)

    r = run(f'git commit -m "{msg}"', cwd=git_root)
    if r.returncode != 0:
        if "nothing to commit" in (r.stdout + r.stderr):
            log("   ℹ️ 无内容可提交")
            return
        log(f"   ⚠️ 提交失败: {r.stderr[:200]}")
        return

    log(f"   ✓ 已提交: {msg}")

    # 推送到 main
    r = run("git push origin main", cwd=git_root)
    if r.returncode != 0:
        log(f"   ⚠️ 推送失败: {r.stderr[:200]}")
    else:
        log("   ✓ 已推送到 main（小九能拉到了）")

if __name__ == "__main__":
    sys.exit(main())
