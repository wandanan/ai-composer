"""kit/loops — Agent 引擎适配器集。

每个引擎实现 AgentLoop 协议，经 ctx.agentLoop 注册接入。
- FakeLoop: 确定性输出，不依赖 LLM（协议验证/测试/离线开发）
- HermesLoop: 真实引擎（接入 run_agent.AIAgent，需 API 密钥）
- FailoverLoop: 主引擎失败 → 备用引擎降级（API 故障兜底）
"""
from .failover_loop import FailoverLoop
from .fake_loop import FakeLoop
from .hermes_loop import HermesEnginePlugin, HermesLoop

__all__ = ["FakeLoop", "HermesLoop", "HermesEnginePlugin", "FailoverLoop"]
