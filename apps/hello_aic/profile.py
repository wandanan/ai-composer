"""apps/hello_aic/profile.py — 示例应用: 挂载模板全部公共插件。"""
from extensions.business.standard import StandardPlugin
from extensions.platform.base import DbPlugin
from extensions.platform.extract import ExtractPlugin

PLUGINS = [
    StandardPlugin(),
    DbPlugin(),
    ExtractPlugin(),
]
