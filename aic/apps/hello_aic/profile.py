"""apps/hello_aic/profile.py — 示例应用: 挂载模板全部公共插件。"""
from aic.extensions.platform.standard import StandardPlugin
from aic.extensions.platform.base import DbPlugin
from aic.extensions.platform.extract import ExtractPlugin

PLUGINS = [
    StandardPlugin(),
    DbPlugin(),
    ExtractPlugin(),
]
