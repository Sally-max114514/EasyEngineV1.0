"""EasyEngine 核心包：资源扫描、读取、启动自检与 Galgame 引擎。"""

__author__ = "Sally-max114514"
__github__ = "https://github.com/Sally-max114514/EasyEngineV1.0"
__github_profile__ = "https://github.com/Sally-max114514"
__version__ = "1.0.0 (MIT License)"
__generator__ = f"EasyEngine by {__author__}"

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
    "__author__",
    "__github__",
    "__github_profile__",
    "__generator__",
    "__version__",
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
