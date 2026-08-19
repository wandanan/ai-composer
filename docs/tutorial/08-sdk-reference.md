# 08 - SDK 参考（API 速查）

开发时用到的全部 API 一览——写插件/壳直接查表，**无需读 kernel/ 源码**（kernel 可能来自 pip 包 site-packages，API 以本参考为准）。

## 1. 内核（kernel 包）

### Context（ctx）

| 方法 | 签名 | 说明 |
|---|---|---|
| register | `register(key, impl) -> Disposer` | 注册服务；同 key 后注册覆盖；挂载期间自动入插件桶（可逆） |
| get | `get(key) -> Any` | 按 key 取服务；未注册抛 `ServiceNotFound` |
| has | `has(key) -> bool` | key 是否已注册 |
| on | `on(event, handler, mode=EMIT) -> Disposer` | 注册事件监听；模式由首次注册决定，之后必须一致 |
| emit | `emit(event, payload=None) -> Any` | 按事件声明的模式派发；waterfall/serial 返回加工后 payload |
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
    inject: list[str] = ["sessions", "jobs"]   # 需要什么（内核据此自动推导装配顺序）
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

## 2. 协议（kernel.protocols）

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

### 其他协议

```
ToolHandler      name / toolset / schema + handle(args, **kw) -> str（业务工具）
KnowledgeProvider  scope(task_id, meta) -> list[str]（知识注入）
AgentLoop        run_conversation(user_message, conversation_history=None, **kw) -> dict
                 → 返回 {final_response, messages, token_usage, ...}; close() 释放资源
```

**AgentLoop 消费纪律**：每次调用时 `ctx.get("agentLoop")`，不缓存引用 → 引擎可任意替换。

## 3. 平台服务表（消费方永远 `ctx.get(key)`）

| key | 插件构造 | 服务 API |
|---|---|---|
| config | `ConfigPlugin(path=...)` | `get(section, key, default="")` / `get_int` / `get_bool` |
| telemetry | `TelemetryPlugin()` | `trace(event, **fields)` / `log(level, message)` |
| storage | `StoragePlugin(impl=None)` | `put(key, bytes)` / `get(key) -> bytes` / `exists(key)`；实现：LocalStorage（默认）/ MemoryStorage / MinioStorage（未接） |
| cache | `CachePlugin(impl=None)` | `set(key, value, ttl=None)` / `get(key) -> str\|None` / `set_nx(key, value, ttl=None) -> bool`（原子锁）/ `delete(key)`；MemoryCache（默认）/ RedisCache（多进程必须） |
| jobs | `JobsPlugin(impl=None, app_pkg="<应用名>")` | `register_task(name, fn)` / `enqueue(task_name, args=None, queue="default") -> task_id` / `result(task_id, timeout=None)` / `health() -> bool`；Thread/Celery/Failover 队列；**app_pkg 触发任务名协议校验** |
| db | `DbPlugin(url=None)` | `engine` / `session()`（SQLAlchemy Session）/ `create_all(base)`；模块函数 `database_url() -> str` |
| sessions | `SessionPlugin()` | `create_session(meta=None) -> Session` / `get(session_id)` / `attach(session_id, meta=None)`（跨进程重建）/ `start_turn(session) -> int`；Session 字段：`session_id` / `dir`（工作区）/ `meta` / `turn` |
| renderers | `RenderPlugin()` | `register(renderer)` / `get(name)` / `has(name)` / `names()`；渲染器协议：`name` + `render(session, *, merged, outline, version, **kw) -> 输出文件名` |
| stream | `StreamPlugin(redis_url=None)` | `subscribe(session_id) -> (实时队列, 事件快照)` / `unsubscribe(session_id, q)` / `publish(session_id, event, data)`；`redis_enabled`（跨进程走 Redis pub/sub） |
| sandbox | `SandboxPlugin()` | `set_workspace/get_workspace/clear_workspace` / `lock_dir_readonly(path)` / `unlock_dir(path)` / `sanitize_filename(filename, max_length=200)` |
| extract | `ExtractPlugin(impl=None)` | `extract(content, filename, use_ocr=False, progress_callback=None, **kw) -> str`；模块函数 `extract_document(...)`；LocalExtractor 支持 docx/pdf/MinerU |
| agentLoop | `FakeLoop(name, replies, delay)`（默认） | AgentLoop 协议（见 §2）；真实引擎 = 自挂引擎插件覆盖 |

**事件契约**：事件名由业务自定义；payload 必须携带 `session_id`（stream 依赖它路由推送）。

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
    shell.register("config", load_config())

    # 引擎是部署决策: 默认 fake（免 API 成本, 确定性）。
    # 真实引擎 = profile.py 的 PLUGINS 挂载引擎插件（提供 "agentLoop" 即覆盖 fake）。
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
    result = SHELL.get("todos").add(session.session_id, req.title)
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

## 6. 最小业务插件（照抄骨架）

```python
# extensions/business/chat/plugin.py
from kernel import Context, Plugin

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
