"""EasyEngine 核心包：资源扫描、读取、启动自检与 Galgame 引擎。"""

from .galgame import (
    GalgameEngine,
    GameView,
    SaveError,
    ScriptError,
    TextTyper,
    load_script,
)
from .resources import (
    category_dir,
    ensure_category_dirs,
    find_resource,
    load_bytes,
    load_text,
    read_bytes,
    read_text,
    scan_assets,
)

__all__ = [
    "GalgameEngine",
    "GameView",
    "SaveError",
    "ScriptError",
    "TextTyper",
    "category_dir",
    "ensure_category_dirs",
    "find_resource",
    "load_bytes",
    "load_text",
    "load_script",
    "read_bytes",
    "read_text",
    "scan_assets",
]
