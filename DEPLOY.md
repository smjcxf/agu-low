# 🚀 部署流程（必读）

## ⚠️ 致命提醒

**每次修改代码后务必按顺序执行：**

```bash
# 1. 修改 index_master.html（根目录）
# ... 修改代码 ...

# 2. 注入最新数据（⚠️ 不可跳过）
python update_data_v2.py

# 3. 部署到 GitHub Pages
python deploy_now.py --force
```

## ❌ 禁止操作

**绝对禁止**直接用 `cp` 命令复制文件到 dist/：
```bash
# 错误！会导致线上数据回退到旧日期
cp index_master.html dist/index.html
```

## ⚡ 为什么必须走 update_data_v2.py？

- 根目录 `index_master.html` 的嵌入式数据是**旧的**（update_time ≈ 6月13日）
- `update_data_v2.py` 会从 `data/*.json` 读取最新数据并注入到 dist/
- 跳过此步骤会导致线上数据回退7天！

## 📋 快速检查

部署前确认数据日期：
```bash
grep -o '"update_time": "[^"]*"' dist/index.html | head -3
```

应该是今天的日期，如果不是，说明数据未正确注入。

## 🌐 访问地址

- 正式站：https://ah-quant999.github.io/quant-scanner-v6/
- 仓库：ah-quant999/quant-scanner-v6
