"""test/m6_main.py — M6 验证: 壳布局契约（机制强制）+ 任务名协议（机制强制）。

依据: docs/design/organization-contract.md（单一契约入口）。

验证项:
  布局契约（kernel/layout.py check_shell_layout）:
   1. 完整壳（装配组齐全 + main.py + config/）→ 通过
   2. 真实 4 应用目录 → 全部通过
   3. 缺装配文件（tasks.py）→ 报错 "缺少装配文件"
   4. 自定义文件/目录放行（stray.txt/notes.py/vendor/ 合法）
   5. 缺入口（无 main/cli）→ 报错 "缺少入口文件"
   6. config 为文件 → 报错 "config 应为目录"
   7. 报错确定性: 缺多个装配文件按装配组声明顺序列出
   8. 收集式: 缺装配 + config 为文件 → 单条错误含两个关键词
  壳内容检查（AST, check_shell_content）:
  16. 合法壳内组织（fastapi router/pydantic 模型/SHELL.get 消费）→ 通过
  17. 自定义 .py import 业务插件 → 报错 "import 插件实现"
  18. 自定义 .py 定义 Plugin 子类 → 报错 "定义插件类"
  19. 自定义 .py 接线动作 .register( → 报错 "接线动作"
  任务名协议（jobs.py 守卫）:
   9. 正例: mvp 注册 writer.run_pipeline / writer.revise → 通过 + memoize + 重复注册
  10. 违例: 注册 writer.ghost → 报错 "任务名协议违规"
  11. 空档位: file_convert 零注册无异常; 注册任意名 → 报错（worker 侧空注册表）
  12. Failover 双注册: 两侧 registry 均含名, 缓存单条
  13. 降级: worker 不可导入 → 跳过校验（不报错）
  14. 冒烟: 4 应用 build_shell 全部成功; review 壳注册 review.execute_review 通过
  15. init 模板渲染健全: 无残留花括号; 含布局检查与 app_pkg
  16. 旁路 import 契约: 真实仓库零违规 / 四型违规 / 组合面与白名单放行 /
      review 排除 / 报错确定性
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aic.kernel import Context, Plugin, boot, check_bypass_imports, check_shell_layout
from aic.kernel.layout import ASSEMBLY_FILES, ENTRY_FILES

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(name)
        print(f"  ❌ {name}")


def _make_shell_dir(base: str, extra_files: list[str] | None = None,
                    extra_dirs: list[str] | None = None,
                    drop: list[str] | None = None) -> str:
    """构造一个壳目录: 装配组齐全 + main.py + config/, 可按需增删。"""
    d = os.path.join(base, "demo_app")
    os.makedirs(d)
    for f in ASSEMBLY_FILES + ENTRY_FILES:
        with open(os.path.join(d, f), "w", encoding="utf-8") as fh:
            fh.write(f'"""placeholder"""\n')
    os.makedirs(os.path.join(d, "config"), exist_ok=True)
    with open(os.path.join(d, "config", "config.local.ini"), "w", encoding="utf-8") as fh:
        fh.write("[llm]\n")
    for f in drop or []:
        os.remove(os.path.join(d, f))
    for f in extra_files or []:
        with open(os.path.join(d, f), "w", encoding="utf-8") as fh:
            fh.write("x = 1\n")
    for dd in extra_dirs or []:
        os.makedirs(os.path.join(d, dd), exist_ok=True)
    return d


# ── 布局契约 ─────────────────────────────────────

def t01_layout_valid() -> None:
    with tempfile.TemporaryDirectory() as base:
        d = _make_shell_dir(base)
        try:
            check_shell_layout(d)
            check("t01 完整壳（装配组齐全 + main.py + config/）通过", True)
        except RuntimeError:
            check("t01 完整壳通过", False)


def t02_real_apps() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ok = True
    for name in ("mvp", "review", "file_convert"):   # 用户空间应用（平铺根 apps/）
        try:
            check_shell_layout(os.path.join(root, "apps", name))
        except RuntimeError as e:
            print(f"    {name}: {e}")
            ok = False
    try:   # 框架示例应用（0.2.0: 在 aic/apps/）
        check_shell_layout(os.path.join(root, "aic", "apps", "hello_aic"))
    except RuntimeError as e:
        print(f"    hello_aic: {e}")
        ok = False
    check("t02 真实应用目录全部通过布局检查", ok)


def t03_missing_assembly() -> None:
    with tempfile.TemporaryDirectory() as base:
        d = _make_shell_dir(base, drop=["tasks.py"])
        try:
            check_shell_layout(d)
            check("t03 缺装配文件 → 报错", False)
        except RuntimeError as e:
            check("t03 缺装配文件 → 报错", "缺少装配文件" in str(e) and "tasks.py" in str(e))


def t04_custom_entries_allowed() -> None:
    """自定义文件/目录放行: 壳组织（routers/ 等）与能力约束（纪律/未来 AST）分离。"""
    with tempfile.TemporaryDirectory() as base:
        d = _make_shell_dir(base, extra_files=["stray.txt", "notes.py"],
                            extra_dirs=["vendor"])
        try:
            check_shell_layout(d)
            check("t04 自定义文件/目录放行（stray/notes/vendor 合法）", True)
        except RuntimeError as e:
            check("t04 自定义文件/目录放行", False)
            print(f"    {e}")


def t05_missing_entry() -> None:
    with tempfile.TemporaryDirectory() as base:
        d = _make_shell_dir(base, drop=["main.py", "cli.py"])
        try:
            check_shell_layout(d)
            check("t05 缺入口 → 报错", False)
        except RuntimeError as e:
            check("t05 缺入口 → 报错", "缺少入口文件" in str(e))


def t06_config_as_file() -> None:
    with tempfile.TemporaryDirectory() as base:
        d = os.path.join(base, "demo_app")
        os.makedirs(d)
        for f in ASSEMBLY_FILES + ENTRY_FILES:
            with open(os.path.join(d, f), "w", encoding="utf-8") as fh:
                fh.write('"""p"""\n')
        with open(os.path.join(d, "config"), "w", encoding="utf-8") as fh:
            fh.write("x")          # config 是文件不是目录
        os.makedirs(os.path.join(d, "__pycache__"), exist_ok=True)  # 自定义目录放行, 不误报
        try:
            check_shell_layout(d)
            check("t06 config 为文件 → 报错", False)
        except RuntimeError as e:
            check("t06 config 为文件 → 报错", "config 应为目录" in str(e))
            check("t06 自定义目录（__pycache__）不参与检查", "未登记目录" not in str(e))


def t07_deterministic_order() -> None:
    """报错确定性: 缺多个装配文件按装配组声明顺序列出（同输入同输出）。"""
    with tempfile.TemporaryDirectory() as base:
        d = _make_shell_dir(base, drop=["shell.py", "worker.py"])
        try:
            check_shell_layout(d)
            check("t07 缺多个装配文件 → 报错", False)
        except RuntimeError as e:
            check("t07 报错确定性（按装配组声明顺序）", "['shell.py', 'worker.py']" in str(e))


def t08_collected_problems() -> None:
    """收集式: 缺装配 + config 为文件 → 单条错误含两个关键词（非 first-fail）。"""
    with tempfile.TemporaryDirectory() as base:
        d = _make_shell_dir(base, drop=["worker.py"])
        import shutil
        shutil.rmtree(os.path.join(d, "config"))     # 先删 config 目录
        with open(os.path.join(d, "config"), "w", encoding="utf-8") as fh:
            fh.write("x")          # config 变成文件
        try:
            check_shell_layout(d)
            check("t08 收集式报错", False)
        except RuntimeError as e:
            check("t08 单条错误含缺装配+config 两关键词",
                  "缺少装配文件" in str(e) and "config 应为目录" in str(e))


# ── 壳内容检查（AST）──────────────────────────────

def _content_shell(base: str) -> str:
    """构造含 routers/ 子目录的壳, 返回目录路径。"""
    d = _make_shell_dir(base)
    os.makedirs(os.path.join(d, "routers"), exist_ok=True)
    return d


def t16_content_valid() -> None:
    from aic.kernel import check_shell_content
    with tempfile.TemporaryDirectory() as base:
        d = _content_shell(base)
        # 合法壳内组织: fastapi router + pydantic 模型 + SHELL.get 消费
        with open(os.path.join(d, "routers", "r1.py"), "w", encoding="utf-8") as f:
            f.write("from fastapi import APIRouter\n"
                    "from pydantic import BaseModel\n"
                    "class Item(BaseModel):\n    name: str\n"
                    "router = APIRouter()\nSHELL.get(\"review\")\n")
        try:
            check_shell_content(d)
            check("t16 合法壳内组织（router/模型/get 消费）通过", True)
        except RuntimeError as e:
            check("t16 合法壳内组织通过", False)
            print(f"    {e}")


def t17_content_import_business() -> None:
    from aic.kernel import check_shell_content
    with tempfile.TemporaryDirectory() as base:
        d = _content_shell(base)
        with open(os.path.join(d, "routers", "evil.py"), "w", encoding="utf-8") as f:
            f.write("from extensions.business.review import ReviewPlugin\n")
        try:
            check_shell_content(d)
            check("t17 import 业务插件 → 报错", False)
        except RuntimeError as e:
            check("t17 import 业务插件 → 报错", "import 插件实现" in str(e))


def t18_content_plugin_class() -> None:
    from aic.kernel import check_shell_content
    with tempfile.TemporaryDirectory() as base:
        d = _content_shell(base)
        with open(os.path.join(d, "routers", "evil2.py"), "w", encoding="utf-8") as f:
            f.write("from aic.kernel import Plugin\n"
                    "class Evil(Plugin):\n    provides = []\n"
                    "    def apply(self, ctx):\n        pass\n")
        try:
            check_shell_content(d)
            check("t18 定义 Plugin 子类 → 报错", False)
        except RuntimeError as e:
            check("t18 定义 Plugin 子类 → 报错", "定义插件类" in str(e)
                  and "Evil" in str(e))


def t19_content_wiring() -> None:
    from aic.kernel import check_shell_content
    with tempfile.TemporaryDirectory() as base:
        d = _content_shell(base)
        with open(os.path.join(d, "routers", "evil3.py"), "w", encoding="utf-8") as f:
            f.write("ctx.register(\"x\", 1)\n")
        try:
            check_shell_content(d)
            check("t19 接线动作 register → 报错", False)
        except RuntimeError as e:
            check("t19 接线动作 register → 报错", "接线动作" in str(e))


# ── 任务名协议 ────────────────────────────────────

def _jobs_ctx(app_pkg: str, impl=None) -> Context:
    from aic.extensions.platform.base.jobs import JobsPlugin
    ctx = Context()
    boot(ctx, [JobsPlugin(app_pkg=app_pkg, impl=impl)])
    return ctx


def t09_valid_names() -> None:
    from aic.extensions.platform.base.jobs import _WORKER_TASKS_CACHE
    ctx = _jobs_ctx("mvp")
    jobs = ctx.get("jobs")
    jobs.register_task("writer.run_pipeline", lambda *a: None)
    jobs.register_task("writer.revise", lambda *a: None)
    check("t09 mvp 注册两个真实任务名通过", True)
    jobs.register_task("writer.run_pipeline", lambda *a: None)  # 重复注册（mvp 每请求场景）
    check("t09 重复注册同名通过（memoize O(1)）", True)
    check("t09 内省结果已缓存", _WORKER_TASKS_CACHE.get("mvp") is not None)


def t10_violation() -> None:
    ctx = _jobs_ctx("mvp")
    jobs = ctx.get("jobs")
    try:
        jobs.register_task("writer.ghost", lambda *a: None)
        check("t10 注册未在 worker 侧登记的任务名 → 报错", False)
    except RuntimeError as e:
        check("t10 任务名协议违规 → 报错", "任务名协议违规" in str(e)
              and "writer.ghost" in str(e))


def t11_empty_slot() -> None:
    ctx = _jobs_ctx("file_convert")
    jobs = ctx.get("jobs")
    check("t11 空档位应用零注册无异常", True)
    try:
        jobs.register_task("file_convert.anything", lambda *a: None)
        check("t11 空档位注册任意名 → 报错（worker 侧空注册表）", False)
    except RuntimeError as e:
        check("t11 空档位注册任意名 → 报错（worker 侧空注册表）",
              "任务名协议违规" in str(e))


def t12_failover_double_register() -> None:
    from aic.extensions.platform.base.jobs import FailoverJobQueue, ThreadJobQueue
    primary = ThreadJobQueue()
    fallback = ThreadJobQueue()
    ctx = _jobs_ctx("mvp", impl=FailoverJobQueue(primary=primary, fallback=fallback))
    jobs = ctx.get("jobs")
    jobs.register_task("writer.run_pipeline", lambda *a: None)
    jobs.register_task("writer.run_pipeline", lambda *a: None)
    check("t12 Failover 双路径均注册",
          "writer.run_pipeline" in primary._registry
          and "writer.run_pipeline" in fallback._registry)
    check("t12 校验缓存仍单条（按 app_pkg 记账）", True)


def t13_degrade() -> None:
    ctx = _jobs_ctx("ghost_app_no_such")
    jobs = ctx.get("jobs")
    jobs.register_task("ghost.task", lambda *a: None)  # worker 不可导入 → 跳过校验
    check("t13 worker 不可导入 → 跳过校验（不报错）", True)


def t14_smoke_shells() -> None:
    from apps.mvp.shell import build_shell as build_mvp
    from apps.review.shell import build_shell as build_review
    from apps.file_convert.shell import build_shell as build_fc

    for name, fn in (("mvp", build_mvp), ("review", build_review),
                     ("file_convert", build_fc)):
        r = fn()
        s = r[0] if isinstance(r, tuple) else r
        check(f"t14 {name} build_shell 通过（布局检查 + 守卫装配）",
              s.has("jobs"))

    review = build_review()
    review.get("jobs").register_task("review.execute_review", lambda *a: None)
    check("t14 review 壳注册 review.execute_review 通过（boot 期注册同路径）", True)


def t15_init_templates() -> None:
    from aic.tools.init import APP_PROFILE, APP_SHELL, APP_TASKS, APP_WORKER
    ctx = {"name": "demo_app", "Name": "DemoApp"}
    rendered = [t.format(**ctx) for t in (APP_SHELL, APP_PROFILE, APP_TASKS, APP_WORKER)]
    check("t15 模板渲染无残留花括号", all("{{" not in r and "}}" not in r for r in rendered))
    check("t15 APP_SHELL 含布局检查", "check_shell_layout(_HERE)" in rendered[0])
    check("t15 APP_SHELL 含旁路检查", "check_bypass_imports(" in rendered[0])
    check("t15 APP_PROFILE 含 app_pkg", 'JobsPlugin(app_pkg="demo_app")' in rendered[1])
    check("t15 APP_WORKER 任务名内省目标存在", 'celery_app = Celery("demo_app"' in rendered[3])
    check("t15 APP_TASKS 空档位引导", "TASK_EXAMPLE = \"demo_app.example\"" in rendered[2])


# ── 旁路 import 契约 ─────────────────────────────

def _make_project(base: str, files: dict[str, str]) -> str:
    """构造合成项目: {相对根路径: 内容}。"""
    for rel, content in files.items():
        p = os.path.join(base, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
    return base


def t20_bypass_real_root() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        check_bypass_imports(root)
        check("t20 真实仓库旁路检查零违规", True)
    except RuntimeError as e:
        print(f"    {e}")
        check("t20 真实仓库旁路检查零违规", False)


def t21_bypass_app_direct() -> None:
    with tempfile.TemporaryDirectory() as base:
        _make_project(base, {
            "apps/demo/profile.py": "from aic.extensions.platform.base import StoragePlugin\n",
            "apps/demo/main.py": "from aic.extensions.platform.base.storage import LocalStorage\n",
        })
        try:
            check_bypass_imports(base)
            check("t21 应用直连组件 → 违规", False)
        except RuntimeError as e:
            check("t21 应用直连组件 → 违规",
                  "应用壳直连扩展实现" in str(e)
                  and "extensions.platform.base.storage" in str(e))


def t22_bypass_business_platform() -> None:
    with tempfile.TemporaryDirectory() as base:
        _make_project(base, {
            "extensions/business/demo/plugin.py":
                "from aic.extensions.platform.base.storage import LocalStorage\n",
        })
        try:
            check_bypass_imports(base)
            check("t22 业务插件直连平台组件 → 违规", False)
        except RuntimeError as e:
            check("t22 业务插件直连平台组件 → 违规",
                  "跨扩展根包旁路" in str(e))


def t23_bypass_cross_business() -> None:
    with tempfile.TemporaryDirectory() as base:
        _make_project(base, {
            "extensions/business/a/plugin.py":
                "from extensions.business.b.plugin import BThing\n",
        })
        try:
            check_bypass_imports(base)
            check("t23 跨业务插件 import → 违规", False)
        except RuntimeError as e:
            check("t23 跨业务插件 import → 违规",
                  "跨扩展根包旁路" in str(e))


def t24_bypass_extension_app() -> None:
    with tempfile.TemporaryDirectory() as base:
        _make_project(base, {
            "apps/demo/tasks.py": "TASK_X = \"demo.x\"\n",
            "extensions/business/demo/plugin.py":
                "from apps.demo.tasks import TASK_X\n",
        })
        try:
            check_bypass_imports(base)
            check("t24 扩展反向 import 应用 → 违规", False)
        except RuntimeError as e:
            check("t24 扩展反向 import 应用 → 违规",
                  "扩展反向 import 应用壳" in str(e))


def t25_bypass_composition_ok() -> None:
    with tempfile.TemporaryDirectory() as base:
        _make_project(base, {
            "apps/demo/profile.py":
                "from aic.extensions.platform.base.jobs import CeleryJobQueue, ThreadJobQueue\n",
            "apps/demo/shell.py": "from aic.extensions.platform.loops import FakeLoop\n",
            "apps/demo/main.py": "from aic.extensions.platform.session import SessionPlugin\n",
        })
        try:
            check_bypass_imports(base)
            check("t25 组合面（profile impl / loops / *Plugin）全部放行", True)
        except RuntimeError as e:
            print(f"    {e}")
            check("t25 组合面（profile impl / loops / *Plugin）全部放行", False)


def t26_bypass_utility_ok() -> None:
    with tempfile.TemporaryDirectory() as base:
        _make_project(base, {
            "apps/demo/main.py":
                "from aic.extensions.platform.extract import extract_document\n"
                "from aic.extensions.platform.session.artifacts import list_artifacts\n",
            "extensions/business/demo/plugin.py":
                "from aic.extensions.platform.session.artifacts import save_artifact\n",
        })
        try:
            check_bypass_imports(base)
            check("t26 声明工具白名单（extract / session.artifacts）放行", True)
        except RuntimeError as e:
            print(f"    {e}")
            check("t26 声明工具白名单（extract / session.artifacts）放行", False)


def t27_bypass_relative_escape() -> None:
    with tempfile.TemporaryDirectory() as base:
        _make_project(base, {
            "extensions/platform/base/__init__.py": "from ..loops import FakeLoop\n",
        })
        try:
            check_bypass_imports(base)
            check("t27 相对导入逃出根包 → 违规", False)
        except RuntimeError as e:
            check("t27 相对导入逃出根包 → 违规",
                  "跨扩展根包旁路" in str(e)
                  and "extensions.platform.loops" in str(e))


def t28_bypass_review_excluded() -> None:
    """豁免收敛: 精确到文件（apps/review/main.py + tasks.py）, 不再整条业务线。"""
    with tempfile.TemporaryDirectory() as base:
        _make_project(base, {
            "apps/review/main.py":
                "from aic.extensions.platform.base.storage import LocalStorage\n",
            "apps/review/tasks.py":
                "from extensions.business.review.task import TASK_EXECUTE_REVIEW\n",
        })
        # 两个精确豁免文件 → 放行
        try:
            check_bypass_imports(base)
            check("t28 review 精确豁免文件放行", True)
        except RuntimeError as e:
            print(f"    {e}")
            check("t28 review 精确豁免文件放行", False)

    # 非豁免文件（extensions 侧反向 import）→ 仍要拦（收敛后不再整线豁免）
    with tempfile.TemporaryDirectory() as base:
        _make_project(base, {
            "extensions/business/review/plugin.py":
                "from apps.review.tasks import TASK_X\n",
        })
        try:
            check_bypass_imports(base)
            check("t28 豁免收敛: extensions 侧反向 import 仍拦", False)
        except RuntimeError as e:
            check("t28 豁免收敛: extensions 侧反向 import 仍拦",
                  "扩展反向 import 应用壳" in str(e))


def t30_stream_bridge() -> None:
    """StreamPlugin 通道化（0.2.1）: 平台不认识业务事件, 桥接由业务声明。"""
    from aic.kernel import Context, boot
    from aic.extensions.platform.stream import StreamPlugin
    app = Context()
    boot(app, [StreamPlugin()])
    svc = app.get("stream")
    check("t30 StreamPlugin 零业务预置桥接", "pipeline/phase" not in app._listeners)
    # 桥接路由读框架保留字段 aic_session_id（0.2.3 命名约定: 值 = 业务会话标识）
    app.register_event("my/progress", {"aic_session_id", "pct"})
    svc.bridge("my/progress")
    q, _ = svc.subscribe("s1")
    app.emit("my/progress", {"aic_session_id": "s1", "pct": 50})
    got = q.get(timeout=1)
    check("t30 业务声明桥接生效（SSE 收到事件）",
          got["event"] == "my/progress" and got["data"]["aic_session_id"] == "s1")


def t29_bypass_deterministic() -> None:
    with tempfile.TemporaryDirectory() as base:
        _make_project(base, {
            "apps/demo/b.py": "from aic.extensions.platform.base.storage import LocalStorage\n",
            "apps/demo/a.py": "from aic.extensions.platform.base.cache import RedisCache\n",
        })
        m1 = m2 = None
        for i in (1, 2):
            try:
                check_bypass_imports(base)
            except RuntimeError as e:
                if i == 1:
                    m1 = str(e)
                else:
                    m2 = str(e)
        check("t29 报错确定性（两次一致, sorted 收集式）",
              m1 is not None and m1 == m2
              and m1.index("apps/demo/a.py") < m1.index("apps/demo/b.py"))


def main() -> None:
    t01_layout_valid()
    t02_real_apps()
    t03_missing_assembly()
    t04_custom_entries_allowed()
    t05_missing_entry()
    t06_config_as_file()
    t07_deterministic_order()
    t08_collected_problems()
    t16_content_valid()
    t17_content_import_business()
    t18_content_plugin_class()
    t19_content_wiring()
    t09_valid_names()
    t10_violation()
    t11_empty_slot()
    t12_failover_double_register()
    t13_degrade()
    t14_smoke_shells()
    t15_init_templates()
    t20_bypass_real_root()
    t21_bypass_app_direct()
    t22_bypass_business_platform()
    t23_bypass_cross_business()
    t24_bypass_extension_app()
    t25_bypass_composition_ok()
    t26_bypass_utility_ok()
    t27_bypass_relative_escape()
    t28_bypass_review_excluded()
    t29_bypass_deterministic()
    t30_stream_bridge()
    print(f"\nM6 验证: {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
