"""biz/writer/task.py — 编写任务（AgentTask 协议实现）。"""
from __future__ import annotations

from aic.kernel import Context
from aic.extensions.platform.agent import AgentTask, Phase

# 测试/验证用确定性回复（接入真实 LLM 后由引擎输出替代）
OUTLINE_REPLY = """# 施工方案大纲
## 一、编制依据
## 二、工程概况
## 三、施工部署
## 四、主要施工工艺
## 五、质量保证措施
## 六、安全保证措施
"""

CHAPTER_REPLY = """# 一、编制依据
## 1.1 主要规范
本方案依据《公路工程施工安全技术规范》(JTG F90-2015)、《公路工程质量检验评定标准》(JTG F80/1-2017) 编制。
"""


class WriterTask:
    """编写任务：AgentTask 协议实现。"""

    id = "writer-plan"

    def build_system_prompt(self, ctx: Context) -> str:
        return "[writer] 你是施工方案编写助手，请按大纲分章编写完整方案。"

    def toolsets(self, phase: Phase) -> list[str]:
        return ["file", "context_engine"]

    def knowledge_scope(self, meta: dict) -> list[str]:
        return ["writing/standards", "writing/templates"]

    def on_result(self, session, result):
        return {"artifacts": result}
