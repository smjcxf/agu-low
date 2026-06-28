#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整流水线集成测试
验证：fetch → 信号计算 → HTML注入 → 输出正确性

测试范围：
1. 数据文件完整性（data/*.json 存在且格式正确）
2. update_data_v2.py 能正确注入数据到 HTML
3. 注入后的 HTML 能通过 JS 语法验证
4. 关键数据块（SCAN_DATA / GOLD_POOL / HERDING_DATA）正确注入
"""
import sys, os, json, tempfile, shutil
sys.path.insert(0, r"E:\workspace\stock-scanner")

# 添加项目根目录到 Python 路径
BASE_DIR = r"E:\workspace\stock-scanner"
DATA_DIR = os.path.join(BASE_DIR, "data")
DIST_DIR = os.path.join(BASE_DIR, "dist")
INDEX_MASTER = os.path.join(BASE_DIR, "index_master.html")
INDEX_HTML = os.path.join(DIST_DIR, "index.html")

def test_data_files_exist():
    """测试1：关键数据文件存在"""
    print("\n📋 测试1：关键数据文件存在性")
    critical_files = [
        "scan_result.json",
        "gold_pool.json",
        "watch_result.json",
        "lhb_result.json",
        "sector_fund_flow.json",
        "north_fund.json",
        "main_stock.json",
    ]
    
    missing = []
    for fname in critical_files:
        fpath = os.path.join(DATA_DIR, fname)
        if not os.path.exists(fpath):
            missing.append(fname)
            print(f"  ❌ {fname}: 不存在")
        else:
            # 检查文件是否为有效的 JSON
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    json.load(f)
                print(f"  ✅ {fname}: 存在且格式正确")
            except json.JSONDecodeError as e:
                missing.append(fname)
                print(f"  ❌ {fname}: JSON格式错误: {e}")
    
    if missing:
        print(f"\n  ⚠️  {len(missing)} 个关键文件缺失或格式错误")
        return False
    else:
        print(f"\n  ✅ 所有关键数据文件存在且格式正确")
        return True

def test_update_data_v2():
    """测试2：update_data_v2.py 能正确运行"""
    print("\n🔄 测试2：update_data_v2.py --fast 运行")
    
    if not os.path.exists(INDEX_MASTER):
        print(f"  ❌ 母版文件不存在: {INDEX_MASTER}")
        return False
    
    # 备份原始的 dist/index.html（如果存在）
    backup_path = None
    if os.path.exists(INDEX_HTML):
        backup_path = INDEX_HTML + ".bak"
        shutil.copy2(INDEX_HTML, backup_path)
        print(f"  ℹ️  已备份原始 index.html")
    
    try:
        # 运行 update_data_v2.py --fast
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "update_data_v2.py"), "--fast"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            cwd=BASE_DIR
        )
        
        print(f"  返回码: {result.returncode}")
        if result.stdout:
            # 只显示最后10行
            lines = result.stdout.strip().split("\n")
            for line in lines[-10:]:
                print(f"    {line}")
        
        if result.returncode != 0:
            print(f"  ❌ update_data_v2.py 运行失败")
            if result.stderr:
                print(f"  错误: {result.stderr[:500]}")
            return False
        
        # 检查输出文件是否存在
        if not os.path.exists(INDEX_HTML):
            print(f"  ❌ 输出文件不存在: {INDEX_HTML}")
            return False
        
        print(f"  ✅ update_data_v2.py 运行成功")
        return True
        
    finally:
        # 恢复备份
        if backup_path and os.path.exists(backup_path):
            shutil.move(backup_path, INDEX_HTML)
            print(f"  ℹ️  已恢复原始 index.html")

def test_html_injection():
    """测试3：HTML 中关键数据块正确注入"""
    print("\n🔍 测试3：HTML 数据注入正确性")
    
    if not os.path.exists(INDEX_HTML):
        print(f"  ❌ index.html 不存在，请先运行测试2")
        return False
    
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 检查关键数据块是否存在
    markers = [
        "window.SCAN_DATA = ",
        "window.GOLD_POOL = ",
        "window.WATCH_DATA = ",
        "window.HERRING_DATA = ",
        "window.MAIN_STOCK_DATA = ",
    ]
    
    all_ok = True
    for marker in markers:
        if marker in content:
            # 尝试提取并解析 JSON
            start = content.find(marker)
            if start >= 0:
                # 找到分号结束位置
                end = content.find(";", start)
                if end > start:
                    json_str = content[start + len(marker):end].strip()
                    try:
                        json.loads(json_str)
                        print(f"  ✅ {marker.strip(' =')} : JSON格式正确")
                    except json.JSONDecodeError as e:
                        print(f"  ❌ {marker.strip(' =')} : JSON格式错误: {e}")
                        all_ok = False
                else:
                    print(f"  ❌ {marker.strip(' =')} : 找不到 JSON 结束位置")
                    all_ok = False
        else:
            print(f"  ❌ {marker.strip(' =')} : 数据块不存在")
            all_ok = False
    
    return all_ok

def test_js_syntax():
    """测试4：注入后的 HTML 能通过 JS 语法验证"""
    print("\n✅ 测试4：JS 语法验证")
    
    if not os.path.exists(INDEX_HTML):
        print(f"  ❌ index.html 不存在")
        return False
    
    # 导入 update_data_v2.py 的验证函数
    try:
        sys.path.insert(0, BASE_DIR)
        import importlib
        import update_data_v2 as ud
        importlib.reload(ud)
        
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 运行验证
        verify_out = ud.verify_data(content)
        print(f"  {verify_out}")
        
        if "ERR" in verify_out or "NOT FOUND" in verify_out:
            print(f"  ❌ JS 语法验证失败")
            return False
        
        print(f"  ✅ JS 语法验证通过")
        return True
        
    except Exception as e:
        print(f"  ❌ 验证过程异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """运行所有集成测试"""
    print("=" * 60)
    print("完整流水线集成测试")
    print("=" * 60)
    
    results = []
    
    # 测试1：数据文件存在性
    r1 = test_data_files_exist()
    results.append(("数据文件存在性", r1))
    
    if not r1:
        print("\n⚠️  数据文件缺失，跳过后续测试")
        print("\n" + "=" * 60)
        print("测试结果汇总:")
        for name, result in results:
            print(f"  {'✅' if result else '❌'} {name}")
        print("=" * 60)
        return
    
    # 测试2：update_data_v2.py 运行
    r2 = test_update_data_v2()
    results.append(("update_data_v2.py 运行", r2))
    
    if r2:
        # 测试3：HTML 数据注入
        r3 = test_html_injection()
        results.append(("HTML 数据注入", r3))
        
        # 测试4：JS 语法验证
        r4 = test_js_syntax()
        results.append(("JS 语法验证", r4))
    
    # 输出结果汇总
    print("\n" + "=" * 60)
    print("测试结果汇总:")
    for name, result in results:
        print(f"  {'✅' if result else '❌'} {name}")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"\n总计: {passed}/{total} 通过")
    print("=" * 60)

if __name__ == "__main__":
    main()
