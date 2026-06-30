#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026世界杯数据抓取 — 从 thesoccerworldcups.com 获取比赛结果
输出: data/worldcup.json
用法: python fetch_worldcup.py        # 全量更新
     python fetch_worldcup.py --auto  # 自动模式（仅更新新结果）
"""
import json, os, sys, re
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DATA_FILE = os.path.join(DATA_DIR, "worldcup.json")

# ===== 小组阵容（固定数据） =====
TEAMS = {
    'A': ['墨西哥','韩国','捷克','南非'],
    'B': ['加拿大','瑞士','波黑','卡塔尔'],
    'C': ['巴西','摩洛哥','苏格兰','海地'],
    'D': ['美国','澳大利亚','巴拉圭','土耳其'],
    'E': ['德国','科特迪瓦','厄瓜多尔','库拉索'],
    'F': ['荷兰','日本','瑞典','突尼斯'],
    'G': ['埃及','比利时','伊朗','新西兰'],
    'H': ['西班牙','佛得角','乌拉圭','沙特'],
    'I': ['法国','挪威','塞内加尔','伊拉克'],
    'J': ['阿根廷','奥地利','约旦','阿尔及利亚'],
    'K': ['哥伦比亚','葡萄牙','刚果金','乌兹别克'],
    'L': ['英格兰','加纳','巴拿马','克罗地亚'],
}

# 球队→大洲映射
REGION_MAP = {
    '墨西哥':'CONCACAF','韩国':'AFC','捷克':'UEFA','南非':'CAF',
    '加拿大':'CONCACAF','瑞士':'UEFA','波黑':'UEFA','卡塔尔':'AFC',
    '巴西':'CONMEBOL','摩洛哥':'CAF','苏格兰':'UEFA','海地':'CONCACAF',
    '美国':'CONCACAF','澳大利亚':'AFC','巴拉圭':'CONMEBOL','土耳其':'UEFA',
    '德国':'UEFA','科特迪瓦':'CAF','厄瓜多尔':'CONMEBOL','库拉索':'CONCACAF',
    '荷兰':'UEFA','日本':'AFC','瑞典':'UEFA','突尼斯':'CAF',
    '埃及':'CAF','比利时':'UEFA','伊朗':'AFC','新西兰':'OFC',
    '西班牙':'UEFA','佛得角':'CAF','乌拉圭':'CONMEBOL','沙特':'AFC',
    '法国':'UEFA','挪威':'UEFA','塞内加尔':'CAF','伊拉克':'AFC',
    '阿根廷':'CONMEBOL','奥地利':'UEFA','约旦':'AFC','阿尔及利亚':'CAF',
    '哥伦比亚':'CONMEBOL','葡萄牙':'UEFA','刚果金':'CAF','乌兹别克':'AFC',
    '英格兰':'UEFA','加纳':'CAF','巴拿马':'CONCACAF','克罗地亚':'UEFA',
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def fetch_results():
    """从 thesoccerworldcups.com 抓取完赛结果"""
    import requests
    url = 'https://www.thesoccerworldcups.com/world_cups/2026_results.php'
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        r.encoding = 'utf-8'
        text = r.text
    except Exception as e:
        log(f"  抓取失败: {e}")
        return []
    
    results = []
    
    # 按日期分割
    dates = re.split(r'Date: \*\*(.*?)\*\*', text)
    
    i = 1
    while i < len(dates) - 1:
        date_str = dates[i].strip()  # "Jun 11, 2026"
        content = dates[i + 1]
        
        # 解析每场比赛: "Mexico" ... [2 - 0] ... "South Africa"
        # 模式：球队名 → [score] → 球队名，且后面有Group标记
        matches = re.findall(
            r'([A-Z][a-zA-Z\s]+?)\s*\n?\s*\[(\d+\s*-\s*\d+)\]\s*(?:\n|.*?)\n?\s*([A-Z][a-zA-Z\s]+?)(?:\n|\s*\[)',
            content
        )
        
        if not matches:
            # Try alternative pattern
            matches = re.findall(
                r'\[(\d+\s*-\s*\d+)\].*?\n?\s*\n?\s*\[1st Round, Group (\w)\]',
                content
            )
            # Extract team names separately
            team_pattern = re.findall(r'(?:^|\n)([A-Z][a-zA-Z\s]+?)\s*\n\s*\[', content)
        
        # Simpler approach: find score blocks
        score_blocks = re.findall(
            r'\[1st Round, Group (\w)\].*?\n\s*([A-Za-z\s]+)\s*\n\s*\[(\d+)\s*-\s*(\d+)\]',
            content
        )
        
        for group, home_str, hg_str, ag_str in score_blocks:
            hg = int(hg_str)
            ag = int(ag_str)
            # Find away team - next non-empty text after score
            home = home_str.strip()
            # The away team follows the score
            away_match = re.search(r'\[%d\s*-\s*%d\]\s*\n\s*([A-Za-z\s]+)' % (hg, ag), content)
            away = away_match.group(1).strip() if away_match else 'Unknown'
            
            results.append({
                'date': date_str,
                'group': group,
                'home': home,
                'away': away,
                'home_goals': hg,
                'away_goals': ag,
                'score': f'{hg}-{ag}'
            })
        
        i += 2
    
    return results


def build_knockout_schedule(standings, results):
    """
    2026世界杯淘汰赛赛程 — 硬编码真实对阵数据。
    数据源：Yahoo Sports / Olympics.com
    32强于2026.06.28-07.03进行，16强于07.04开始。
    比分按实际比赛结果逐步更新。
    
    Returns: list of dict with date, round, home, away, score, venue
    """
    # 32强真实对阵（16场），含已完赛比分
    r32_real = [
        # Jun 28 — 已完成
        {'date':'Jun 28','home':'南非','away':'加拿大','score':'0-1','venue':'洛杉矶 · Los Angeles Stadium'},
        # Jun 29 — 已完成
        {'date':'Jun 29','home':'巴西','away':'日本','score':'2-1','venue':'休斯敦 · NRG Stadium'},
        {'date':'Jun 29','home':'德国','away':'巴拉圭','score':'1-1 (3-4p)','venue':'波士顿 · Gillette Stadium'},
        {'date':'Jun 29','home':'摩洛哥','away':'荷兰','score':'1-1 (3-2p)','venue':'蒙特雷 · Estadio BBVA'},
        # Jun 30 — 待进行
        {'date':'Jun 30','home':'科特迪瓦','away':'挪威','score':'','venue':'阿灵顿 · AT&T Stadium', 'home_raw':'象牙海岸'},
        {'date':'Jun 30','home':'法国','away':'瑞典','score':'','venue':'东卢瑟福 · MetLife Stadium'},
        {'date':'Jun 30','home':'墨西哥','away':'厄瓜多尔','score':'','venue':'墨西哥城 · Estadio Azteca'},
        # Jul 1
        {'date':'Jul 1','home':'英格兰','away':'刚果民主共和国','score':'','venue':'亚特兰大 · Mercedes-Benz Stadium'},
        {'date':'Jul 1','home':'比利时','away':'塞内加尔','score':'','venue':'西雅图 · Lumen Field'},
        {'date':'Jul 1','home':'美国','away':'波黑','score':'','venue':'圣克拉拉 · Levi\'s Stadium'},
        # Jul 2
        {'date':'Jul 2','home':'西班牙','away':'奥地利','score':'','venue':'英格尔伍德 · SoFi Stadium'},
        {'date':'Jul 2','home':'葡萄牙','away':'克罗地亚','score':'','venue':'多伦多 · BMO Field'},
        {'date':'Jul 2','home':'瑞士','away':'阿尔及利亚','score':'','venue':'温哥华 · BC Place'},
        # Jul 3
        {'date':'Jul 3','home':'澳大利亚','away':'埃及','score':'','venue':'阿灵顿 · AT&T Stadium'},
        {'date':'Jul 3','home':'阿根廷','away':'佛得角','score':'','venue':'迈阿密 · Hard Rock Stadium'},
        {'date':'Jul 3','home':'哥伦比亚','away':'加纳','score':'','venue':'堪萨斯城 · Arrowhead Stadium'},
    ]
    for m in r32_real:
        m['round'] = '32强'
        m['home_seed'] = 0
        m['away_seed'] = 0
    
    # 16强及后续轮次（球队待定，日期和场馆按真实赛程显示）
    upcoming_template = [
        # 16强：7/4 - 7/5（8场）
        ('Jul 4', '16强', '费城 · Lincoln Financial Field'),
        ('Jul 4', '16强', '休斯敦 · NRG Stadium'),
        ('Jul 4', '16强', '洛杉矶 · Los Angeles Stadium'),
        ('Jul 4', '16强', '温哥华 · BC Place'),
        ('Jul 5', '16强', '纽约/新泽西 · MetLife Stadium'),
        ('Jul 5', '16强', '迈阿密 · Hard Rock Stadium'),
        ('Jul 5', '16强', '达拉斯 · AT&T Stadium'),
        ('Jul 5', '16强', '墨西哥城 · Estadio Azteca'),
        # 1/4决赛：7/9 - 7/10（4场）
        ('Jul 9', '1/4决赛', '亚特兰大 · Mercedes-Benz Stadium'),
        ('Jul 9', '1/4决赛', '波士顿 · Gillette Stadium'),
        ('Jul 10', '1/4决赛', '达拉斯 · AT&T Stadium'),
        ('Jul 10', '1/4决赛', '洛杉矶 · SoFi Stadium'),
        # 半决赛：7/13 - 7/14（2场）
        ('Jul 13', '半决赛', '达拉斯 · AT&T Stadium'),
        ('Jul 14', '半决赛', '洛杉矶 · SoFi Stadium'),
        # 决赛周
        ('Jul 18', '三四名决赛', '迈阿密 · Hard Rock Stadium'),
        ('Jul 19', '决赛', '纽约/新泽西 · MetLife Stadium'),
    ]
    
    knockout = r32_real[:]
    for date, round_name, venue in upcoming_template:
        knockout.append({
            'date': date,
            'round': round_name,
            'home': '待定',
            'away': '待定',
            'score': '',
            'venue': venue,
            'home_seed': 0,
            'away_seed': 0,
        })
    
    return knockout


def build_standings(results):
    """根据比赛结果计算小组积分"""
    standings = {}
    for g in TEAMS:
        standings[g] = {t: {'w': 0, 'd': 0, 'l': 0, 'gf': 0, 'ga': 0} for t in TEAMS[g]}
    
    for r in results:
        if 'group' not in r: continue
        g = r['group']
        home = r['home']
        away = r['away']
        hg = r['home_goals']
        ag = r['away_goals']
        
        if g not in standings: continue
        if home not in standings[g]: continue
        if away not in standings[g]: continue
        
        standings[g][home]['gf'] += hg
        standings[g][home]['ga'] += ag
        standings[g][away]['gf'] += ag
        standings[g][away]['ga'] += hg
        
        if hg > ag:
            standings[g][home]['w'] += 1
            standings[g][away]['l'] += 1
        elif hg < ag:
            standings[g][home]['l'] += 1
            standings[g][away]['w'] += 1
        else:
            standings[g][home]['d'] += 1
            standings[g][away]['d'] += 1
    
    return standings


def team_strength(team_data):
    """根据进球/失球率计算球队强度分数"""
    gp = team_data['w'] + team_data['d'] + team_data['l'] or 1
    return (team_data['gf'] - team_data['ga']) / gp


def simulate_group_qualification(standings):
    """Monte Carlo 模拟：每组前2名晋级概率"""
    import random
    ITER = 5000
    qual_probs = {}

    # 已打完的比赛
    played = set()
    for g_id, tlist in TEAMS.items():
        for r in ALL_RESULTS:
            if r.get('group') != g_id: continue
            h, a = r['home'], r['away']
            played.add((g_id, h, a))

    for _ in range(ITER):
        for g_id in TEAMS:
            sim = {}
            for t_name in TEAMS[g_id]:
                s = standings[g_id].get(t_name, {'w':0,'d':0,'l':0,'gf':0,'ga':0})
                sim[t_name] = {'w': s['w'], 'd': s['d'], 'l': s['l'],
                               'gf': s['gf'], 'ga': s['ga'],
                               'pts': s['w']*3 + s['d']}

            teams = TEAMS[g_id]
            for a_idx in range(4):
                for b_idx in range(a_idx+1, 4):
                    h, a = teams[a_idx], teams[b_idx]
                    if (g_id, h, a) in played or (g_id, a, h) in played:
                        continue
                    sh = team_strength(sim[h])
                    sa = team_strength(sim[a])
                    diff = sh - sa
                    home_exp = max(0.3, 1.3 + diff*0.5 + random.gauss(0, 0.4))
                    away_exp = max(0.3, 1.3 - diff*0.5 + random.gauss(0, 0.4))
                    hg = max(0, round(home_exp + random.gauss(0, 0.8)))
                    ag = max(0, round(away_exp + random.gauss(0, 0.8)))
                    sim[h]['gf'] += hg; sim[h]['ga'] += ag
                    sim[a]['gf'] += ag; sim[a]['ga'] += hg
                    if hg > ag:
                        sim[h]['w'] += 1; sim[h]['pts'] += 3; sim[a]['l'] += 1
                    elif hg < ag:
                        sim[h]['l'] += 1; sim[a]['w'] += 1; sim[a]['pts'] += 3
                    else:
                        sim[h]['d'] += 1; sim[h]['pts'] += 1
                        sim[a]['d'] += 1; sim[a]['pts'] += 1

            ranked = sorted(sim.items(),
                key=lambda x: (x[1]['pts'], x[1]['gf']-x[1]['ga'], x[1]['gf']), reverse=True)
            if g_id not in qual_probs:
                qual_probs[g_id] = {t: 0.0 for t in TEAMS[g_id]}
            for i, (name, _) in enumerate(ranked):
                if i < 2:
                    qual_probs[g_id][name] += 1

    result = {}
    for g_id in TEAMS:
        result[g_id] = {}
        for t_name in TEAMS[g_id]:
            result[g_id][t_name] = round(qual_probs[g_id][t_name] / ITER * 100, 1)
    return result


def calculate_adj_efficiency(all_teams, standings):
    """加权净胜球效率：进球含金量×对手积分系数"""
    adj_data = {}
    for t in all_teams:
        adj_data[t['name']] = {
            'adj_gf': t['gf'], 'adj_ga': t['ga'],
            'raw_gf': t['gf'], 'raw_ga': t['ga'],
            'opponent_strength': 0.0
        }

    for r in ALL_RESULTS:
        if 'group' not in r: continue
        g_id = r['group']
        h, a = r['home'], r['away']
        if h not in adj_data or a not in adj_data: continue

        h_opp = standings[g_id].get(a, {}).get('w',0)*3 + standings[g_id].get(a, {}).get('d',0)
        a_opp = standings[g_id].get(h, {}).get('w',0)*3 + standings[g_id].get(h, {}).get('d',0)

        # 对手越强，进球权重越高
        w_h = 1 + h_opp/15.0
        w_a = 1 + a_opp/15.0

        adj_data[h]['adj_gf'] = round(adj_data[h]['adj_gf'] + r['home_goals']*(w_h-1), 1)
        adj_data[h]['adj_ga'] = round(adj_data[h]['adj_ga'] + r['away_goals']*(1 - h_opp/25.0), 1)
        adj_data[a]['adj_gf'] = round(adj_data[a]['adj_gf'] + r['away_goals']*(w_a-1), 1)
        adj_data[a]['adj_ga'] = round(adj_data[a]['adj_ga'] + r['home_goals']*(1 - a_opp/25.0), 1)

        adj_data[h]['opponent_strength'] = round(adj_data[h]['opponent_strength'] + h_opp, 1)
        adj_data[a]['opponent_strength'] = round(adj_data[a]['opponent_strength'] + a_opp, 1)

    return adj_data


# ===== 已完成的所有比赛结果（截至2026-06-24，小组赛全部结束） =====
# 【2026-06-26注】6月25-27日为休息日，无比赛。32强淘汰赛6月28日开始。
ALL_RESULTS = [
    # Jun 11
    {'date':'Jun 11','group':'A','home':'墨西哥','away':'南非','home_goals':2,'away_goals':0},
    {'date':'Jun 11','group':'A','home':'韩国','away':'捷克','home_goals':2,'away_goals':1},
    # Jun 12
    {'date':'Jun 12','group':'B','home':'加拿大','away':'波黑','home_goals':1,'away_goals':1},
    {'date':'Jun 12','group':'D','home':'美国','away':'巴拉圭','home_goals':4,'away_goals':1},
    # Jun 13
    {'date':'Jun 13','group':'C','home':'巴西','away':'摩洛哥','home_goals':1,'away_goals':1},
    {'date':'Jun 13','group':'D','home':'澳大利亚','away':'土耳其','home_goals':2,'away_goals':0},
    {'date':'Jun 13','group':'C','home':'海地','away':'苏格兰','home_goals':0,'away_goals':1},
    {'date':'Jun 13','group':'B','home':'卡塔尔','away':'瑞士','home_goals':1,'away_goals':1},
    # Jun 14
    {'date':'Jun 14','group':'E','home':'德国','away':'库拉索','home_goals':7,'away_goals':1},
    {'date':'Jun 14','group':'E','home':'科特迪瓦','away':'厄瓜多尔','home_goals':1,'away_goals':0},
    {'date':'Jun 14','group':'F','home':'荷兰','away':'日本','home_goals':2,'away_goals':2},
    {'date':'Jun 14','group':'F','home':'瑞典','away':'突尼斯','home_goals':5,'away_goals':1},
    # Jun 15
    {'date':'Jun 15','group':'H','home':'西班牙','away':'佛得角','home_goals':0,'away_goals':0},
    {'date':'Jun 15','group':'H','home':'沙特','away':'乌拉圭','home_goals':1,'away_goals':1},
    {'date':'Jun 15','group':'G','home':'比利时','away':'埃及','home_goals':1,'away_goals':1},
    {'date':'Jun 15','group':'G','home':'伊朗','away':'新西兰','home_goals':2,'away_goals':2},
    # Jun 16
    {'date':'Jun 16','group':'I','home':'法国','away':'塞内加尔','home_goals':3,'away_goals':1},
    {'date':'Jun 16','group':'I','home':'伊拉克','away':'挪威','home_goals':1,'away_goals':4},
    {'date':'Jun 16','group':'J','home':'阿根廷','away':'阿尔及利亚','home_goals':3,'away_goals':0},
    {'date':'Jun 16','group':'J','home':'奥地利','away':'约旦','home_goals':3,'away_goals':1},
    # Jun 17
    {'date':'Jun 17','group':'L','home':'英格兰','away':'克罗地亚','home_goals':4,'away_goals':2},
    {'date':'Jun 17','group':'L','home':'加纳','away':'巴拿马','home_goals':1,'away_goals':0},
    {'date':'Jun 17','group':'K','home':'葡萄牙','away':'刚果金','home_goals':1,'away_goals':1},
    {'date':'Jun 17','group':'K','home':'乌兹别克','away':'哥伦比亚','home_goals':1,'away_goals':3},
    # Jun 18
    {'date':'Jun 18','group':'A','home':'捷克','away':'南非','home_goals':1,'away_goals':1},
    {'date':'Jun 18','group':'B','home':'瑞士','away':'波黑','home_goals':4,'away_goals':1},
    {'date':'Jun 18','group':'B','home':'加拿大','away':'卡塔尔','home_goals':6,'away_goals':0},
    {'date':'Jun 18','group':'A','home':'墨西哥','away':'韩国','home_goals':1,'away_goals':0},
    # Jun 19
    {'date':'Jun 19','group':'C','home':'巴西','away':'海地','home_goals':3,'away_goals':0},
    {'date':'Jun 19','group':'C','home':'苏格兰','away':'摩洛哥','home_goals':0,'away_goals':1},
    {'date':'Jun 19','group':'D','home':'土耳其','away':'巴拉圭','home_goals':0,'away_goals':1},
    {'date':'Jun 19','group':'D','home':'美国','away':'澳大利亚','home_goals':2,'away_goals':0},
    # Jun 20
    {'date':'Jun 20','group':'E','home':'德国','away':'科特迪瓦','home_goals':2,'away_goals':1},
    {'date':'Jun 20','group':'E','home':'厄瓜多尔','away':'库拉索','home_goals':0,'away_goals':0},
    {'date':'Jun 20','group':'F','home':'荷兰','away':'瑞典','home_goals':5,'away_goals':1},
    {'date':'Jun 20','group':'F','home':'突尼斯','away':'日本','home_goals':0,'away_goals':4},
    # Jun 21
    {'date':'Jun 21','group':'H','home':'西班牙','away':'沙特','home_goals':4,'away_goals':0},
    {'date':'Jun 21','group':'H','home':'乌拉圭','away':'佛得角','home_goals':2,'away_goals':2},
    {'date':'Jun 21','group':'G','home':'比利时','away':'伊朗','home_goals':0,'away_goals':0},
    {'date':'Jun 21','group':'G','home':'新西兰','away':'埃及','home_goals':1,'away_goals':3},
    # Jun 22
    {'date':'Jun 22','group':'I','home':'法国','away':'伊拉克','home_goals':3,'away_goals':0},
    {'date':'Jun 22','group':'I','home':'挪威','away':'塞内加尔','home_goals':3,'away_goals':2},
    {'date':'Jun 22','group':'J','home':'阿根廷','away':'奥地利','home_goals':2,'away_goals':0},
    {'date':'Jun 22','group':'J','home':'约旦','away':'阿尔及利亚','home_goals':1,'away_goals':2},
    # Jun 23
    {'date':'Jun 23','group':'L','home':'英格兰','away':'加纳','home_goals':0,'away_goals':0},
    {'date':'Jun 23','group':'L','home':'巴拿马','away':'克罗地亚','home_goals':0,'away_goals':1},
    {'date':'Jun 23','group':'K','home':'葡萄牙','away':'乌兹别克','home_goals':5,'away_goals':0},
    {'date':'Jun 23','group':'K','home':'哥伦比亚','away':'刚果金','home_goals':0,'away_goals':0},  # ?
    # Jun 24 — 小组赛第三轮
    {'date':'Jun 24','group':'C','home':'苏格兰','away':'巴西','home_goals':0,'away_goals':3},
    {'date':'Jun 24','group':'C','home':'摩洛哥','away':'海地','home_goals':4,'away_goals':2},
    {'date':'Jun 24','group':'B','home':'瑞士','away':'加拿大','home_goals':2,'away_goals':1},
    {'date':'Jun 24','group':'B','home':'波黑','away':'卡塔尔','home_goals':3,'away_goals':1},
]


def main():
    log("=" * 50)
    log("2026世界杯数据生成")
    log("=" * 50)
    
    # 尝试在线抓取最新结果
    auto = '--auto' in sys.argv
    new_online = fetch_results()
    if new_online:
        log(f"  在线抓取到 {len(new_online)} 条比赛结果")
    
    # 使用已知结果 + 在线结果合并
    results = ALL_RESULTS.copy()
    existing_keys = {(r['date'], r['home'], r['away']) for r in results}
    
    # 保留已有 worldcup.json 中的结果（防止 API 不可用时丢失已获取数据）
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                old = json.load(f)
            old_results = old.get('results', [])
            kept = 0
            for r in old_results:
                key = (r.get('d', ''), r.get('h', ''), r.get('a', ''))
                if key not in existing_keys and r.get('h') and r.get('a'):
                    results.append({
                        'date': r['d'], 'group': r.get('g', '?'), 
                        'home': r['h'], 'away': r['a'],
                        'home_goals': r.get('hg', 0), 'away_goals': r.get('ag', 0)
                    })
                    existing_keys.add(key)
                    kept += 1
            if kept: log(f"  从已有文件保留 {kept} 条比赛结果")
        except Exception:
            pass
    
    for nr in new_online:
        key = (nr['date'], nr['home'], nr['away'])
        if key not in existing_keys:
            results.append(nr)
            existing_keys.add(key)
    
    log(f"  合并后: {len(results)} 场比赛")
    
    # 计算积分榜
    standings = build_standings(results)
    
    # 生成淘汰赛赛程表（从小组赛结果推导）
    log('  生成淘汰赛赛程表...')
    knockout = build_knockout_schedule(standings, results)
    log(f'    {len(knockout)} 场淘汰赛')
    
    # 构建球队输出格式
    groups_data = []
    all_teams = []
    for g in TEAMS:
        team_list = []
        for name in TEAMS[g]:
            s = standings[g].get(name, {'w':0,'d':0,'l':0,'gf':0,'ga':0})
            team_list.append({
                'name': name,
                'w': s['w'], 'd': s['d'], 'l': s['l'],
                'gf': s['gf'], 'ga': s['ga'],
                'region': REGION_MAP.get(name, '?'),
            })
            all_teams.append(team_list[-1])
        groups_data.append({'id': g, 'teams': team_list})
    
    # 晋级概率模拟 + 加权效率
    log('  模拟晋级概率 (5000 iterations)...')
    qual_probs = simulate_group_qualification(standings)
    log(f'    完成')
    
    adj_eff = calculate_adj_efficiency(all_teams, standings)
    
    for g_data in groups_data:
        for t in g_data['teams']:
            t['qual_prob'] = qual_probs.get(g_data['id'], {}).get(t['name'], 0)
    
    for t in all_teams:
        ae = adj_eff.get(t['name'], {})
        t['adj_gf'] = ae.get('adj_gf', t['gf'])
        t['adj_ga'] = ae.get('adj_ga', t['ga'])
        t['opp_strength'] = ae.get('opponent_strength', 0)

    # 赔率（阶段更新）
    odds = [
        {'n':'法国','prob':22.2},{'n':'西班牙','prob':14.3},{'n':'英格兰','prob':14.3},{'n':'阿根廷','prob':11.1},
        {'n':'葡萄牙','prob':9.1},{'n':'巴西','prob':7.7},{'n':'德国','prob':6.7},{'n':'荷兰','prob':4.8},
        {'n':'挪威','prob':3.8},{'n':'摩洛哥','prob':2.4},{'n':'比利时','prob':2.4},{'n':'哥伦比亚','prob':2.4},
        {'n':'美国','prob':2.4},{'n':'日本','prob':2.0},{'n':'墨西哥','prob':2.0},{'n':'乌拉圭','prob':1.5},
    ]
    
    output = {
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'matchday': '⚽ 32强淘汰赛进行中',
        'status_note': '🔥 6月28日起32强淘汰赛正式开战',
        'qual_probs': qual_probs,
        'adj_eff': {name: {'adj_gf': ae['adj_gf'], 'adj_ga': ae['adj_ga'], 
                           'opp_strength': ae['opponent_strength']} 
                    for name, ae in adj_eff.items()},
        'groups': groups_data,
        'results': [{
            'd': r['date'], 'h': r['home'], 'a': r['away'],
            's': f"{r['home_goals']}-{r['away_goals']}",
            'hg': r['home_goals'], 'ag': r['away_goals']
        } for r in results],
        'knockout': knockout,
        'odds': odds,
        'all_teams': [{
            'n': t['name'], 'w': t['w'], 'd': t['d'], 'l': t['l'],
            'gf': t['gf'], 'ga': t['ga'], 'region': t['region'],
            'adj_gf': t.get('adj_gf', t['gf']),
            'adj_ga': t.get('adj_ga', t['ga']),
            'opp_strength': t.get('opp_strength', 0),
        } for t in all_teams],
    }
    
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    # 摘要
    total_goals = sum(r['home_goals'] + r['away_goals'] for r in results)
    log(f"  ✅ {len(results)}场比赛, {total_goals}个进球")
    log(f"  ✅ 已保存: {DATA_FILE}")

if __name__ == "__main__":
    from fetch_logger import record_success, record_failure
    try:
        main()
        record_success(__file__)
    except Exception as e:
        record_failure(__file__, str(e))
        raise

