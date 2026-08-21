# 04 - 应用壳与装配

本教程的目标：理解应用壳（apps/）的完整形态——五个文件的职责、引擎决策、异步任务双路径。

## 壳是什么（为什么存在）

**壳 = 组合者**：选插件清单 + 开入口，不实现任何业务能力。

```
file_convert 应用 = 10 个平台插件 + FileConvertPlugin（转换）
todo 应用        = 10 个平台插件 + TodoPlugin（待办）

平台插件不变、内核不变——只换业务插件，就是另一个应用
```

这就是"加不同业务插件 = 不同应用"的成立前提：**壳是薄薄的一层组合**，能力全在插件里。

```
apps/<app>/
├── profile.py   插件清单（选哪些插件 —— 组装点）
├── shell.py     装配（建背包 + 引擎决策 + boot）
├── main.py      HTTP 入口（端点: 校验 → 调能力 → 返回）
├── tasks.py     异步任务定义（双路径: 线程内联 + Celery）
├── worker.py    Celery worker 入口（任务独立进程执行）
└── config/      应用配置
```

## profile.py：插件清单

```python
import os
from aic.extensions.platform.agent import TasksPlugin
from aic.extensions.platform.base import (CachePlugin, ConfigPlugin, JobsPlugin,
                                          StoragePlugin, TelemetryPlugin)
from aic.extensions.platform.render import RenderPlugin
from aic.extensions.platform.security import SandboxPlugin
from aic.extensions.platform.session import SessionPlugin
from aic.extensions.platform.stream import StreamPlugin
from extensions.business.my_app import MyAppPlugin

PLUGINS = [
    # ── 基础设施 ──
    ConfigPlugin(path=__file__.replace("profile.py",
                                       f"config/config.{os.environ.get('APP_ENV', 'local')}.ini")),
    TelemetryPlugin(), StoragePlugin(), CachePlugin(),
    JobsPlugin(app_pkg="my_app"),   # app_pkg: 任务名协议（机制强制）
    # ── 平台能力 ──
    SandboxPlugin(), SessionPlugin(), RenderPlugin(), StreamPlugin(),
    TasksPlugin(),             # 任务注册表（聚合键: AI 插件登记而非 dict 覆盖）
    # ── 业务 ──
    MyAppPlugin(),             # ← 你的业务插件
]
```

## shell.py：装配与引擎决策

```python
def build_shell() -> Context:
    check_shell_layout(_HERE)    # 壳布局契约: 存在性检查（机制强制）
    check_shell_content(_HERE)   # 壳布局契约: 内容检查（壳内不得有业务代码/接线）
    check_bypass_imports(os.path.dirname(os.path.dirname(_HERE)))  # 旁路 import 契约
    shell = Context()

    # 引擎是部署决策（插件化）: 壳只提供默认 FakeLoop（免 API 成本）;
    # profile.py 挂引擎插件（提供 "agentLoop" 即覆盖）→ 换引擎零壳改动。
    shell.register("agentLoop", FakeLoop(name="my_app-fake"))
    mounts = boot(shell, PLUGINS)   # 自动装配: 依赖顺序不用管
    shell._mounts = mounts
    return shell
```

要点：

- **引擎是部署决策（插件化）**——壳只提供默认 `FakeLoop`（免 API 成本）；profile.py 挂引擎插件（提供 `"agentLoop"` 即覆盖）→ 换引擎零壳改动。**壳内不要写"探测 key 决定引擎"的条件逻辑**（新引擎就得改壳源码, 违背插件化）；config 由 profile 的 `ConfigPlugin(path=...)` 提供，壳不注册 config
- **boot 自动装配**——按 `inject`/`inject_optional`/`provides` 拓扑排序，乱序传入也能排对，依赖环直接拒绝

## main.py：HTTP 入口

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
    result = SHELL.get("todos").add(session.session_id, req.title)   # 调能力
    return result
```

**壳的纪律**：端点只做三件事——校验（Pydantic 自动）→ 调能力（`get(key)`）→ 格式化返回。不写业务逻辑。

## tasks.py / worker.py：异步任务双路径

长任务（分钟级的 LLM 调用）不能占住 HTTP 请求——任务化后走**双路径**：

```
任务名 "my_app.run"（tasks.py 常量, 单一来源）
  ├─ 线程内联: API 进程闭包（jobs.register_task 注册, broker 不可用时兜底）
  └─ Celery:   worker 进程同名任务（send_task 按名分发）
```

- `tasks.py` 定义任务名常量 + 两种 runner
- `worker.py` 用 `@celery_app.task(name=...)` 注册**同名**任务
- **任务名协议（机制强制）**：装配时校验两处同名，脱锚直接报错（防止消息进 broker 后才静默失败）
- 不部署 Redis/Celery 也能跑——线程内联自动兜底

## 壳的约束（机制强制）

壳是"一次性代码层"，范式用两道机制检查保护它：

```
① 存在性检查:  装配组 5 文件必须齐全（tasks/worker 空档位也算）
               入口组至少一个（main.py/cli.py）
               config/ 必须为目录
② 内容检查:    壳内自定义 .py 不得 import aic.extensions.*（直接拿实现）、
               不得定义 Plugin 子类、不得调用 register/emit/effect（接线动作）
```

违规 → 装配时报错（"大声失败"），而不是运行期悄悄出问题。

**为什么需要这些约束？** 壳是"每应用一份"的代码——壳里的东西永远不会被第二个应用复用。
业务逻辑放进壳 = 把可复用资产做成一次性代码。所以机制强制"能力必须落在可复用层（插件）"。

> **注意**：想往壳里放东西时先问——这是业务能力吗？→ 进插件。
> 这是通用能力吗？→ 进公共插件。壳只留"组合与入口"。

## 下一步

进入 [05 - 工具链](05-tools.md)，掌握 aic 五命令（装/看/升/卸/模板）。
