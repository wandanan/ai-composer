"""m1c_main.py — M1c 验证：工作区沙箱插件（可逆 + 边界拦截 + 真实引擎集成）。

运行: PYTHONIOENCODING=utf-8 python m1c_main.py
前置: hermes-agent 源码路径（sys.path 注入）；[4] 需 config.local.ini 的 LLM 配置（1 次 API）

验证项:
  [1] 沙箱插件挂载: ctx.sandbox 服务 + 补丁安装
  [2] 边界检查（确定性, 无 LLM）: 工作区内放行 / 工作区外拒绝 / bash 路径 / 切换跟随
  [3] 卸载还原: 补丁恢复原函数 + 服务撤销（零残留）
  [4] 真实引擎集成（1 次 API）: agent 写工作区内成功, 项目根目录无新文件
"""
from __future__ import annotations
# ── 路径引导: 脚本位于 test/ 下, 确保项目根在 sys.path ──
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import configparser
import os
import sys
import tempfile
from pathlib import Path

HERMES_AGENT_SRC = r"D:/standard_workspace/products_dev/upstream/hermes-agent"
sys.path.insert(0, HERMES_AGENT_SRC)  # biz 改名后无 plugins 遮蔽冲突, 可提前注入

from kernel import Context, ServiceNotFound, boot
from extensions.platform.loops.hermes import HermesEnginePlugin
from extensions.platform.security.sandbox import SandboxPlugin

_PASS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _PASS.append(ok)
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


def _load_llm_config() -> dict:
    parser = configparser.ConfigParser()
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根
    parser.read(os.path.join(here, "apps", "mvp", "config", "config.local.ini"),
                encoding="utf-8")
    keys = ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER")
    return {k: parser.get("llm", k, fallback="") for k in keys}


def main() -> int:
    skip_real = "--skip-real" in sys.argv
    print("=" * 64)
    print("M1c 验证: 工作区沙箱插件（可逆 + 边界拦截）"
          + ("（跳过真实引擎）" if skip_real else ""))
    print("=" * 64)

    app = Context()
    app.register("config", {"llm": _load_llm_config()})
    [sandbox_mount, engine_mount] = boot(app, [SandboxPlugin(), HermesEnginePlugin()])

    print("\n[1] 沙箱插件挂载")
    sb = app.get("sandbox")
    check("ctx.sandbox 服务已注册", sb is not None, type(sb).__name__)
    import tools.file_tools as ft
    check("_resolve_path_for_task 已被替换",
          ft._resolve_path_for_task.__name__ == "_sandboxed_resolve_path",
          ft._resolve_path_for_task.__name__)

    print("\n[2] 边界检查（确定性, 无 LLM）")
    ws = tempfile.mkdtemp(prefix="m1c_ws_")
    sb.set_workspace(ws)
    inside = os.path.join(ws, "materials", "a.md")
    os.makedirs(os.path.dirname(inside), exist_ok=True)

    resolved = ft._resolve_path_for_task(inside)
    check("工作区内路径放行", str(resolved) == str(Path(inside).resolve()), str(resolved))

    try:
        ft._resolve_path_for_task("C:/Windows/win.ini")
        blocked = False
    except PermissionError:
        blocked = True
    check("工作区外绝对路径被拒 (PermissionError)", blocked)

    ws_bash = f"/{ws[0].lower()}/{ws[3:].replace(chr(92), '/')}"
    try:
        ft._resolve_path_for_task(ws_bash + "/materials/a.md")
        bash_ok = True
    except PermissionError:
        bash_ok = False
    check("bash 格式路径 (/c/...) 归一化后放行", bash_ok)

    ws2 = tempfile.mkdtemp(prefix="m1c_ws2_")
    sb.set_workspace(ws2)
    try:
        ft._resolve_path_for_task(inside)
        switched = False
    except PermissionError:
        switched = True
    check("工作区切换后边界跟随（旧工作区文件越界）", switched)

    print("\n[3] 卸载还原（可逆）")
    app.unmount(sandbox_mount)
    check("补丁还原: 原函数恢复",
          ft._resolve_path_for_task.__name__ != "_sandboxed_resolve_path",
          ft._resolve_path_for_task.__name__)
    try:
        app.get("sandbox")
        svc_gone = False
    except ServiceNotFound:
        svc_gone = True
    check("ctx.sandbox 服务已撤销（零残留）", svc_gone)

    print("\n[4] 真实引擎集成（1 次 API 调用）")
    if skip_real:
        print("  ⏭  --skip-real, 跳过真实引擎集成")
    else:
        [sandbox_mount2] = boot(app, [SandboxPlugin()])
        sb = app.get("sandbox")
        ws3 = tempfile.mkdtemp(prefix="m1c_run_")
        sb.set_workspace(ws3)
        os.environ["TERMINAL_CWD"] = ws3

        root_before = set(os.listdir("."))
        loop = app.get("agentLoop")
        result = loop.run_conversation(
            f"请完成两个任务并用简短结果报告: "
            f"1) 创建文件 {os.path.join(ws3, 'welcome.txt')} 内容为 hello; "
            f"2) 尝试读取 C:/Windows/win.ini 并说明是否成功。",
            system_prompt="你是文件操作测试助手, 请如实执行并报告。",
            toolsets=["file"],
        )
        root_after = set(os.listdir("."))

        welcome_path = os.path.join(ws3, "welcome.txt")
        check("agent 写入落在工作区内", os.path.exists(welcome_path), welcome_path)

        new_outside = [f for f in (root_after - root_before) if not f.startswith("m1c_")]
        check("项目根目录无新文件（越界写被拦）", len(new_outside) == 0, str(new_outside))
        for f in new_outside:  # 保险清理
            os.remove(os.path.join(".", f))
        os.environ.pop("TERMINAL_CWD", None)

    print("\n" + "=" * 64)
    failed = _PASS.count(False)
    if failed == 0:
        print("✅ M1c 全部通过 — 沙箱插件可逆、边界拦截生效、真实引擎受限")
    else:
        print(f"❌ {failed} 项失败")
    print("=" * 64)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
