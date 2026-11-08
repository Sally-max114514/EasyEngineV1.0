"""Package one validated EasyEngine story as a PyInstaller one-file game."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from easyengine import __author__, __generator__, __version__
from easyengine.galgame import ScriptError, assets_root_for_story, load_script

PROJECT_ROOT = Path(__file__).resolve().parent
MAIN_FILE = PROJECT_ROOT / "main.py"
_EXCLUDED_MODULES = (
    "PySide6",
    "PyQt6",
    "PyQt5",
    "PySide2",
    "shiboken6",
    "shiboken2",
)


def _ignore_script_library(
    source_assets: Path,
) -> Callable[[str, list[str]], set[str]]:
    text_dir = (source_assets / "text").resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        if Path(directory).resolve() == text_dir and "scripts" in names:
            return {"scripts"}
        return set()

    return ignore


def stage_assets(
    source_assets: str | Path,
    destination: str | Path,
    story_path: str | Path,
) -> Path:
    """Copy game assets while embedding only the selected story as demo.json."""
    source = Path(source_assets).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    selected_story = Path(story_path).expanduser().resolve()

    if source.is_dir():
        shutil.copytree(
            source,
            target,
            ignore=_ignore_script_library(source),
        )
    else:
        target.mkdir(parents=True, exist_ok=True)

    default_story = target / "text" / "scripts" / "demo.json"
    default_story.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw_story = json.loads(selected_story.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScriptError(f"剧本无法加入打包资源：{selected_story}（{exc}）") from exc
    if not isinstance(raw_story, dict):
        raise ScriptError(f"剧本顶层必须是 JSON 对象：{selected_story}")
    if "generator" not in raw_story and "_generator" not in raw_story:
        raw_story["_generator"] = __generator__
    default_story.write_text(
        json.dumps(raw_story, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return target


def write_windows_version_file(path: str | Path, *, executable_name: str) -> Path:
    """Write PyInstaller's Windows version resource with EasyEngine attribution."""
    target = Path(path)
    version = __version__.split(maxsplit=1)[0]
    target.write_text(
        "\n".join(
            (
                "VSVersionInfo(",
                "  ffi=FixedFileInfo(",
                "    filevers=(1, 0, 0, 0),",
                "    prodvers=(1, 0, 0, 0),",
                "    mask=0x3f, flags=0x0, OS=0x4,",
                "    fileType=0x1, subtype=0x0, date=(0, 0)",
                "  ),",
                "  kids=[",
                "    StringFileInfo([",
                "      StringTable('040904B0', [",
                f"        StringStruct('CompanyName', {__author__!r}),",
                "        StringStruct('FileDescription', 'EasyEngine game'),",
                f"        StringStruct('FileVersion', {version!r}),",
                f"        StringStruct('InternalName', {executable_name!r}),",
                f"        StringStruct('OriginalFilename', {(executable_name + '.exe')!r}),",
                f"        StringStruct('ProductName', {'EasyEngine'!r}),",
                f"        StringStruct('ProductVersion', {version!r}),",
                f"        StringStruct('LegalCopyright', {'Copyright (c) ' + __author__!r})",
                "      ])",
                "    ]),",
                "    VarFileInfo([VarStruct('Translation', [1033, 1200])])",
                "  ]",
                ")",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def distribution_archive_path(executable: str | Path) -> Path:
    game = Path(executable)
    name = game.stem if game.suffix.casefold() == ".exe" else game.name
    return game.with_name(f"{name}.zip")


def create_distribution_archive(executable: str | Path) -> Path:
    """Create a redistributable ZIP containing the game and project license."""
    game = Path(executable)
    license_path = PROJECT_ROOT / "LICENSE"
    if not license_path.is_file():
        raise FileNotFoundError(f"项目许可证不存在：{license_path}")
    archive_path = distribution_archive_path(game)
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.write(game, arcname=game.name)
        archive.write(license_path, arcname="LICENSE")
    return archive_path


def build_pyinstaller_command(
    *,
    name: str,
    staged_assets: str | Path,
    output_dir: str | Path,
    work_dir: str | Path,
    spec_dir: str | Path,
    main_file: str | Path = MAIN_FILE,
    python_executable: str | Path = sys.executable,
    version_file: str | Path | None = None,
    windows: bool | None = None,
) -> list[str]:
    """Build the platform-specific PyInstaller command without using a shell."""
    command = [
        str(python_executable),
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--name",
        name,
        "--distpath",
        str(output_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--add-data",
        f"{staged_assets}{os.pathsep}assets",
        "--hidden-import",
        "easyengine.desktop.app",
    ]
    for module in _EXCLUDED_MODULES:
        command.extend(("--exclude-module", module))
    if (os.name == "nt" if windows is None else windows) and version_file is not None:
        command.extend(("--version-file", str(version_file)))
    command.append(str(main_file))
    return command


def _validate_name(name: str) -> str:
    value = name.strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("游戏名称不能为空，也不能包含目录分隔符")
    return value


def export_game(
    story_path: str | Path,
    *,
    name: str | None = None,
    output_dir: str | Path = PROJECT_ROOT / "dist",
) -> Path:
    """Validate a story, stage its assets, and run PyInstaller."""
    story = load_script(story_path)
    if story.source_path is None:
        raise ScriptError("剧本没有来源文件，无法打包")
    game_name = _validate_name(name or story.title)
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    assets_root = assets_root_for_story(story)

    with TemporaryDirectory(prefix="easyengine-export-") as temporary:
        work_root = Path(temporary)
        staged_assets = stage_assets(
            assets_root,
            work_root / "assets",
            story.source_path,
        )
        version_file: Path | None = None
        if os.name == "nt":
            version_file = write_windows_version_file(
                work_root / "version_info.txt",
                executable_name=game_name,
            )
        command = build_pyinstaller_command(
            name=game_name,
            staged_assets=staged_assets,
            output_dir=output,
            work_dir=work_root / "build",
            spec_dir=work_root / "spec",
            version_file=version_file,
        )
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)

    suffix = ".exe" if os.name == "nt" else ""
    executable = output / f"{game_name}{suffix}"
    if not executable.is_file():
        raise RuntimeError(f"PyInstaller 未生成可执行文件：{executable}")
    create_distribution_archive(executable)
    return executable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="将指定 EasyEngine 剧本打包为单文件桌面游戏"
    )
    parser.add_argument("--story", required=True, type=Path, help="要打包的 JSON 剧本")
    parser.add_argument("--name", help="游戏名称（默认使用剧本标题）")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "dist",
        help="可执行文件输出目录（默认 dist/）",
    )
    args = parser.parse_args(argv)

    if importlib.util.find_spec("PyInstaller") is None:
        print(
            "未安装 PyInstaller。请运行："
            "python -m pip install -r requirements-export.txt"
        )
        return 1

    try:
        executable = export_game(
            args.story,
            name=args.name,
            output_dir=args.output,
        )
    except (
        ScriptError,
        ValueError,
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"游戏打包失败：{exc}")
        return 1

    print(f"游戏已打包：{executable}")
    archive_path = distribution_archive_path(executable)
    print(f"发布压缩包：{archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
