"""
@author:alex
@date:2025/8/10
@time:14:06
"""

__author__ = "alex"
import random

from fake_useragent import UserAgent

import oldman.conf as conf
from oldman.conf import constants

random_ua = UserAgent(
    browsers=constants.USER_AGENT_DICT_DEFINE["browsers"],
    os=constants.USER_AGENT_DICT_DEFINE["os"],
    platforms=constants.USER_AGENT_DICT_DEFINE["platforms"],
)


def get_fake_user_agent() -> str:
    """Return the configured outbound User-Agent or a generated fallback."""
    configured_user_agent = conf.settings.http_client.user_agent
    return configured_user_agent or random_ua.random


def get_random_ua() -> str:
    """Generate one Chrome-like User-Agent without reading project settings."""
    a = random.randint(55, 62)
    c = random.randint(0, 3200)
    d = random.randint(0, 140)
    os_type = ["(Windows NT 6.1; WOW64)", "(Windows NT 10.0; WOW64)", "(X11; Linux x86_64)", "(Macintosh; Intel Mac OS X 10_12_6)"]
    chrome_version = f"Chrome/{a}.0.{c}.{d}"
    ua = " ".join(["Mozilla/5.0", random.choice(os_type), "AppleWebKit/537.36", "(KHTML, like Gecko)", chrome_version, "Safari/537.36"])
    return ua


def only_ua_header() -> dict[str, str]:
    """Return a header mapping containing only the effective User-Agent."""
    return {"user-agent": get_fake_user_agent()}
