"""无界面 Galgame 核心引擎。

引擎只负责剧情推进、变量、分支、存读档和资源引用解析，不依赖任何
界面或音频库。界面层通过 StepResult.events 响应背景、音乐、立绘变化，
通过 GameView 渲染当前台词和选项。
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..config import ASSETS_DIR, SAVE_DIR
from ..resources import AssetCatalog, GroupedResources, find_resource, scan_assets
from .expressions import ExpressionError, evaluate_expression
from .script import (
    JSONValue,
    Line,
    ScriptError,
    Story,
    Transition,
    VariableChange,
    load_script,
)
from .state import (
    GameState,
    SaveError,
    SpriteState,
    load_game,
    save_game,
    slot_path,
)
from .text import TextTyper

_MAX_CONSECUTIVE_JUMPS = 100
_JUMP_LOOP_ERROR = "检测到可能的死循环跳转，请检查剧本的 goto/next 逻辑"
logger = logging.getLogger(__name__)


def assets_root_for_story(story: Story) -> Path:
    """Infer the asset directory associated with a file-backed story."""
    source_path = story.source_path
    if source_path is None:
        return ASSETS_DIR

    source_path = source_path.resolve()
    for parent in source_path.parents:
        if parent.name.casefold() == "assets":
            return parent
    return source_path.parent / "assets"


class EngineError(RuntimeError):
    """Galgame 引擎错误基类。"""


class EngineStateError(EngineError):
    """调用顺序或当前状态不允许该操作。"""


class ChoiceUnavailableError(EngineStateError):
    """选项的前置条件未满足。"""


@dataclass(frozen=True)
class AssetRef:
    """剧本中的资源引用；path 为 None 表示文件尚未放入 assets/。"""

    name: str
    path: Path | None = None

    @property
    def exists(self) -> bool:
        return self.path is not None


@dataclass(frozen=True)
class SpriteView:
    id: str
    image: AssetRef
    position: str


@dataclass(frozen=True)
class ChoiceView:
    index: int
    text: str
    available: bool


@dataclass(frozen=True)
class GameEvent:
    """界面层需要响应的瞬时事件，例如换背景、播放音乐。"""

    kind: str
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GameView:
    """当前画面快照，可在任意时刻重复读取。"""

    started: bool
    ended: bool
    scene_id: str | None
    line_index: int
    speaker_id: str | None
    speaker: str | None
    text: str
    visible_text: str
    text_complete: bool
    background: AssetRef | None
    bgm: AssetRef | None
    voice: AssetRef | None
    sprites: tuple[SpriteView, ...]
    choices: tuple[ChoiceView, ...]
    variables: Mapping[str, JSONValue]


@dataclass(frozen=True)
class StepResult:
    events: tuple[GameEvent, ...]
    view: GameView


@dataclass(frozen=True)
class _HistorySnapshot:
    state: GameState
    visible_chars: int


class GalgameEngine:
    """推进 JSON 剧本的无界面核心引擎。"""

    def __init__(
        self,
        story: Story,
        *,
        assets_root: str | Path | None = None,
        resources: GroupedResources | None = None,
        asset_catalog: AssetCatalog | None = None,
        save_dir: str | Path = SAVE_DIR,
    ) -> None:
        self.story = story
        if asset_catalog is not None and resources is not None:
            raise ValueError("asset_catalog 与 resources 不能同时传入")
        self.asset_catalog = asset_catalog
        self._assets_root_explicit = assets_root is not None or asset_catalog is not None
        self._scan_resources_on_reload = resources is None and asset_catalog is None
        self.assets_root = (
            asset_catalog.root
            if asset_catalog is not None
            else (
                Path(assets_root).absolute()
                if assets_root is not None
                else assets_root_for_story(story)
            )
        )
        self.save_dir = Path(save_dir)
        if asset_catalog is not None:
            self.resources = asset_catalog.resources
        else:
            self.resources = (
                resources if resources is not None else self._scan_resources()
            )
        self.state: GameState | None = None
        self.typer: TextTyper | None = None
        self._line: Line | None = None
        self.jump_count = 0
        self._history: list[_HistorySnapshot] = []
        self._read_history: set[str] = set()
        self._reported_missing_assets: set[str] = set()

    def _scan_resources(self) -> GroupedResources:
        try:
            return scan_assets(self.assets_root)
        except FileNotFoundError as exc:
            logger.error("资源目录不可用：%s（%s）", self.assets_root, exc)
            return {}

    def resolve_asset(self, name: str | None) -> AssetRef | None:
        """把剧本中的资源名解析为实际路径，找不到时 path 为 None。"""
        if not name:
            return None
        try:
            path = (
                self.asset_catalog.resolve(name)
                if self.asset_catalog is not None
                else find_resource(self.resources, name)
            )
            return AssetRef(name, path)
        except FileNotFoundError:
            key = name.casefold()
            if key not in self._reported_missing_assets:
                logger.error("资源缺失：%s（资源目录：%s）", name, self.assets_root)
                self._reported_missing_assets.add(key)
            return AssetRef(name, None)
        except ValueError as exc:
            logger.error("资源路径无效：%s（%s）", name, exc)
            raise

    def missing_assets(self) -> tuple[str, ...]:
        """列出剧本引用但 assets/ 中不存在的资源。"""
        missing: list[str] = []
        for name in self.story.asset_references():
            reference = self.resolve_asset(name)
            if reference is None or reference.path is None:
                missing.append(name)
        return tuple(missing)

    def start(self, scene_id: str | None = None) -> StepResult:
        """从起始场景（或指定场景）开始，重置全部运行时状态。"""
        target = scene_id or self.story.start
        if target not in self.story.scenes:
            logger.error("起始场景不存在：%s", target)
            raise EngineStateError(f"场景不存在：{target!r}")

        logger.info("开始剧本《%s》，场景：%s", self.story.title, target)
        events: list[GameEvent] = []
        self.state = GameState(
            scene_id=target,
            variables=copy.deepcopy(dict(self.story.variables)),
            seen_lines=set(self._read_history),
        )
        self.typer = None
        self._line = None
        self.jump_count = 0
        self._history.clear()
        self._enter_scene(target, events)
        return StepResult(tuple(events), self.view)

    def reload_script(self) -> StepResult:
        """Reload the source JSON and reset the runtime to its starting scene."""
        source_path = self.story.source_path
        if source_path is None:
            message = "当前剧本不是从文件加载的，无法重新加载"
            logger.error(message)
            raise EngineStateError(message)

        try:
            story = load_script(source_path)
        except ScriptError as exc:
            logger.error("重新加载剧本失败：%s", exc)
            raise

        self.story = story
        if not self._assets_root_explicit:
            self.assets_root = assets_root_for_story(story)
        if self._scan_resources_on_reload:
            self.resources = self._scan_resources()
        self._reported_missing_assets.clear()
        self._read_history.clear()
        self.jump_count = 0
        logger.info("已重新加载剧本《%s》", story.title)
        return self.start()

    def advance(self) -> StepResult:
        """显示完整当前行；已完整时推进到下一行或下一场景。"""
        state = self._require_state()
        if state.ended:
            return StepResult((), self.view)

        if self.typer is not None and not self.typer.is_complete:
            self.typer.reveal_all()
            self._mark_current_line_seen()
            return StepResult(
                (GameEvent("text_complete", {"text": self.typer.text}),),
                self.view,
            )

        line = self._line
        if line is None:
            self._remember_current()
            events: list[GameEvent] = []
            self._finish_scene(events)
            return StepResult(tuple(events), self.view)

        if line.choices:
            logger.error("当前台词包含选项，不能直接推进")
            raise EngineStateError("当前行有选项，请调用 choose(index)")

        self._mark_current_line_seen()
        self._remember_current()
        events = []
        if line.end:
            self._end_game(events)
        elif line.goto is not None:
            self._record_jump(line.goto)
            self._enter_scene(line.goto, events)
        else:
            self._show_line(state.line_index + 1, events)
        return StepResult(tuple(events), self.view)

    def choose(self, index: int) -> StepResult:
        """选择一个选项；index 是 GameView.choices 中的原始下标。"""
        state = self._require_state()
        if state.ended:
            logger.error("剧本已结束，不能选择选项")
            raise EngineStateError("剧本已经结束")
        line = self._line
        if line is None or not line.choices:
            logger.error("当前台词没有可选分支")
            raise EngineStateError("当前行没有选项")
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("选项下标必须是整数")
        if not 0 <= index < len(line.choices):
            raise IndexError(f"选项下标越界：{index}")

        choice = line.choices[index]
        if not choice.available(state.variables):
            logger.error("选项条件未满足：%s", choice.text)
            raise ChoiceUnavailableError(f"选项尚未解锁：{choice.text}")

        if self.typer is not None and not self.typer.is_complete:
            self.typer.reveal_all()
        self._mark_current_line_seen()
        self._remember_current()

        events: list[GameEvent] = [
            GameEvent("choice", {"index": index, "text": choice.text})
        ]
        self._apply_changes(choice.changes, events)
        if choice.goto is not None:
            self._record_jump(choice.goto)
            self._enter_scene(choice.goto, events)
        else:
            self._show_line(state.line_index + 1, events)
        return StepResult(tuple(events), self.view)

    def tick(self, count: int = 1) -> GameView:
        """打字机推进 count 个字符，返回最新画面快照。"""
        self._require_state()
        if self.typer is not None:
            self.typer.tick(count)
            if self.typer.is_complete:
                self._mark_current_line_seen()
        return self.view

    def reveal_all(self) -> GameView:
        """立即显示当前行全部文字。"""
        self._require_state()
        if self.typer is not None:
            self.typer.reveal_all()
            self._mark_current_line_seen()
        return self.view

    @property
    def current_line_seen(self) -> bool:
        state = self.state
        if state is None or self._line is None:
            return False
        key = self._line_key(state.scene_id, state.line_index)
        return key in self._read_history or key in state.seen_lines

    @property
    def rollback_depth(self) -> int:
        return len(self._history)

    def rollback(self, steps: int = 1) -> StepResult:
        """Restore a previous dialogue snapshot, including partial typewriter text."""
        if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
            raise ValueError("steps 必须是正整数")
        if steps > len(self._history):
            raise EngineStateError("没有足够的剧情记录可回滚")

        snapshot = self._history[-steps]
        del self._history[-steps:]
        self.state = copy.deepcopy(snapshot.state)
        state = self.state
        state.seen_lines.update(self._read_history)
        scene = self.story.scenes.get(state.scene_id)
        if scene is None or not 0 <= state.line_index < len(scene.lines):
            raise EngineStateError("回滚记录指向无效的剧情位置")
        self._line = scene.lines[state.line_index]
        self.typer = TextTyper(self._line.text, snapshot.visible_chars)
        scene_transition = self.story.scenes[state.scene_id].transition
        events = [
            GameEvent("rollback", {"steps": steps}),
            GameEvent(
                "scene",
                {"scene": state.scene_id, "transition": scene_transition},
            ),
            GameEvent("background", {"ref": self.resolve_asset(state.background)}),
            GameEvent("bgm", {"ref": self.resolve_asset(state.bgm)}),
            GameEvent("sprites", {"sprites": self.view.sprites}),
            GameEvent("variables", {"values": dict(state.variables)}),
            self._line_event(self._line),
        ]
        return StepResult(tuple(events), self.view)

    @property
    def available_choices(self) -> tuple[ChoiceView, ...]:
        return tuple(choice for choice in self.view.choices if choice.available)

    @property
    def view(self) -> GameView:
        if self.state is None:
            return GameView(
                started=False,
                ended=False,
                scene_id=None,
                line_index=0,
                speaker_id=None,
                speaker=None,
                text="",
                visible_text="",
                text_complete=True,
                background=None,
                bgm=None,
                voice=None,
                sprites=(),
                choices=(),
                variables={},
            )

        state = self.state
        line = self._line
        text = line.text if line is not None else ""
        typer = self.typer
        visible_text = typer.visible_text if typer is not None else text
        text_complete = typer.is_complete if typer is not None else True

        sprites = tuple(
            SpriteView(
                id=sprite_id,
                image=self._resolved_ref(sprite.image),
                position=sprite.position,
            )
            for sprite_id, sprite in sorted(state.sprites.items())
        )

        return GameView(
            started=True,
            ended=state.ended,
            scene_id=state.scene_id,
            line_index=state.line_index,
            speaker_id=line.speaker if line is not None else None,
            speaker=self.story.speaker_name(line.speaker) if line is not None else None,
            text=text,
            visible_text=visible_text,
            text_complete=text_complete,
            background=self.resolve_asset(state.background),
            bgm=self.resolve_asset(state.bgm),
            voice=(
                self.resolve_asset(line.voice)
                if line is not None and line.voice
                else None
            ),
            sprites=sprites,
            choices=self._choice_views(line, state),
            variables=dict(state.variables),
        )

    def save(self, slot: str = "quick") -> Path:
        """保存到 saves/<slot>.json，返回存档路径。"""
        state = self._require_state()
        path = slot_path(self.save_dir, slot)
        save_game(
            path,
            state,
            script_title=self.story.title,
            script_fingerprint=self.story.fingerprint,
        )
        return path

    def load(self, slot: str = "quick") -> StepResult:
        """读取存档并恢复剧情位置、变量、背景、音乐和立绘。

        当前行会从头开始打字机显示，界面层调用 tick() 推进即可。
        """
        path = slot_path(self.save_dir, slot)
        save_data = load_game(path)
        if save_data.script_title and save_data.script_title != self.story.title:
            raise SaveError(
                f"存档属于剧本《{save_data.script_title}》，"
                f"当前剧本是《{self.story.title}》"
            )
        if (
            save_data.script_fingerprint is not None
            and save_data.script_fingerprint != self.story.fingerprint
        ):
            raise SaveError(
                "存档的剧本内容与当前版本不匹配；请恢复原剧本或新开存档"
            )

        state = save_data.state
        scene = self.story.scenes.get(state.scene_id)
        if scene is None:
            raise SaveError(f"存档指向不存在的场景：{state.scene_id!r}")

        if state.ended:
            if scene.lines:
                if state.line_index >= len(scene.lines):
                    state.line_index = len(scene.lines) - 1
                self._line = scene.lines[state.line_index]
                typer = TextTyper(self._line.text)
                typer.reveal_all()
                self.typer = typer
            else:
                self._line = None
                self.typer = None
        else:
            if not 0 <= state.line_index < len(scene.lines):
                raise SaveError("存档中的行号超出剧本范围")
            self._line = scene.lines[state.line_index]
            self.typer = TextTyper(self._line.text)

        self.state = state
        self.jump_count = 0
        self._history.clear()
        self._read_history.update(state.seen_lines)

        events: list[GameEvent] = [
            GameEvent(
                "load",
                {
                    "slot": slot,
                    "unverified": save_data.script_fingerprint is None,
                },
            ),
            GameEvent(
                "scene",
                {
                    "scene": state.scene_id,
                    "transition": self.story.scenes[state.scene_id].transition,
                },
            ),
            GameEvent("background", {"ref": self.resolve_asset(state.background)}),
            GameEvent("bgm", {"ref": self.resolve_asset(state.bgm)}),
            GameEvent("sprites", {"sprites": self.view.sprites}),
            GameEvent("variables", {"values": dict(state.variables)}),
        ]
        if self._line is not None:
            events.append(self._line_event(self._line))
        if state.ended:
            events.append(GameEvent("end", {"scene": state.scene_id}))
        return StepResult(tuple(events), self.view)

    def list_saves(self) -> tuple[str, ...]:
        """列出当前剧本存档目录中的存档名。"""
        if not self.save_dir.is_dir():
            return ()
        return tuple(
            sorted(
                path.stem
                for path in self.save_dir.glob("*.json")
                if path.is_file() and path.name != "voice-favorites.json"
            )
        )

    def _enter_scene(self, scene_id: str, events: list[GameEvent]) -> None:
        state = self._require_state()
        scene = self.story.scenes.get(scene_id)
        if scene is None:
            logger.error("跳转目标场景不存在：%s", scene_id)
            raise EngineStateError(f"场景不存在：{scene_id!r}")

        logger.info("进入场景：%s", scene_id)
        state.scene_id = scene_id
        state.line_index = 0
        state.ended = False
        self._line = None
        self.typer = None

        events.append(
            GameEvent(
                "scene",
                {"scene": scene_id, "transition": scene.transition},
            )
        )
        if scene.background is not None:
            self._set_background(scene.background, events)
        if scene.bgm is not None:
            self._set_bgm(scene.bgm, events)
        self._show_line(0, events)

    def _show_line(self, index: int, events: list[GameEvent]) -> None:
        state = self._require_state()
        scene = self.story.scenes[state.scene_id]
        if index >= len(scene.lines):
            self._finish_scene(events)
            return

        state.line_index = index
        line = scene.lines[index]
        self._line = line
        self._apply_line(line, events)
        self.typer = TextTyper(line.text)
        logger.info("显示台词：场景 %s，第 %s 行", state.scene_id, index)
        if not line.text:
            self._mark_current_line_seen()
        events.append(self._line_event(line))

    def _finish_scene(self, events: list[GameEvent]) -> None:
        state = self._require_state()
        scene = self.story.scenes[state.scene_id]
        if scene.next is not None:
            self._record_jump(scene.next)
            self._enter_scene(scene.next, events)
            return
        self._end_game(events)

    def _record_jump(self, target: str) -> None:
        state = self._require_state()
        self.jump_count += 1
        if self.jump_count > _MAX_CONSECUTIVE_JUMPS:
            logger.error("%s；当前场景 ID：%s", _JUMP_LOOP_ERROR, state.scene_id)
            raise ScriptError(_JUMP_LOOP_ERROR)
        logger.info(
            "剧情跳转：%s -> %s（连续无台词跳转 %s 次）",
            state.scene_id,
            target,
            self.jump_count,
        )

    def _end_game(self, events: list[GameEvent]) -> None:
        state = self._require_state()
        logger.info("剧本结束：场景 %s", state.scene_id)
        state.ended = True
        if self.typer is not None:
            self.typer.reveal_all()
        events.append(GameEvent("end", {"scene": state.scene_id}))

    def _apply_line(self, line: Line, events: list[GameEvent]) -> None:
        state = self._require_state()
        if line.transition is not None:
            events.append(GameEvent("transition", {"transition": line.transition}))
        elif line.background is not None and state.line_index > 0:
            events.append(GameEvent("transition", {"transition": Transition()}))
        if line.background is not None:
            self._set_background(line.background, events)
        if line.bgm is not None:
            self._set_bgm(line.bgm, events)
        if line.se:
            events.append(GameEvent("se", {"ref": self._resolved_ref(line.se)}))

        for sprite in line.show:
            state.sprites[sprite.id] = SpriteState(sprite.image, sprite.position)
            events.append(
                GameEvent(
                    "sprite_show",
                    {
                        "id": sprite.id,
                        "image": self._resolved_ref(sprite.image),
                        "position": sprite.position,
                    },
                )
            )
        for sprite_id in line.hide:
            if sprite_id == "all":
                state.sprites.clear()
                events.append(GameEvent("sprite_hide", {"id": "all"}))
            else:
                state.sprites.pop(sprite_id, None)
                events.append(GameEvent("sprite_hide", {"id": sprite_id}))

        self._apply_changes(line.changes, events)

    def _apply_changes(
        self,
        changes: VariableChange,
        events: list[GameEvent],
    ) -> None:
        state = self._require_state()
        changed: dict[str, JSONValue] = {}
        for key, value in changes.set_values.items():
            changed[key] = state.set(key, value)
        for key, amount in changes.add_values.items():
            changed[key] = state.add(key, amount)
        for key, expression in changes.set_expressions.items():
            changed[key] = self._evaluate_change(key, expression, state)
            state.set(key, changed[key])
        for key, expression in changes.add_expressions.items():
            value = self._evaluate_change(key, expression, state)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                message = f"变量 {key!r} 的 add_expr 必须计算出数字"
                logger.error(message)
                raise EngineError(message)
            changed[key] = state.add(key, value)
        if changed:
            events.append(GameEvent("variables", {"values": dict(changed)}))

    @staticmethod
    def _evaluate_change(
        key: str,
        expression: str,
        state: GameState,
    ) -> JSONValue:
        try:
            return evaluate_expression(expression, state.variables)
        except ExpressionError as exc:
            logger.error(
                "变量 %r 的表达式运行失败：%r（%s）",
                key,
                expression,
                exc,
            )
            raise EngineError(
                f"变量 {key!r} 的表达式运行失败：{expression!r}（{exc}）"
            ) from exc

    def _remember_current(self) -> None:
        if self.state is None or self._line is None:
            return
        visible_chars = self.typer.visible_chars if self.typer is not None else 0
        self._history.append(
            _HistorySnapshot(copy.deepcopy(self.state), visible_chars)
        )

    def _mark_current_line_seen(self) -> None:
        state = self.state
        if state is None or self._line is None:
            return
        key = self._line_key(state.scene_id, state.line_index)
        state.seen_lines.add(key)
        self._read_history.add(key)

    @staticmethod
    def _line_key(scene_id: str, line_index: int) -> str:
        return f"{len(scene_id)}:{scene_id}:{line_index}"

    def _set_background(self, reference: str, events: list[GameEvent]) -> None:
        state = self._require_state()
        if reference == "":
            state.background = None
            events.append(GameEvent("background", {"ref": None}))
        else:
            state.background = reference
            events.append(
                GameEvent("background", {"ref": self._resolved_ref(reference)})
            )

    def _set_bgm(self, reference: str, events: list[GameEvent]) -> None:
        state = self._require_state()
        if reference == "":
            state.bgm = None
            events.append(GameEvent("bgm", {"ref": None}))
        else:
            state.bgm = reference
            events.append(GameEvent("bgm", {"ref": self._resolved_ref(reference)}))

    def _resolved_ref(self, name: str) -> AssetRef:
        reference = self.resolve_asset(name)
        return reference if reference is not None else AssetRef(name)

    def _line_event(self, line: Line) -> GameEvent:
        state = self._require_state()
        self.jump_count = 0
        return GameEvent(
            "line",
            {
                "speaker_id": line.speaker,
                "speaker": self.story.speaker_name(line.speaker),
                "text": line.text,
                "voice": (
                    self._resolved_ref(line.voice)
                    if line.voice
                    else None
                ),
                "transition": line.transition,
                "choices": self._choice_views(line, state),
            },
        )

    def _choice_views(
        self,
        line: Line | None,
        state: GameState,
    ) -> tuple[ChoiceView, ...]:
        if line is None or state.ended or not line.choices:
            return ()
        return tuple(
            ChoiceView(index, choice.text, choice.available(state.variables))
            for index, choice in enumerate(line.choices)
        )

    def _require_state(self) -> GameState:
        if self.state is None:
            raise EngineStateError("引擎尚未启动，请先调用 start()")
        return self.state
