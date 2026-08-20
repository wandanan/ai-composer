---
name: aic-paradigm
description: AIComposer 范式开发 Skill——约束、规范、最佳实践与 aic 命令速查。当任务涉及 kernel/extensions/apps/tools 的代码修改、新建应用或插件、上浮/卸载/模板提取等范式操作时使用。
---

# AIComposer 范式开发 Skill

## 范式一句话

```
组件 = 能力实现（普通类/函数, 不认识内核）
插件 = 组件 + 插件声明（inject/provides/apply, 内核接入器）
应用 = 组件组合（内核组织 + 插件接入 + 应用壳声明清单）
```

- **框架**（`aic/`，0.2.0 命名空间重构）：内核（注册/事件/装配/可逆卸载，零业务零能力）
  + 平台插件（aic.extensions.platform）+ 工具（aic.tools）+ 示例应用（aic.apps.hello_aic）
- **用户业务**（项目根平铺）：插件（extensions/business/*，三步法编写）+ 应用壳（apps/*）
- **统一入口**：`from aic import Context, boot, Plugin`（与 aic.kernel 等价）

**纪律核心**：业务逻辑永远在插件里，壳只做组合。
**跨盒纪律**：消费方永不 import 实现（走 ctx 服务）; 组合面（*Plugin / loops 包 / profile.py
组合点）、协议面（aic.extensions.platform.agent / .loops 协议包）与声明工具
（extract、session.artifacts）豁免——旁路 import 装配期报错（kernel/imports.py）。
**事件契约（0.2.1）**：事件先登记再 emit——业务插件 apply 里 `ctx.register_event(name, fields)`
声明（未登记 emit 报错、payload 超集报错）; SSE 桥接由业务声明
`ctx.get("stream").bridge(event)`（StreamPlugin 是通用通道, 不认识业务事件）。

## 命令速查（aic 六命令）

| 命令 | 作用 | 备注 |
|---|---|---|
| `aic init <name>` | 生成新应用：壳 6 文件 + 插件骨架 + config/ | tasks/worker 为空档位（可以不用但必须要有） |
| `aic graph` | 生成 `graph-viz.html` 交互图谱（力导向 + 代码树 + 弹窗） | 自包含，双击即开 |
| `aic caps` | 显示框架可用能力：平台服务 / 业务插件 / 声明工具 / 引擎 | 写能力前先查（能力阶梯 rung 1） |
| `aic promote <类> [--yes]` | 私有插件上浮为公共插件：移动包 + 更新全项目 import + 写 `PUBLIC` 标记 | **默认预演**（只显示影响清单），`--yes` 执行；`--to platform/business/路径` |
| `aic uninstall <应用> [--yes]` | 卸载应用（壳 + 专属插件）；`--plugin <类>` 卸载插件 | **默认预演**，`--yes` 执行；共享/公共插件保留 |
| `aic template <应用> [--out]` | 提取新应用开发模板：基础 AIC + 公共插件 + 示例壳 hello_aic | `--dry-run` 预演 |

仓库开发模式等价命令：`python -m aic.tools.cli <命令>`（或 `python -m aic.tools.<命令>`）。
所有工具支持 `KIT_PROJECT_ROOT` 环境变量指定项目根（测试用）。

**按目标速查**（完整流程见 docs/tutorial/07-command-reference.md）：

| 我想…… | 命令 | 关键流程 |
|---|---|---|
| 创建新应用 | `aic init <name>` | 生成壳+插件骨架 → 三步法写插件 → 挂载 → 启动 |
| 查看项目结构/插件关系 | `aic graph` | 生成图谱 → 双击打开 → 点击交互 |
| 查框架有什么可用能力 | `aic caps` | 平台服务表（key/换法/特性）→ ctx.get 消费；业务插件 → profile.py 挂载 |
| 把私有插件变成公共插件 | `aic promote <类>` | 预演看清单 → `--yes` 执行 → 验证 |
| 卸载一个应用 | `aic uninstall <应用>` | 预演看删除/保留 → `--yes` 执行 |
| 卸载一个插件 | `aic uninstall --plugin <类>` | 预演（有消费方会拒绝）→ `--yes` 执行 |
| 提取新应用开发模板 | `aic template <应用>` | `--dry-run` 看清单 → `--out` 提取 |
| 从模板开始新项目 | `aic template` + `aic init` | 提取模板 → 进入模板目录 → 创建应用 |
| 查看命令帮助 | `aic -h` / `aic <命令> -h` | 命令与参数说明 |
| 指定项目根（测试/多项目） | `KIT_PROJECT_ROOT=<路径> aic <命令>` | 默认作用于 cwd 的项目 |

## 强制约束（机制强制，违反装配即报错）

### 1. 壳布局契约（`check_shell_layout`）

```
装配组（必须齐全）:  __init__.py / profile.py / shell.py / tasks.py / worker.py
入口组（至少一个）:  main.py(HTTP) / cli.py(CLI)
config/              必须为目录
```

### 2. 壳内容契约（`check_shell_content`，AST 检查）

壳内自定义 .py（非装配组/入口组/test_*）**不得**：

```
a. import aic.extensions.*            → 直接拿实现（消费纪律: get 不 import）
b. 定义 Plugin 子类               → 壳不提供能力
c. 调用 .register/.emit/.effect   → 提供/接线动作属插件 apply（.get 消费放行）
```

### 3. 任务名协议

```
shell 侧 register_task(name) ⇒ name ∈ apps.<app>.worker 模块内 @celery_app.task 注册
```

- 任务名常量在 `tasks.py` 单一来源，shell 与 worker 双侧同名
- `JobsPlugin(app_pkg="<应用名>")` 声明所属应用（装配时校验）

### 4. 插件区（隐式概念）

```
地基（不可动）:  aic/（框架包, 只读——promote/uninstall 拒绝）根 apps/（壳）
插件区（自由）:  根 extensions/ 是惯例位（business=领域, platform=项目平台/promote 上浮目标）
平台两层:       aic.extensions.platform（框架平台, 内置） + 根 extensions/platform（项目平台, 可写）
```

## 开发规范（三步法）

写插件只回答三个问题：

```
① 能力   提供什么功能    → 服务类 / AgentTask（AI 驱动时实现四问协议）
② 流程   怎么组合        → pipeline.py（单步操作可跳过）
③ 声明   要什么/给什么    → inject / provides / apply
```

- **消费纪律**：每次调用时 `ctx.get(key)`，不缓存引用（缓存了替换就失效）
- **能力面纪律**：`provides` 必须覆盖 `apply` 里注册的全部 key
- **IO 纪律**：能力里不直接写文件/连库——落盘走产物通道（`save_artifact`）或数据通道（`ctx.get("storage")`）
- **能力阶梯**（写任何能力前先爬, 第一级成立就停）：
  ```
  1. 平台已有服务?    → aic caps / SDK §3: ctx.get(key) 直接消费（storage/cache/jobs/...）
  2. 已有业务插件?    → extensions/business/*: profile.py 挂载
  3. 声明工具可用?    → UTILITY_MODULES（extract / session.artifacts 纯函数直接 import）
  4. 部分满足?       → 扩展优先（见下）: 注入换实现 / 包装器 / 覆盖注册 —— 不动轮子本体
  5. 以上都没有（语义不同）→ 才写新插件（组件 + 声明）
  ```
- **扩展 vs 修改 vs 新造**（现有轮子部分满足时, 四问诊断, 判断源在声明层不看源码）：
  ```
  语义（是不是这功能?）  不是 → 造新插件
  形状（消费方代码能跑?） 不能 → 适配器 / 新 key 并存（加法原则）
  实现（内部件合适?）    不合适 → 构造注入换实现（CachePlugin(impl=RedisCache()) 同款）
  行为（要横切增强?）    要 → 包装器组件（协议化转发, 轮子本体不动）
  改轮子本体 = 影响所有消费者 → 最后手段: blast_radius 先算影响 + 上浮三问
  ```
- **契约**：输入 = 会话 meta（`create_session({"job": ...})`）；输出 = 产物（文件）或数据（记录）

## 官方教程（Skill 内嵌副本，随 Skill 分发）

写插件/壳时**直接参考教程里的完整代码示例，无需读 kernel 源码**（kernel 可能来自 pip 包 site-packages，API 以教程为准）：

| 想做什么 | 教程文件 |
|---|---|
| **API 速查（签名/服务表/SSE/换引擎/最小插件，开发时查这个）** | `tutorial/08-sdk-reference.md` |
| 换引擎/换插件（统一机制 + 引擎适配器写法） | `tutorial/08-sdk-reference.md` §8 |
| 最小插件完整示例（可整段照抄） | `tutorial/03-first-plugin.md` |
| 壳与装配（profile/shell/main/tasks/worker 代码） | `tutorial/04-app-shell.md` |
| 安装与 3 步快速开始 | `tutorial/01-installation.md` / `02-quickstart.md` |
| 工具链流程（装/看/查/升/卸/模板） | `tutorial/05-tools.md` / `07-command-reference.md` |
| 设计判断（上浮三问/契约/诚实边界） | `tutorial/06-best-practices.md` |

## 最佳实践（上浮三问）

```
① 会不会被替换？   可能换引擎/换 DB/换实现 → 上浮（隔离变更）
② 谁会用？         ≥2 个业务/应用 → 上浮（复用）
③ 会不会拖垮宿主？ 大到牵一发动全身 → 上浮（保可演进性）
```

- **能上浮 ≠ 该上浮**：promote 不拦任何插件（技术可行），三问决定（价值判断）
- **上浮 = 生命周期解绑**：私有（随应用删）→ 公共（独立生命周期，只能单独卸）
- **模板只带走公共插件**：想带进模板的先 promote（上浮 = 传承声明）
- **模板沉淀飞轮**：应用 → 沉淀公共插件 → template 提取 → 新项目从模板起步 → 再沉淀

## 常见操作流程（按目标）

### 1. 新建应用 + 插件

```bash
aic init my_app                       # ① 生成壳 + 插件骨架
# ② 三步法: ① 能力（服务类/AgentTask）② 流程（复杂才加 pipeline）
#           ③ 声明（inject/provides/apply）
# ③ 挂载: apps/my_app/profile.py 的 PLUGINS 加 MyAppPlugin()
uvicorn apps.my_app.main:app --port 8001   # ④ 启动
# ⑤ 验证: http://127.0.0.1:8001/health（plugins 含 MyAppPlugin）
```

### 2. 查看项目结构

```bash
aic graph && start graph-viz.html    # 生成并打开（力导向/代码树/过滤/弹窗）
```

用途：看清插件关系、孤儿（虚线）、共享与 AI 插件；点击插件 = 查看引用闭包与卸载影响。

### 3. 上浮为公共插件

```bash
aic promote MyPlugin                  # ① 预演: 移动/引用/标记清单
aic promote MyPlugin --yes            # ② 执行（默认到 extensions/platform/）
# ③ 验证应用仍能装配（引用更新没漏）
# ④ 之后卸载任何应用都不再删除它（独立生命周期）
```

### 4. 卸载应用

```bash
aic uninstall my_app                  # ① 预演: 删除壳+专属插件; 共享/公共保留
aic uninstall my_app --yes            # ② 执行（卸载后自动验证剩余应用）
```

### 5. 卸载插件

```bash
aic uninstall --plugin MyPlugin       # ① 预演: 有挂载/消费方会拒绝并列出
aic uninstall --plugin MyPlugin --yes # ② 执行（无阻碍时删除插件包）
```

### 6. 提取模板 / 7. 模板起步

```bash
aic template review --dry-run         # ① 预演: 公共插件 + 未上浮共享提示
aic template review --out ~/my-tpl    # ② 提取（基础 AIC + 公共插件 + hello_aic）
cd ~/my-tpl                           # ③ 进入模板
pip install -r requirements.txt       # ④ 装依赖
python test/template_check.py         # ⑤ 模板自检
aic init my_biz                       # ⑥ 在模板上加新应用
```

**范式推荐起步方式**：从模板（已验证的公共插件）开始，而不是空白骨架。

## 验证

```
python test/m0_main.py ... m7_main.py   # 回归（内核/引擎/沙箱/流水线/生产化/契约/工具）
```

改动后至少跑相关回归：内核改动跑 m0；壳/装配改动跑 m6；工具改动跑 m7。
