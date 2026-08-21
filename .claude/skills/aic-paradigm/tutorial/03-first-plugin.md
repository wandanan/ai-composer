# 03 - 开发第一个业务插件

本教程的目标：用**三步法**写一个完整的业务插件——以待办管理（todo）为例，不依赖任何 LLM。

## 三步法：为什么是这三步

写一个插件只需回答三个问题：

```
① 能力   这个业务提供什么功能？    → 写服务类
② 流程   功能怎么组合成流程？      → 单步操作可跳过
③ 声明   要什么 / 给什么？         → inject / provides / apply
```

**为什么需要流程（②）？** 能力是一步操作（如"转换文件"），但用户点一次往往背后是多步：
校验参数 → 转换 → 落盘 → 通知。没有流程，这几步得由每个调用方自己编排——重复又易错。
有流程，调用方只说"帮我转换"，内部几步封装在插件里。

> 类比：餐厅点"鱼香肉丝"（能力），后厨"洗→切→炒→装盘"（流程）——封装在后厨，你不需要指挥每一步。

**为什么需要声明（③）？** 你只写 `inject=["storage"]`，内核的装配自动保证 storage 先装、你后装——顺序不用你管。

## ① 能力：写服务类

`extensions/business/my_app/plugin.py`——`MyAppPlugin` 类的下方加入：

```python
class TodoService:
    """待办管理: 增/查/改/完成。纯逻辑, 数据经平台存储协议持久化。"""

    def __init__(self, ctx):
        self.ctx = ctx

    def _key(self, session_id: str) -> str:
        return f"todo:{session_id}"

    def list(self, session_id: str) -> list:
        raw = self.ctx.get("storage").get(self._key(session_id))
        return json.loads(raw) if raw else []

    def add(self, session_id: str, title: str) -> dict:
        items = self.list(session_id)
        item = {"id": len(items) + 1, "title": title, "done": False}
        items.append(item)
        self.ctx.get("storage").put(self._key(session_id),
                                    json.dumps(items, ensure_ascii=False).encode())
        return item

    def complete(self, session_id: str, todo_id: int) -> dict:
        items = self.list(session_id)
        for item in items:
            if item["id"] == todo_id:
                item["done"] = True
                break
        self.ctx.get("storage").put(self._key(session_id),
                                    json.dumps(items, ensure_ascii=False).encode())
        return {"ok": True}
```

> **注意（能力的 IO 边界）**：服务类不直接写文件、不直接连数据库——**落盘必须走显式通道**：
> - 数据存取 → `ctx.get("storage").put/get(...)`（数据通道，协议化，换实现零改动）
> - 产物落盘 → `save_artifact(session.dir, kind, name, content)`（产物通道，流程里做）
>
> 直接写文件 = 绑定本地磁盘（换 MinIO 就废）+ 落盘行为不可追踪。走显式通道 = 可替换 + 可追踪。

## ② 流程：单步操作可跳过

待办的增删改查都是单步操作——**能力即流程**，不需要 pipeline。复杂的多阶段业务（如方案编写流水线）才需要单独写 pipeline.py：

```python
class ConvertPipeline:
    """转换流程: 校验 → 转换 → 产物落盘 → 广播事件。"""

    def run(self, session, content, src_type, dst_type):
        svc = self.ctx.get("converter")                    # 取能力（get, 不 import）
        result = svc.convert(content, src_type, dst_type)  # 调能力（纯逻辑）
        save_artifact(session.dir, "output", name, result) # 落产物通道
        self.ctx.emit("convert/done", {...})               # 广播事件（进度可观察）
        return {"output": name}
```

## ③ 声明：接线

```python
class MyAppPlugin(Plugin):
    """③ 声明: 插件接线。"""

    inject: list[str] = ["storage"]          # 要什么（平台能力）
    provides: list[str] = ["todos", "my_app"]   # 给什么

    def apply(self, ctx: Context):
        ctx.register("todos", TodoService(ctx))    # 把能力放进背包
        ctx.register("my_app", lambda: "ready")
```

- `inject` 声明依赖——内核自动保证 storage 先装配（拓扑排序，乱序传入也能排对）
- `provides` 声明能力——其他插件/应用壳按 key 取用
- `apply` 是接线动作——装配时被内核调用一次

## 挂载到应用

`apps/my_app/profile.py` 的 `PLUGINS` 列表中加入：

```python
from extensions.business.my_app import MyAppPlugin

PLUGINS = [
    # ... 平台插件 ...
    MyAppPlugin(),          # ← 你的业务插件
]
```

## 契约：输入与输出

写插件前先约定两件事（就像写函数的签名）：

```
输入 = 会话 meta         create_session({"job": "todo"})
                         aic_session_id / meta / dir / turn（平台生成; aic_ 前缀与业务 id 隔离）
输出 = 两种形态:
  产物通道（文件）        save_artifact(...) —— 要下载/版本化的成果
  数据通道（记录）        ctx.get("storage").put(...) —— 要持续增删改查的记录
```

选哪个由"结果怎么被使用"决定：审查报告 → 产物通道；待办记录 → 数据通道。

## 启动并验证

```bash
uvicorn apps.my_app.main:app --port 8001
```

```bash
# 创建一个待办列表（一个列表 = 一个会话）
curl -X POST http://127.0.0.1:8001/api/v1/lists

# 添加待办
curl -X POST http://127.0.0.1:8001/api/v1/lists/<session_id>/todos \
  -H "Content-Type: application/json" -d '{"title": "写报告"}'
# 预期: {"id": 1, "title": "写报告", "done": false}

# 查询列表
curl http://127.0.0.1:8001/api/v1/lists/<session_id>/todos
```

> **注意**：端点在 `main.py` 中定义（壳只做"校验 → 调能力 → 返回"），业务逻辑全部在插件里。
> 如果你写了业务逻辑进 main.py——壳的内容检查会在装配时拦截。

## 让插件由 AI 驱动（可选）

如果能力由 LLM 引擎驱动，实现 `AgentTask` 协议形状（引擎每次跑任务向你问四个问题）：

```python
class MyTask:
    id = "my-app"

    def build_system_prompt(self, ctx): ...   # 引擎问: 系统提示词?
    def toolsets(self, phase): ...            # 引擎问: 配什么工具?
    def knowledge_scope(self, meta): ...      # 引擎问: 需要哪些知识?
    def on_result(self, session, result): ... # 引擎问: 结果怎么收拾?
```

普通服务类没有这些方法——因为没有人需要问它。**AI 只是能力的一种形状，范式不绑定 AI**。

## 下一步

进入 [04 - 应用壳与装配](04-app-shell.md)，理解壳的完整形态（引擎决策、异步任务）。
