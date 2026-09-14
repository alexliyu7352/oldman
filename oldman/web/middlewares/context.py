"""
@author:alex
@date:2025/11/20
@time:19:11
"""

__author__ = "alex"

from oldman.db.schemas import tz_manager


async def add_timezone_info(request):
    tz_name = request.headers.get("X-Timezone", None)
    if not tz_name:
        # 从cookie中获取时区
        tz_name = request.cookies.get("timezone", "UTC")
    request.ctx.timezone = tz_manager.get_timezone(tz_name)
