"""Concrete project settings."""

from __future__ import annotations

from typing import cast

from oldman import conf

from config.schemas import Settings

settings = cast(Settings, conf.settings)
