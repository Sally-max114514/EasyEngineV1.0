"""启动自检：操作系统、工作目录和项目目录结构。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .clock import get_current_time
from .config import ASSETS_DIR, CONFIG_DIR, PLATFORM_FILE


class SelfCheckError(RuntimeError):
    """启动自检未通过。"""


def check_os() -> None:
    """确认平台受支持，并把平台标识写入 config/platform.txt。"""
    if os.name not in {"posix", "nt"}:
        raise SelfCheckError(f"不支持的操作系统：{os.name}")
    print("Operating system is valid.")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PLATFORM_FILE.write_text(sys.platform, encoding="utf-8")


def check_working_directory() -> None:
    """确认当前工作目录存在且可枚举，scandir 句柄会自动关闭。"""
    cwd = Path.cwd()
    try:
        with os.scandir(cwd) as entries:
            next(entries, None)
    except OSError as exc:
        raise SelfCheckError(f"当前目录不可访问：{cwd}（{exc}）") from exc
    print("Current directory path is valid.")


def check_project_layout() -> None:
    """确认资源和配置目录存在，替代旧的 tree.txt 清单校验。"""
    missing = [path for path in (ASSETS_DIR, CONFIG_DIR) if not path.is_dir()]
    if missing:
        raise SelfCheckError("缺少必要目录：" + "、".join(map(str, missing)))
    print("Directory structure is valid.")


def run_self_checks() -> None:
    """依次运行全部自检，任一失败都会抛出 SelfCheckError。"""
    print(f"当前时间：{get_current_time()}")
    check_os()
    check_working_directory()
    check_project_layout()
