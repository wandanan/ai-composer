"""kit/loops — Agent 引擎适配器（平台自带: 通用, 不绑定任何真实引擎）。

每个引擎实现 AgentLoop 协议，经 ctx.agentLoop 注册接入。
- FakeLoop: 确定性输出，不依赖 LLM（协议验证/测试/离线开发, 平台默认）
- FailoverLoop: 主引擎失败 → 备用引擎降级（API 故障兜底）

真实引擎（如 Hermes）作为独立插件挂载: profile.py 里加入提供 "agentLoop" 的引擎
插件即覆盖 FakeLoop。见 extensions/platform/loops/hermes/（不进发布包）。
"""
from .failover_loop import FailoverLoop
from .fake_loop import FakeLoop

__all__ = ["FakeLoop", "FailoverLoop"]
