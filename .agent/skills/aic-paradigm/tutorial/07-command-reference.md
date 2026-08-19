# 07 - 命令参考（按目标速查）

本参考按**目标**组织：你想做什么，用什么命令，流程怎么走。命令的完整参数见 `aic <命令> -h`。

## 通用约定

- 所有命令在项目根目录执行
- **预演语义**：promote / uninstall 默认只显示影响清单（预演，不实际执行）——确认后加 `--yes`
- 仓库开发模式等价命令：`python -m tools.cli <命令>`（或 `python -m tools.<命令>`）
- `KIT_PROJECT_ROOT=<路径>` 可指定项目根（测试、多项目场景）

## 按目标速查

| 我想…… | 命令 | 关键流程 |
|---|---|---|
| 创建新应用 | `aic init <name>` | 生成壳 + 插件骨架 → 三步法写插件 → 挂载 → 启动 |
| 查看项目结构/插件关系 | `aic graph` | 生成图谱 → 双击打开 → 点击交互 |
| 把私有插件变成公共插件 | `aic promote <类>` | 预演看清单 → `--yes` 执行 → 验证 |
| 卸载一个应用 | `aic uninstall <应用>` | 预演看删除/保留 → `--yes` 执行 |
| 卸载一个插件 | `aic uninstall --plugin <类>` | 预演（有消费方会拒绝）→ `--yes` 执行 |
| 提取新应用开发模板 | `aic template <应用>` | `--dry-run` 看清单 → `--out` 提取 |
| 从模板开始新项目 | `aic template` + `aic init` | 提取模板 → 进入模板目录 → 创建应用 |
| 查看命令帮助 | `aic -h` / `aic <命令> -h` | 命令与参数说明 |

## 目标详解

### 1. 创建新应用

```bash
aic init my_app
```

流程：

```
① aic init my_app        生成壳（6 文件 + config/）+ 插件骨架
② 三步法写插件           ① 能力（服务类/AgentTask）② 流程（复杂才加 pipeline）
                          ③ 声明（inject/provides/apply）
③ 挂载                   apps/my_app/profile.py 的 PLUGINS 加 MyAppPlugin()
④ 启动                   uvicorn apps.my_app.main:app --port 8001
⑤ 验证                   http://127.0.0.1:8001/health（plugins 含 MyAppPlugin）
```

> 完整的三步法示例见 [03 - 开发第一个业务插件](03-first-plugin.md)。

### 2. 查看项目结构（图谱）

```bash
aic graph
start graph-viz.html      # Windows; macOS/Linux 用 open
```

图谱的三种形态与交互：

```
力导向图    节点大小 ∝ 引用数; 点击插件高亮引用闭包（= 卸载影响）
代码树      左侧面板: 应用 → 插件 → 归属分组; 点击 ↔ 图谱双向联动
过滤        按应用查看 / 按类别（平台/领域/孤儿/动态/AI）
```

**用途**：新人对项目"看清内部"的第一工具——孤儿插件（虚线）、共享插件、AI 插件一目了然。

### 3. 把私有插件变成公共插件（上浮）

```bash
aic promote StandardPlugin          # ① 预演: 显示移动/引用更新/标记位置
aic promote StandardPlugin --yes    # ② 确认后执行
```

流程与效果：

```
① 预演      显示: 移动 extensions/business/x → extensions/platform/x
             引用更新 N 个文件 / PUBLIC 标记写入位置
② 执行      移动包 + 更新全项目 import + 写 PUBLIC = True
③ 验证      应用仍能装配（引用更新没漏）
④ 后续      卸载任何应用都不再删除它（独立生命周期）
```

**先 promote 再提取模板**——只有上浮过的公共插件会进入模板。

### 4. 卸载一个应用

```bash
aic uninstall my_app                 # ① 预演: 删除/保留清单
aic uninstall my_app --yes           # ② 确认后执行
```

影响分析规则：

```
删除   壳目录 + 专属插件（只挂载该应用且非公共）
保留   共享插件 / 公共插件（独立生命周期）/ 动态插件
```

卸载后自动验证剩余应用（壳契约）——卸载不能伤及他人。

### 5. 卸载一个插件

```bash
aic uninstall --plugin MyPlugin      # ① 预演: 有挂载/消费方会拒绝并列出
aic uninstall --plugin MyPlugin --yes   # ② 确认后执行
```

**有应用挂载或包外消费方 → 拒绝**（列出阻碍者）；无 → 删除插件包。
公共插件（上浮过）只能通过这种方式单独卸载。

### 6. 提取新应用开发模板

```bash
aic template review --dry-run         # ① 预演: 公共插件清单 + 未上浮共享提示
aic template review --out ~/my-tpl    # ② 提取
```

模板内容：

```
基础 AIC（kernel/tools/引擎）+ 公共插件 + 示例壳 hello_aic
+ docs/learn + 自动生成的 requirements.txt（按模板实际 import 过滤）
```

模板只带走**公共插件**（上浮过 = 你显式声明的传承）——未上浮的插件列出提示，不自动带走。

### 7. 从模板开始新项目

```bash
aic template review --out ~/my-tpl    # ① 提取模板
cd ~/my-tpl                           # ② 进入模板
pip install -r requirements.txt       # ③ 安装依赖
python test/template_check.py         # ④ 模板自检（壳契约 + hello_aic 装配）
aic init my_biz                       # ⑤ 在模板上加新应用
uvicorn apps.hello_aic.main:app       # ⑥ 示例应用开箱即用
```

**这是范式的推荐起步方式**：新项目从"已验证的公共插件"开始，而不是空白骨架。

### 8. 查看命令帮助

```bash
aic -h                  # 命令列表
aic promote -h          # 单命令参数（init/graph/promote/uninstall/template 均可）
```

### 9. 指定项目根（测试/多项目）

```bash
KIT_PROJECT_ROOT=/path/to/proj aic graph     # 对指定项目运行工具
```

默认作用于当前工作目录（cwd）的项目。

## 完整开发规范

命令之外，范式开发的约束与最佳实践（壳契约、三步法、上浮三问）见项目 Skill：`.claude/skills/aic-paradigm/`。
