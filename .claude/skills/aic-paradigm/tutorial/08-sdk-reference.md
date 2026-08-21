# 08 - SDK 参考（API 速查）

开发时用到的全部 API 一览——写插件/壳直接查表，**无需读 kernel/ 源码**（kernel 可能来自 pip 包 site-packages，API 以本参考为准）。

## 0. 统一入口（0.2.0 命名空间重构）

框架包全部在 `aic/` 下（`aic.kernel` / `aic.extensions.platform` / `aic.tools` /
`aic.apps.hello_aic`）；**用户业务平铺项目根**（`apps/` + `extensions/business/`）——
安装包只装 aic，顶层命名冲突根治（0.1.x 的平铺 kernel/extensions/apps/tools 是旧形态）。

```python
import aic
aic.__version__                                   # "0.2.2.post2"
from aic import Context, boot, Plugin             # 统一入口（与 aic.kernel 等价）
from aic.extensions.platform.base import StoragePlugin      # 平台插件
from aic.extensions.platform.loops import OpenAIEnginePlugin  # 引擎
from apps.my_app.profile import PLUGINS           # 用户应用（平铺）
from extensions.business.my_app import MyAppPlugin          # 用户业务插件（平铺）
```

**平台两层**：`aic/extensions/platform`（框架平台，只读——内置插件）与项目根
`extensions/platform`（项目平台——`aic promote` 上浮目标，可写）。caps/graph
把两处合并展示。

## 1. 内核（kernel 包）

### Context（ctx）

| 方法 | 签名 | 说明 |
|---|---|---|
| register | `register(key, impl) -> Disposer` | 注册服务；同 key 后注册覆盖；挂载期间自动入插件桶（可逆） |
| get | `get(key) -> Any` | 按 key 取服务；未注册抛 `ServiceNotFound` |
| has | `has(key) -> bool` | key 是否已注册 |
| on | `on(event, handler, mode=EMIT) -> Disposer` | 注册事件监听；模式由首次注册决定，之后必须一致 |
| emit | `emit(event, payload=None) -> Any` | 按事件声明的模式派发；waterfall/serial 返回加工后 payload；**事件契约校验**（0.2.1）：未登记事件 / payload 超集声明字段 → RuntimeError |
| register_event | `register_event(name, payload_fields=None, mode=EMIT)` | 声明事件契约（0.2.1）：业务插件 apply 里登记；内核预登记引擎事件（llm/stream 等 5 个）；一次登记全局生效 |
| mount | `mount(plugin) -> PluginMount` | 挂载插件：apply 效果入桶 + 能力面校验 |
| unmount | `unmount(mount)` | 逆序撤销该插件全部效果，零残留 |
| effect | `effect(disposer)` | 注册可逆效果（挂载期间自动入插件桶） |

`EventMode` 四种派发模式：

```
EMIT      观察: 监听器按注册顺序执行, 不等待, 无返回值
WATERFALL 中间件: handler(payload, next); 不调 next() 即短路
SERIAL    顺序加工: 返回值传给下一个监听器
PARALLEL  扇出: 并发执行
```

### Plugin 基类（kernel.Plugin）

```python
class MyPlugin(Plugin):
    inject: list[str] = ["sessions", "jobs"]   # 强制依赖（缺席装配报错）
    inject_optional: list[str] = ["stream"]    # 可选依赖（有则排序, 缺席不报错）
    provides: list[str] = ["my"]               # 提供什么（能力面校验依据）

    def apply(self, ctx: Context):             # 注册服务/监听/效果（一切自动可逆）
        ctx.register("my", MyService())
```

### 装配函数

```
boot(root, plugins) -> list[PluginMount]      拓扑装配: 乱序传入也能排对, 依赖环 → RuntimeError
blast_radius(plugins, plugin) -> list         撤销影响闭包（间接依赖全部）
direct_dependents(plugins, plugin) -> set     直接依赖方
```

**能力面校验**（mount 时自动，双向核对，违规装配即报错）：

```
apply 注册了 provides 未声明的 key   → 未声明注册（偷偷提供能力）
provides 声明了但 apply 没注册       → 声明未注册（承诺不兑现）
```

## 2. 协议（0.2.1 内核零 AI: AI 协议归宿平台层）

内核 = 纯机制，**不承载任何 AI 协议**。协议按能力域内聚：

```
引擎协议   from aic.extensions.platform.loops import AgentLoop     （跟引擎实现同包）
AI 任务协议 from aic.extensions.platform.agent import AgentTask, Phase, ToolHandler, KnowledgeProvider
```

### AgentTask（一个业务 = 一个任务，实现协议形状即可，无需继承）

```python
class MyTask:
    id = "my"                                      # 任务 id

    def build_system_prompt(self, ctx) -> str: ...  # 组装系统提示词
    def toolsets(self, phase: Phase) -> list[str]: ...   # 主代理工具集（按阶段）
    def knowledge_scope(self, meta: dict) -> list[str]: ...  # 知识注入范围
    def on_result(self, session, result) -> Any: ...      # 结果处理
```

`Phase`: `FIRST = "first"`（首轮）/ `FOLLOWUP = "followup"`（追问轮）

**AI 任务的接线**（inject `tasks` + 登记进聚合注册表, 不 `ctx.register("tasks", dict)`）:

```python
class MyAppPlugin(Plugin):
    inject = ["tasks"]                          # 任务注册表（TasksPlugin 提供, 聚合键）
    provides = ["my_app"]                       # 能力面（不含 tasks）

    def apply(self, ctx):
        ctx.effect(ctx.get("tasks").register(MyTask()))   # 登记, unmount 可撤销
        ctx.register("my_app", MyService(ctx))
```

### 其他协议

```
ToolHandler      name / toolset / schema + handle(args, **kw) -> str（业务工具）
KnowledgeProvider  scope(task_id, meta) -> list[str]（知识注入）
AgentLoop        run_conversation(user_message, conversation_history=None, **kw) -> dict
                 → 返回 {final_response, messages, token_usage, ...}; close() 释放资源
                 流式: 引擎逐片 emit "llm/stream" 事件（payload: {aic_session_id, delta}）,
                 aic_session_id 来自 **kw 的 aic_session_id 参数——SSE 打字机效果靠它
```

**AgentLoop 消费纪律**：每次调用时 `ctx.get("agentLoop")`，不缓存引用 → 引擎可任意替换。
**引擎是"哑的"**：角色提示词/工具集由调用方经 `**kw` 传入（`system_prompt` / `toolsets` / `aic_session_id`），
引擎不组装业务 prompt——换引擎业务零改动。

## 3. 平台服务表（消费方永远 `ctx.get(key)`）

| key | 插件构造 | 服务 API |
|---|---|---|
| config | `ConfigPlugin(path=...)` | `get(section, key, default="")` / `get_int` / `get_bool` |
| telemetry | `TelemetryPlugin()` | `trace(event, **fields)` / `log(level, message)` |
| storage | `StoragePlugin(impl=None)` | `put(key, bytes)` / `get(key) -> bytes` / `exists(key)`；实现：LocalStorage（默认）/ MemoryStorage / MinioStorage（未接） |
| cache | `CachePlugin(impl=None)` | `set(key, value, ttl=None)` / `get(key) -> str\|None` / `set_nx(key, value, ttl=None) -> bool`（原子锁）/ `delete(key)`；MemoryCache（默认）/ RedisCache（多进程必须） |
| jobs | `JobsPlugin(impl=None, app_pkg="<应用名>")` | `register_task(name, fn)` / `enqueue(task_name, args=None, queue="default") -> task_id` / `result(task_id, timeout=None)` / `health() -> bool`；Thread/Celery/Failover 队列；**app_pkg 触发任务名协议校验** |
| db | `DbPlugin(url=None)` | `engine` / `session()`（SQLAlchemy Session）/ `create_all(base)`；模块函数 `database_url() -> str` |
| sessions | `SessionPlugin(runtime_dir=None)` | `create_session(meta=None) -> Session` / `get(session_id)` / `attach(aic_session_id, meta=None)`（跨进程重建）/ `start_turn(session) -> int`；Session 字段：`aic_session_id` / `dir`（工作区）/ `meta` / `turn`；多机部署 `runtime_dir` 传共享目录 |
| renderers | `RenderPlugin()` | `register(renderer) -> disposer` / `get(name)` / `has(name)` / `names()`；渲染器协议：`name` + `render(session, *, merged, outline, version, **kw) -> 输出文件名` |
| tasks | `TasksPlugin()` | 聚合键（多业务插件共存）: `ctx.effect(ctx.get("tasks").register(XxxTask()))` 登记（disposer 撤销）/ `get(id)` / `[id]` / `in` / `ids()`；**勿 `ctx.register("tasks", dict)`——同 key 覆盖, 共挂互删** |
| stream | `StreamPlugin(redis_url=None)` | `subscribe(aic_session_id) -> (实时队列, 事件快照)` / `unsubscribe(aic_session_id, q)` / `publish(aic_session_id, event, data)` / `bridge(event_name)`（业务声明事件→SSE 桥接）；`redis_enabled`（跨进程走 Redis pub/sub） |
| sandbox | `SandboxPlugin()` | `set_workspace/get_workspace/clear_workspace` / `lock_dir_readonly(path)` / `unlock_dir(path)` / `sanitize_filename(filename, max_length=200)` |
| extract | `ExtractPlugin(impl=None)` | `extract(content, filename, use_ocr=False, progress_callback=None, **kw) -> str`；模块函数 `extract_document(...)`；LocalExtractor 支持 docx/pdf/MinerU |
| agentLoop | `FakeLoop(name, replies, delay)`（无配置默认）/ `OpenAIEnginePlugin()`（配好 `LLM_API_KEY` 即真引擎） | AgentLoop 协议（见 §2）；换引擎 = 换提供 agentLoop 的插件（见 §8） |

**事件契约**：事件先登记再 emit（业务插件 apply 里 `ctx.register_event(name, fields)`; 未登记/字段超集 → RuntimeError）；payload 须携带 `aic_session_id`（stream 依赖它路由推送）。`StreamPlugin` 是通用通道, 不认识业务事件——**桥接由业务声明** `ctx.get("stream").bridge(event)`（见 §5）。

## 4. 产物通道（extensions.platform.session.artifacts）

```
{session_dir}/
├── summary.md            # kind=summary
├── chapters/01_xx.md     # kind=chapters
├── merged/draft_v1.md    # kind=merged（版本化）
└── output/方案_v1.md     # kind=output（版本化）
```

```
artifact_path(session_dir, kind, name) -> str      产物绝对路径
save_artifact(session_dir, kind, name, content)    落盘, 返回路径
read_artifact(session_dir, kind, name) -> str      读取文本
list_artifacts(session_dir, kind) -> list[str]     列出文件名
next_draft_version(session_dir, kind="merged", prefix="draft_v", suffix=".md") -> int
```

## 5. 应用壳标准模式（profile / shell / main）

> **标准壳以 `aic init` 最新生成骨架为准**——存量应用升级时对照本节同步
> （尤其 shell.py 的引擎决策块），避免"能跑但不标准"的碎片化。

### profile.py — 插件清单（组装点）

```python
PLUGINS = [
    ConfigPlugin(path=...), TelemetryPlugin(), StoragePlugin(),
    CachePlugin(), JobsPlugin(app_pkg="my_app"),   # app_pkg: 任务名协议（机制强制）
    SandboxPlugin(), SessionPlugin(), RenderPlugin(), StreamPlugin(),
    MyAppPlugin(),                                 # ← 你的业务插件
]
```

### shell.py — 装配 + 引擎决策

```python
def build_shell() -> Context:
    check_shell_layout(_HERE)     # 壳布局契约: 存在性检查（机制强制）
    check_shell_content(_HERE)    # 壳布局契约: 内容检查（壳内不得有业务代码/接线）
    shell = Context()

    # 引擎是部署决策: 默认 fake（免 API 成本, 确定性）。
    # 真实引擎 = profile.py 的 PLUGINS 挂载引擎插件（提供 "agentLoop" 即覆盖 fake）。
    # config 由 profile 的 ConfigPlugin(path=...) 提供, 壳不注册 config。
    shell.register("agentLoop", FakeLoop(name="my_app-fake"))
    plugins = PLUGINS

    mounts = boot(shell, plugins)     # 自动装配: 依赖顺序不用管
    return shell
```

### main.py — 端点（只做三件事：校验 → 调能力 → 返回）

```python
SHELL = None

@asynccontextmanager
async def lifespan(_: FastAPI):
    global SHELL
    SHELL = build_shell()
    yield

@app.post("/api/v1/todos")
async def add_todo(req: TodoReq):
    session = SHELL.get("sessions").create_session({"job": "todo"})
    result = SHELL.get("todos").add(session.aic_session_id, req.title)
    return result
```

### 异步任务双路径（tasks.py + worker.py）

```
任务名 "my_app.run"（tasks.py 常量, 单一来源）
  ├─ 线程内联: API 进程闭包（jobs.register_task 注册, broker 不可用时兜底）
  └─ Celery:   worker 进程同名任务（send_task 按名分发）
```

```python
# 提交侧（端点/服务里）
jobs = SHELL.get("jobs")
jobs.register_task("chat.run", run_chat)            # 任务名协议: worker 需同名
tid = jobs.enqueue("chat.run", args=[session_id])   # 返回 task_id
result = jobs.result(tid, timeout=60)

# worker.py 侧
@celery_app.task(name="chat.run")
def run_chat(session_id: str): ...
```

### SSE 进度推送（完整可照抄）

**事件 → SSE 接线规则**（0.2.1 起）：`StreamPlugin` 是**通用通道**——不认识任何业务事件
（平台零业务耦合）。**事件先登记、桥接由业务声明**——业务插件 `apply` 里两步：

```python
class MyPlugin(Plugin):
    inject = ["stream", ...]
    provides = ["my"]

    def apply(self, ctx: Context):
        # ① 事件契约登记（未登记事件 emit 时 RuntimeError——大声失败）
        ctx.register_event("my/progress", {"aic_session_id", "pct"})
        # ② 声明桥接: 事件 → 会话推送（payload 必须携带 aic_session_id）
        ctx.get("stream").bridge("my/progress")
        ctx.register("my", MyService(...))
```

**单连接闭环端点**（创建会话 + 订阅 + 派发 + 推送 + done，一个端点走完）：

```python
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

@app.post("/api/v1/discussions")
async def create_discussion(req: DiscussReq):
    shell = SHELL
    session = shell.get("sessions").create_session({"topic": req.topic})
    svc = shell.get("stream")
    q, snapshot = svc.subscribe(session.aic_session_id)   # 先订阅, 后派发——事件不丢

    async def gen():
        try:
            yield _sse("session_created", {"session_id": session.aic_session_id})
            for item in snapshot:                      # 防御性回放（通常为空）
                yield _sse(item["event"], item["data"])
            jobs = shell.get("jobs")
            jobs.register_task(TASK_RUN, run_task)     # 双路径: 见上节
            jobs.enqueue(TASK_RUN, [session.aic_session_id])
            while True:
                try:
                    item = await asyncio.to_thread(q.get, timeout=15)
                except Exception:
                    yield _sse("heartbeat", {})        # 15s 心跳保活
                    continue
                yield _sse(item["event"], item["data"])
                if item["event"] == "my/done":
                    break
        finally:
            svc.unsubscribe(session.aic_session_id, q)     # 断连清理

    return StreamingResponse(gen(), media_type="text/event-stream")
```

要点：

```
先订阅再派发      订阅建立后才 enqueue——避免"任务快于订阅"丢事件
事件在任务/服务里发  ctx.emit("my/progress", {...}) → 桥接 → publish → SSE（双路径都走事件总线）
断连清理          finally 里 unsubscribe; 15s 心跳保活（q.get timeout）
重连场景          独立流端点同模式: subscribe → 回放 snapshot → 继续; 已完成直接断开
跨进程            StreamPlugin(redis_url=...) 时事件经 Redis pub/sub 双通道,
                  端点侧 daemon 线程桥回队列（见 aic init 骨架 + 本教程 §5 双路径）
```

## 6. 最小业务插件（照抄骨架）

```python
# extensions/business/chat/plugin.py
from aic.kernel import Context, Plugin

class ChatService:
    """① 能力: 服务类（AI 驱动时用 AgentTask, 见 §2）。"""
    def __init__(self, loop):
        self._loop = loop

    def reply(self, question: str) -> str:
        result = self._loop.run_conversation(question)   # AgentLoop 协议
        return result["final_response"]

class ChatPlugin(Plugin):
    """③ 声明: 依赖 inject + 能力面 provides。"""
    inject = ["agentLoop"]              # 需要什么
    provides = ["chat"]                 # 提供什么

    def apply(self, ctx: Context):
        # ② 接线: 从背包取依赖, 注册自己的能力
        ctx.register("chat", ChatService(ctx.get("agentLoop")))
```

挂载（profile.py 加一行）→ 消费（端点里 `SHELL.get("chat").reply(question)`）→ 启动。

## 7. 参考应用骨架：对话/问答类全链路（可整段照抄）

把 AgentLoop + 会话 + 事件桥接 + SSE + 双路径任务串成一个完整应用。
形状：**人类提问 → 两个 AI 角色轮流发言 → 全程事件推送**（圆桌对话）。

### 业务插件（能力 + 事件桥接）

```python
# extensions/business/roundtable/plugin.py
from aic.kernel import Context, Plugin, EventMode

ROLE_PROMPTS = {                      # 角色定义: 系统提示词走 **kw（引擎是"哑的"）
    "A": "你是甲方代表, 立场: 控制成本。",
    "B": "你是乙方代表, 立场: 保证质量。",
}

class RoundtableService:
    """① 能力: 圆桌讨论。"""
    def __init__(self, loop, ctx):
        self._loop, self._ctx = loop, ctx

    def turn(self, session, speaker: str, question: str) -> str:
        self._ctx.emit("roundtable/turn", {"aic_session_id": session.aic_session_id,
                                            "speaker": speaker})
        result = self._loop.run_conversation(
            question, system_prompt=ROLE_PROMPTS[speaker], toolsets=[])
        self._ctx.emit("roundtable/reply", {"aic_session_id": session.aic_session_id,
                                             "speaker": speaker,
                                             "reply": result["final_response"]})
        return result["final_response"]

class RoundtablePlugin(Plugin):
    """③ 声明 + 事件桥接（业务自定义事件要自己接线, 见 §5）。"""
    inject = ["agentLoop", "sessions", "stream"]
    provides = ["roundtable"]

    def apply(self, ctx: Context):
        svc = ctx.get("stream")
        for ev in ("roundtable/turn", "roundtable/reply"):
            ctx.on(ev, lambda p, e=ev: svc.publish(
                p.get("aic_session_id", ""), e, p), EventMode.EMIT)
        ctx.register("roundtable", RoundtableService(ctx.get("agentLoop"), ctx))
```

### 端点（SSE 闭环, 见 §5 完整模式）

```python
# apps/roundtable/main.py —— lifespan 建 SHELL（§5）+ 以下端点
@app.post("/api/v1/discussions")
async def start(req: DiscussReq):     # 完全套用 §5 单连接闭环端点
    ...                                #   session_created → roundtable/turn*
    ...                                #   roundtable/reply* → roundtable/done 断开

@app.get("/api/v1/discussions/{sid}")
async def status(sid: str):           # 状态查询: 不占 SSE 连接
    session = SHELL.get("sessions").attach(sid)
    return {"topic": session.meta.get("topic"), "turn": session.turn}
```

### 长回复任务化（可选, 双路径）

```python
# apps/roundtable/tasks.py
TASK_TURN = "roundtable.turn"                       # 任务名常量（单一来源）

def make_inline_tasks(shell):
    def run_turn(session_id: str, speaker: str, question: str):
        session = shell.get("sessions").attach(session_id)
        return shell.get("roundtable").turn(session, speaker, question)
    return run_turn

# apps/roundtable/worker.py —— 任务名协议: 与 tasks.py 同名
@celery_app.task(name="roundtable.turn")
def run_turn(session_id: str, speaker: str, question: str):
    shell = build_shell()                            # worker 自举（同一组合）
    session = shell.get("sessions").attach(session_id)
    return shell.get("roundtable").turn(session, speaker, question)
```

**多轮发言**：`turn` 计数在会话 meta 上（`session.turn`），轮次由业务编排——
引擎无跨轮记忆（每轮新建），历史要显式拼进 `question` 或 `conversation_history`。

## 8. 换引擎/换插件（同一个机制）

**一切都是组件组合**——换引擎和换插件是同一件事（插件 = 组件 + 插件声明，换插件就是换组件或换接入方式）：改 `profile.py` 的 `PLUGINS` 一行。
消费方只认 key + 协议形状（`ctx.get(key)`），永远不 import 实现。

| key | 默认实现 | 可换实现 | 换法 |
|---|---|---|---|
| agentLoop | FakeLoop（壳按配置自动决策） | `OpenAIEnginePlugin()` / 自写引擎插件 | profile.py 加/换引擎插件 |
| cache | MemoryCache（单进程） | `RedisCache(...)`（多进程必须） | `CachePlugin(impl=RedisCache())` |
| storage | LocalStorage | `MemoryStorage()` / `MinioStorage(...)` | `StoragePlugin(impl=...)` |
| jobs | ThreadJobQueue | `CeleryJobQueue(...)` / `FailoverJobQueue` | `JobsPlugin(impl=...)` |

```python
# profile.py —— 引擎是部署决策（换引擎 = 换一行）
PLUGINS = [
    ...,
    OpenAIEnginePlugin(),          # 真引擎: 覆盖壳默认 fake（config [llm] 配好即可）
    # HermesEnginePlugin(),        # 换其他引擎: 换这一行（自定义引擎见下）
]
```

**壳的默认决策**：`config [llm]` 里 `LLM_API_KEY` 非空 → 自动挂 OpenAI 兼容真引擎；
为空 → fake（离线开发零成本）。想固定用其他引擎 → profile.py 挂载对应引擎插件即覆盖。

### 写自己的引擎适配器（扩展场景——优先用内置的 `OpenAIEnginePlugin`）

> 复用优先：平台已内置 OpenAI 兼容引擎（OpenAI/DeepSeek/通义/Kimi…，配好 `LLM_API_KEY` 即用）。
> 只有需要非 OpenAI 兼容引擎时才自己写——实现 AgentLoop 协议即可挂载
> （模板：发布包内置的 `extensions/platform/loops/openai/`，抄它改引擎调用）：

```
协议形状   run_conversation(user_message, conversation_history=None, **kw) -> dict
**kw 约定  system_prompt（角色提示词）/ toolsets / aic_session_id（流式事件用）
返回       {final_response, messages, token_usage, ...}
流式       逐片 ctx.emit("llm/stream", {"aic_session_id": ..., "delta": ...}) —— 事件名与内置引擎一致
close()    释放引擎资源
```

```python
# extensions/platform/loops/myengine/__init__.py —— 仿 openai 适配器
from aic.kernel import Context, Plugin

class MyEngineLoop:
    name = "myengine"

    def __init__(self, *, model: str, api_key: str, base_url: str,
                 ctx: Context | None = None):
        ...

    def run_conversation(self, user_message, conversation_history=None, **kw):
        system_prompt = kw.get("system_prompt", "")
        aic_session_id = kw.get("aic_session_id", "")
        ...                                        # 调你的引擎 API（流式逐片）
        if self.ctx is not None:
            self.ctx.emit("llm/stream", {"aic_session_id": aic_session_id, "delta": chunk})
        return {"final_response": text, "messages": [...], "token_usage": {...}}

    def close(self) -> None:
        ...

class MyEnginePlugin(Plugin):                      # 与 OpenAIEnginePlugin 同构
    inject = ["config"]                            # LLM 配置来源
    provides = ["agentLoop"]

    def apply(self, ctx: Context):
        cfg = ctx.get("config")   # ConfigService（双参 get(section, key, default), 非 dict）
        conf = {k: cfg.get("llm", k) for k in ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL")}
        missing = [k for k in conf if not conf[k]]
        if missing:   # 装配期大声失败（能力面校验禁止条件注册 → 无条件注册 + 校验配置）
            raise RuntimeError(f"[engine] 配置缺失: [llm] {missing}")
        ctx.register("agentLoop", MyEngineLoop(
            ctx=ctx,
            model=conf["LLM_MODEL"],
            api_key=conf["LLM_API_KEY"],
            base_url=conf["LLM_BASE_URL"],
        ))
```

挂载后即覆盖 fake——业务插件、SSE 桥接、前端全部零改动（消费方只认 `agentLoop` + 协议形状）。

## 9. 跨盒 import 规则（旁路契约）

"黑箱之间藏了多少未知依赖"由结构机制回答（inject 声明 / graph / blast_radius / 装配期校验），
**旁路 import 是最后一道结构约束**：业务代码绕过 ctx 直接 import 其他扩展的实现/组件
（如 `from aic.extensions.platform.base.storage import LocalStorage`）——换实现时它还继续生效，
契约被悄悄绕过。`kernel/imports.py` 的 `check_bypass_imports` 在每次装配（build_shell）时
扫描**四区**（根 `apps/` + 根 `extensions/` + 框架 `aic/extensions/` + 框架 `aic/apps/`）的跨盒 import，
违规直接报错（`[kernel]` 前缀，收集式，sorted 确定性）。

### 三类合法跨盒 import

| 类别 | 规则 | 识别 |
|---|---|---|
| ① 组合面 | 应用壳可 import 扩展的适配器类与引擎 | 名字 `*Plugin` 结尾；或源模块在 loops 包 |
| ② 组合点 | profile.py 内实现选择自由（`JobsPlugin(impl=...)` 是文档化换法） | 文件名 == `profile.py` |
| ③ 声明工具 | 无状态纯函数公共 API，任意层可 import | 白名单（见下） |

其余跨盒 import 一律违规（违规四型，装配期 RuntimeError）：
- **应用壳直连扩展实现**（main.py/tasks.py 里 import 组件/函数/常量）→ 应走 `ctx.get(key)` 服务
- **跨应用 import**（apps.A → apps.B）→ 应用之间不得互相依赖
- **跨扩展根包旁路**（业务↔平台、业务↔业务）→ 应走 ctx 服务，或声明为公共工具
- **扩展反向 import 应用壳** → 依赖方向倒置

### 声明工具白名单（当前）

```python
UTILITY_MODULES = (
    "aic.extensions.platform.extract",            # extract_document / ALLOWED_TYPES 等（纯函数）
    "aic.extensions.platform.session.artifacts",  # save/list/read/next_draft_version（无状态文件助手）
    "aic.extensions.platform.security.sanitize",  # sanitize_filename（文件名净化）
)
```

> **新增公共工具** = 改 `kernel/imports.py` 白名单 + 同步本文档（声明强制显式，不允许静默旁路）。
> 有 ctx 服务的能力（storage/cache/jobs/agentLoop/extract 服务形态）**不走白名单**——走 `ctx.get`。

**协议面豁免**（0.2.1）：业务插件 import 平台协议（`aic.extensions.platform.agent` /
`aic.extensions.platform.loops` 协议包）合法——实现协议必须 import 形状，契约面不算旁路。

### 边界

- 默认无豁免（整仓按契约扫描）; 业务遗留债经 KIT_EXCLUDED_DIRS 精确到文件豁免
- extensions→tools 不在检查范围（sandbox 补丁/工具注册是 CLI 层附属，设计上反向）
- `importlib.import_module(f"apps.{app_pkg}.worker")` 等动态字符串形态不在此检查（运行时内省，任务名协议另管）

### 扩展 vs 修改 vs 新造（现有轮子部分满足时, 四问诊断）

判断源全在声明层（`aic caps` / 协议类）, **不看源码**：

```
语义（是不是这功能?）  不是 → 造新插件（组件 + 声明）
形状（代码能不能跑?）  不能 → 适配器 / 新 key 并存（加法原则, 老消费方零影响）
实现（内部件合适?）    不合适 → 构造注入换实现（CachePlugin(impl=RedisCache()) 同款）
行为（要横切增强?）    要 → 包装器组件（协议化转发, 轮子本体不动, 其他消费者零影响）
```

**改轮子本体 = 最后手段**：影响所有消费者——先 `blast_radius` 算影响面 + 上浮三问
（会不会被替换 / 谁会用 / 会不会拖垮宿主）, 通过才改。

优先序：扩展（注入/包装/覆盖, 影响面 1 个消费者）< 改本体（影响面所有消费者）< 新造（双份维护）。
