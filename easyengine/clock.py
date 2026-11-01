"""时间相关的小工具。"""

from __future__ import annotations

from datetime import datetime


def get_current_time() -> str:
    """返回 YYYY-MM-DD HH:MM:SS 格式的当前时间。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")