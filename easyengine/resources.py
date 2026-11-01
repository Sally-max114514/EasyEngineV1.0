"""递归扫描 assets/ 并按类型或子目录归类。

每个逻辑分类在 assets/ 下有独立文件夹：video、audio、image、text、other。
扩展名匹配统一转小写，因此 .MP4、.Mp4 和 .mp4 会归到同一类。文件内容
读取统一使用 with，句柄在读取结束后自动关闭。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

from .config import ASSETS_DIR, EXTENSION_GROUPS, OTHER_GROUP, RESOURCE_GROUPS

GroupedResources = dict[str, list[Path]]

_GROUP_BY_EXTENSION = {
    extension: group
    for group, extensions in EXTENSION_GROUPS.items()
    for extension in extensions
}
_GROUP_BY_NAME = {name.casefold(): name for name in RESOURCE_GROUPS}


def classify(path: str | Path, root: str | Path | None = None) -> str:
    """返回文件所属的资源类型。

    已知扩展名优先按扩展名判断；未知扩展名会参考 root 下的一级分类
    文件夹（例如 assets/image/sprite.aseprite -> image），否则归入 other。
    """
    path = Path(path)
    suffix = path.suffix.casefold().removeprefix(".")
    group = _GROUP_BY_EXTENSION.get(suffix)
    if group is not None:
        return group

    if root is not None:
        try:
            parts = path.relative_to(Path(root)).parts
        except ValueError:
            parts = ()
        if len(parts) > 1:
            folder_group = _GROUP_BY_NAME.get(parts[0].casefold())
            if folder_group is not None:
                return folder_group

    return OTHER_GROUP


def category_dir(category: str, root: str | Path = ASSETS_DIR) -> Path:
    """返回某个资源分类对应的规范文件夹，例如 assets/video。"""
    if category not in RESOURCE_GROUPS:
        raise ValueError(f"未知资源分类：{category!r}")
    return Path(root) / category


def ensure_category_dirs(root: str | Path = ASSETS_DIR) -> dict[str, Path]:
    """确保每种资源都有独立文件夹，已存在的目录保持原样。

    返回 {分类: 文件夹路径}。这些目录只是推荐的存放位置，扫描仍会
    递归查找整个 assets/，因此未归位的旧文件也不会被漏掉。
    """
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"资源目录不存在或不是目录：{root}")

    folders: dict[str, Path] = {}
    for category in RESOURCE_GROUPS:
        folder = category_dir(category, root)
        folder.mkdir(parents=True, exist_ok=True)
        folders[category] = folder
    return folders


def iter_asset_files(
    root: str | Path = ASSETS_DIR,
    *,
    include_hidden: bool = False,
) -> Iterator[Path]:
    """递归遍历 root 下的所有文件，默认跳过 . 开头的文件和目录。"""
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"资源目录不存在或不是目录：{root}")

    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        if not include_hidden and any(
            part.startswith(".") for part in path.relative_to(root).parts
        ):
            continue
        yield path


def scan_assets(
    root: str | Path = ASSETS_DIR,
    *,
    group_by: str = "type",
    include_hidden: bool = False,
) -> GroupedResources:
    """扫描资源目录并返回 {分组: [文件路径]}。

    group_by="type"：按扩展名归类到 video/audio/image/text/other，
    与 assets/ 下的同名分类文件夹保持一致；
    group_by="folder"：按相对子目录归类，根目录文件归入 "."。
    """
    root = Path(root)
    files = list(iter_asset_files(root, include_hidden=include_hidden))

    if group_by == "type":
        grouped: GroupedResources = {
            name: [] for name in (*EXTENSION_GROUPS, OTHER_GROUP)
        }
        for path in files:
            grouped[classify(path, root)].append(path)
        return grouped

    if group_by == "folder":
        grouped = {}
        for path in files:
            folder = path.parent.relative_to(root).as_posix()
            grouped.setdefault(folder or ".", []).append(path)
        return grouped

    raise ValueError(f"不支持的分组方式：{group_by!r}，请使用 'type' 或 'folder'")


def normalize_name(name: str) -> str:
    """统一分隔符并去掉首尾空白（包括换行符），用于资源查找。"""
    normalized = name.replace("\\", "/").strip().casefold()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def iter_resources(resources: Mapping[str, Iterable[Path]]) -> Iterator[Path]:
    """按分组顺序遍历资源，并跳过重复路径。"""
    seen: set[Path] = set()
    for paths in resources.values():
        for path in paths:
            if path not in seen:
                seen.add(path)
                yield path


class AssetCatalog:
    """一次扫描 assets/ 并建立大小写不敏感的资源索引。

    路径查找优先使用相对路径，文件名查找作为回退；同名文件按扫描顺序
    返回第一个匹配项。目录扫描用 pathlib 完成，索引可供引擎和渲染层复用。
    """

    def __init__(
        self,
        root: str | Path = ASSETS_DIR,
        *,
        resources: Mapping[str, Iterable[Path]] | None = None,
        include_hidden: bool = False,
    ) -> None:
        self.root = Path(root).absolute()
        if resources is None:
            self.resources = scan_assets(
                self.root,
                include_hidden=include_hidden,
            )
        else:
            self.resources = {
                group: list(paths)
                for group, paths in resources.items()
            }

        self._by_relative_path: dict[str, Path] = {}
        self._by_basename: dict[str, list[Path]] = {}
        for path in iter_resources(self.resources):
            absolute_path = Path(path)
            if not absolute_path.is_absolute():
                absolute_path = absolute_path.absolute()
            try:
                relative = absolute_path.relative_to(self.root).as_posix()
            except ValueError:
                continue
            self._by_relative_path.setdefault(relative.casefold(), absolute_path)
            self._by_basename.setdefault(absolute_path.name.casefold(), []).append(
                absolute_path
            )

    def resolve(self, name: str) -> Path:
        """按相对路径或文件名查找资源，大小写不敏感。"""
        target = normalize_name(name)
        if not target or any(part == ".." for part in Path(target).parts):
            raise ValueError(f"无效资源路径：{name!r}")

        match = self._by_relative_path.get(target)
        if match is not None:
            return match

        basename_matches = self._by_basename.get(Path(target).name.casefold())
        if basename_matches:
            if "/" in target:
                suffix = f"/{target}"
                for path in basename_matches:
                    try:
                        relative = path.relative_to(self.root).as_posix().casefold()
                    except ValueError:
                        continue
                    if relative.endswith(suffix):
                        return path
            return basename_matches[0]

        raise FileNotFoundError(f"找不到资源：{name}")

    def category(self, path: str | Path) -> str:
        """返回路径所属的资源分类。"""
        return classify(path, self.root)


def find_resource(
    resources: Mapping[str, Iterable[Path]],
    name: str,
) -> Path:
    """按文件名或相对路径查找资源，大小写不敏感。

    只给文件名且存在同名文件时，返回排序后的第一个匹配项；
    存在多份同名资源时应传入相对路径，例如 "video/intro.mp4"。
    """
    target = normalize_name(name)
    if not target:
        raise ValueError("资源名不能为空")

    candidates = list(iter_resources(resources))
    for path in candidates:
        if path.as_posix().casefold() == target:
            return path
    for path in candidates:
        if path.name.casefold() == target:
            return path
    for path in candidates:
        if path.as_posix().casefold().endswith("/" + target):
            return path
    raise FileNotFoundError(f"找不到资源：{name}")


def read_text(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> str:
    """读取文本资源，with 会在读取结束后自动关闭句柄。"""
    with Path(path).open("r", encoding=encoding, errors=errors) as handle:
        return handle.read()


def read_bytes(path: str | Path) -> bytes:
    """读取二进制资源，with 会在读取结束后自动关闭句柄。"""
    with Path(path).open("rb") as handle:
        return handle.read()


def load_text(
    resources: Mapping[str, Iterable[Path]],
    name: str,
    *,
    encoding: str = "utf-8",
) -> str:
    """查找并读取文本资源；查找不区分大小写，句柄自动关闭。"""
    return read_text(find_resource(resources, name), encoding=encoding)


def load_bytes(
    resources: Mapping[str, Iterable[Path]],
    name: str,
) -> bytes:
    """查找并读取二进制资源；查找不区分大小写，句柄自动关闭。"""
    return read_bytes(find_resource(resources, name))


def relative_path(path: str | Path, root: str | Path = ASSETS_DIR) -> str:
    """返回相对 root 的 POSIX 路径，便于展示；无法相对化时返回绝对路径。"""
    path = Path(path)
    try:
        return path.relative_to(Path(root)).as_posix()
    except ValueError:
        return path.as_posix()
