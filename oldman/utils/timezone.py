"""
@author:alex
@date:2024/10/30
@time:23:33
"""

__author__ = "alex"

from datetime import UTC, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import oldman.conf as conf
from oldman.utils.singleton import singleton


@lru_cache(maxsize=100)
def _tz_for_name(tz_name: str) -> ZoneInfo:
    return ZoneInfo(tz_name)


@singleton
class TimezoneManager:
    """时区管理器单例：按名字取时区、把时间转到指定时区；ZoneInfo 由 _tz_for_name 缓存。"""

    def get_timezone(self, tz_name: str | None) -> ZoneInfo:
        """按名字取时区；为空时用部署默认时区（``core.time_zone``）。

        名字无效时回落到默认时区而不报错：Web 中间件每个请求都用它解析请求带来的时区名，不能因为客户端
        传了一个错名字就让请求失败。默认时区本身无效是配置错误，照常抛出。
        """
        default_name = conf.settings.core.time_zone
        try:
            return _tz_for_name(tz_name or default_name)
        except (ValueError, ZoneInfoNotFoundError, OSError):
            # OSError: with the tzdata package installed, zoneinfo opens the name as a file
            # inside it, and an over-long name or a directory's name fails to open.
            return _tz_for_name(default_name)

    def convert_to_local(self, dt_value: datetime, tz_name: str) -> datetime:
        """转换时间到指定时区"""
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=UTC)
        target_tz = self.get_timezone(tz_name)
        return dt_value.astimezone(target_tz)
