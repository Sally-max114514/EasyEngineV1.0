"""EasyEngine 入口：启动自检 + 资源扫描 + Galgame 剧本校验/演示。

资源不再依赖 resources.txt / tree.txt 清单，目录里有什么就加载什么。
启动时会自动创建 assets/video、audio、image、text、other 五个分类文件夹，
新资源直接放进对应目录即可。

Galgame 核心用法：
    python main.py --validate            # 校验示例剧本
    python main.py --demo                # 无界面跑一遍示例剧本
    python main.py --story path/to.json  # 校验指定剧本
    python main.py --play                # 启动 Pygame 桌面窗口
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from importlib import import_module
from pathlib import Path

from easyengine.config import ASSETS_DIR, DEMO_SCRIPT, SCRIPTS_DIR
from easyengine.galgame import (
    EngineError,
    GalgameEngine,
    GameEvent,
    SaveError,
    ScriptError,
    Story,
    load_script,
)
from easyengine.resources import (
    GroupedResources,
    ensure_category_dirs,
    relative_path,
    scan_assets,
)
from easyengine.selfcheck import SelfCheckError, run_self_checks


def prepare_category_dirs(root: str | Path = ASSETS_DIR) -> dict[str, Path]:
    """为每种资源创建独立文件夹，并打印目录结构。"""
    folders = ensure_category_dirs(root)
    print("资源分类目录：")
    for category, folder in folders.items():
        print(f"  {category:<6} -> {relative_path(folder, root)}/")
    return folders


def show_resources(root: str | Path = ASSETS_DIR) -> GroupedResources:
    """扫描资源目录并打印分类结果，返回 {分组: [文件路径]}。"""
    resources = scan_assets(root)
    total = sum(len(paths) for paths in resources.values())
    print(f"游戏资源读取成功，共 {total} 个文件：{root}")

    for group, paths in resources.items():
        print(f"  {group}: {len(paths)} 个")
        for path in paths:
            print(f"    {relative_path(path, root)}")
    return resources


def show_story(
    story: Story,
    *,
    resources: GroupedResources | None = None,
) -> GalgameEngine:
    """打印剧本摘要和缺失资源，返回已构建的引擎。"""
    engine = GalgameEngine(story, resources=resources)
    print(f"Galgame 剧本：{story.title}")
    print(f"  起始场景：{story.start}，场景数：{len(story.scenes)}")
    if story.characters:
        names = "，".join(character.name for character in story.characters.values())
        print(f"  角色：{names}")

    missing = engine.missing_assets()
    if missing:
        print(f"  缺失资源 {len(missing)} 个（核心引擎仍可运行）：")
        for name in missing:
            print(f"    - {name}")
    return engine


def _print_events(events: Sequence[GameEvent]) -> None:
    for event in events:
        data = event.data
        if event.kind == "scene":
            print(f"  [场景] {data.get('scene')}")
        elif event.kind == "line":
            speaker = data.get("speaker")
            text = data.get("text", "")
            print(f"{speaker}：{text}" if speaker else text)
        elif event.kind == "choice":
            print(f"  > 选择：{data.get('text', '')}")
        elif event.kind == "variables":
            values = data.get("values", {})
            if values:
                changes = "，".join(f"{key}={value}" for key, value in values.items())
                print(f"  [变量] {changes}")
        elif event.kind == "background":
            reference = data.get("ref")
            print(f"  [背景] {reference.name if reference else '（清除）'}")
        elif event.kind == "bgm":
            reference = data.get("ref")
            print(f"  [BGM] {reference.name if reference else '（停止）'}")
        elif event.kind == "se":
            reference = data.get("ref")
            if reference is not None:
                print(f"  [音效] {reference.name}")
        elif event.kind == "sprite_show":
            print(f"  [立绘] {data.get('id')} @ {data.get('position')}")
        elif event.kind == "sprite_hide":
            print(f"  [立绘隐藏] {data.get('id')}")
        elif event.kind == "load":
            print(f"  [读档] {data.get('slot')}")
        elif event.kind == "end":
            print("—— 剧本结束 ——")


def _run_demo(engine: GalgameEngine, *, max_steps: int = 500) -> int:
    """无界面演示：自动选第一个可用选项，用于验证剧本流程。"""
    result = engine.start()
    _print_events(result.events)

    for _ in range(max_steps):
        view = engine.view
        if view.ended:
            return 0
        if not view.text_complete:
            engine.reveal_all()
            continue

        if view.choices:
            choices = engine.available_choices
            if not choices:
                print("当前选项全部未解锁，演示结束。")
                return 1
            result = engine.choose(choices[0].index)
        else:
            result = engine.advance()
        _print_events(result.events)

    print(f"演示达到 {max_steps} 步上限，剧本可能存在循环。")
    return 1


def run_story(
    path: Path,
    *,
    demo: bool,
    resources: GroupedResources | None = None,
) -> int:
    """加载、校验并可选运行一个剧本。"""
    try:
        story = load_script(path)
    except ScriptError as exc:
        print(f"剧本加载失败：{exc}")
        return 1

    engine = show_story(story, resources=resources)
    if not demo:
        return 0

    try:
        return _run_demo(engine)
    except (EngineError, SaveError) as exc:
        print(f"演示失败：{exc}")
        return 1


def _story_library(selected: Story) -> tuple[Story, ...]:
    """Load valid JSON scripts for the desktop story selector."""
    stories: list[Story] = []
    seen: set[str] = set()
    for path in sorted(
        (
            item
            for item in SCRIPTS_DIR.rglob("*")
            if item.is_file() and item.suffix.casefold() == ".json"
        ),
        key=lambda item: item.as_posix().casefold(),
    ):
        try:
            candidate = load_script(path)
        except ScriptError as exc:
            print(f"故事库忽略无效剧本：{path}（{exc}）")
            continue
        if candidate.fingerprint is not None and candidate.fingerprint not in seen:
            stories.append(candidate)
            seen.add(candidate.fingerprint)

    if selected.fingerprint not in seen:
        stories.insert(0, selected)
    return tuple(stories)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EasyEngine 启动器与 Galgame 核心")
    parser.add_argument("--story", type=Path, help="JSON 剧本路径")
    parser.add_argument("--validate", action="store_true", help="校验剧本并显示摘要")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="无界面运行剧本，自动选择第一个可用选项",
    )
    parser.add_argument(
        "--play",
        action="store_true",
        help="以 Pygame 桌面窗口运行剧本（需安装 requirements-ui.txt）",
    )
    args = parser.parse_args(argv)

    try:
        run_self_checks()
    except (SelfCheckError, OSError) as exc:
        print(f"启动自检失败：{exc}")
        return 1

    try:
        prepare_category_dirs()
        resources = show_resources()
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"资源读取失败：{exc}")
        return 1

    story_path = args.story or DEMO_SCRIPT
    if args.play:
        try:
            story = load_script(story_path)
        except ScriptError as exc:
            print(f"剧本加载失败：{exc}")
            return 1

        try:
            run_window: Callable[..., int] = import_module(
                "easyengine.desktop.app"
            ).run_window
        except ModuleNotFoundError as exc:
            if exc.name != "pygame":
                raise
            print(
                "桌面模式缺少 Pygame-CE。"
                "请运行：python -m pip install -r requirements-ui.txt"
            )
            return 1

        return run_window(
            story,
            assets_root=ASSETS_DIR,
            resources=resources,
            stories=_story_library(story),
        )

    if args.story or args.validate or args.demo:
        return run_story(story_path, demo=args.demo, resources=resources)

    if DEMO_SCRIPT.is_file():
        try:
            story = load_script(DEMO_SCRIPT)
        except ScriptError as exc:
            print(f"示例剧本校验失败：{exc}")
            return 1
        print(f"Galgame 示例剧本：{story.title}（{len(story.scenes)} 个场景）")
        print("  校验：python main.py --validate")
        print("  演示：python main.py --demo")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())