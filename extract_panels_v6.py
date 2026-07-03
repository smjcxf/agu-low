#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# DO NOT DELETE: 独立页生成脚本，standalone/ 目录的来源 (see DO_NOT_DELETE.md)
"""
独立页面提取 v6（最小改动方案）
只改两处：1) CSS 让所有面板可见 2) 隐藏标签栏 + 注入顶栏渲染JS
用法: python extract_panels_v6.py
"""

import re
import os

BASE_HTML = "dist/index.html"
OUTPUT_DIR = "standalone"

PANELS = [
    ("overview",   "总览"),
    ("shmonitor",  "数据监控"),
    ("predict",    "预判信号"),
    ("gold",       "金股观测"),
    ("query",      "个股查询"),
    ("health",     "健康看板"),
]

def main():
    print(f"读取 {BASE_HTML} ...")
    with open(BASE_HTML, 'r', encoding='utf-8') as f:
        content = f.read()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"  大小: {len(content)//1024}KB")

    ut_match = re.search(r'"update_time"\s*:\s*"([^"]+)"', content)
    scan_time = ut_match.group(1) if ut_match else '未知'
    print(f"  数据时间: {scan_time}")

    # === 全局修改（对所有页面都一样）===
    # 1. 把 .tab-panel { display: none; } 改为 display: block;
    base_modified = content.replace(
        '.tab-panel { display: none; }',
        '.tab-panel { display: block !important; }'
    )
    base_modified = base_modified.replace(
        '.tab-panel{display:none}',
        '.tab-panel{display:block!important}'
    )
    print("  ✓ 已修改 .tab-panel 规则为全部可见")

    # 2. 给目标面板加 active 类 + 去掉内联 display:none
    for pid, _ in PANELS:
        base_modified = base_modified.replace(
            f'<div class="tab-panel" id="panel-{pid}" style="display:none;">',
            f'<div class="tab-panel active" id="panel-{pid}">'
        )

    # 对每个面板生成独立文件
    for target_id, target_name in PANELS:
        print(f"\n生成: {target_id}.html ({target_name}) ...")

        modified = base_modified

        # 隐藏其他面板（用CSS）
        css_hides = ''
        for pid, _ in PANELS:
            if pid != target_id:
                css_hides += f'  #panel-{pid} {{ display: none !important; }}\n'

        # 注入到 </head> 前
        inject = f'''<style>
/* ====== 独立页面：只显示 {target_name} ====== */
html,body{{height:auto;min-height:100vh;overflow-y:auto;padding-top:56px}}
.header{{display:none!important}}
.sa-bar{{
  background:linear-gradient(135deg,#1a237e,#283593);color:#fff;
  padding:10px 20px;display:flex;align-items:center;gap:10px;
  position:fixed;top:0;left:0;right:0;z-index:9999;
}}
.sa-bar .r{{font-size:20px}} .sa-bar .b{{font-size:15px;font-weight:700}}
.sa-bar .s{{font-size:10px;opacity:.7}}
.sa-bar a{{
  margin-left:auto;background:rgba(255,255,255,.15);
  border:1px solid rgba(255,255,255,.3);color:#fff;
  padding:4px 12px;border-radius:4px;text-decoration:none;font-size:11px;
}}
.sa-bar a:hover{{background:rgba(255,255,255,.25)}}
.tabs{{display:none!important}}
{css_hides}
</style>
<script>
// 顶栏
document.addEventListener('DOMContentLoaded',function(){{
  var d=document.createElement('div');d.className='sa-bar';
  d.innerHTML='<span class=r>🚀</span>'
    +'<div><div class=b>九宝量化 V6.0</div><div class=s>独立 · {target_name}</div></div>'
    +'<a href=index.html>← 全部</a>';
  document.body.insertBefore(d,document.body.firstChild);
}});
// 渲染
window.addEventListener('load',function(){{
  var list=[
    ['renderRecommend',0],['renderSummaryCards',0],['renderShMonitor',0],
    ['renderAISummary',0],['renderETFFlow',0],['renderSectorFundFlow',0],
    ['renderUnlistedDataCards',0],['renderCffex',0],['renderConceptRanking',0],
    ['renderMacro',0],['renderUpdateSchedule',0],['renderCalendar',0],
    ['renderHealthDashboard',0],['renderWorldcup',0],['renderLottery',0],
    ['renderLimitUpHeatmap',0],['renderTop10Daily',0],['renderSectorRotation',0],
    ['renderSuspensionAlert',0],['renderIpoScore',0],
    ['renderPredictSummary',0],['renderSelectedSignals',0],
    ['renderTrendFlow',0],['renderSectorRS',0],['renderMacroOverview',0]
  ];
  list.forEach(function(item){{
    try {{
      var fn=window[item[0]];
      if(typeof fn==='function'){{
        if(item[0]==='renderGoldPool'&&window.NT_DATA&&window.NT_DATA.gold_pool)
          fn(window.NT_DATA.gold_pool,window.NT_DATA.analysis_date);
        else if(item[0]==='renderLhbPredict'&&!window.LHB_DATA)return;
        else if(item[0]==='renderNorthFund'&&!window.NORTH_FUND_DATA)return;
        else fn();
      }}
    }}catch(e){{}}
  }});
  console.log('[standalone] rendered');
}});
</script>
</head>'''

        last_head = modified.rfind('</head>')
        final = modified[:last_head] + inject + modified[last_head+7:]

        out_path = os.path.join(OUTPUT_DIR, f"{target_id}.html")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(final)
        print(f"  ✓ {len(final)//1024}KB")

    # 导航首页
    cards = ''.join(f'''<a href="{p}.html" class=c><div class=ci>📊</div><div class=cn>{n}</div></a>''' for p,n in PANELS)
    # extra standalone pages (not in PANELS list)
    _extra = [
        ('worldcup', '🎰', '竞彩娱乐'),
        ('guide',    '📖', '逻辑详解'),
        ('triple_resonance', '⚡', '三线追踪'),
        ('multi_resonance',  '🔗', '多维追踪'),
    ]
    cards += ''.join(f'''<a href="{p}.html" class=c><div class=ci>{i}</div><div class=cn>{n}</div></a>''' for p,i,n in _extra)

    idx=f'''<!DOCTYPE html><html lang=zh-CN><head><meta charset=UTF-8>
<meta name=viewport content="width=device-width,initial-scale=1.0">
<title>九宝量化 V6.0 - 导航</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:linear-gradient(135deg,#e8eaf6,#f5f7fa);min-height:100vh}}
.hd{{background:linear-gradient(135deg,#1a237e,#283593);color:#fff;padding:40px 24px 28px;text-align:center}}
.hd r{{font-size:48px}} .hd b{{font-size:26px;font-weight:700}} .hd s{{font-size:12px;opacity:.6}} .hd t{{font-size:11px;opacity:.5;margin-top:6px}}
.ct{{max-width:800px;margin:40px auto;padding:0 16px 80px}}
.n{{background:#e8f5e9;border-left:3px solid #4caf50;padding:14px 18px;border-radius:0 8px 8px 0;font-size:12px;color:#2e7d32;margin-bottom:24px;line-height:1.9}}
.gs{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}}
.c{{background:#fff;border-radius:12px;padding:22px 14px;text-decoration:none;color:#333;box-shadow:0 2px 8px rgba(0,0,0,.06);text-align:center;display:block;transition:transform .15s}}
.c:hover{{transform:translateY(-3px);box-shadow:0 6px 20px rgba(0,0,0,.12)}}
.ci{{font-size:28px;margin-bottom:8px}} .cn{{font-size:14px;font-weight:600}}
.ft{{text-align:center;padding:32px 16px;font-size:11px;color:#bbb;margin-top:48px;border-top:1px solid #e0e0e0}}</style></head>
<body><div class=hd><div class=r>🚀</div><div class=b>九宝量化 V6.0</div><div class=s>独立页面导航</div><div class=t>{scan_time}</div></div>
<div class=ct><div class=n>✅ v6 方案：改CSS规则+注入渲染 | 📁 standalone/ | 🔄 extract_panels_v6.py</div><div class=gs>{cards}</div></div>
<div class=ft>不构成投资建议</div></body></html>'''
    with open(os.path.join(OUTPUT_DIR,'index.html'),'w',encoding='utf-8') as f:
        f.write(idx)
    print(f"\n✅ {len(PANELS)} 个面板完成 | {OUTPUT_DIR}/index.html")

if __name__=='__main__':
    main()
