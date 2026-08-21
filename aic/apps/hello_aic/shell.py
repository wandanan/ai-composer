"""apps/hello_aic/shell.py — 装配（aic.tools.init 生成）。

与 apps/mvp/shell.py 同构: 默认 FakeLoop + boot 插件组合（引擎插件挂载即覆盖）。
"""
from __future__ import annotations

import os

from aic.kernel import (Context, boot, check_bypass_imports,
                    check_shell_content, check_shell_layout)
from aic.extensions.platform.loops import FakeLoop
from aic.apps.hello_aic.profile import PLUGINS

_HERE = os.path.dirname(os.path.abspath(__file__))


def build_shell() -> Context:
    check_shell_layout(_HERE)   # 壳布局契约: 存在性检查（机制强制）
    check_shell_content(_HERE)  # 壳布局契约: 内容检查（AST, 壳内不得有业务代码/接线）
    # 框架内应用（aic/apps/hello_aic）: 项目根 = 上三级（用户应用在根 apps/, init 模板是上两级）
    check_bypass_imports(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))  # 旁路 import 契约（机制强制）
    shell = Context()

    # 引擎是部署决策（插件化）: 壳只提供默认 FakeLoop（免 API 成本）;
    # profile.py 挂载引擎插件（提供 "agentLoop" 即覆盖）→ 换引擎零壳改动。
    shell.register("agentLoop", FakeLoop(name="hello_aic-fake"))
    mounts = boot(shell, PLUGINS)
    shell._mounts = mounts  # health 端点展示用
    return shell
