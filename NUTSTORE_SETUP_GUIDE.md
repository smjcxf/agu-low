# 坚果云排除规则设置指南（重要！）

## 🚨 问题根因

`.nutstoreignore` 文件 **坚果云不认**！坚果云不支持 `.gitignore` 风格的忽略文件。

必须在 **坚果云 GUI 客户端** 中手动设置排除规则。

## ✅ 操作步骤（必须做）

### 方法一：文件夹级排除（推荐）

1. 打开 **坚果云客户端**
2. 找到 `stock-scanner` 文件夹
3. 右键 → **设置**
4. 找到 **「不同步」或「排除」** 选项
5. 添加以下路径到排除列表：

```
stock-scanner\.git
stock-scanner\dist
stock-scanner\index_master.html
stock-scanner\__pycache__
```

6. 点击确定，等待坚果云重新扫描

### 方法二：全局过滤规则

1. 打开坚果云客户端
2. 点击右上角 **设置（齿轮图标）**
3. 找到 **「同步规则」或「过滤规则」**
4. 添加全局排除模式：

```
*.pyc
__pycache__
.git
dist
index_master.html
```

## 📋 验证是否生效

设置完成后，在另一台电脑上检查：

```bash
# 检查 .git 目录是否还在同步
ls -la stock-scanner/.git

# 检查 index_master.html 的修改时间
# 如果修改时间是最近且符合预期，说明排除成功
```

## 🔗 参考文档

坚果云官方帮助：https://help.jianguoyun.com/?p=3162

（如果链接打不开，在坚果云客户端里搜索「不同步」或「排除同步」）

## ⚠️ 临时 workaround（代码已加固）

如果暂时无法设置 GUI 排除规则，`sync_check.py` 已经加固：

- `check_index_master_lock()` 会在部署前自动检测并恢复被覆盖的 `index_master.html`
- 直接用 git HEAD 内容覆盖，重试5次对抗坚果云实时覆盖

**但这只是临时方案，根本解决还是要设置 GUI 排除规则！**
