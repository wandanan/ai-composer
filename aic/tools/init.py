"""tools/init.py — 初始化新应用（仓库内命令, 免手动复制）。

用法:
    python -m aic.tools.init my-app

生成:
    apps/{name}/                    精简应用壳（health 端点 + 插件组合点）
    extensions/business/{name}/     业务插件骨架（AgentTask + Plugin 引导注释）
    → 打印插件设计三步法引导

参考实现: apps/mvp/（完整示例, 不复制——新应用从精简壳起步）
"""
from __future__ import annotations

import os
import re
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _root() -> str:
    """项目根 = cwd（aic 全局命令生成到当前项目; KIT_PROJECT_ROOT 测试覆盖）。"""
    return os.environ.get("KIT_PROJECT_ROOT") or os.getcwd()

APP_MAIN = '''"""{name} — {name} 应用壳（aic.tools.init 生成）。

应用 = 平台 + 插件组合。改 profile.py 挂载业务插件。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.{name}.shell import build_shell

SHELL = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global SHELL
    SHELL = build_shell()
    yield


app = FastAPI(title="{name}", lifespan=lifespan)


@app.get("/health")
async def health():
    from aic.kernel import ServiceNotFound
    plugins = [m.plugin.__class__.__name__ for m in SHELL._mounts]
    jobs_health = "?"
    try:
        jobs_health = SHELL.get("jobs").health()
    except ServiceNotFound:
        pass
    return {{"status": "healthy", "app": "{name}", "plugins": plugins,
            "jobs_health": jobs_health}}
'''

APP_SHELL = '''"""apps/{name}/shell.py — 装配（aic.tools.init 生成）。

与 apps/mvp/shell.py 同构: 注册 config + 引擎决策 + boot 插件组合。
"""
from __future__ import annotations

import configparser
import os

from aic.kernel import (Context, boot, check_bypass_imports,
                    check_shell_content, check_shell_layout)
from apps.{name}.profile import PLUGINS

_HERE = os.path.dirname(os.path.abspath(__file__))


def load_config() -> dict:
    parser = configparser.ConfigParser()
    parser.read(os.path.join(_HERE, "config", "config.local.ini"), encoding="utf-8")
    llm = {{k: parser.get("llm", k, fallback="") for k in
           ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER")}}
    return {{"llm": llm}}


def build_shell() -> Context:
    check_shell_layout(_HERE)   # 壳布局契约: 存在性检查（机制强制）
    check_shell_content(_HERE)  # 壳布局契约: 内容检查（AST, 壳内不得有业务代码/接线）
    check_bypass_imports(os.path.dirname(os.path.dirname(_HERE)))  # 旁路 import 契约（机制强制）
    shell = Context()
    shell.register("config", load_config())

    # 引擎是部署决策: 配置了 LLM_API_KEY → OpenAI 兼容真引擎开箱即用; 否则 fake（免 API 成本）。
    # 想固定用其他引擎 → profile.py 挂载引擎插件（提供 "agentLoop" 即覆盖）。
    if shell.get("config").get("llm", {{}}).get("LLM_API_KEY"):
        from aic.extensions.platform.loops import OpenAIEnginePlugin
        plugins = PLUGINS + [OpenAIEnginePlugin()]
    else:
        from aic.extensions.platform.loops import FakeLoop
        shell.register("agentLoop", FakeLoop(name="{name}-fake"))
        plugins = PLUGINS

    mounts = boot(shell, plugins)
    shell._mounts = mounts  # health 端点展示用
    return shell
'''

APP_PROFILE = '''"""apps/{name}/profile.py — 插件组合（aic.tools.init 生成）。

应用壳的组装点: 平台插件 + 你的业务插件。
"""
from aic.extensions.platform.base import CachePlugin, ConfigPlugin, JobsPlugin, StoragePlugin, TelemetryPlugin
from aic.extensions.platform.render import RenderPlugin
from aic.extensions.platform.security import SandboxPlugin
from aic.extensions.platform.session import SessionPlugin
from aic.extensions.platform.stream import StreamPlugin
from extensions.business.{name} import {Name}Plugin   # 业务插件（import 必须在文件顶部）

PLUGINS = [
    # ── 基础设施 ──
    ConfigPlugin(path=__file__.replace("profile.py", "config/config.local.ini")),
    TelemetryPlugin(),
    StoragePlugin(),
    CachePlugin(),
    JobsPlugin(app_pkg="{name}"),   # 任务名协议（机制强制）: 注册名须与 worker 侧同名
    # ── 平台能力 ──
    SandboxPlugin(),
    SessionPlugin(),
    RenderPlugin(),
    StreamPlugin(),
    # ── 业务（③ 声明: 挂载你的业务插件, 取消注释即可）──
    {Name}Plugin(),
]
'''

APP_CONFIG = '''[llm]
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-pro
LLM_API_KEY=
LLM_PROVIDER=
'''

APP_TASKS = '''"""apps/{name}/tasks.py — 任务定义（双路径: 线程内联 + Celery worker 自举）。

空档位骨架（aic.tools.init 生成）: 同步应用可不注册任何任务, 但文件必须存在
（壳布局契约: 装配组 tasks.py/worker.py 必须齐全）。
需要异步任务时（参考 apps/mvp/tasks.py）:
  1. 定义任务名常量 TASK_X = "{name}.x"
  2. 实现 make_inline_tasks(shell) 线程降级路径（闭包捕获 shell）
  3. worker.py 用 @celery_app.task(name=TASK_X) 注册同名任务（任务名协议: 双侧同名）
"""
from __future__ import annotations

# ── 任务名常量（send_task 按名提交, worker 侧同名注册）──
# TASK_EXAMPLE = "{name}.example"


def make_inline_tasks(shell):
    """线程降级路径: 复用 API 进程 shell 的内联任务（空档位, 暂无实现）。"""
    raise NotImplementedError("空档位: 需要异步任务时按上方步骤 1-3 填充")
'''

APP_WORKER = '''"""apps/{name}/worker.py — Celery worker 入口（空档位骨架, aic.tools.init 生成）。

无任务注册时的状态:
- celery_app 存在（任务名协议的内省目标: 本模块内 @celery_app.task 注册的任务名）
- 不注册任何业务任务; 需要异步任务时按 apps/mvp/worker.py 补 @celery_app.task

启动（需 Redis broker 可用）:
    python -m apps.{name}.worker
"""
from __future__ import annotations

import os

from celery import Celery

_BROKER = os.environ.get("KIT_BROKER_URL", "redis://127.0.0.1:6379/1")

celery_app = Celery("{name}", broker=_BROKER, backend=_BROKER)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    broker_transport_options={{"visibility_timeout": 14400}},
)


def main() -> None:
    """直接启动标准 celery worker（空档位: 无业务任务, 验证/空跑用）。"""
    import subprocess
    import sys

    concurrency = os.environ.get("KIT_WORKER_CONCURRENCY", "4")
    subprocess.run([
        sys.executable, "-m", "celery", "-A", "apps.{name}.worker", "worker",
        "--loglevel=info", "--pool=threads", f"--concurrency={{concurrency}}",
        "-n", "{name}@%h", "-Q", "default",
    ], check=False)


if __name__ == "__main__":
    main()
'''

BUSINESS_INIT = '''"""extensions/business/{name} — {name} 业务插件（aic.tools.init 生成）。"""
from .plugin import {Name}Plugin

__all__ = ["{Name}Plugin"]
'''

BUSINESS_PLUGIN = '''"""extensions/business/{name}/plugin.py — {name} 业务插件骨架。

插件位置是惯例不是强制: 除地基（kernel/apps/tools）外的一切目录都是插件区,
extensions/ 是 init 模板与推荐目录（一切皆插件, 除了地基谁都可以动）。

按「插件设计三步法」填充（docs/design/business-organization.md）:
  ① 能力: 提供什么功能 → 实现服务/AgentTask（本文件下方）
  ② 流程: 功能怎么组合 → 加 pipeline.py（可选）
  ③ 声明: inject 需要什么 / provides 提供什么（本文件下方）
  调用契约: 输入=meta, 输出=产物(文件)/数据(通道) —— 运行时概念, 非设计步骤
"""
from aic.kernel import Context, Plugin
from aic.kernel.protocols import AgentTask, Phase


class {Name}Task:
    """① 能力: 业务能力定义（实现 AgentTask 协议形状, 或普通服务）。"""

    id = "{name}"

    def build_system_prompt(self, ctx: Context) -> str:
        return f"你是 {name} 任务助手。"

    def toolsets(self, phase: Phase) -> list[str]:
        return []

    def knowledge_scope(self, meta: dict) -> list[str]:
        return []

    def on_result(self, session, result):
        return {{"task": self.id}}


class {Name}Plugin(Plugin):
    """③ 声明: 插件接线（依赖 inject + 能力面 provides）。"""

    inject: list[str] = []            # 需要什么（例: ["sessions", "renderers"]）
    provides: list[str] = ["tasks", "{name}"]   # 提供什么

    def apply(self, ctx: Context):
        ctx.register("tasks", {{{Name}Task.id: {Name}Task()}})
        ctx.register("{name}", lambda: f"{name} ready")
'''


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def init_app(name: str) -> dict:
    """生成新应用: 精简壳 + 业务插件骨架。"""
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        raise SystemExit(f"应用名不合法（小写字母/数字, 下划线分隔）: {name}")

    name_cls = name.title().replace("_", "")
    ctx = {"name": name, "Name": name_cls}

    app_dir = os.path.join(_root(), "apps", name)
    biz_dir = os.path.join(_root(), "extensions", "business", name)

    _write(os.path.join(app_dir, "__init__.py"),
           f'"""apps/{name} — {name} 应用壳。"""\n')
    _write(os.path.join(app_dir, "main.py"), APP_MAIN.format(**ctx))
    _write(os.path.join(app_dir, "shell.py"), APP_SHELL.format(**ctx))
    _write(os.path.join(app_dir, "profile.py"), APP_PROFILE.format(**ctx))
    _write(os.path.join(app_dir, "tasks.py"), APP_TASKS.format(**ctx))
    _write(os.path.join(app_dir, "worker.py"), APP_WORKER.format(**ctx))
    _write(os.path.join(app_dir, "config", "config.local.ini"), APP_CONFIG)

    _write(os.path.join(biz_dir, "__init__.py"), BUSINESS_INIT.format(**ctx))
    _write(os.path.join(biz_dir, "plugin.py"), BUSINESS_PLUGIN.format(**ctx))

    return {"name": name, "Name": name_cls,
            "app_dir": app_dir, "biz_dir": biz_dir}


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        raise SystemExit("用法: aic init <应用名>  （如 my-app → my_app）")
    if args[0] in ("-h", "--help"):
        print("用法: aic init <应用名>  （如 my-app → my_app）")
        return
    name = args[0].replace("-", "_")
    r = init_app(name)
    print(f"✅ 新应用已生成: {r['name']}")
    print(f"   应用壳:  {r['app_dir']}")
    print(f"   业务插件: {r['biz_dir']}")
    print()
    print("下一步（插件设计三步法, 详见 docs/design/business-organization.md）:")
    print(f"  ① 能力:   extensions/business/{r['name']}/plugin.py 实现服务/AgentTask")
    print(f"  ② 流程:   加 pipeline.py（可选, 能力即流程则跳过）")
    print(f"  ③ 声明:   {r['Name']}Plugin.provides/inject（已注释引导）")
    print("  契约:    输入=meta, 输出=产物/数据（约定格式, 非设计步骤）")
    print(f"  异步任务: apps/{r['name']}/tasks.py + worker.py（空档位骨架已生成, 需要时填充）")
    print()
    print("  验证: PYTHONIOENCODING=utf-8 python -m uvicorn "
          f"apps.{r['name']}.main:app --port 8008")


if __name__ == "__main__":
    main()
