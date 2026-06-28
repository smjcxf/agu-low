function renderHiddenData(){
  var el = document.getElementById('hiddenDataContent');
  if(!el) return;

  var hd = window.HIDDEN_DATA || {};
  var html = '<div style="font-size:12px;color:#666;">';

  // ===== 区块1: 扫描执行记录（粉系）=====
  var signalLog = hd.signal_log || [];
  if(signalLog.length > 0){
    html += '<div style="border-left:3px solid #f48fb1;padding:12px 16px;background:#fce4ec;border-radius:0 8px 8px 0;margin-bottom:14px;">';
    html += '<div style="font-weight:700;font-size:14px;color:#555;margin-bottom:8px;">🔍 扫描执行记录（最近20次）</div>';
    html += '<div style="font-size:11px;line-height:1.8;">';
    signalLog.slice(0, 20).forEach(function(log){
      html += '<div style="display:flex;gap:10px;padding:3px 0;border-bottom:1px solid #f8bbd0;font-family:monospace;">';
      html += '<span style="color:#888;min-width:60px;">'+(log.scan_time||'').substring(5,16)+'</span>';
      html += '<span style="min-width:50px;">'+(log.mode||'')+'</span>';
      html += '<span>扫描'+ (log.total_scanned||0) +'只 / 三线'+ (log.triple_count||0) +' / 双线'+ (log.double_count||0);
      if(log.new_triple_count > 0) html += ' <b style="color:#c62828;">新三线'+log.new_triple_count+'</b>';
      html += '</span></div>';
    });
    html += '</div></div>';
  } else {
    html += '<div style="border-left:3px solid #f48fb1;padding:12px 16px;background:#fce4ec;border-radius:0 8px 8px 0;margin-bottom:14px;">';
    html += '<div style="font-weight:700;font-size:14px;color:#555;margin-bottom:8px;">🔍 扫描执行记录</div>';
    html += '<div style="font-size:11px;color:#999;">暂无扫描日志（signal_log.json 为空或不存在）</div>';
    html += '</div>';
  }

  // ===== 区块2: 信号回测 + 当前扫描（蓝/绿并排）=====
  html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px;">';

  var backtest = hd.backtest || {};
  html += '<div style="border-left:3px solid #64b5f6;padding:12px 16px;background:#e3f2fd;border-radius:0 8px 8px 0;">';
  html += '<div style="font-weight:700;font-size:14px;color:#555;margin-bottom:8px;">📊 信号回测胜率</div>';
  html += '<div style="font-size:11px;line-height:1.9;">';
  var btKeys = backtest.win_rates || {};
  for(var sig in btKeys){
    var wr = btKeys[sig];
    html += '<div style="display:flex;justify-content:space-between;padding:1px 0;"><span>'+sig+'</span><span style="font-weight:700;color:'+(wr>=70?'#c62828':wr>=50?'#e65100':'#666')+';">'+wr.toFixed(1)+'%</span></div>';
  }
  if(backtest.total_tested) html += '<div style="margin-top:4px;color:#666;">样本: '+backtest.total_tested+'只 | 更新: '+(backtest.updated||'未知')+'</div>';
  html += '</div></div>';

  var scanStats = hd.scan_stats || {};
  html += '<div style="border-left:3px solid #81c784;padding:12px 16px;background:#e8f5e9;border-radius:0 8px 8px 0;">';
  html += '<div style="font-weight:700;font-size:14px;color:#555;margin-bottom:8px;">🔧 当前扫描状态</div>';
  html += '<div style="font-size:11px;line-height:1.9;">';
  html += '<div>金股池: <b>'+(hd.gold_pool_meta&&hd.gold_pool_meta.total||'?')+'</b>只（信号股'+((hd.gold_pool_meta&&hd.gold_pool_meta.with_signal)||0)+'只）</div>';
  html += '<div>最新扫描: <b>'+(scanStats.last_scan_time||'未知')+'</b></div>';
  html += '<div>扫描模式: <b>'+(scanStats.last_mode||'?')+'</b> | 错误: <b style="color:'+(scanStats.last_errors>0?'#c62828':'#2e7d32')+';">'+(scanStats.last_errors||0)+'</b>个</div>';
  html += '<div>增强日志: '+(hd.enhance_log||'无')+'</div>';
  html += '</div></div>';

  html += '</div>';

  // ===== 区块3: 部署审计记录（橙系）=====
  var audit = hd.audit || {};
  html += '<div style="border-left:3px solid #ffb74d;padding:12px 16px;background:#fff3e0;border-radius:0 8px 8px 0;margin-bottom:14px;">';
  html += '<div style="font-weight:700;font-size:14px;color:#555;margin-bottom:8px;">📋 部署审计记录</div>';
  html += '<div style="font-size:11px;line-height:1.9;">';
  if(audit.last_deploy){
    html += '<div>最近部署: <b>'+(audit.last_deploy.time||'?')+'</b> | 结果: <b style="color:'+(audit.last_deploy.status==='SUCCESS'?'#2e7d32':'#c62828')+';">'+(audit.last_deploy.status||'?')+'</b></div>';
  }
  var errs = audit.errors || [];
  var warns = audit.warnings || [];
  if(errs.length > 0){
    html += '<div style="margin-top:4px;"><span style="color:#c62828;font-weight:700;">ERROR ('+errs.length+'):</span><div style="margin-left:8px;color:#c62828;">';
    errs.slice(0,10).forEach(function(e){ html += '• '+e+'<br>'; });
    html += '</div></div>';
  }
  if(warns.length > 0){
    html += '<div style="margin-top:4px;"><span style="color:#e65100;font-weight:700;">WARN ('+warns.length+'):</span><div style="margin-left:8px;color:#e65100;">';
    warns.slice(0,10).forEach(function(w){ html += '• '+w+'<br>'; });
    html += '</div></div>';
  }
  if(errs.length === 0 && warns.length === 0) html += '<div style="color:#2e7d32;">✅ 无ERROR/WARNING</div>';
  html += '</div></div>';

  // ===== 区块4: 历史追踪数据量（紫/青并排）=====
  html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px;">';

  var tripleMeta = hd.triple_history_meta || {};
  html += '<div style="border-left:3px solid #ba68c8;padding:12px 16px;background:#f3e5f5;border-radius:0 8px 8px 0;">';
  html += '<div style="font-weight:700;font-size:14px;color:#555;margin-bottom:8px;">🧬 三线共振历史</div>';
  html += '<div style="font-size:11px;line-height:1.9;">';
  html += '<div>追踪中: <b>'+(tripleMeta.active||0)+'</b>只 | 新入榜: <b>'+(tripleMeta.new_entries||0)+'</b>只</div>';
  html += '<div>已完成21日: <b>'+(tripleMeta.completed_21||0)+'</b>只 | 已满60日: <b>'+(tripleMeta.completed_60||0)+'</b>只</div>';
  html += '<div>数据范围: '+(tripleMeta.date_range||'未知')+'</div>';
  html += '</div></div>';

  var multiMeta = hd.multi_history_meta || {};
  html += '<div style="border-left:3px solid #4dd0e1;padding:12px 16px;background:#e0f7fa;border-radius:0 8px 8px 0;">';
  html += '<div style="font-weight:700;font-size:14px;color:#555;margin-bottom:8px;">🧬 多维共振历史</div>';
  html += '<div style="font-size:11px;line-height:1.9;">';
  html += '<div>追踪中: <b>'+(multiMeta.active||0)+'</b>只 | 新入榜: <b>'+(multiMeta.new_entries||0)+'</b>只</div>';
  html += '<div>已完成21日: <b>'+(multiMeta.completed_21||0)+'</b>只 | 已满60日: <b>'+(multiMeta.completed_60||0)+'</b>只</div>';
  html += '<div>数据范围: '+(multiMeta.date_range||'未知')+'</div>';
  html += '</div></div>';

  html += '</div>';

  // ===== 区块5: 定时任务配置表（淡青）=====
  var schedule = hd.update_schedule || {};
  var schedules = schedule.schedules || [];
  html += '<div style="border-left:3px solid #90a4ae;padding:12px 16px;background:#eceff1;border-radius:0 8px 8px 0;margin-bottom:14px;">';
  html += '<div style="font-weight:700;font-size:14px;color:#555;margin-bottom:8px;">⏰ 定时任务配置表（'+schedules.length+'个自动化）</div>';
  html += '<div style="font-size:11px;line-height:1.8;font-family:monospace;">';
  if(schedule.updated) html += '<div style="color:#888;margin-bottom:4px;">更新时间: '+schedule.updated+'</div>';
  schedules.forEach(function(s){
    html += '<div style="display:flex;gap:6px;padding:2px 0;border-bottom:1px solid #cfd8dc;">';
    html += '<span style="color:#455a64;min-width:45px;">'+s.time+'</span>';
    html += '<span style="font-weight:600;min-width:110px;">'+s.task+'</span>';
    html += '<span style="color:#666;">'+s.content+'</span>';
    html += '</div>';
  });
  html += '</div></div>';

  html += '</div>';
  el.innerHTML = html;
}
