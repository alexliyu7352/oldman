import enum
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def naive_utcnow() -> datetime:
    """当前 UTC 时间，去掉 tzinfo。

    数据库里的 DateTime 列大多是无时区的，存一个带时区的值会让同一列出现两种语义；模型默认值、
    “最后一次看到”时间戳和图表的起点都用这一个函数，不各写一遍 `datetime.now(UTC).replace(...)`。
    """
    return datetime.now(UTC).replace(tzinfo=None)


def convert_timezone(dt: datetime | str, from_tz: str | ZoneInfo, to_tz: str | ZoneInfo, dt_format: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """
    高效的时区转换函数

    Args:
        dt: datetime 对象或时间字符串
        from_tz: 源时区，如 "Asia/Shanghai" 或 ZoneInfo 对象
        to_tz: 目标时区，如 "UTC" 或 ZoneInfo 对象
        dt_format: 当 dt 为字符串时使用的格式

    Returns:
        转换后的 datetime 对象

    Example:
        >>> convert_timezone("2024-01-01 12:00:00", "Asia/Shanghai", "UTC")
        >>> convert_timezone(datetime.now(), "UTC", "America/New_York")
    """
    # 处理字符串输入
    if isinstance(dt, str):
        dt = datetime.strptime(dt, dt_format)

    # 转换时区参数
    from_zone = ZoneInfo(from_tz) if isinstance(from_tz, str) else from_tz
    to_zone = ZoneInfo(to_tz) if isinstance(to_tz, str) else to_tz

    # 设置源时区（如果 dt 是 naive datetime）
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=from_zone)

    # 转换到目标时区
    return dt.astimezone(to_zone)


def convert_to_utc(dt: datetime | str, from_tz: str | ZoneInfo, dt_format: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """将指定时区的时间转换为UTC时间"""
    return convert_timezone(dt, from_tz, "UTC", dt_format)


def convert_to_utc_text(dt: datetime | str, from_tz: str | ZoneInfo, dt_format: str = "%Y-%m-%d %H:%M:%S") -> str:
    """将指定时区的时间转换为UTC时间字符串；输入是字符串时按同一个 dt_format 解析。

    例如北京时间：``convert_to_utc_text("2026-09-26 08:00:00", "Asia/Shanghai")`` 得到 ``"2026-09-26 00:00:00"``。
    """
    return convert_to_utc(dt, from_tz, dt_format).strftime(dt_format)


def get_current_time_in_timezone(tz: str | ZoneInfo) -> datetime:
    """获取指定时区的当前时间"""
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    return datetime.now(zone)


class ElapsedType(enum.StrEnum):
    """ElapsedTimer.stop() 返回耗时所用的单位。"""

    MILLISECONDS = "milliseconds"
    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


_SECONDS_PER_UNIT = {
    ElapsedType.MILLISECONDS: 0.001,
    ElapsedType.SECONDS: 1.0,
    ElapsedType.MINUTES: 60.0,
    ElapsedType.HOURS: 3600.0,
    ElapsedType.DAYS: 86400.0,
}


class ElapsedTimer:
    """计时器：创建时即开始计时，stop() 按指定单位和精度返回经过的时间。

    用 ``time.perf_counter()``：单调递增、分辨率远高于毫秒，不受系统校时影响；``time.time()`` 会随校时跳变，
    算出的耗时可能偏大、偏小甚至为负。
    """

    def __init__(self) -> None:
        self.start_time: float | None = time.perf_counter()

    def start(self) -> None:
        """重新开始计时。"""
        self.start_time = time.perf_counter()

    def stop(self, unit: ElapsedType = ElapsedType.SECONDS, ndigits: int = 3) -> float:
        """停止计时，返回经过的时间：换算成 unit，保留 ndigits 位小数。

        默认是秒、3 位小数，即精确到毫秒；``stop(ElapsedType.MILLISECONDS, 1)`` 得到毫秒、精确到 0.1 毫秒。
        停止后要再计时先调用 start()。
        """
        if self.start_time is None:
            raise ValueError("Timer has not been started.")
        elapsed_seconds = time.perf_counter() - self.start_time
        self.start_time = None
        return round(elapsed_seconds / _SECONDS_PER_UNIT[unit], ndigits)


__all__ = [
    "naive_utcnow",
]
