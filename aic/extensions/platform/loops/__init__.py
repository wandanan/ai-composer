"""kit/loops — Agent 引擎适配器（平台自带: 通用, 不绑定任何真实引擎）。

每个引擎实现 AgentLoop 协议，经 ctx.agentLoop 注册接入。
- FakeLoop: 确定性输出，不依赖 LLM（协议验证/测试/离线开发, 无配置时的默认）
- OpenAIEnginePlugin: OpenAI 兼容真引擎（OpenAI/DeepSeek/通义/Kimi...,
  纯标准库实现, 配好 LLM_API_KEY 即开箱即用）
- FailoverLoop: 主引擎失败 → 备用引擎降级（API 故障兜底）

换引擎 = 换提供 "agentLoop" 的插件（profile.py 一行）; 自定义引擎实现 AgentLoop
协议即可, 见 docs/tutorial/08-sdk-reference.md §8（引擎适配器写法）。
"""
from .failover_loop import FailoverLoop
from .fake_loop import FakeLoop
from .openai import OpenAIEnginePlugin, OpenAILoop

__all__ = ["FakeLoop", "OpenAILoop", "OpenAIEnginePlugin", "FailoverLoop"]
