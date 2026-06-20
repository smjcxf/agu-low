#!/usr/bin/env python3
"""
batch_update.py — 九宝量化统一调度脚本
每个步骤独立超时 → 失败自动重试一次 → 汇总报告

流程：... → update_data_v2 → enhance_dist → deploy → ...
enhance_dist 负责注入 MAHORO_COVERAGE、同步 getScore()、同步逻辑详解页 HTML

用法：
  python batch_update.py pre_market     09:15 盘前（研报+mahoro→全量扫描→增强→部署）
  python batch_update.py morning_scan   09:45 盘中快速扫描
  python batch_update.py morning_plus   10:00/10:30 扫描+三卡刷新（板块/ETF/AI速览）
  python batch_update.py morning_report 11:45 午间（研报+mahoro→扫描→增强→部署）
  python batch_update.py afternoon      13:30/14:30/15:30/16:30 午后
  python batch_update.py close          19:30 收盘全量（研报+mahoro→全量fetch→扫描→增强→部署）
  python batch_update.py backup         21:00 备份
"""

import subprocess
import sys
import time
import os

WORKSPACE = os.path.dirname(os.path.abspath(__file__))

# 查找系统 Python 3.14（避免 managed Python 的 py_mini_racer 崩溃）
def _find_system_python():
    # 尝试 py launcher
    try:
        r = subprocess.run(
            ["py", "-3.14", "-c", "import sys; print(sys.executable)"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            p = r.stdout.strip()
            if p and "workbuddy" not in p.lower():
                return p
    except Exception:
        pass
    # 常见路径兜底
    for c in [
        r"C:\Users\HH20210606\AppData\Local\Programs\Python\Python314\python.exe",
        r"C:\Python314\python.exe",
    ]:
        if os.path.exists(c):
            return c
    return sys.executable   # 找不到就用自己的

SYSTEM_PYTHON = _find_system_python()

# ──────────────────────────────────────────────────────────
# 模式定义：每个步骤 (命令, 超时秒数)
# ──────────────────────────────────────────────────────────
MODES = {
    "pre_market": {
        "desc": "盘前全量 (09:15)",
        "steps": [
            ("guanlan_extractor.py", 300),
            ("fetch_mahoro_signals.py --non-interactive", 120),
            ("scanner.py full", 600),
            ("generate_recommend.py", 120),
            ("update_data_v2.py", 300),
            ("enhance_dist.py", 30),
            ("deploy_now.py --force", 180),
        ],
    },
    "morning_scan": {
        "desc": "盘中快速扫描 (09:45)",
        "steps": [
            ("scanner.py", 300),
            ("update_data_v2.py", 300),
            ("enhance_dist.py", 30),
            ("deploy_now.py --force", 180),
        ],
    },
    "morning_plus": {
        "desc": "盘中扫描+三卡刷新 (10:00/10:30)",
        "steps": [
            ("fetch_sector_fund_flow.py", 120),
            ("fetch_etf_subscription.py", 120),
            ("fetch_market_alerts.py", 120),
            ("fetch_concept_ranking.py", 120),
            ("scanner.py", 300),
            ("update_data_v2.py", 300),
            ("enhance_dist.py", 30),
            ("deploy_now.py --force", 180),
        ],
    },
    "morning_report": {
        "desc": "午间研报+扫描 (11:45)",
        "steps": [
            ("guanlan_extractor.py", 300),
            ("fetch_mahoro_signals.py --non-interactive", 120),
            ("scanner.py", 300),
            ("fetch_concept_ranking.py", 180),
            ("fetch_market_alerts.py", 180),
            ("fetch_sector_fund_flow.py", 180),
            ("update_data_v2.py", 300),
            ("enhance_dist.py", 30),
            ("deploy_now.py --force", 180),
        ],
    },
    "afternoon": {
        "desc": "午后扫描 (13:30/14:30/16:30)",
        "steps": [
            ("scanner.py", 300),
            ("fetch_concept_ranking.py", 180),
            ("fetch_market_alerts.py", 180),
            ("fetch_sector_fund_flow.py", 180),
            ("fetch_herding_data.py", 180),
            ("update_data_v2.py", 300),
            ("enhance_dist.py", 30),
            ("deploy_now.py --force", 180),
        ],
    },
    "close": {
        "desc": "收盘后全量 (19:30)",
        "steps": [
            ("guanlan_extractor.py", 300),
            ("fetch_mahoro_signals.py --non-interactive", 120),
            ("fetch_nt_data.py", 120),
            ("fetch_margin.py", 120),
            ("fetch_margin_etf.py", 120),
            ("fetch_etf_subscription.py", 120),
            ("fetch_sh_index_fib.py", 60),
            ("fetch_sh_sz_history.py", 120),
            ("fetch_sector_fund_flow.py", 180),
            ("fetch_main_week.py", 120),
            ("fetch_market_alerts.py", 180),
            ("fetch_concept_ranking.py", 180),
            ("fetch_lhb.py", 300),
            ("fetch_main_stock.py", 300),
            ("fetch_north_fund.py", 300),
            ("fetch_herding_data.py", 180),
            ("scanner.py full", 600),
            ("generate_recommend.py", 120),
            ("update_triple_resonance_daily.py", 120),
            ("update_data_v2.py", 300),
            ("enhance_dist.py", 30),
            ("deploy_now.py", 180),
            ("push_notify.py", 120),
        ],
    },
    "backup": {
        "desc": "自动备份 (21:00)",
        "steps": [
            ("backup_daily.py", 300),
        ],
    },
}


def run_step(command, timeout):
    """Run a single step with subprocess timeout.
    Returns (ok, elapsed, detail).
    """
    start = time.time()
    parts = command.split()
    # scanner.py 必须用系统 Python 3.14（managed Python 的 py_mini_racer 会崩溃）
    exe = SYSTEM_PYTHON if parts[0] == "scanner.py" else sys.executable
    try:
        proc = subprocess.run(
            [exe] + parts,
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start
        ok = proc.returncode == 0
        detail = ""
        if not ok:
            detail = f"exit={proc.returncode}"
            if proc.stderr:
                tail = proc.stderr.strip()[-150:]
                if tail:
                    detail += " | " + tail
        return ok, elapsed, detail
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return False, elapsed, "TIMEOUT"
    except FileNotFoundError:
        elapsed = time.time() - start
        return False, elapsed, "NOT_FOUND"
    except Exception as e:
        elapsed = time.time() - start
        return False, elapsed, str(e)[:150]


def _sync_dual_machine_code(workspace):
    """双机代码同步：阿狸咪↔小九，每次任务执行前拉取对方最新版本。
    
    流程：
      1. git add + commit（确保本地数据改动不丢失）
      2. git pull --autostash（自动暂存未提交改动，拉取对端）
      3. git push（把本地上次的数据改动推回去通知对端）
    """
    print("  [0/1] 🔄 双机代码同步...", end="", flush=True)
    start = time.time()

    # 1. 暂存本地所有变更（包括 data/ 中的新数据）
    r1 = subprocess.run(
        "git add -A",
        shell=True, cwd=workspace, capture_output=True, text=True, timeout=30
    )
    # 轻量 commit，有真正改动才创建
    r2 = subprocess.run(
        "git commit -m 'auto: pre-sync data' --allow-empty",
        shell=True, cwd=workspace, capture_output=True, text=True, timeout=30
    )

    # 2. 拉取对端最新代码（自动 stash 未提交改动）
    r3 = subprocess.run(
        "git pull --autostash --no-rebase origin main",
        shell=True, cwd=workspace, capture_output=True, text=True, timeout=120
    )
    pull_ok = r3.returncode == 0

    if pull_ok:
        # 3. 推回，让对端下次也能拉到我们的改动
        subprocess.run(
            "git push origin main",
            shell=True, cwd=workspace, capture_output=True, timeout=60
        )
        elapsed = time.time() - start
        print(f"✓  {elapsed:.1f}s")
    else:
        # pull 冲突/失败：用本地版继续，不阻塞流程
        err = r3.stderr.strip()[-150:] if r3.stderr else "未知错误"
        print(f"⚠  ({err[:80]})")
        print(f"    继续使用本地代码，不影响本次执行")

    # 恢复 stash（如果有未跟踪文件也被 stash 了）
    subprocess.run(
        "git stash pop", shell=True, cwd=workspace,
        capture_output=True, timeout=30
    )


def print_header(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}  —  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}\n")


def print_summary(results, still_failed):
    total = len(results)
    ok_count = sum(1 for _, ok, _, _ in results if ok)
    fail_count = total - ok_count
    print(f"\n{'=' * 60}")
    print(f"  总计: {total}  成功: {ok_count}  失败: {fail_count}")
    if not still_failed:
        print(f"  ✓ 全部通过")
    else:
        print(f"  ✗ 以下步骤重试后仍未通过:")
        for name in still_failed:
            print(f"    - {name}")
    print(f"{'=' * 60}\n")
    return 0 if not still_failed else 1


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print("batch_update.py — 九宝量化统一调度脚本")
        print("\n可用模式:")
        for k, v in MODES.items():
            print(f"  {k:<18s} {v['desc']}")
        print("\n用法: python batch_update.py <模式>")
        return

    mode = sys.argv[1]
    if mode not in MODES:
        print(f"✗ 未知模式: {mode}")
        print(f"  可用: {', '.join(MODES.keys())}")
        sys.exit(2)

    cfg = MODES[mode]
    print_header(f"📊 {cfg['desc']}")

    # ── Step 0: 双机代码同步（阿狸咪 ↔ 小九互相识别对方最新版） ──
    _sync_dual_machine_code(WORKSPACE)

    results = []
    failed_indices = []

    # ── Phase 1: 首轮执行 ──
    for i, (cmd, tmo) in enumerate(cfg["steps"]):
        label = f"[{i + 1}/{len(cfg['steps'])}]"
        print(f"  {label} {cmd:<35s} ", end="", flush=True)
        ok, elapsed, detail = run_step(cmd, tmo)
        results.append((cmd, ok, elapsed, detail))

        icon = "✓" if ok else "✗"
        extra = f"  {detail}" if detail else ""
        print(f"{icon}  {elapsed:.1f}s{extra}")

        if not ok:
            failed_indices.append(i)

    # ── Phase 2: 失败步骤重试（仅一次） ──
    still_failed = []
    if failed_indices:
        print(f"\n  ── 重试 {len(failed_indices)} 个失败步骤 ──")
        for idx in failed_indices:
            cmd, tmo = cfg["steps"][idx]
            label = "[R]"
            print(f"  {label} {cmd:<35s} ", end="", flush=True)
            ok, elapsed, detail = run_step(cmd, tmo)
            results[idx] = (cmd, ok, elapsed, detail)

            icon = "✓" if ok else "✗"
            extra = f"  {detail}" if detail else ""
            print(f"{icon}  {elapsed:.1f}s{extra}")

            if not ok:
                still_failed.append(cmd)

        if still_failed:
            names = ", ".join(still_failed)
            print(f"\n  ⚠ 重试后仍然超时/失败: {names}")

    exit_code = print_summary(results, still_failed)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
