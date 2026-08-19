"""apps/file_convert/cli.py — CLI 入口（与 HTTP 壳共享同一业务插件）。

演示范式不绑定入口: 同一组插件（file_convert 业务）配不同形态的壳。
用法:
    python -m apps.file_convert.cli <文件路径> <src_type> <dst_type>
"""
from __future__ import annotations

import sys

from apps.file_convert.shell import build_shell


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(
            "用法: python -m apps.file_convert.cli <文件路径> <src_type> <dst_type>\n"
            "例:   python -m apps.file_convert.cli input.txt txt md")

    path, src_type, dst_type = sys.argv[1], sys.argv[2], sys.argv[3]

    # 与 HTTP 端点完全相同的装配（build_shell）与业务调用（convertPipeline）
    shell = build_shell()
    session = shell.get("sessions").create_session({"job": "cli"})

    with open(path, encoding="utf-8") as f:
        content = f.read()

    result = shell.get("convertPipeline").run(session, content, src_type, dst_type)
    print(f"✅ 转换完成: {result['output']}（{result['chars']} 字符, {dst_type}）")


if __name__ == "__main__":
    main()
