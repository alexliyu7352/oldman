"""
@author:alex
@date:2024/10/30
@time:23:33
"""

__author__ = "alex"

from datetime import UTC, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import oldman.conf as conf
from oldman.utils.singleton import singleton_adv


@lru_cache(maxsize=100)
def _tz_for_name(tz_name: str) -> ZoneInfo:
    return ZoneInfo(tz_name)


@singleton_adv
class TimezoneManager:
    """时区管理器单例"""

    _common_timezones: dict[str, ZoneInfo] = {}

    def __init__(self):
        super().__init__()
        # 预加载常用时区
        self._init_common_timezones()

    def _init_common_timezones(self):
        """初始化常用时区"""
        self._common_timezones.setdefault("UTC", ZoneInfo("UTC"))

    def get_timezone(self, tz_name: str | None) -> ZoneInfo:
        """获取时区对象"""
        default_name = conf.settings.core.time_zone
        resolved_name = tz_name or default_name
        try:
            tz = self._common_timezones.get(resolved_name)
            if tz is None:
                tz = _tz_for_name(resolved_name)
                self._common_timezones[resolved_name] = tz
            return tz
        except Exception:
            fallback = self._common_timezones.get(default_name)
            if fallback is None:
                fallback = _tz_for_name(default_name)
                self._common_timezones[default_name] = fallback
            return fallback

    def convert_to_local(self, dt_value: datetime, tz_name: str) -> datetime:
        """转换时间到指定时区"""
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=UTC)
        target_tz = self.get_timezone(tz_name)
        return dt_value.astimezone(target_tz)
