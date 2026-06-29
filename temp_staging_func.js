// ===== 暂不上架（管理员调试页）=====
function renderStaging(){
  var el = document.getElementById('stagingContent');
  if(!el) { console.error('stagingContent not found'); return; }

  var h = '<div style="background:#fff;border-radius:10px;padding:20px;">';
  h += '<h3 style="margin:0 0 12px;color:#4527a0;">🔧 暂不上架 · 管理员调试页</h3>';

  // ═══ 卡片1: 五维评分卡 ═══
  try {
    var macroData = window.MACRO_DATA || {};
    h += '<div style="background:#fff;border:1px solid #e8eaed;border-radius:8px;overflow:hidden;margin-bottom:10px;">';
    h += '<div style="background:linear-gradient(135deg,#e8eaf6,#c5cae9);color:#283593;padding:8px 14px;font-weight:700;font-size:13px;">🧠 五维评分卡</div>';
    h += '<div style="padding:10px;">';
    var scores = macroData.five_dimension || {};
    var dims = [{n:'技术面',k:'technical',i:'📈'},{n:'资金面',k:'fund',i:'💰'},{n:'宏观面',k:'macro',i:'📊'},{n:'机构面',k:'institution',i:'🏦'},{n:'全球面',k:'global',i:'🌍'}];
    if (Object.keys(scores).length > 0) {
      dims.forEach(function(d){
        var s = scores[d.k] || 5;
        var c = s>=7?'#c62828':s>=5?'#e65100':s>=3?'#888':'#2e7d32';
        h += '<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid #f0f0f0;"><span>'+d.i+' '+d.n+'</span><span style="font-weight:700;color:'+c+';">'+s+'/10</span></div>';
      });
    } else {
      h += '<div style="color:#999;font-size:12px;">五维评分等待数据…（需MACRO_DATA.five_dimension字段）</div>';
    }
    h += '</div></div>';
  } catch(e) { h += '<div style="color:#c62828;padding:8px;font-size:12px;">五维加载: '+e.message+'</div>'; }

  // ═══ 卡片2: F窗口 ═══
  try {
    var fib = window.SH_FIB || {}, cur = fib.current || {}, wins = fib.windows || [];
    h += '<div style="background:#fff;border:1px solid #e8eaed;border-radius:8px;overflow:hidden;margin-bottom:10px;">';
    h += '<div style="background:linear-gradient(135deg,#f3e5f5,#e1bee7);color:#7b1fa2;padding:8px 14px;font-weight:700;font-size:13px;">⏱️ F窗口·缠论视角</div>';
    h += '<div style="padding:10px;">';
    if(cur.days_down !== undefined){
      h += '<div><b>上证</b> 连跌'+cur.days_down+'天 | 累计'+(cur.total_pct||0).toFixed(2)+'% | 状态:'+(cur.mode||'--')+'</div>';
    } else { h += '<div style="color:#999;font-size:12px;">等待斐波那契数据…</div>'; }
    h += '</div></div>';
  } catch(e) { h += '<div style="color:#c62828;padding:8px;">F窗口: '+e.message+'</div>'; }

  // ═══ 卡片3: 板块强度 ═══
  try {
    var sf = window.SECTOR_FUND_FLOW || {}, sIn = sf.sectors_in||[], sOut = sf.sectors_out||[];
    h += '<div style="background:#fff;border:1px solid #e8eaed;border-radius:8px;overflow:hidden;margin-bottom:10px;">';
    h += '<div style="background:linear-gradient(135deg,#e8f5e9,#c8e6c9);color:#2e7d32;padding:8px 14px;font-weight:700;font-size:13px;">📊 板块强度</div>';
    h += '<div style="padding:10px;">';
    if(sIn.length){
      h += '<b>流入TOP5:</b><br>';
      sIn.slice(0,5).forEach(function(s,i){ h += '<div style="font-size:12px;padding:2px 0;">'+(i+1)+'. '+s.name+' <span style="color:#c62828;">+'+s.net.toFixed(1)+'亿</span></div>'; });
      h += '<br>';
    }
    if(sOut.length){
      h += '<b>流出TOP5:</b><br>';
      sOut.slice(0,5).forEach(function(s,i){ h += '<div style="font-size:12px;padding:2px 0;">'+(i+1)+'. '+s.name+' <span style="color:#2e7d32;">'+s.net.toFixed(1)+'亿</span></div>'; });
    }
    if(!sIn.length && !sOut.length) h += '<div style="color:#999;font-size:12px;">暂无板块数据</div>';
    h += '</div></div>';
  } catch(e) { h += '<div style="color:#c62828;padding:8px;">板块: '+e.message+'</div>'; }

  // ═══ 卡片4: 主力抱团 ═══
  try {
    var hd = window.HERRING_DATA || {}, cls = hd.current_clusters || hd.clusters || [];
    h += '<div style="background:#fff;border:1px solid #e8eaed;border-radius:8px;overflow:hidden;margin-bottom:10px;">';
    h += '<div style="background:linear-gradient(135deg,#fff3e0,#ffe0b2);color:#e65100;padding:8px 14px;font-weight:700;font-size:13px;">🔥 主力抱团</div>';
    h += '<div style="padding:10px;">';
    if(cls.length){
      h += '<b>抱团板块:'+cls.length+'个</b><br>';
      cls.forEach(function(c){ h += '<div style="font-size:12px;padding:2px 0;">🏷️ '+c.sector+' · '+(c.direction||'?')+' · '+(c.amount||0).toFixed(1)+(c.unit||'亿')+'</div>'; });
    } else h += '<div style="color:#999;font-size:12px;">暂无抱团数据</div>';
    h += '</div></div>';
  } catch(e) { h += '<div style="color:#c62828;padding:8px;">抱团: '+e.message+'</div>'; }

  // ═══ 卡片5: IPO评分 ═══
  try {
    var ipo = window.IPO_DATA || {}, ipoList = ipo.stocks || ipo.rankings || ipo.list || [];
    h += '<div style="background:#fff;border:1px solid #e8eaed;border-radius:8px;overflow:hidden;margin-bottom:10px;">';
    h += '<div style="background:linear-gradient(135deg,#e0f7fa,#b2ebf2);color:#006064;padding:8px 14px;font-weight:700;font-size:13px;">📈 IPO评分</div>';
    h += '<div style="padding:10px;">';
    if(ipoList.length){
      ipoList.slice(0,10).forEach(function(s,i){ h += '<div style="font-size:12px;padding:2px 0;">'+(i+1)+'. <b>'+s.name+'</b>('+s.code+') '+s.score+'分</div>'; });
    } else h += '<div style="color:#999;font-size:12px;">暂无近期待上市新股</div>';
    h += '</div></div>';
  } catch(e) { h += '<div style="color:#c62828;padding:8px;">IPO: '+e.message+'</div>'; }

  h += '</div>'; // close outer div

  el.innerHTML = h;
  console.log('renderStaging done, content length:', h.length);
}
