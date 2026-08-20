"""mvp_app/shell.py — 装配共用（API 进程与 Celery worker 进程使用同一组合）。

"应用 = 插件组合"的跨进程一致性：两处装配走同一份代码。
引擎是部署决策（KIT_ENGINE=hermes → 真实引擎; 默认 fake 免 API 成本）。
"""
from __future__ import annotations

import configparser
import os

from aic.kernel import (Context, boot, check_bypass_imports,
                    check_shell_content, check_shell_layout)
from aic.extensions.platform.loops import FakeLoop
from apps.mvp.profile import PLUGINS

_HERE = os.path.dirname(os.path.abspath(__file__))

# 默认假引擎回复（KIT_ENGINE=fake 时使用）
FAKE_REPLIES = {
    "总结": "项目概况摘要 (mvp fake)",
    "大纲": "# 施工方案大纲\n## 一、编制依据\n## 二、工程概况\n## 三、施工部署\n",
    "编制依据": "# 一、编制依据\nmvp fake 内容",
    "工程概况": "# 二、工程概况\nmvp fake 内容",
    "施工部署": "# 三、施工部署\nmvp fake 内容",
    "合并": "## 合并结果\n各章节已合并 (mvp fake)",
    "重写": "## 修订后的章节\n已按评审反馈更新 (mvp fake)",
}


def load_config(config_path: str | None = None) -> dict:
    parser = configparser.ConfigParser()
    parser.read(config_path or os.path.join(_HERE, "config", "config.local.ini"),
                encoding="utf-8")
    llm = {k: parser.get("llm", k, fallback="") for k in
           ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER")}
    return {"llm": llm}


def build_shell(config_path: str | None = None) -> tuple[Context, list]:
    """装配完整 shell（10 插件 + 引擎决策），返回 (shell, mounts)。"""
    check_shell_layout(_HERE)   # 壳布局契约: 存在性检查（机制强制）
    check_shell_content(_HERE)  # 壳布局契约: 内容检查（AST, 壳内不得有业务代码/接线）
    check_bypass_imports(os.path.dirname(os.path.dirname(_HERE)))  # 旁路 import 契约（机制强制）
    shell = Context()
    shell.register("config", load_config(config_path))

    # 引擎是部署决策: 配置了 LLM_API_KEY → OpenAI 兼容真引擎开箱即用; 否则 fake（免 API 成本）。
    # 想固定用其他引擎 → profile.py 挂载引擎插件（提供 "agentLoop" 即覆盖）。
    if shell.get("config").get("llm", {}).get("LLM_API_KEY"):
        from aic.extensions.platform.loops import OpenAIEnginePlugin
        plugins = PLUGINS + [OpenAIEnginePlugin()]
    else:
        shell.register("agentLoop", FakeLoop(name="mvp-fake", replies=FAKE_REPLIES))
        plugins = PLUGINS

    mounts = boot(shell, plugins)
    return shell, mounts
