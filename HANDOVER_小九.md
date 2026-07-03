# 🔥 阿狸咪 → 小九 交接文档

**日期**: 2026-07-03 晚  
**交接人**: 阿狸咪（家里电脑）  
**接收人**: 小九（单位电脑）  

---

## ⚠️ 最重要的事：别覆盖旧版本！

**小九，听好了！**

❌ **禁止操作**：
- 不要直接运行 `extract_panels_v6.py` 而不保护竞彩/逻辑页
- 不要手动编辑 `standalone/worldcup.html` 和 `standalone/guide.html`
- 不要用旧版 `dist/index.html` 覆盖新版

✅ **正确流程**：
1. 先 `git pull` 拉最新代码
2. 运行定时任务（`batch_update.py`）
3. 让自动化脚本自动更新独立页面
4. 部署前先验证

---

## 📊 当前状态（2026-07-03 晚）

### ✅ 已修复
- 主网站数据注入完整（GOLD_POOL 604只，SCAN_DATA 正常）
- 独立页面（10个）全部生成并部署到 GitHub Pages
- 三线共振历史追踪数据完整（26天历史 + 价格走势）
- 竞彩娱乐和逻辑详解页内容预渲染（纯静态，不依赖JS）
- 顶部遮挡问题修复（所有独立页加 `padding-top:56px`）
- 自动化流程已加入（`refresh_standalone_and_deploy.py`）

### ⚠️ 仍需注意
1. **NT_DATA 只有4个key**（`update_time`, `alerts`, `etfFlow`, `calendar`）
   - 其他数据在独立变量里（`GOLD_POOL`, `SCAN_DATA`, `MAIN_STOCK_DATA` 等）
   - 主网站应该正常，因为前端会从这些变量读取
   - 如果还有页面空白，运行 `python update_data_v2.py`（完整模式，别加 `--fast`）

2. **独立页面数据更新**
   - 已自动化：定时任务跑完会自动重新生成并部署
   - 脚本：`refresh_standalone_and_deploy.py`
   -  manual触发：`python refresh_standalone_and_deploy.py --skip-data`

---

## 🔧 明天的工作流程

### 早晨（09:15 盘前）
```bash
cd E:/workspace/workspace/stock-scanner
git pull  # 先拉最新代码！
python batch_update.py --mode pre_market
```

### 盘中（09:45 / 10:30 / 11:45 / 13:30 / 14:30）
```bash
git pull  # 如果有更新
python batch_update.py --mode morning_scan  # 或 afternoon
```

### 收盘后（15:20 / 16:30）
```bash
git pull
python batch_update.py --mode post_close  # 或 close
```

### 自动化已配置
- `batch_update.py` 每个模式都会在部署前自动重新生成独立页面
- 不用手动运行 `extract_panels_v6.py` 或 `extract_standalone_final.py`
- 如果自动化失败，手动运行：
  ```bash
  python refresh_standalone_and_deploy.py --skip-data
  ```

---

## 📁 关键文件说明

| 文件 | 作用 | 注意事项 |
|------|------|----------|
| `dist/index.html` | 主网站（部署用） | 每次 `update_data_v2.py` 会重新注入数据 |
| `standalone/` | 独立页面源码 | 别直接编辑，让脚本自动生成 |
| `dist/standalone/` | 独立页面部署目录 | 自动同步，不用手动改 |
| `data/triple_resonance_history.json` | 三线共振历史数据 | 定时任务会自动更新 |
| `refresh_standalone_and_deploy.py` | 独立页面自动更新脚本 | 已集成到 `batch_update.py` |
| `batch_update.py` | 定时任务主入口 | 7个模式，别改步骤顺序 |

---

## 🚨 常见问题处理

### 问题1：主网站某个面板空白
**原因**: `dist/index.html` 数据注入不完整  
**解决**:
```bash
python update_data_v2.py  # 完整注入（可能需要10-15分钟）
python deploy_now.py --force
```

### 问题2：独立页面空白（竞彩/逻辑）
**原因**: `extract_panels_v6.py` 覆盖了这两个页  
**解决**:
```bash
python extract_standalone_final.py  # 重新生成竞彩+逻辑页
python refresh_standalone_and_deploy.py --skip-data
```
**预防**: 别运行 `extract_panels_v6.py`，除非你改了它的 `PANELS` 列表

### 问题3：GitHub Pages 部署失败
**原因**: `deploy_now.py` 审计失败或 git 冲突  
**解决**:
```bash
git checkout gh-pages
git pull origin gh-pages
python deploy_now.py --force  # 强制部署
```

### 问题4：定时任务卡住（比特币数据获取超时）
**原因**: 外网数据获取慢或失败  
**解决**:
- 改 `update_data_v2.py`，给比特币数据获取加 timeout
- 或者跳过比特币数据：`python update_data_v2.py --skip-bitcoin`

---

## 📝 给小九的特别提醒

1. **每次开始工作前先 `git pull`**  
   阿狸咪（家里电脑）可能已推送更新，别用旧代码覆盖

2. **别手动编辑 `standalone/` 里的文件**  
   让脚本自动生成，手动改会被覆盖

3. **部署前先验证**  
   ```bash
   python refresh_standalone_and_deploy.py --verify-only
   ```

4. **如果改了代码，提交并推送**  
   ```bash
   git add -f <修改的文件>
   git commit -m "描述这次改了什么"
   git push origin main
   ```
   这样阿狸咪周末能拉到你的更新

5. **遇到问题先看这个文档**  
   如果这文档没覆盖你的问题，问阿狸咪（微信或GitHub Issues）

---

## 📞 紧急联系方式

- **阿狸咪（家里电脑）**: 周末也在，有紧急问题可以call
- **GitHub**: https://github.com/ah-quant999/quant-scanner-v6
- **线上地址**: https://ah-quant999.github.io/quant-scanner-v6/

---

## ✅ 交接检查清单

小九，明天开始工作前确认：

- [ ] 已 `git pull` 拉最新代码（包括 `HANDOVER_小九.md`）
- [ ] 已检查 `dist/index.html` 数据是否完整（GOLD_POOL 应有600+只）
- [ ] 已检查 `standalone/` 里竞彩和逻辑页是否存在且非空
- [ ] 已理解 `batch_update.py` 的7个模式
- [ ] 已理解自动化流程（定时任务 → 独立页更新 → 部署）

---

**阿狸咪 签字**: 🔥  
**日期**: 2026-07-03  

**小九 确认收到**: ___________  
**日期**: ___________
