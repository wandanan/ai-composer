"""aic.kernel.events — 事件契约注册表（0.2.1 事件注册表）。

事件名是跨组件的字符串契约——emit 与 on 靠名字对齐, 拼错即静默失败
（SSE 前端等不到进度, 不报错）。注册表把它变成大声失败:
- 未登记事件 → emit 时 RuntimeError（可用事件清单随报错给出）
- payload 含未声明字段 → emit 时 RuntimeError

内核预登记 = **引擎协议事件**（平台能力契约, 无业务色彩）;
业务事件（pipeline/phase、convert/done 等）由业务插件 apply 里
`ctx.register_event(name, payload_fields)` 声明——全局生效, 一次登记处处 emit。
"""
from __future__ import annotations

# 引擎协议事件（llm/stream 由 OpenAI/hermes 引擎 emit; hermes 另有 4 个回调事件）
# 命名约定（0.2.2.post1）: 事件 payload 是跨插件字符串契约, 框架保留字段一律 aic_ 前缀——
# 与业务事件的字段（chapter_no/name/job 等）从命名空间隔离, 杜绝同名字段互相混淆。
EVENT_REGISTRY: dict[str, dict] = {
    "llm/stream":          {"payload": {"aic_session_id", "delta"}},
    "agent/thinking":      {"payload": {"delta"}},
    "tools/pre-execute":   {"payload": {"call_id", "aic_name", "args"}},
    "tools/post-execute":  {"payload": {"call_id", "aic_name", "result"}},
    "agent/tool_progress": {"payload": {"event_type", "kw"}},
}
