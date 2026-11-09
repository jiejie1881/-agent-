"""Business dates are independent of the operating system's timezone."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def business_today():
    return datetime.now(ZoneInfo(get_settings().business_timezone)).date()
