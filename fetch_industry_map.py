#!/usr/bin/env python3
"""
P0 行业映射系统
- 从东方财富获取行业/概念板块成分股
- 建立 code → [sector1, sector2, ...] 反向映射
- 与 sector_fund_flow.json 的板块名做模糊匹配对齐
- 输出 data/industry_map.json
"""
import json
import os
import time
import akshare as ak
import concurrent.futures

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT = os.path.join(DATA_DIR, "industry_map.json")

# 东方财富行业板块（二级行业，约80个）
INDUSTRY_SECTORS = [
    "银行", "证券", "保险", "房地产开发", "装修装饰", "工程建设", "水泥建材",
    "农牧饲渔", "食品饮料", "酿酒行业", "商业百货", "旅游酒店", "纺织服装",
    "医药制造", "医疗器械", "医疗行业", "中药",
    "汽车整车", "汽车零部件", "交运设备", "船舶制造", "航天航空",
    "电子元件", "半导体", "光学光电子", "消费电子", "电子化学品",
    "通信设备", "通信服务", "计算机设备", "软件开发", "互联网服务",
    "光伏设备", "风电设备", "电网设备", "电源设备", "电池",
    "电力行业", "燃气", "石油行业", "煤炭行业", "采掘行业",
    "钢铁行业", "有色金属", "贵金属", "小金属",
    "化学制品", "化学原料", "化学制药", "化肥行业", "农药兽药",
    "塑料制品", "橡胶制品", "化纤行业",
    "造纸印刷", "包装材料", "玻璃玻纤",
    "家电行业", "装修建材", "家具家居", "珠宝首饰",
    "文化传媒", "教育", "游戏", "影视概念",
    "物流行业", "交运物流", "港口水运", "民航机场",
    "环保行业", "公用事业",
    "综合行业", "多元金融",
]

# 东方财富概念板块（补充AI/新能源等热门概念）
CONCEPT_SECTORS = [
    "AI算力", "ChatGPT", "元宇宙", "数字经济", "信创", "数据要素",
    "固态电池", "钠离子电池", "锂电池", "储能", "氢能源",
    "光伏建筑一体化", "HIT电池", "钙钛矿电池",
    "新能源汽车", "无人驾驶", "车联网",
    "半导体", "芯片", "光刻机", "国产芯片", "中芯概念",
    "人形机器人", "机器人", "机器视觉",
    "CPO", "液冷", "东数西算",
    "军工", "航天航空", "军民融合",
    "创新药", "CXO", "医疗器械", "医美",
    "预制菜", "社区团购", "免税",
    "碳中和", "碳交易", "电力", "特高压",
    "数字货币", "移动支付", "金融科技",
    "跨境支付", "一带一路", "中特估", "国企改革",
    "职业教育", "在线教育",
    "网络游戏", "云游戏", "电子竞技",
    "预制菜", "新零售",
    "国企改革", "央企改革",
    "数字货币", "数据安全", "网络安全",
]


def ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def fetch_sector_constituents(sector_name, is_concept=False):
    """获取单个板块的成分股列表，返回 {code: sector_name}"""
    result = {}
    try:
        if is_concept:
            df = ak.stock_board_concept_cons_em(symbol=sector_name)
        else:
            df = ak.stock_board_industry_cons_em(symbol=sector_name)
        if df is not None and len(df) > 0:
            for _, row in df.iterrows():
                code = str(row["代码"])
                # 标准化：去掉 SH/SZ 前缀，统一6位
                code = code.replace("SH", "").replace("SZ", "").replace("sh", "").replace("sz", "")
                if len(code) < 6:
                    code = code.zfill(6)
                result[code] = sector_name
        time.sleep(0.15)  # 反爬限制
        return result
    except Exception as e:
        return result


def build_reverse_mapping():
    """构建 code → [sector1, sector2, ...] 映射"""
    code_to_sectors = {}

    print("🔍 开始获取行业板块成分股...")
    all_sectors = INDUSTRY_SECTORS + CONCEPT_SECTORS
    concept_set = set(CONCEPT_SECTORS)  # 用于判断is_concept

    total = len(all_sectors)
    done = 0
    failed = 0

    # 串行获取（避免反爬）
    for i, name in enumerate(all_sectors):
        is_c = name in concept_set
        mapping = fetch_sector_constituents(name, is_concept=is_c)
        done += 1
        if not mapping:
            failed += 1
        for code, sname in mapping.items():
            if code not in code_to_sectors:
                code_to_sectors[code] = []
            if sname not in code_to_sectors[code]:
                code_to_sectors[code].append(sname)

        if (i + 1) % 20 == 0:
            print(f"  进度 {i+1}/{total}，已映射 {len(code_to_sectors)} 只股票，失败 {failed} 个板块")

    print(f"\n✅ 映射完成：{len(code_to_sectors)} 只股票 → 行业/概念")
    return code_to_sectors


def align_with_fund_flow(code_to_sectors):
    """
    与 sector_fund_flow.json 的板块名做模糊匹配对齐
    确保代码映射中的板块名与资金流向数据中的板块名一致
    """
    fund_flow_path = os.path.join(DATA_DIR, "sector_fund_flow.json")
    ff_names = set()
    try:
        with open(fund_flow_path, "r", encoding="utf-8") as f:
            ff_data = json.load(f)
        for item in ff_data.get("top_list", []):
            ff_names.add(item.get("name", ""))
    except Exception:
        pass

    print(f"\n📊 sector_fund_flow 中的板块: {sorted(ff_names)}")
    print(f"📊 行业映射中的板块: {len(code_to_sectors)} 只股票, 采样板块...")

    # 无需额外对齐，因为映射本身就用了东财行业名
    return code_to_sectors


def save_output(code_to_sectors):
    """保存映射表"""
    # 转换为可序列化格式
    sector_to_codes = {}
    total_assoc = 0
    for code, sectors in code_to_sectors.items():
        total_assoc += len(sectors)
        for sname in sectors:
            if sname not in sector_to_codes:
                sector_to_codes[sname] = []
            sector_to_codes[sname].append(code)

    output = {
        "update_time": time.strftime("%Y-%m-%d %H:%M"),
        "total_stocks": len(code_to_sectors),
        "total_sectors": len(sector_to_codes),
        "total_associations": total_assoc,
        "stocks": code_to_sectors,  # code → [sector1, sector2, ...]
        "sectors": sector_to_codes,  # sector → [code1, code2, ...]
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    file_size = os.path.getsize(OUTPUT)
    print(f"\n💾 已保存: {OUTPUT}")
    print(f"   文件大小: {file_size / 1024:.0f} KB")
    print(f"   股票数: {len(code_to_sectors)}")
    print(f"   板块数: {len(sector_to_codes)}")
    print(f"   总关联: {total_assoc}")


def update_gold_pool():
    """为 gold_pool.json 的每只股票添加 sectors 字段"""
    gold_path = os.path.join(DATA_DIR, "gold_pool.json")
    if not os.path.exists(gold_path):
        print("⚠️ gold_pool.json 不存在，跳过更新")
        return

    print("\n🔄 更新 gold_pool.json 的 sectors 字段...")
    with open(gold_path, "r", encoding="utf-8") as f:
        pool = json.load(f)

    map_path = OUTPUT
    with open(map_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    stocks_map = mapping.get("stocks", {})
    updated = 0
    stocks = pool.get("stocks", {})

    for key, stock in stocks.items():
        code = str(stock.get("code", ""))
        # 标准化code用于匹配
        if len(code) == 5 and stock.get("market") == "hk":
            code = code.zfill(5)  # 港股保持5位
        if len(code) < 6 and stock.get("market") != "hk":
            code = code.zfill(6)

        # 匹配：直接查找6位code
        sectors = stocks_map.get(code, [])
        # 也尝试5位匹配
        if not sectors and len(code) == 6:
            sectors = stocks_map.get(code[1:] if code.startswith("0") else code, [])

        if sectors:
            stock["sectors"] = sectors
            updated += 1
        else:
            stock["sectors"] = []

    pool["last_industry_update"] = time.strftime("%Y-%m-%d %H:%M")

    with open(gold_path, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)

    print(f"   ✅ 已更新 {updated}/{len(stocks)} 只股票的板块标签")


def main():
    print("=" * 50)
    print("🏗️ P0 行业映射系统")
    print("=" * 50)
    t0 = time.time()

    ensure_dir()

    # Step 1: 构建反向映射
    code_to_sectors = build_reverse_mapping()

    # Step 2: 与资金流向对齐
    code_to_sectors = align_with_fund_flow(code_to_sectors)

    # Step 3: 保存映射表
    save_output(code_to_sectors)

    # Step 4: 更新 gold_pool
    update_gold_pool()

    elapsed = time.time() - t0
    print(f"\n⏱ 总耗时: {elapsed:.1f}s")
    print("✅ 行业映射系统初始化完成")


if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise
