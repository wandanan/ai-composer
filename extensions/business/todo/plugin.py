"""extensions/business/todo/plugin.py — 待办管理（非 AI 业务插件, 纯数据服务型）。

按「插件设计三步法」组织（docs/design/business-organization.md）:
  ① 能力:   TodoService（CRUD + 状态流转, 普通服务）
  ② 流程:   简单操作, 无需 pipeline（能力即流程）
  ③ 声明:   TodoPlugin（inject: ["storage"] 依赖平台存储; provides: ["todos"]）
调用契约（运行时, 非设计步骤）:
  输入: 会话 meta = {list: "todos"}（一个待办列表 = 一个会话）
  输出: 待办记录 → 数据通道（ctx.storage, 无文件产物）
"""
import json

from kernel import Context, Plugin


class TodoService:
    """③ 能力: 待办 CRUD + 状态流转（数据存对象存储）。"""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def _key(self, session_id: str) -> str:
        return f"todo/{session_id}"

    def _load(self, session_id: str) -> list[dict]:
        storage = self.ctx.get("storage")           # 依赖注入: 平台存储协议
        if storage.exists(self._key(session_id)):
            return json.loads(storage.get(self._key(session_id)).decode())
        return []

    def _save(self, session_id: str, items: list[dict]) -> None:
        self.ctx.get("storage").put(
            self._key(session_id),
            json.dumps(items, ensure_ascii=False).encode())

    def list(self, session_id: str) -> list[dict]:
        return self._load(session_id)

    def add(self, session_id: str, title: str) -> dict:
        items = self._load(session_id)
        item = {"id": len(items) + 1, "title": title, "done": False}
        items.append(item)
        self._save(session_id, items)
        return item

    def complete(self, session_id: str, todo_id: int) -> dict:
        items = self._load(session_id)
        for item in items:
            if item["id"] == todo_id:
                item["done"] = True
                self._save(session_id, items)
                return item
        raise ValueError(f"待办不存在: {todo_id}")


class TodoPlugin(Plugin):
    """⑤ 插件声明: 依赖平台存储, 提供待办能力。"""

    inject: list[str] = ["storage"]          # 需要什么: 查协议清单 → storage
    provides: list[str] = ["todos"]          # 提供什么

    def apply(self, ctx: Context):
        ctx.register("todos", TodoService(ctx))
