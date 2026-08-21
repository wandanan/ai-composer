# 框架隐藏 bug 全面审计（2026-08-21）

> 审计范围：内核 5 文件、平台服务 12 包、引擎适配器 3 个、工具链 7 命令、业务插件 4 包、壳 4 个。
> 方法：静态逐文件 + 运行时实证（内核语义均实测）+ 两路并行深扫。发现按三类归档，编号全文固定。
> 状态列：⬜ 未修 / ✅ 已修 / ⏸️ 暂缓（注明原因）。

## 背景

承接 config 形态 bug（引擎插件 dict 假设 vs ConfigService 双参）与引擎选择插件化重构，
排查同类「两层各自假设、特定组合才炸」的隐藏 bug、「正当需求被机制挡住」的阻碍、
以及「违反插件化设计」的硬编码/方向倒置。

---

## 一、运行时隐藏 bug

### 族 1：事件契约错位（0.2.1 事件注册表落地时未全量对齐，与 config 形态 bug 同根）

| # | 问题 | 证据 | 后果 | 状态 |
|---|---|---|---|---|
| 1 | hermes 适配器 emit 违反注册表：`agent/thinking` 发 `{content}`（注册表 `{delta}`）；`agent/tool_progress` 发 `{event, **kw}`（注册表 `{event_type, kw}`）；`llm/stream` 不带 session_id | `aic/extensions/platform/loops/hermes/__init__.py:87-96` vs `aic/kernel/events.py:16-20` | hermes 引擎一跑回调即 RuntimeError——自 0.2.1 后 hermes 从未真正跑通；流式也推不到 SSE | ✅ |
| 2 | ReviewPlugin 从未 `register_event`，但 `pipeline.py:26` emit `pipeline/phase` | `extensions/business/review/plugin.py:20-41`（零登记）；实测 review 壳 emit 报「事件未登记」 | 生产中被 `pipeline.py:25-28` try/except 吞掉 → 审查阶段事件静默丢失 | ✅ |
| 3 | review 引擎事件桥按错误形状读：取 `payload["content"]`/`payload["event"]`，注册表字段为 `delta`/`event_type` | `extensions/business/review/service.py:280,286` | 三重错位：hermes emit 炸内核；emit 修对后桥仍读错；连 emit 正确的 OpenAI 引擎 SSE content 也恒空 | ✅ |
| 4 | demo 插件残留 dict 形态 config 调用 `cfg.get('mode', '?')` | `extensions/business/demo/plugin.py:53` | configparser fallback 吞错返回 `''` → 静默错值（config 形态 bug 孪生） | ✅ |

### 族 2：内核语义缺陷（均运行时实证）

| # | 问题 | 实证 | 状态 |
|---|---|---|---|
| 5 | 覆盖不可恢复：A 注册 → B 覆盖 → unmount B → key 消失而非恢复 A | 实测：壳 FakeLoop 被引擎插件覆盖后 unmount，`has("agentLoop")` → False。「可逆卸载零残留」在 override 场景破缺 | ✅ |
| 6 | `register_event` 不进效果桶：unmount 后事件残留；同名事件两插件字段集不同 → 后挂载覆盖，emit 校验随挂载顺序变 | 实测：unmount 后 emit 仍成功；E1/E2 换序同一 payload 一过一报 | ✅ |
| 7 | sandbox 补丁不可重入：二次挂载 `_ORIGINAL_SEARCH_REF` 存下已补丁函数 → search 无限递归；交叠 unmount → 边界静默失效/陈旧残留；`hasattr(fo.ShellFileOperations, ...)` 求值炸 AttributeError → 已装补丁泄漏（非原子） | `aic/extensions/platform/security/sandbox.py:241-255`，与模块 docstring「零残留」承诺矛盾 | ✅ |
| 8 | `_sandboxed_resolve_path` 丢弃 task_id：相对路径一律按 `"default"` 任务 cwd 解析 | `sandbox.py:182-185` vs hermes 原函数按 task_id 取 cwd → 子代理路径基址错误 | ✅ |

### 族 3：进程/部署边界

| # | 问题 | 证据 | 状态 |
|---|---|---|---|
| 9 | 跨应用队列冲突：mvp 与 review worker 都监听 `review,followup`、共享默认 broker | `apps/mvp/worker.py:62`、`apps/review/worker.py:49`、`apps/mvp/main.py:84,126` | 双应用并行 → 任务被对面 worker 偷取 | ✅ |
| 10 | LocalStorage 默认 root=mkdtemp（每进程新目录）→ worker 进程读不到 API 写入；与 sessions 稳定共享默认不一致 | `base/storage.py:51-52` vs `session/session_service.py:33-35` | ✅ |
| 11 | DbPlugin 默认 `sqlite:///aic.db` 相对路径 → DB 位置随启动 cwd 漂移 | `base/db.py:17-18` | ✅ |
| 12 | `apps/mvp/worker.py:60` `-A mvp_app.worker`：0.2.0 改名残留可执行字符串 | 实测 `import mvp_app` → ModuleNotFoundError → `python -m apps.mvp.worker` 直接启动必炸 | ✅ |
| 13 | review workspace 每会话写进程级 `os.environ[TERMINAL_CWD/HERMES_GIT_BASH_PATH]` → 并发会话互覆 + unmount 残留 | `review/workspace.py:122-123` | ⬜ |
| 14 | import 即写 hermes 全局注册表（绕 effect 桶）：`review/tools/save_review_report.py:124`、`standard/tool.py:96` 模块级 `_register()`；standard 双实例分叉（hermes 走默认实例、ctx 走构造注入实例） | unmount 不撤销；`aic caps` 枚举即留痕 | ⬜ |
| 15 | StreamService.publish 每次新建 Redis 连接且不关闭；hermes `llm/stream` 无 session_id → bridge 警告跳过 | `stream/sse.py:88-95`、`hermes/__init__.py:88` | ⬜ |
| 16 | RedisCache 惰性连接无降级 + `ex=int(ttl)` 截断（0<ttl<1 → Redis 报错）；MinerU multipart 拼装污染 + `started_at` 类型炸轮询；extract `use_ocr` 死参数；telemetry.events 无界增长 | `base/cache.py:72-92`、`extract/mineru_client.py:59-64,96,146`、`extract/__init__.py:23-55`、`base/telemetry.py` | ⬜ |

---

## 二、框架机制阻碍

| # | 阻碍 | 现状/后果 | 状态 |
|---|---|---|---|
| 17 | 能力面校验禁止条件注册（实证「有 key 才注册」→ 装配拒绝） | 合理但推论未文档化：引擎插件必须无条件注册 + apply 校验配置。OpenAI/Hermes 插件目前不校验空配置 → 空 key 装配成功、首对话才炸，违背大声失败 | ✅ |
| 18 | 无可选依赖概念：inject 全强制 | WriterPlugin inject 含 `renderers` 又 try/except → docstring「未挂载 md 兜底」是谎言；file_convert 可选 stream 消费无拓扑保证、顺序错静默跳过（`writer/plugin.py:23,32-35`、`file_convert/plugin.py:71-75`） | ✅ |
| 19 | 无聚合键语义：`"tasks"`/`"knowledge"` 同 key 后挂载整体覆盖 | 共挂 review+writer → 一方任务字典消失 → KeyError；renderers 注册表对象（merge 安全）vs tasks dict 覆盖（危险）两范式并存，init 模板把危险范式复制给每个新插件（`init.py:242`） | ✅ |
| 20 | TYPE_CHECKING import 也被旁路扫描 → 业务插件无法类型标注平台服务，只能 Any | `kernel/imports.py` ast.walk 不区分 | ⬜ |
| 21 | ctx.get 不校验 inject 声明 → uninstall/promote/blast_radius 信任的 inject 元数据纯属自愿 | writer 消费 `agentLoop` 未声明（`writer/pipeline.py:39` vs `plugin.py:23`） | ✅ |
| 22 | profile「组合点自由」vs graph AST 扫描子集矛盾：`PLUGINS` 只认字面列表；`_scan_dynamic` 只认 `plugins = PLUGINS + [X()]` 一种形态 → mvp ConfigPlugin 覆盖、review register_task 块不可见 →「dynamic=[]」假清白；graph 少报挂载时 uninstall 可能误删「看似专属」插件 | `tools/graph.py:57-88,91-107` | ✅ |
| 23 | graph 以类名为键：用户/框架空间同名插件 → 框架条目静默覆盖用户条目 → 工具链分析错对象 | `tools/graph.py:230-233` | ✅ |
| 24 | `check_bypass_imports` 不扫 `aic/apps`（hello_aic 漏检）；组合面判定同行混 import 可绕过；`_is_plugin_base` 只认基类名恰为 Plugin | `kernel/imports.py:193`、`kernel/layout.py:128-131` | ⬜ |

---

## 三、违反插件化设计

| # | 违规 | 证据 | 状态 |
|---|---|---|---|
| 25 | 插件反向 import 应用壳（方向倒置，检查器四型之一）：`from apps.review.tasks import TASK_EXECUTE_REVIEW` | `review/service.py:564`，靠 `_DEFAULT_EXCLUDED` 豁免未被抓 → ReviewPlugin 不可移植，template 提取即坏 | ✅ |
| 26 | `_DEFAULT_EXCLUDED` 把整个 review 业务线豁免于旁路检查 → 最大业务插件不受核心纪律约束（#25 直接后果） | `kernel/imports.py:51` | ⬜ |
| 27 | template 硬编码插件构造知识：`_mount_line` 特判 ConfigPlugin/JobsPlugin；生成的 ConfigPlugin 挂载行无 APP_ENV 选择（与 init 模板不一致） | `tools/template.py:184-191` | ⬜ |
| 28 | template `_IMPORT_TO_PKG` 与 pyproject dependencies 双源手动同步；import 反推漏未知包 → 模板缺依赖 | `tools/template.py:35-43` | ⬜ |
| 29 | promote 三处：`--to ../x` 可逃出项目根；`_write_public` 静默不写却照打「已写入」（文件任意处含 `PUBLIC = True` 子串即跳过，注释也算）；`_verify` 只验布局不验重写后 import 可用性 → 假绿 | `tools/promote.py:115-126,91-103,178-192` | ⬜ |
| 30 | caps：hermes 存在却永不出现在引擎清单（loops/__init__ 不导出）；`_SECTIONS` 死常量；`engines = ...` 赋值非 extend；self 剥离死代码 → 换法列噪音 | `tools/caps.py:28,73-79,157-162` | ⬜ |
| 31 | 文档漂移一族：mvp profile/main/shell 仍描述已删的 KIT_ENGINE；`layout.py:10` 还说「shell.py 的 load_config 硬编码读它」；kernel docstring 旧品牌 agent-service-kit；教程 `foundation.md:363` emit `convert/done` 用 `{file}` 而插件声明 `{output}`（照抄即炸）；tutorial 03/04/08 todo 示例存在于 `aic/tools/assets/skills/`（随 aic init 分发） | 多处 | ⬜ |

---

## 修复计划

**P0（真引擎/双应用一跑就坏）**：#1、#2、#3（同一处事件契约对齐，一次修）、#9、#12、#7、#4
**P1（语义承诺破缺）**：#5、#6、#17、#19、#25
**P2（机制补全）**：#18、#21、#22、#23、#10、#11
**P3（卫生）**：#8、#13-#16、#20、#24、#26-#31

## 修复记录

### 2026-08-21 P0 + P1（已完成, 回归 m0–m7/m1b 全绿）

**P0**

- **#1 hermes 事件契约**（`loops/hermes/__init__.py`）: `agent/thinking` 改发 `{delta}`; `llm/stream` 补 `session_id`（顺带修复 #15 的 hermes 流式推不到 SSE）; `agent/tool_progress` 改发 `{event_type, kw}`（内部 `**tkw` 消除 kw 遮蔽）。实证: 正确形状过注册表校验, 旧形状被拒。
- **#2 ReviewPlugin 补事件登记**（`review/plugin.py`）: `register_event("pipeline/phase", {session_id, phase})` + `stream.bridge`。`pipeline.py` 的 try/except 吞错移除 → 契约内大声失败; 顺手删掉因此闲置的 logging。
- **#3 review 引擎桥读对字段**（`review/service.py`）: tool_progress 读 `event_type`+`kw`; 其他事件 content 取自 `delta`（OpenAI 引擎 emit 正确但桥读错 → SSE content 恒空, 一并修复）。
- **#9 队列应用域化**（`apps/mvp/main.py`/`worker.py`）: enqueue 队列 `review/followup` → `mvp/mvp_followup`, worker `-Q` 同步; 消除与 review 应用共享 broker 时的跨应用偷任务。
- **#12 mvp_app 残留**（`apps/mvp/worker.py`）: 可执行字符串 `-A mvp_app.worker` → `apps.mvp.worker`（直接启动路径修复）; 同文件 docstring 与 main.py/profile.py/shell.py 的 KIT_ENGINE 残留描述一并清理（部分 #31）。
- **#7 sandbox 补丁可重入**（`security/sandbox.py`）: 引用计数 `_PATCH_STATE` + 锁——重复挂载只计数不重复捕获（根治自引用递归）; 交叠卸载末次才还原; 安装先全量解析目标再动手（原子性, `getattr(fo, "ShellFileOperations", None)` 修掉 AttributeError 泄漏路径）。实证: 双挂载/交叠卸载/重挂全场景零残留。**#8 顺带修复**: `_check_boundary` 透传 task_id, 相对路径按各任务 live-tracking cwd 解析（不再一律 "default"）。
- **#4 demo config 形态**（`demo/plugin.py`）: dict 单参 → ConfigService 双参 `cfg.get("llm", "LLM_PROVIDER", "unset")`; m0 的 dict config 同步换 ConfigService（形态统一）。

**P1**

- **#5 覆盖可恢复**（`kernel/kernel.py`）: register 改 per-key 注册栈, dispose 恢复最近仍存活实现。实证: 壳 FakeLoop 被引擎覆盖后 unmount → FakeLoop 恢复; 三层覆盖链正确。m0 一处断言曾把 bug 编码为预期（"平台默认也被带走"）→ 改写为新语义断言。
- **#6 事件登记可逆**（`kernel/kernel.py`）: register_event 进效果桶, unmount 撤销; 同名重登记卸载后恢复前一个声明（根治挂载顺序漂移）。均实证。
- **#17 引擎插件装配期校验**（`loops/openai`/`loops/hermes`）: apply 校验 [llm] LLM_MODEL/API_KEY/BASE_URL, 缺失即 RuntimeError（能力面校验禁止条件注册的必然推论: 无条件注册 + 装配期大声失败）。m1b 测试适配（--skip-real 填占位 key）。
- **#25 任务名常量归插件**（`review/task.py` 新增 `TASK_EXECUTE_REVIEW`）: `apps/review/tasks.py` 改为从插件 import（方向: 壳→插件）; `review/service.py` 不再反向 import 壳。
- **#19 tasks 聚合键注册表化**: 平台新增 `TaskRegistry`/`TasksPlugin`（`platform/agent`, PUBLIC）——`register(task) -> disposer`, 同名替换可恢复; `RenderRegistry.register` 同步返回 disposer。demo/hello/review/writer 四插件改 `ctx.effect(ctx.get("tasks").register(XxxTask()))`, provides 去掉 "tasks"、inject 加上; mvp/review profile 与 init 模板挂载 TasksPlugin; m0/m1/m1b/m2/m3/m4/m5 测试适配。实证: 4 任务插件共挂不互删, unmount 精确撤销。文档: quickstart/kernel-principles/review-app-architecture/08-sdk 服务表同步（08 的 6 份镜像已刷）。
  - 残留: `"knowledge"` 键 review/writer 共挂仍会覆盖（单提供方语义, 当前无共挂场景; 如需共挂需 scope 路由设计, 另议）。
- **附带**: `08-sdk-reference.md` "StreamPlugin 仅自动桥接…" 陈旧描述修正（0.2.1 已改业务声明桥接）。

**回归**: m0/m1/m1b(--skip-real)/m2/m3/m4/m4b/m4c/m5(13)/m6(44)/m7(77) 全绿;
m2/m3 外部依赖段（hermes provider、test/biz 路径）为既有环境问题, 与本次改动无关。

### 2026-08-21 P2（已完成, 回归全绿）

- **#18 内核可选依赖 `inject_optional`**（`kernel/plugin.py`/`kernel.py`）: 有提供者则拓扑排前、缺席不报错（`build_dependency_graph` 参与排序, boot 硬校验只管强制 inject; `direct_dependents`/`blast_radius` 保守计入）。实证: 乱序装配排序正确、缺席不炸、强制依赖仍大声失败。采用: WriterPlugin `inject=["sessions","tasks"]` + `inject_optional=["renderers","stream","agentLoop"]`（renderers「未挂载 md 兜底」从谎言变为机制真相）; FileConvertPlugin `inject_optional=["stream"]`。
- **#21 消费声明可见化**: writer 消费 agentLoop 补进 `inject_optional`; ReviewPlugin 删掉从未消费的 `inject "config"`（声明漂移）。graph 新增 `_scan_consumers` 咨询: 包级扫描 `ctx.get("key")` 字面消费（单参 + ctx 接收者, 排除 dict.get 误报）, 未声明的 `aic graph` 输出 ⚠️ 咨询——当前仓库零未声明。
- **#22 graph 扫描面扩展**（`tools/graph.py`）: `_scan_profile` 支持 AnnAssign 与 `PLUGINS = [...] + [...]` BinOp; `_scan_dynamic` 识别 `plugins += [X()]`/`.append(X())`/列表推导条件覆盖——mvp 的 ConfigPlugin worker 覆盖现在诚实显示为动态边（m7 t04 断言同步）。uninstall `verify_remaining` 增加 profile 导入烟测（graph AST 子集漏报挂载导致误删时, 断裂引用大声暴露）。
- **#23 同名冲突大声失败**（`tools/graph.py`）: 用户空间与框架平台插件类名冲突 → build_graph SystemExit（不再静默覆盖错对象）。
- **#10 LocalStorage 稳定默认**（`base/storage.py`）: mkdtemp 每进程新目录 → `tempdir/kit_storage` 稳定共享（与 sessions 同构, 跨进程读写不再静默断裂）。
- **#11 sqlite 路径锚定显形**（`base/db.py`）: 相对 sqlite 路径在 DbService 构造时锚定启动 cwd 为绝对路径并 log 显形（DB 位置不再随启动目录静默漂移）。

**回归**: m0–m7/m1b 全绿; graph 边数 80→83（inject_optional 边）, m7 t04 动态断言更新为 mvp ConfigPlugin。

**下一批**: P3（#13-#16、#20、#24、#26-#31 卫生项）。
