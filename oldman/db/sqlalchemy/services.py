"""
@author:alex
@date:2024/10/30
@time:22:44
"""

__author__ = "alex"

import abc


class BaseModelService(abc.ABC):  # noqa: B024 -- abstract marker base without abstract methods is intentional
    """
    用于定义基本的模型服务接口
    """

    def __init__(self, session):
        self.session = session
