import enum
import time
from datetime import datetime
from zoneinfo import ZoneInfo


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


def convert_cst_to_utc(dt: datetime | str, dt_format: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """将东八区时间转换为UTC时间"""
    return convert_timezone(dt, "Asia/Shanghai", "UTC", dt_format)


def convert_cst_to_utc_text(dt: datetime | str, dt_format: str = "%Y-%m-%d %H:%M:%S") -> str:
    """将东八区时间转换为UTC时间字符串"""
    utc_dt = convert_cst_to_utc(dt, dt_format)
    return utc_dt.strftime(dt_format)


def get_current_time_in_timezone(tz: str | ZoneInfo) -> datetime:
    """获取指定时区的当前时间"""
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    return datetime.now(zone)


class ElapsedType(enum.StrEnum):
    """
    定义时间间隔类型
    """

    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


class ElapsedTimer:
    def __init__(self) -> None:
        self.start_time: float | None = time.time()

    def start(self) -> None:
        self.start_time = time.time()

    def stop(self) -> float:
        if self.start_time is None:
            raise ValueError("Timer has not been started.")
        elapsed_time = time.time() - self.start_time
        self.start_time = None
        # 保留2位小数
        return round(elapsed_time, 2)
