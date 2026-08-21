"""apps/hello_aic/profile.py — 示例应用: 挂载模板全部公共插件。"""
import os

from aic.extensions.platform.standard import StandardPlugin
from aic.extensions.platform.base import ConfigPlugin, DbPlugin
from aic.extensions.platform.extract import ExtractPlugin

PLUGINS = [
    StandardPlugin(),
    DbPlugin(),
    ExtractPlugin(),
    ConfigPlugin(path=__file__.replace("profile.py",
                                       f"config/config.{os.environ.get('APP_ENV', 'local')}.ini")),
]
