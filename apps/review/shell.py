"""apps/review/shell.py — 装配（与 apps/mvp/shell.py 同构）。

建背包 → 注册 config → 引擎决策（KIT_ENGINE=hermes 真实引擎, 默认 fake）→ boot。
"""
from __future__ import annotations

import configparser
import os

from kernel import Context, boot, check_shell_content, check_shell_layout

from apps.review.profile import PLUGINS

_HERE = os.path.dirname(os.path.abspath(__file__))


def load_config() -> dict:
    parser = configparser.ConfigParser()
    parser.read(os.path.join(_HERE, "config", "config.local.ini"), encoding="utf-8")
    llm = {k: parser.get("llm", k, fallback="") for k in
           ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER")}
    return {"llm": llm}


def build_shell() -> Context:
    check_shell_layout(_HERE)   # 壳布局契约: 存在性检查（机制强制）
    check_shell_content(_HERE)  # 壳布局契约: 内容检查（AST, 壳内不得有业务代码/接线）
    shell = Context()
    shell.register("config", load_config())

    # 引擎是部署决策: 默认 fake（免 API 成本, 确定性）。
    # 真实引擎 = profile.py 的 PLUGINS 挂载引擎插件（提供 "agentLoop" 即覆盖 fake）。
    from extensions.platform.loops import FakeLoop
    shell.register("agentLoop", FakeLoop(name="review-fake"))
    plugins = PLUGINS

    mounts = boot(shell, plugins)
    shell._mounts = mounts  # health 端点展示用

    # 注册审查任务（线程内联降级 + Celery worker 同名任务）
    from apps.review.tasks import TASK_EXECUTE_REVIEW, make_execute_review
    try:
        shell.get("jobs").register_task(
            TASK_EXECUTE_REVIEW, make_execute_review(shell))
    except Exception as e:  # jobs 未就绪/降级不影响装配
        print(f"[review] 任务注册失败: {e}")

    return shell
