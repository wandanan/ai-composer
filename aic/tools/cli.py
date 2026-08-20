"""tools/cli.py — aic 统一命令行入口（pip 安装后的命令）。

用法:
    aic init my-app                  # 初始化新应用（装）
    aic graph                        # 生成项目结构图谱（看）
    aic promote MyPlugin --yes       # 私有插件上浮为公共插件（升）
    aic uninstall my-app --yes       # 卸载应用/插件（卸）
    aic template review --out ~/tpl  # 新应用开发模板提取（模板）

各命令参数见: aic <命令> -h
"""
from __future__ import annotations

import importlib
import sys

_COMMANDS = {
    "init": "aic.tools.init",
    "graph": "aic.tools.graph",
    "promote": "aic.tools.promote",
    "uninstall": "aic.tools.uninstall",
    "template": "aic.tools.template",
    "caps": "aic.tools.caps",
    "skills": "aic.tools.skills",
}

_USAGE = """\
用法: aic <命令> [参数]

命令:
  init       初始化新应用（生成壳 + 业务插件骨架 + 空档位 tasks/worker）
  graph      生成项目结构图谱 graph-viz.html（自包含交互, 双击即开）
  caps       显示框架可用能力（平台服务 / 业务插件 / 声明工具 / 引擎）
  skills     覆盖更新项目根三平台开发 Skill（安装新版本后同步 aic-paradigm）
  promote    私有插件 → 公共插件（移动包 + 更新引用 + PUBLIC 标记, 默认只显示影响清单（预演））
  uninstall  应用/插件卸载（影响分析后删除, 默认只显示影响清单（预演））
  template   新应用开发模板提取（只带走公共插件 + 示例壳 hello_aic）

各命令参数见: aic <命令> -h
"""


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        return
    cmd, rest = argv[0], argv[1:]
    module_name = _COMMANDS.get(cmd)
    if module_name is None:
        raise SystemExit(f"未知命令: {cmd}（可用: {', '.join(sorted(_COMMANDS))}）")
    module = importlib.import_module(module_name)
    module.main(rest)


if __name__ == "__main__":
    main()
