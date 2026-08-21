"""mvp_app/shell.py — 装配共用（API 进程与 Celery worker 进程使用同一组合）。

"应用 = 插件组合"的跨进程一致性：两处装配走同一份代码。
引擎是部署决策（插件化）: 壳默认 fake; profile 挂引擎插件即覆盖。
"""
from __future__ import annotations

import os

from aic.kernel import (Context, boot, check_bypass_imports,
                    check_shell_content, check_shell_layout)
from aic.extensions.platform.loops import FakeLoop
from apps.mvp.profile import PLUGINS

_HERE = os.path.dirname(os.path.abspath(__file__))

# 默认假引擎回复（未挂引擎插件时使用）
FAKE_REPLIES = {
    "总结": "项目概况摘要 (mvp fake)",
    "大纲": "# 施工方案大纲\n## 一、编制依据\n## 二、工程概况\n## 三、施工部署\n",
    "编制依据": "# 一、编制依据\nmvp fake 内容",
    "工程概况": "# 二、工程概况\nmvp fake 内容",
    "施工部署": "# 三、施工部署\nmvp fake 内容",
    "合并": "## 合并结果\n各章节已合并 (mvp fake)",
    "重写": "## 修订后的章节\n已按评审反馈更新 (mvp fake)",
}


def build_shell(config_path: str | None = None) -> tuple[Context, list]:
    """装配完整 shell（10 插件 + 默认 fake 引擎），返回 (shell, mounts)。"""
    check_shell_layout(_HERE)   # 壳布局契约: 存在性检查（机制强制）
    check_shell_content(_HERE)  # 壳布局契约: 内容检查（AST, 壳内不得有业务代码/接线）
    check_bypass_imports(os.path.dirname(os.path.dirname(_HERE)))  # 旁路 import 契约（机制强制）
    shell = Context()

    # 引擎是部署决策（插件化）: 壳只提供默认 FakeLoop（免 API 成本）;
    # profile.py 挂载引擎插件（提供 "agentLoop" 即覆盖）→ 换引擎零壳改动。
    shell.register("agentLoop", FakeLoop(name="mvp-fake", replies=FAKE_REPLIES))
    plugins = PLUGINS
    if config_path:  # Celery worker: 运行时注入配置路径（组合点覆盖 profile 的 ConfigPlugin）
        from aic.extensions.platform.base.config import ConfigPlugin
        plugins = [ConfigPlugin(path=config_path)
                   if isinstance(p, ConfigPlugin) else p for p in plugins]

    mounts = boot(shell, plugins)
    return shell, mounts
