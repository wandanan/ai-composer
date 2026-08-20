"""test/m7_main.py — M7 验证: 工具回归（graph / promote / uninstall）。

依据: docs/learn/tool-closed-loop.md（工具闭环）。

验证项:
  graph 数据层（真实项目）:
   1. build_graph: 4 应用 / 关键插件 / keys（AnnAssign 支持）/ 边
   2. public 标记: ExtractPlugin/DbPlugin/StandardPlugin=True, ReviewPlugin=False
   3. ai 判定: ReviewPlugin/WriterPlugin=True, TodoPlugin=False
   4. 孤儿: DemoPlugin/EchoPlugin/HelloPlugin; 动态: HermesEnginePlugin
   5. 函数包装展开: review 挂载 CachePlugin（_cache_plugin）
  uninstall 影响分析（纯计算, 不删）:
   6. 卸载 review: 专属=[ReviewPlugin], DbPlugin/ExtractPlugin/StandardPlugin 保留,
      删除清单仅 2 项（壳 + review 包）
   7. 同包保护: DbPlugin 与共享插件同包 → 降级保留
   8. 卸载 todo: 专属=[TodoPlugin]
   9. 插件卸载: StandardPlugin 拒绝（挂载 review）; DemoPlugin 允许（同包闭包）
  promote 分析:
  10. 预演: ReviewPlugin 移动/引用更新清单正确
  11. 幂等: ExtractPlugin 已在 platform → already 分支
  12. 地基拒绝: --to apps → SystemExit
  13. 引用替换边界: 前缀 + .plugin 段保留; todo2 不误伤
 模拟项目集成（KIT_PROJECT_ROOT, 临时目录）:
  14. promote --yes 全流程: 包移动/引用更新/PUBLIC 标记
  15. 上浮后卸载应用: 专属=无（生命周期解绑）, 插件保留
  16. graph 模拟项目: 插件归属/公共标记反映在图中
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.graph import build_graph
from tools.promote import _replace_refs, promote
from tools.uninstall import analyze_app_removal, analyze_plugin_removal

PASS: list[str] = []
FAIL: list[str] = []

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(name: str, cond: bool) -> None:
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(name)
        print(f"  ❌ {name}")


def _base_of(path: str) -> str:
    return os.path.basename(os.path.normpath(path))


# ── graph 数据层（真实项目）────────────────────────

def t01_graph_data() -> None:
    g = build_graph()
    check("t01 应用 5 个", len(g["apps"]) == 5
          and set(g["apps"]) == {"mvp", "review", "todo", "file_convert", "hello_aic"})
    check("t01 插件 ≥ 18", len(g["plugins"]) >= 18)
    check("t01 keys 含 todos/converter（AnnAssign 支持）",
          "todos" in g["keys"] and "converter" in g["keys"])
    check("t01 边 ≥ 80", len(g["edges"]) >= 80)


def t02_public_markers() -> None:
    g = build_graph()
    for cls in ("ExtractPlugin", "DbPlugin", "StandardPlugin"):
        check(f"t02 {cls} public=True", g["plugins"][cls].get("public") is True)
    check("t02 ReviewPlugin public=False", g["plugins"]["ReviewPlugin"].get("public") is False)


def t03_ai_detection() -> None:
    g = build_graph()
    check("t03 ReviewPlugin ai（inject agentLoop）", g["plugins"]["ReviewPlugin"]["ai"])
    check("t03 WriterPlugin ai（包内 WriterTask）", g["plugins"]["WriterPlugin"]["ai"])
    check("t03 TodoPlugin 非 ai", not g["plugins"]["TodoPlugin"]["ai"])


def t04_orphan_dynamic() -> None:
    g = build_graph()
    orphans = sorted(n for n, i in g["plugins"].items()
                     if not i["apps"] and not i["dynamic"])
    check("t04 孤儿 = 演示 + hermes 适配器",
          orphans == ["DemoPlugin", "EchoPlugin", "HelloPlugin", "HermesEnginePlugin"])
    dyn = sorted(n for n, i in g["plugins"].items() if i["dynamic"])
    check("t04 动态 = OpenAIEnginePlugin（壳按配置追加真引擎）",
          dyn == ["OpenAIEnginePlugin"])


def t05_factory_expansion() -> None:
    g = build_graph()
    review_mounts = [e["to"] for e in g["edges"]
                     if e["kind"] == "mount" and e["from"] == "review"]
    check("t05 _cache_plugin 展开为 CachePlugin", "CachePlugin" in review_mounts)


# ── uninstall 影响分析（纯计算）────────────────────

def t06_review_uninstall() -> None:
    g = build_graph()
    r = analyze_app_removal(_ROOT, g, "review")
    check("t06 专属仅 ReviewPlugin", r["exclusive_plugins"] == ["ReviewPlugin"])
    for kept in ("DbPlugin", "ExtractPlugin", "StandardPlugin"):
        check(f"t06 公共插件 {kept} 保留", kept in r["shared_plugins"])
    check("t06 删除仅 2 项（壳 + review 包）", len(r["delete"]) == 2
          and all(_base_of(d) in ("review",) for d in r["delete"]))


def t07_same_pkg_protection() -> None:
    g = build_graph()
    r = analyze_app_removal(_ROOT, g, "review")
    # DbPlugin 与 StoragePlugin 等共享插件同在 base 包 → 整包不可删 → 降级保留
    check("t07 DbPlugin 降级保留（同包保护）", "DbPlugin" in r["shared_plugins"])
    check("t07 删除清单不含 platform/base", all("base" not in d for d in r["delete"]))


def t08_todo_uninstall() -> None:
    g = build_graph()
    r = analyze_app_removal(_ROOT, g, "todo")
    check("t08 todo 专属 TodoPlugin", r["exclusive_plugins"] == ["TodoPlugin"])
    check("t08 todo 删除 2 项", len(r["delete"]) == 2)


def t09_plugin_removal() -> None:
    g = build_graph()
    blocked = analyze_plugin_removal(_ROOT, g, "StandardPlugin")
    check("t09 StandardPlugin 拒绝（挂载 review）", blocked["blocked"] != []
          and "review" in str(blocked["blocked"]))
    allowed = analyze_plugin_removal(_ROOT, g, "DemoPlugin")
    check("t09 DemoPlugin 允许（同包孤儿闭包）", allowed["blocked"] == []
          and allowed["candidates"] == ["DemoPlugin", "EchoPlugin"])


# ── promote 分析（预演 纯计算）──────────────────

def t10_promote_dry_run() -> None:
    g = build_graph()
    rep = promote(_ROOT, g, "ReviewPlugin", "platform", dry=True)
    check("t10 非幂等分支", not rep["already"])
    check("t10 移动源在 business/review", "business" in rep["move"][0] and "review" in rep["move"][0])
    check("t10 目标在 platform/review", "platform" in rep["move"][1] and "review" in rep["move"][1])
    check("t10 引用更新含 profile", any("profile" in os.path.basename(p) for p in rep["refs"]))
    check("t10 引用更新 > 0", len(rep["refs"]) > 0)


def t11_promote_idempotent() -> None:
    g = build_graph()
    rep = promote(_ROOT, g, "ExtractPlugin", "platform", dry=True)
    check("t11 ExtractPlugin 已在目标位 → already", rep["already"])


def t12_promote_ground_guard() -> None:
    g = build_graph()
    try:
        promote(_ROOT, g, "TodoPlugin", "apps", dry=True)
        check("t12 地基目录拒绝", False)
    except SystemExit as e:
        check("t12 地基目录拒绝", "地基" in str(e))


def t13_ref_boundary() -> None:
    with tempfile.TemporaryDirectory() as base:
        f = os.path.join(base, "m.py")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("from extensions.business.todo import A\n"
                     "from extensions.business.todo.plugin import B\n"
                     "from extensions.business.todo2 import C\n")
        n = _replace_refs(f, "extensions.business.todo", "extensions.platform.todo")
        content = open(f, encoding="utf-8").read()
        check("t13 替换 2 处", n == 2)
        check("t13 包前缀更新", "extensions.platform.todo import A" in content)
        check("t13 .plugin 段保留", "extensions.platform.todo.plugin import B" in content)
        check("t13 todo2 不误伤", "extensions.business.todo2 import C" in content)


# ── 模拟项目集成（KIT_PROJECT_ROOT）────────────────

def _make_mock_project(base: str) -> str:
    """构造模拟项目: apps/{todo,mvp} + extensions/business/todo（TodoPlugin）。"""
    root = os.path.join(base, "proj")
    for app in ("todo", "mvp"):
        d = os.path.join(root, "apps", app, "config")
        os.makedirs(d)
        for f in ("__init__.py", "profile.py", "shell.py",
                  "tasks.py", "worker.py", "main.py"):
            with open(os.path.join(root, "apps", app, f), "w", encoding="utf-8") as fh:
                fh.write('"""x"""\n')
        with open(os.path.join(root, "apps", app, "config", "config.local.ini"),
                  "w", encoding="utf-8") as fh:
            fh.write("[llm]\n")
    biz = os.path.join(root, "extensions", "business", "todo")
    os.makedirs(biz)
    with open(os.path.join(biz, "__init__.py"), "w", encoding="utf-8") as fh:
        fh.write('"""x"""\n')
    with open(os.path.join(biz, "plugin.py"), "w", encoding="utf-8") as fh:
        fh.write("from kernel import Plugin\n"
                 "class TodoPlugin(Plugin):\n"
                 '    provides: list[str] = ["todos"]\n'
                 "    def apply(self, ctx):\n        pass\n")
    with open(os.path.join(root, "apps", "todo", "profile.py"), "w", encoding="utf-8") as fh:
        fh.write("from extensions.business.todo import TodoPlugin\n"
                 "PLUGINS = [TodoPlugin()]\n")
    with open(os.path.join(root, "apps", "mvp", "profile.py"), "w", encoding="utf-8") as fh:
        fh.write("PLUGINS = []\n")
    for pkg in (("apps",), ("extensions",), ("extensions", "business")):
        with open(os.path.join(root, *pkg, "__init__.py"), "w", encoding="utf-8") as fh:
            fh.write('"""x"""\n')
    return root


def t14_mock_promote_flow() -> None:
    with tempfile.TemporaryDirectory() as base:
        root = _make_mock_project(base)
        old = os.environ.get("KIT_PROJECT_ROOT")
        os.environ["KIT_PROJECT_ROOT"] = root
        try:
            graph = build_graph()
            rep = promote(root, graph, "TodoPlugin", "platform", dry=False)
            check("t14 包已移动", os.path.isdir(os.path.join(root, "extensions", "platform", "todo")))
            check("t14 引用已更新", "extensions.platform.todo import TodoPlugin"
                  in open(os.path.join(root, "apps", "todo", "profile.py"), encoding="utf-8").read())
            check("t14 PUBLIC 标记已写入", "PUBLIC = True"
                  in open(os.path.join(root, "extensions", "platform", "todo", "plugin.py"),
                          encoding="utf-8").read())
            # 上浮后卸载应用: 生命周期解绑
            g2 = build_graph()
            r = analyze_app_removal(root, g2, "todo")
            check("t14 卸载应用专属=无（解绑）", r["exclusive_plugins"] == [])
            check("t14 TodoPlugin 保留（公共）", "TodoPlugin" in r["shared_plugins"])
            check("t14 删除仅壳 1 项", len(r["delete"]) == 1)
        finally:
            if old is None:
                os.environ.pop("KIT_PROJECT_ROOT", None)
            else:
                os.environ["KIT_PROJECT_ROOT"] = old


def t15_mock_graph_public() -> None:
    with tempfile.TemporaryDirectory() as base:
        root = _make_mock_project(base)
        old = os.environ.get("KIT_PROJECT_ROOT")
        os.environ["KIT_PROJECT_ROOT"] = root
        try:
            g = build_graph()
            check("t15 模拟项目应用 2 个", g["apps"] == ["mvp", "todo"])
            check("t15 TodoPlugin 挂载 todo", g["plugins"]["TodoPlugin"]["apps"] == ["todo"])
            check("t15 未上浮前 public=False", g["plugins"]["TodoPlugin"]["public"] is False)
        finally:
            if old is None:
                os.environ.pop("KIT_PROJECT_ROOT", None)
            else:
                os.environ["KIT_PROJECT_ROOT"] = old


# ── 模板提取（tools.template）──────────────────────

def t16_template_dry_run() -> None:
    from tools.template import build_template
    g = build_graph()
    rep = build_template(_ROOT, g, os.path.join(_ROOT, "tmp-tpl"), dry=True,
                         src_app="review")
    check("t16 公共插件三件套进清单", {"DbPlugin", "ExtractPlugin", "StandardPlugin"}
          <= set(rep["publics"]))
    check("t16 未上浮共享提示", "ConfigPlugin" in rep["unmarked_shared"])


def t17_template_extract() -> None:
    from tools.template import build_template
    g = build_graph()
    out = os.path.join(tempfile.mkdtemp(), "tpl")
    try:
        rep = build_template(_ROOT, g, out, dry=False, src_app="review")
        check("t17 公共插件进模板", {"DbPlugin", "ExtractPlugin", "StandardPlugin"}
              <= set(rep["publics"]))
        check("t17 kernel 复制", os.path.isdir(os.path.join(out, "kernel")))
        check("t17 loops 引擎复制（shell 硬编码依赖）",
              os.path.isdir(os.path.join(out, "extensions", "platform", "loops")))
        check("t17 示例壳 hello_aic", os.path.isdir(os.path.join(out, "apps", "hello_aic")))
        check("t17 公共插件包复制", os.path.isdir(os.path.join(out, "extensions", "platform", "extract")))
        check("t17 自检脚本生成", os.path.isfile(os.path.join(out, "test", "template_check.py")))
        req = open(os.path.join(out, "requirements.txt"), encoding="utf-8").read()
        check("t17 requirements 自动生成", "fastapi>=0.110" in req
              and "uvicorn>=0.27" in req and "pymupdf>=1.24" in req)
        check("t17 requirements 过滤业务专属（python-multipart 不带）",
              "multipart" not in req)
        check("t17 开发 Skill 复制（.claude/.codex/.agent）",
              os.path.isdir(os.path.join(out, ".claude", "skills", "aic-paradigm"))
              and os.path.isdir(os.path.join(out, ".codex", "skills", "aic-paradigm"))
              and os.path.isdir(os.path.join(out, ".agent", "skills", "aic-paradigm")))
        check("t17 docs 只带 learn", os.path.isdir(os.path.join(out, "docs", "learn"))
              and not os.path.isdir(os.path.join(out, "docs", "design")))
        check("t17 私有应用不带（apps 只有 hello_aic）",
              sorted(os.listdir(os.path.join(out, "apps"))) == ["hello_aic"])
    finally:
        import shutil
        shutil.rmtree(os.path.dirname(out), ignore_errors=True)


def t18_template_self_check() -> None:
    """模板自检脚本内容: 壳契约 + hello_aic 装配断言。"""
    from tools.template import _TEMPLATE_CHECK
    check("t18 自检含壳布局存在性", "check_shell_layout" in _TEMPLATE_CHECK)
    check("t18 自检含内容 AST", "check_shell_content" in _TEMPLATE_CHECK)
    check("t18 自检含装配", "build_shell()" in _TEMPLATE_CHECK)


# ── 能力清单（tools.caps）────────────────────────

def _caps_output(root: str) -> tuple[int, str]:
    import io
    from contextlib import redirect_stdout
    from tools.caps import caps
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = caps(root)
    return rc, buf.getvalue()


def t19_caps_real_repo() -> None:
    rc, out = _caps_output(_ROOT)
    check("t19 caps 真实仓库输出四段", rc == 0
          and all(s in out for s in ("== 平台服务", "== 业务插件",
                                     "== 声明工具", "== 引擎")))
    check("t19 平台服务 key（storage/agentLoop）",
          "storage" in out and "agentLoop" in out)
    check("t19 声明工具白名单", "extensions.platform.session.artifacts" in out)
    check("t19 引擎选择", "FailoverLoop" in out and "OpenAILoop" in out)
    check("t19 业务插件（WriterPlugin）", "WriterPlugin" in out)


def t20_caps_broken_module() -> None:
    """坏插件模块不拖垮清单（合成项目, 隔离 extensions 命名空间）。"""
    with tempfile.TemporaryDirectory() as base:
        for rel, content in {
            "extensions/platform/__init__.py": '"""platform"""\n',
            "extensions/platform/broken/__init__.py": "raise ImportError('boom')\n",
            "extensions/platform/ok/__init__.py":
                "from kernel import Plugin\n"
                "class OkPlugin(Plugin):\n"
                "    provides = ['okSvc']\n"
                "    def apply(self, ctx):\n"
                "        ctx.register('okSvc', 1)\n",
        }.items():
            p = os.path.join(base, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(content)
        # 隔离: 临时项目优先于真实仓库的 extensions 命名空间
        saved = {k: v for k, v in sys.modules.items()
                 if k == "extensions" or k.startswith("extensions.")}
        for k in saved:
            del sys.modules[k]
        sys.path.insert(0, base)
        try:
            rc, out = _caps_output(base)
        finally:
            sys.path.remove(base)
            for k in [k for k in sys.modules
                      if k == "extensions" or k.startswith("extensions.")]:
                del sys.modules[k]
            sys.modules.update(saved)
        check("t20 坏模块不拖垮清单", rc == 0 and "okSvc" in out)
        check("t20 坏模块有提示", "broken 不可导入" in out)


def main() -> None:
    t01_graph_data()
    t02_public_markers()
    t03_ai_detection()
    t04_orphan_dynamic()
    t05_factory_expansion()
    t06_review_uninstall()
    t07_same_pkg_protection()
    t08_todo_uninstall()
    t09_plugin_removal()
    t10_promote_dry_run()
    t11_promote_idempotent()
    t12_promote_ground_guard()
    t13_ref_boundary()
    t14_mock_promote_flow()
    t15_mock_graph_public()
    t16_template_dry_run()
    t17_template_extract()
    t18_template_self_check()
    t19_caps_real_repo()
    t20_caps_broken_module()
    print(f"\nM7 验证: {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
