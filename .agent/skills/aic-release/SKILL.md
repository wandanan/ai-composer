---
name: aic-release
description: ai-composer 发布流程 + 提交文案风格 + 隐私保护检查。当任务涉及 pip 打包发布、GitHub 提交/推送、版本 tag/release、提交信息撰写、密钥/隐私扫描时使用。隐私保护是最高优先级。
---

# ai-composer 发布与提交规范

## ⚠️ 隐私保护（最高优先级，每次发布必做）

### 禁止进入公开仓库/发布包的内容

```
① API 密钥类:  LLM_API_KEY / sk- 开头 / AIza / ghp_ / AKIA / sk-ant- / pypi- / JWT
② 业务信息:    内部业务应用名、客户名、业务内部结构（提交信息与发布说明尤其注意）
③ 内部文档:    docs/design、docs/learn、docs/api.md、docs/quickstart.md、docs/test-api.md
               （发布只带 docs/tutorial；其他 docs 目录不提交到 prod）
④ 提交信息细节: 不写"移除某应用""不再泄漏内部形式"这类暴露内部结构的文案
```

### 发布前隐私扫描（必做，命中即停）

```bash
grep -rEn "sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|\
AKIA[A-Z0-9]{16}|sk-ant-[A-Za-z0-9]{20,}|pypi-[A-Za-z0-9_-]{30,}" \
  apps/ extensions/ tools/ kernel/ docs/ test/ \
  --include="*.py" --include="*.ini" --include="*.md" --include="*.toml" 2>/dev/null
# 期望: 零命中
```

另外逐文件确认：所有 `config.local.ini` 的 `LLM_API_KEY=` 必须为空。

### 提交内容检查（误提交防护，每次提交前必做）

**发现即提示用户**——不静默处理、不自动改写历史（是否移除/改写由用户决策）。

```bash
# ① 大文件检查（暂存区 >1MB 的文件）
git diff --cached --name-only | while read f; do
  [ -f "$f" ] && sz=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f") \
    && [ "$sz" -gt 1048576 ] && echo "⚠️ 大文件: $f ($sz bytes)"
done

# ② 误提交模式检查（库文件/日志/密钥/产物/依赖）
git diff --cached --name-only | grep -E "\.(db|sqlite|log|pem|key|p12|env|ini)$|\
config\.local\.ini|__pycache__|\.venv|node_modules|/dist/|/build/|\.egg-info|graph-viz\.html" || true

# ③ 隐私内容检查（暂存区 diff 中的密钥模式）
git diff --cached | grep -En "sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{20,}|\
ghp_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|pypi-[A-Za-z0-9_-]{30,}|LLM_API_KEY=.+[^=]$" || true

# ④ 全历史大文件/敏感文件审计（发布前整体体检）
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' \
  | awk '/^blob/ && $2 > 1048576 {print "⚠️ 历史大文件:", $3, "(" $2 " bytes)"}' | head
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(rest)' \
  | grep -E "\.(db|log|pem|key|env)$|config\.local\.ini" | head
```

命中任一 → **停下提示用户**：列出文件与原因，等用户决定（移除 / 改写历史 / 重建仓库）。`config.local.ini` 的 `LLM_API_KEY` 必须为空才允许进暂存区。

### 密钥处理纪律

- **PyPI token 只走环境变量**（`TWINE_USERNAME=__token__` `TWINE_PASSWORD=...`），
  绝不写入任何文件、绝不放进提交
- token 出现在会话记录中 → 提醒用户轮换
- 泄露过 key 的仓库 → 删除重建 + 用户轮换 key（历史无法真正抹除，只能重建）
- 已推送的错误提交信息 → `git commit --amend` + `git push --force-with-lease` 改写

## 提交文案风格

### 规则

```
- 中性短语, 2~6 字, 不泄露内部业务信息
- 发布提交:  aic-vX.Y.Z版本发布
- 功能提交:  简短名词短语（见示例）
- 已推送的错误文案: 立即改写（amend + force-with-lease），不等下个版本
```

### 示例

| ✅ 好 | ❌ 坏（暴露内部信息） |
|---|---|
| skill更新 / sdk文档 / 引擎解耦 | fix(cli): 用法文案统一（不再泄漏仓库内部 python -m tools.* 形式） |
| 框架机制加固 / 静默失败修复 | 发布包移除XX业务应用 |
| 会话目录可配 / 发布包更新 | 修复XX客户反馈的问题 |
| aic-v0.1.5版本发布 | 删除含泄露密钥的旧提交 |

## 发布流程（pip + GitHub）

### 0. 前置检查

```
- 分支: prod（正式基线；历史干净: 每版本一个提交 + 中性文案）
- 回归: m0~m7 全绿（m1b/m2/m3 真实引擎段用 --skip-real）
- 隐私扫描通过（见上）
```

### 1. 版本号（两处同步）

```bash
# pyproject.toml: version = "X.Y.Z"
# kernel/__init__.py: __version__ = "X.Y.Z"
```

### 2. 构建与验证

```bash
rm -rf dist build *.egg-info
PYTHONIOENCODING=utf-8 python -m build
# wheel 内容检查: 无业务应用 / 无真实引擎适配器 / apps 无顶层 __init__（namespace）/ 版本正确
# 干净 venv 冒烟: pip install --no-cache-dir ai-composer==X.Y.Z → 导入 + 装配
```

### 3. 提交 + tag + 推送

```bash
git commit -m "aic-vX.Y.Z版本发布"
git tag vX.Y.Z
git push origin prod && git push origin vX.Y.Z
```

### 4. GitHub release

```bash
gh release create vX.Y.Z --title "aic vX.Y.Z" --notes "<中性说明, 无业务信息>"
gh release upload vX.Y.Z dist/*.whl dist/*.tar.gz --clobber
```

### 5. PyPI 上传

```bash
TWINE_USERNAME=__token__ TWINE_PASSWORD='<token>' \
  PYTHONIOENCODING=utf-8 python -m twine upload dist/*.whl dist/*.tar.gz
# 验证: curl -s https://pypi.org/pypi/ai-composer/json → info.version
# 注意: pip simple index 传播滞后 JSON API ~30-60s, 等后重试 --no-cache-dir
```

### 6. 默认环境重装（用户机器）

```bash
C:/Python314/python.exe -m pip install -U ai-composer
```

## 环境注意事项

```
- WSL/Linux 视图提交时用 git -c core.autocrlf=input add/commit —— 避免 CRLF churn 混入
- Windows 控制台中文乱码: 命令加 PYTHONIOENCODING=utf-8（仅显示问题）
- 发布用 python -m build（wheel + sdist）; pip wheel 只出 wheel
```

## 发布后检查

```
- PyPI JSON API: latest == 发布版本 ✓
- GitHub release 资产完整（wheel + sdist）✓
- 干净 venv: install + aic init + 装配冒烟 ✓
- 默认环境重装完成 ✓
```
