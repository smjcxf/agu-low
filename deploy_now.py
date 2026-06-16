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
MAX_WARNINGS = 3

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

    python_exe = r"C:\Users\HH20210606\.workbuddy\binaries\python\versions\3.13.12\python.exe"
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
        python_exe = r"C:\Users\HH20210606\.workbuddy\binaries\python\versions\3.13.12\python.exe"
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


def main():
    log("=== Start Deploy (GitHub Pages) ===")
    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)

    # 0. Sync remote data (two-machine merge)
    sync_remote_data()

    # --force skips audit
    force = "--force" in sys.argv
    if not force:
        if not pre_deploy_audit():
            log("\nERROR deploy aborted: data audit failed")
            log("   Use --force to skip audit if data is confirmed OK")
            return 1
    else:
        log("   WARN --force: skipping pre-deploy audit")

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
    else:
        log("   Cloned, cleaning old files...")
        for item in os.listdir(tmpdir):
            if item == ".git":
                continue
            path = os.path.join(tmpdir, item)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)

    # 1.5 CDN cache busting
    log("1.5. Busting CDN cache...")
    import re
    now_stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    pattern = re.compile(r'<!-- build: \d+ -->')
    for root, dirs, files in os.walk(DIST_DIR):
        for fname in files:
            if fname.endswith('.html'):
                fpath = os.path.join(root, fname)
                with open(fpath, 'r', encoding='utf-8') as f:
                    c = f.read()
                c, n = pattern.subn(f'<!-- build: {now_stamp} -->', c)
                if n > 0:
                    with open(fpath, 'w', encoding='utf-8') as f:
                        f.write(c)
    log(f"   Build stamp: {now_stamp}")

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
    return 0

if __name__ == "__main__":
    sys.exit(main())
