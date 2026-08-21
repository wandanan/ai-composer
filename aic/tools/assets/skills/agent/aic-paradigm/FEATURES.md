# 功能特性变化说明（Feature Changelog）

> 用途：指导 agent 与开发者快速了解当前框架**最新功能特性的变化与新增**。
> 写插件/壳前先看这里 + `tutorial/08-sdk-reference.md`；标注「已删除」的旧范式勿再照旧写。
> 按版本倒序：最新在前。**版本号与 `aic.__version__` 对齐**；标注「未发布」的版本段 =
> 工作区已有、但尚未随 pip 包发布（发布时同步 `pyproject.toml` 与 `aic/kernel/__init__.py` 的版本号）。

---

## 0.2.2.post1（命名空间约定——**含破坏性变更**）

### 框架保留字段一律 `aic_` 前缀（命名空间隔离）

事件 payload 是跨插件字符串契约，`session_id`/`name` 这类裸名极易与业务自身 id/名称
概念混淆（例: 多章并发时 `llm/stream` 的 session_id 与业务的 chapter_no/task_id 并存难辨）。
0.2.2.post1 起框架保留字段统一 `aic_` 前缀：

| 位置 | 旧（0.2.2 及之前） | 新（0.2.2.post1） |
|---|---|---|
| 事件 payload（内核预登记 + 业务登记） | `session_id` | `aic_session_id` |
| 引擎工具事件 `tools/pre-/post-execute` | `name` | `aic_name` |
| `Session` 属性 | `session.session_id` | `session.aic_session_id` |
| 会话/推送服务签名 | `get/attach/subscribe/publish(session_id)` | 参数名 `aic_session_id`（位置传参不受影响） |
| AgentLoop `**kw` 约定 | `session_id` | `aic_session_id` |

**破坏性（升级 0.2.2.post1 的既有项目必须同步）**：
- 业务插件 `register_event(..., {"session_id", ...})` / `emit(..., {"session_id": ...})` → 改 `aic_session_id`
- 代码里 `session.session_id` → `session.aic_session_id`
- 调 `run_conversation(..., session_id=sid)` → `aic_session_id=sid`
- 业务**自己的** id 概念（本地变量、DB 字段、URL 路径参数、对前端的 JSON key）**不用改**——前缀只约束"框架协议字段"，业务值照常放进 `aic_session_id` 字段里传。

**不改**：`delta`/`args`/`result`/`call_id`/`event_type`/`kw`（语义明确不易混淆）；
`job`（框架代码无此字段，仅是文档层 meta 约定）、`phase`（业务自定义事件字段 + `Phase` 枚举类型名，均非内核事件关键字）。

---

## 0.2.2（框架机制加固）

> 版本判定：本次主体为审计修复 + 机制补全（bug 修复/加固为 patch 级）。
> 新增的 `inject_optional`/`TasksPlugin`/`security.sanitize` 均为修复手段而非独立新功能。
> 破旧立新的「引擎选择插件化」「config 形态统一」所删旧形态在 0.2.1 中本就是临时态/已修 bug，非稳定 API 破坏。

### 一、范式变化（影响写插件/壳）

#### 1. 引擎选择插件化（变更，破旧立新）
- **新范式**：壳**零引擎逻辑**——只注册默认 `FakeLoop`（免 API 成本）；`profile.py` 挂引擎插件（提供 `"agentLoop"` 即覆盖）→ **换引擎零壳改动**。
- **已删除**（勿再写）：壳内 `if/elif` 硬编码引擎列表、`config [engine] type = fake|openai|hermes` 枚举、`if config 有 API key → 自动探测真引擎`——这些都让"新引擎 = 改壳源码"，违背插件化。
- **config 形态统一**：`ConfigService` 双参 `get(section, key, default)` 是唯一形态；引擎插件读 `[llm]` 段自己的 key。**勿**把 config 当 dict（`cfg.get("llm", {})` 是已修 bug 的旧写法）。
- 详情：`tutorial/04-app-shell.md` shell.py 示例、`tutorial/08-sdk-reference.md` §5/§8。

#### 2. inject_optional（新增：可选依赖）
- 插件新声明字段 `inject_optional: list[str]`：**有提供者则拓扑排序排前、缺席不报错**。
- 消费方 apply 里 `try/except ServiceNotFound` 降级；`inject` 仍是强制依赖（缺席装配报错）。
- 用途：如 `renderers`/`stream` 这种"有则用、无则兜底"的能力。**不声明却消费 = 依赖对 graph/uninstall 不可见**。
- 详情：`tutorial/08-sdk-reference.md` §1。

#### 3. tasks 聚合键（变更）
- **新范式**：`tasks` 是多插件共存的聚合键，用 `TasksPlugin` 提供注册表；业务插件 `inject=["tasks"]` + `ctx.effect(ctx.get("tasks").register(XxxTask()))` 登记（可撤销、共挂不互删）。
- **已删除**：`ctx.register("tasks", {XxxTask.id: XxxTask()})`——dict 后挂载整体覆盖，共挂 review+writer 会互删任务。
- `provides` 不再含 `"tasks"`。renderers 同款（`register(renderer) -> disposer`）。
- 详情：`tutorial/08-sdk-reference.md` §2「AI 任务的接线」/ §3 服务表。

#### 4. 覆盖可恢复（变更）
- `ctx.register` 改 per-key 注册栈：同 key 后注册覆盖，**unmount 覆盖者恢复前一个实现**（壳默认 FakeLoop 被引擎插件覆盖后 unmount → FakeLoop 回来，而非 key 消失）。

#### 5. 事件登记可逆（变更）
- `ctx.register_event` 进效果桶：unmount 撤销登记；同名事件重登记卸载后恢复前一个声明（emit 校验不再随挂载顺序漂移）。

#### 6. 引擎插件装配期校验（新增）
- OpenAI/Hermes 引擎插件 apply 校验 `[llm]` 必填（`LLM_MODEL`/`LLM_API_KEY`/`LLM_BASE_URL`），空配置**装配即 RuntimeError**（不再"装配成功、首对话才炸"）。
- 推论：能力面校验禁止条件注册 → 引擎插件必须**无条件注册 + apply 校验配置**。

#### 7. 声明工具 security.sanitize（新增）
- `sanitize_filename(filename, max_length=200)` 独立成纯函数模块（`aic.extensions.platform.security.sanitize`），进 `UTILITY_MODULES` 白名单——业务可 import 净化文件名（防路径遍历/非法字符）。
- 详情：`tutorial/08-sdk-reference.md` §9 白名单。

#### 8. 任务名常量归能力所有者（变更）
- 插件**自己 enqueue** 时（如 review 服务），任务名常量归插件（如 `review/task.py`），壳 `tasks.py` re-export（方向：壳→插件，不反向 import 壳）；壳 enqueue 则留在壳 `tasks.py`。
- 详情：SKILL.md「任务名协议」。

### 二、工具链变化（aic 命令）

#### 9. graph（变更）
- 扫描面扩展：profile 支持 `AnnAssign`/`PLUGINS = [...] + [...]`；动态组合识别 `+=`/`.append()`/列表推导条件覆盖（此前「dynamic=[]」是假清白）。
- 用户空间 vs 框架平台**同名插件冲突 → 大声报错**（不再静默覆盖错对象）。
- 新增「消费未声明」advisory：包级 `ctx.get(key)` 未在 `inject`/`inject_optional`/`provides` 声明 → `aic graph` 输出 ⚠️。

#### 10. caps（变更）
- 引擎清单纳入 hermes（仓库模式）；`换法` 签名剥离 `self`（无自定义 `__init__` 的插件不再显示 `(self, /, *args, **kwargs)`）。

#### 11. promote（变更）
- `--to ../x` / 绝对路径**防逃出项目根**；`PUBLIC` 标记类作用域精确判定（注释/他类 `PUBLIC = True` 不再误判"已存在"）；`_verify` 增加 profile 导入烟测（重写断裂大声暴露）。

#### 12. template（变更）
- 生成的 profile 挂 `TasksPlugin` + ConfigPlugin 走 APP_ENV 文件选择；未知第三方 import 保守保留 + ⚠️ 提示（不再静默缺包）。

### 三、默认路径（变更）
- `LocalStorage` 默认 `tempdir/kit_storage`（跨进程共享；旧 mkdtemp 每进程新目录 → worker 读不到 API 写入）。
- `DbService` sqlite 相对路径构造时**锚定绝对路径**（DB 位置不再随启动 cwd 漂移）。

---

## 0.2.1（已发布，历史基线）

- 内核零 AI：AI 协议（AgentTask/AgentLoop/ToolHandler/KnowledgeProvider）归宿平台层 `aic.extensions.platform`。
- 事件契约：事件先登记再 emit（`register_event`），未登记/字段超集 emit 报错。
- 命名空间重构（0.2.0）：框架全部收进 `aic/`，业务平铺项目根 `apps/` + `extensions/business/`。
- 统一入口：`from aic import Context, boot, Plugin`。
- 六命令：`init` / `graph` / `caps` / `promote` / `uninstall` / `template` / `skills`。
