"""Concrete project settings."""

from __future__ import annotations

from typing import cast

import oldman.conf as conf
from config.schemas import Settings

settings = cast(Settings, conf.settings)
