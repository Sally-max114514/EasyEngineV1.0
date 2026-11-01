"""集中管理项目路径和资源分类规则。"""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

CONFIG_DIR = PROJECT_ROOT / "config"
PLATFORM_FILE = CONFIG_DIR / "platform.txt"
ASSETS_DIR = PROJECT_ROOT / "assets"

SCRIPTS_DIR = ASSETS_DIR / "text" / "scripts"
DEMO_SCRIPT = SCRIPTS_DIR / "demo.json"
SAVE_DIR = PROJECT_ROOT / "saves"

# 扩展名一律写小写；匹配时会转成小写，所以 .MP4 / .Mp4 / .mp4 归为同一类。
# 每个分类对应 assets/ 下的同名文件夹：
#   assets/video  assets/audio  assets/image  assets/text  assets/other
EXTENSION_GROUPS: dict[str, frozenset[str]] = {
    "video": frozenset({"mp4", "avi", "mkv", "mov", "webm", "flv", "wmv", "m4v"}),
    "audio": frozenset({"mp3", "wav", "ogg", "flac", "m4a", "aac", "wma", "opus"}),
    "image": frozenset({"jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "svg", "ico"}),
    "text": frozenset({"txt", "md", "json", "csv", "xml", "yaml", "yml", "ini", "cfg", "log"}),
}

OTHER_GROUP = "other"

# 逻辑分类与 assets/ 下的物理文件夹一一对应：assets/video、assets/audio ...
RESOURCE_GROUPS: tuple[str, ...] = (*EXTENSION_GROUPS, OTHER_GROUP)
