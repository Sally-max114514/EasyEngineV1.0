"""Galgame JSON 剧本的数据模型、解析与校验。

剧本示例：

    {
      "title": "放学后",
      "start": "start",
      "characters": {"yuki": {"name": "雪乃"}},
      "vars": {"affection.yuki": 0, "flags.met": false},
      "scenes": {
        "start": {
          "background": "image/bg/classroom.png",
          "bgm": "audio/bgm/daily.mp3",
          "lines": [
            {"speaker": "yuki", "text": "一起回家吧？",
             "choices": [
               {"text": "好啊", "add": {"affection.yuki": 1}, "goto": "good"},
               {"text": "下次吧", "goto": "normal"}
             ]}
          ]
        },
        "good": {"lines": [{"text": "—— 好结局 ——", "end": true}]},
        "normal": {"lines": [{"text": "—— 普通结局 ——", "end": true}]}
      }
    }
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, TypeAlias

from .expressions import (
    ExpressionError,
    evaluate_expression,
    lookup_variable,
    validate_expression,
)

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list[Any] | dict[str, Any]
SPRITE_POSITIONS: frozenset[str] = frozenset({"left", "center", "right"})
TRANSITION_TYPES: frozenset[str] = frozenset(
    {"none", "fade", "crossfade", "slide-left", "slide-right"}
)

_COMPARISON_OPS: frozenset[str] = frozenset({"==", "!=", ">", ">=", "<", "<="})
_STORY_KEYS = frozenset({"title", "start", "characters", "vars", "scenes", "gallery"})
_SCENE_KEYS = frozenset(
    {"background", "bgm", "lines", "next", "end", "transition"}
)
_LINE_KEYS = frozenset(
    {
        "speaker",
        "text",
        "background",
        "bgm",
        "se",
        "show",
        "hide",
        "set",
        "add",
        "set_expr",
        "add_expr",
        "goto",
        "choices",
        "end",
        "voice",
        "transition",
    }
)
_CHOICE_KEYS = frozenset(
    {"text", "goto", "set", "add", "set_expr", "add_expr", "require"}
)
_CHARACTER_KEYS = frozenset({"name", "color"})
_GALLERY_KEYS = frozenset({"id", "image", "title", "description"})


class ScriptError(ValueError):
    """剧本格式或引用错误。"""


@dataclass(frozen=True)
class Condition:
    """变量条件，例如 affection.yuki >= 3。"""

    key: str
    op: str
    value: JSONValue

    def test(self, variables: Mapping[str, JSONValue]) -> bool:
        actual = lookup_variable(variables, self.key)
        expected = self.value
        if self.op == "==":
            return actual == expected
        if self.op == "!=":
            return actual != expected
        if self.op not in _COMPARISON_OPS:
            raise ScriptError(f"未知条件运算符：{self.op!r}")
        if isinstance(actual, bool) or isinstance(expected, bool):
            return False
        numeric_pair = (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
        )
        string_pair = isinstance(actual, str) and isinstance(expected, str)
        if not (numeric_pair or string_pair):
            return False
        try:
            if self.op == ">":
                return actual > expected
            if self.op == ">=":
                return actual >= expected
            if self.op == "<":
                return actual < expected
            return actual <= expected
        except TypeError:
            return False


@dataclass(frozen=True)
class ExpressionCondition:
    expression: str

    def test(self, variables: Mapping[str, JSONValue]) -> bool:
        try:
            return bool(evaluate_expression(self.expression, variables))
        except ExpressionError as exc:
            raise ScriptError(
                f"条件表达式运行失败：{self.expression!r}（{exc}）"
            ) from exc


@dataclass(frozen=True)
class ConditionGroup:
    operator: str
    conditions: tuple[ConditionNode, ...]

    def test(self, variables: Mapping[str, JSONValue]) -> bool:
        if self.operator == "all":
            return all(condition.test(variables) for condition in self.conditions)
        if self.operator == "any":
            return any(condition.test(variables) for condition in self.conditions)
        if self.operator == "not":
            return not self.conditions[0].test(variables)
        raise ScriptError(f"未知条件组合：{self.operator!r}")


ConditionNode: TypeAlias = Condition | ExpressionCondition | ConditionGroup


@dataclass(frozen=True)
class VariableChange:
    """一次性变量变更：set 赋绝对值，add 做数值累加。"""

    set_values: Mapping[str, JSONValue] = field(default_factory=dict)
    add_values: Mapping[str, int | float] = field(default_factory=dict)
    set_expressions: Mapping[str, str] = field(default_factory=dict)
    add_expressions: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Transition:
    kind: str = "fade"
    duration: float = 0.32


@dataclass(frozen=True)
class GalleryEntry:
    id: str
    image: str
    title: str
    description: str = ""


@dataclass(frozen=True)
class SpriteCommand:
    id: str
    image: str
    position: str = "center"


@dataclass(frozen=True)
class Choice:
    text: str
    goto: str | None = None
    changes: VariableChange = field(default_factory=VariableChange)
    require: tuple[ConditionNode, ...] = ()

    def available(self, variables: Mapping[str, JSONValue]) -> bool:
        return all(condition.test(variables) for condition in self.require)


@dataclass(frozen=True)
class Line:
    text: str = ""
    speaker: str | None = None
    background: str | None = None
    bgm: str | None = None
    voice: str | None = None
    se: str | None = None
    show: tuple[SpriteCommand, ...] = ()
    hide: tuple[str, ...] = ()
    changes: VariableChange = field(default_factory=VariableChange)
    goto: str | None = None
    choices: tuple[Choice, ...] = ()
    end: bool = False
    transition: Transition | None = None


@dataclass(frozen=True)
class Scene:
    id: str
    lines: tuple[Line, ...] = ()
    background: str | None = None
    bgm: str | None = None
    next: str | None = None
    end: bool = False
    transition: Transition = field(default_factory=Transition)


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    color: str | None = None


@dataclass(frozen=True)
class Story:
    title: str
    start: str
    characters: Mapping[str, Character]
    scenes: Mapping[str, Scene]
    variables: Mapping[str, JSONValue]
    gallery: tuple[GalleryEntry, ...] = ()
    fingerprint: str | None = None

    def speaker_name(self, speaker: str | None) -> str | None:
        """把角色 id 解析为显示名；未知 id 原样返回。"""
        if speaker is None:
            return None
        character = self.characters.get(speaker)
        return character.name if character is not None else speaker

    def asset_references(self) -> Iterator[str]:
        """按出现顺序列出剧本引用的全部资源（去重）。"""
        seen: set[str] = set()
        for scene in self.scenes.values():
            for reference in (scene.background, scene.bgm):
                if reference and reference not in seen:
                    seen.add(reference)
                    yield reference
            for line in scene.lines:
                for reference in (line.background, line.bgm, line.voice, line.se):
                    if reference and reference not in seen:
                        seen.add(reference)
                        yield reference
                for sprite in line.show:
                    if sprite.image and sprite.image not in seen:
                        seen.add(sprite.image)
                        yield sprite.image
        for entry in self.gallery:
            if entry.image and entry.image not in seen:
                seen.add(entry.image)
                yield entry.image


def load_script(path: str | Path) -> Story:
    """从 JSON 文件加载并校验剧本。"""
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise ScriptError(f"剧本不存在：{path}") from None
    except json.JSONDecodeError as exc:
        raise ScriptError(
            f"剧本 JSON 解析失败：{path}:{exc.lineno}:{exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise ScriptError(f"剧本无法读取：{path}（{exc}）") from exc
    return parse_story(raw, source=str(path))


def parse_story(raw: Any, *, source: str = "<memory>") -> Story:
    """校验内存中的剧本数据并转换为 Story。"""
    if not isinstance(raw, dict):
        raise ScriptError(f"{source} 顶层必须是 JSON 对象")
    _check_keys(raw, _STORY_KEYS, source)

    title = raw.get("title", "未命名剧本")
    if not isinstance(title, str) or not title.strip():
        raise ScriptError(f"{source}.title 必须是非空字符串")

    scenes_raw = raw.get("scenes")
    if not isinstance(scenes_raw, dict) or not scenes_raw:
        raise ScriptError(f"{source}.scenes 必须是非空对象")

    start = raw.get("start", next(iter(scenes_raw)))
    if not isinstance(start, str) or start not in scenes_raw:
        raise ScriptError(f"{source}.start 指向不存在的场景：{start!r}")

    characters = _parse_characters(raw.get("characters", {}), f"{source}.characters")
    variables = _parse_variables(raw.get("vars", {}), f"{source}.vars")
    gallery = _parse_gallery(raw.get("gallery", []), f"{source}.gallery")

    scenes: dict[str, Scene] = {}
    for scene_id, scene_raw in scenes_raw.items():
        if not isinstance(scene_id, str) or not scene_id:
            raise ScriptError(f"{source}.scenes 的场景 id 必须是非空字符串")
        scenes[scene_id] = _parse_scene(scene_id, scene_raw, source)

    _validate_targets(scenes, source)
    try:
        canonical = json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ScriptError(f"{source} 无法计算剧本指纹：{exc}") from exc

    return Story(
        title=title,
        start=start,
        characters=characters,
        scenes=scenes,
        variables=variables,
        gallery=gallery,
        fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _parse_characters(raw: Any, context: str) -> dict[str, Character]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ScriptError(f"{context} 必须是对象")

    characters: dict[str, Character] = {}
    for character_id, value in raw.items():
        item_context = f"{context}.{character_id}"
        if not isinstance(character_id, str) or not character_id:
            raise ScriptError(f"{context} 的角色 id 必须是非空字符串")

        if isinstance(value, str):
            name = value
            color = None
        elif isinstance(value, dict):
            _check_keys(value, _CHARACTER_KEYS, item_context)
            name = value.get("name", character_id)
            color = value.get("color")
            if color is not None and not isinstance(color, str):
                raise ScriptError(f"{item_context}.color 必须是字符串")
        else:
            raise ScriptError(f"{item_context} 必须是角色名或角色对象")

        if not isinstance(name, str) or not name:
            raise ScriptError(f"{item_context}.name 必须是非空字符串")
        characters[character_id] = Character(character_id, name, color)
    return characters


def _parse_variables(raw: Any, context: str) -> dict[str, JSONValue]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ScriptError(f"{context} 必须是对象")

    variables: dict[str, JSONValue] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise ScriptError(f"{context} 的变量名必须是非空字符串")
        variables[key] = _json_value(value, f"{context}.{key}")
    return variables


def _parse_gallery(raw: Any, context: str) -> tuple[GalleryEntry, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ScriptError(f"{context} 必须是数组")

    entries: list[GalleryEntry] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw):
        item_context = f"{context}[{index}]"
        if not isinstance(item, dict):
            raise ScriptError(f"{item_context} 必须是对象")
        _check_keys(item, _GALLERY_KEYS, item_context)
        entry_id = _required_string(item.get("id"), f"{item_context}.id")
        if entry_id in seen_ids:
            raise ScriptError(f"{item_context}.id 重复：{entry_id!r}")
        seen_ids.add(entry_id)

        image = _required_string(item.get("image"), f"{item_context}.image")
        title = item.get("title", entry_id)
        description = item.get("description", "")
        if not isinstance(title, str) or not title.strip():
            raise ScriptError(f"{item_context}.title 必须是非空字符串")
        if not isinstance(description, str):
            raise ScriptError(f"{item_context}.description 必须是字符串")
        entries.append(
            GalleryEntry(
                id=entry_id,
                image=image,
                title=title,
                description=description,
            )
        )
    return tuple(entries)


def _parse_transition(
    raw: Any,
    context: str,
    *,
    default: Transition | None = None,
) -> Transition | None:
    if raw is None:
        return default
    if isinstance(raw, str):
        kind = raw
        duration = 0.32
    elif isinstance(raw, dict):
        _check_keys(raw, {"type", "duration"}, context)
        kind = raw.get("type")
        duration = raw.get("duration", 0.32)
    else:
        raise ScriptError(f"{context} 必须是转场名称或对象")

    if not isinstance(kind, str) or kind not in TRANSITION_TYPES:
        raise ScriptError(
            f"{context}.type 必须是 {sorted(TRANSITION_TYPES)} 之一"
        )
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or not 0 <= duration <= 5
    ):
        raise ScriptError(f"{context}.duration 必须是 0 到 5 秒之间的数字")
    return Transition(kind, float(duration))


def _parse_scene(scene_id: str, raw: Any, source: str) -> Scene:
    context = f"{source}.scenes[{scene_id}]"
    if not isinstance(raw, dict):
        raise ScriptError(f"{context} 必须是对象")
    _check_keys(raw, _SCENE_KEYS, context)

    background = _optional_reference(raw.get("background"), f"{context}.background")
    bgm = _optional_reference(raw.get("bgm"), f"{context}.bgm")
    next_scene = _optional_scene_id(raw.get("next"), f"{context}.next")
    end = _optional_bool(raw.get("end", False), f"{context}.end")
    transition = _parse_transition(raw.get("transition"), f"{context}.transition")

    if next_scene is not None and end:
        raise ScriptError(f"{context} 不能同时设置 next 和 end")

    lines_raw = raw.get("lines", [])
    if not isinstance(lines_raw, list):
        raise ScriptError(f"{context}.lines 必须是数组")
    lines = tuple(
        _parse_line(scene_id, index, item, source)
        for index, item in enumerate(lines_raw)
    )

    return Scene(
        id=scene_id,
        lines=lines,
        background=background,
        bgm=bgm,
        next=next_scene,
        end=end,
        transition=transition or Transition(),
    )


def _parse_line(scene_id: str, index: int, raw: Any, source: str) -> Line:
    context = f"{source}.scenes[{scene_id}].lines[{index}]"
    if not isinstance(raw, dict):
        raise ScriptError(f"{context} 必须是对象")
    _check_keys(raw, _LINE_KEYS, context)

    text = raw.get("text", "")
    if not isinstance(text, str):
        raise ScriptError(f"{context}.text 必须是字符串")

    speaker = raw.get("speaker")
    if speaker is not None and (not isinstance(speaker, str) or not speaker):
        raise ScriptError(f"{context}.speaker 必须是非空字符串")

    background = _optional_reference(raw.get("background"), f"{context}.background")
    bgm = _optional_reference(raw.get("bgm"), f"{context}.bgm")
    voice = _optional_reference(raw.get("voice"), f"{context}.voice")
    se = _optional_reference(raw.get("se"), f"{context}.se")
    show = _parse_sprites(raw.get("show"), f"{context}.show")
    hide = _parse_hide(raw.get("hide"), f"{context}.hide")
    changes = _parse_changes(raw, context)
    goto = _optional_scene_id(raw.get("goto"), f"{context}.goto")
    choices = _parse_choices(raw.get("choices"), context)
    end = _optional_bool(raw.get("end", False), f"{context}.end")
    transition = _parse_transition(
        raw.get("transition"),
        f"{context}.transition",
        default=None,
    )

    if goto is not None and choices:
        raise ScriptError(f"{context} 不能同时设置 goto 和 choices")
    if end and choices:
        raise ScriptError(f"{context} 不能同时设置 end 和 choices")
    if end and goto is not None:
        raise ScriptError(f"{context} 不能同时设置 end 和 goto")

    return Line(
        text=text,
        speaker=speaker,
        background=background,
        bgm=bgm,
        voice=voice,
        se=se,
        show=show,
        hide=hide,
        changes=changes,
        goto=goto,
        choices=choices,
        end=end,
        transition=transition,
    )


def _parse_sprites(raw: Any, context: str) -> tuple[SpriteCommand, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ScriptError(f"{context} 必须是数组")

    sprites: list[SpriteCommand] = []
    for index, item in enumerate(raw):
        item_context = f"{context}[{index}]"
        if not isinstance(item, dict):
            raise ScriptError(f"{item_context} 必须是对象")
        _check_keys(item, {"id", "image", "position"}, item_context)

        sprite_id = _required_string(item.get("id"), f"{item_context}.id")
        image = _required_string(item.get("image"), f"{item_context}.image")
        position = item.get("position", "center")
        if not isinstance(position, str) or position not in SPRITE_POSITIONS:
            raise ScriptError(
                f"{item_context}.position 必须是 {sorted(SPRITE_POSITIONS)} 之一"
            )
        sprites.append(SpriteCommand(sprite_id, image, position))
    return tuple(sprites)


def _parse_hide(raw: Any, context: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (_required_string(raw, context),)
    if not isinstance(raw, list):
        raise ScriptError(f"{context} 必须是字符串或字符串数组")
    return tuple(
        _required_string(item, f"{context}[{index}]")
        for index, item in enumerate(raw)
    )


def _parse_changes(raw: Mapping[str, Any], context: str) -> VariableChange:
    set_raw = raw.get("set", {})
    add_raw = raw.get("add", {})
    set_expr_raw = raw.get("set_expr", {})
    add_expr_raw = raw.get("add_expr", {})
    if set_raw is None:
        set_raw = {}
    if add_raw is None:
        add_raw = {}
    if set_expr_raw is None:
        set_expr_raw = {}
    if add_expr_raw is None:
        add_expr_raw = {}
    if not isinstance(set_raw, dict):
        raise ScriptError(f"{context}.set 必须是对象")
    if not isinstance(add_raw, dict):
        raise ScriptError(f"{context}.add 必须是对象")
    if not isinstance(set_expr_raw, dict):
        raise ScriptError(f"{context}.set_expr 必须是对象")
    if not isinstance(add_expr_raw, dict):
        raise ScriptError(f"{context}.add_expr 必须是对象")

    set_values: dict[str, JSONValue] = {}
    for key, value in set_raw.items():
        if not isinstance(key, str) or not key:
            raise ScriptError(f"{context}.set 的变量名必须是非空字符串")
        set_values[key] = _json_value(value, f"{context}.set.{key}")

    add_values: dict[str, int | float] = {}
    for key, value in add_raw.items():
        if not isinstance(key, str) or not key:
            raise ScriptError(f"{context}.add 的变量名必须是非空字符串")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScriptError(f"{context}.add.{key} 必须是数字")
        add_values[key] = value

    set_expressions = _parse_expressions(set_expr_raw, f"{context}.set_expr")
    add_expressions = _parse_expressions(add_expr_raw, f"{context}.add_expr")
    duplicated = (
        set_values.keys() & set_expressions.keys()
        | add_values.keys() & add_expressions.keys()
    )
    if duplicated:
        raise ScriptError(
            f"{context} 同一变量不能同时指定字面值和表达式："
            f"{', '.join(sorted(duplicated))}"
        )

    return VariableChange(
        set_values=set_values,
        add_values=add_values,
        set_expressions=set_expressions,
        add_expressions=add_expressions,
    )


def _parse_expressions(raw: Mapping[str, Any], context: str) -> dict[str, str]:
    expressions: dict[str, str] = {}
    for key, expression in raw.items():
        if not isinstance(key, str) or not key:
            raise ScriptError(f"{context} 的变量名必须是非空字符串")
        if not isinstance(expression, str):
            raise ScriptError(f"{context}.{key} 必须是表达式字符串")
        try:
            validate_expression(expression)
        except ExpressionError as exc:
            raise ScriptError(f"{context}.{key} 表达式无效：{exc}") from exc
        expressions[key] = expression
    return expressions


def _parse_choices(raw: Any, context: str) -> tuple[Choice, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ScriptError(f"{context}.choices 必须是数组")

    choices: list[Choice] = []
    for index, item in enumerate(raw):
        item_context = f"{context}.choices[{index}]"
        if not isinstance(item, dict):
            raise ScriptError(f"{item_context} 必须是对象")
        _check_keys(item, _CHOICE_KEYS, item_context)

        text = _required_string(item.get("text"), f"{item_context}.text")
        goto = _optional_scene_id(item.get("goto"), f"{item_context}.goto")
        changes = _parse_changes(item, item_context)
        require = _parse_require(item.get("require"), f"{item_context}.require")
        choices.append(Choice(text=text, goto=goto, changes=changes, require=require))

    if not choices:
        raise ScriptError(f"{context}.choices 不能是空数组")
    return tuple(choices)


def _parse_require(raw: Any, context: str) -> tuple[ConditionNode, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (_parse_condition_node(raw, context),)
    if isinstance(raw, list):
        return tuple(
            _parse_condition_node(item, f"{context}[{index}]")
            for index, item in enumerate(raw)
        )
    if not isinstance(raw, dict):
        raise ScriptError(f"{context} 必须是对象、数组或表达式字符串")

    logical_operators = set(raw) & {"all", "any", "not"}
    if logical_operators and (
        len(logical_operators) != 1 or len(raw) != 1
    ):
        raise ScriptError(f"{context} 的逻辑条件一次只能包含 all、any 或 not 之一")
    if set(raw) in ({"all"}, {"any"}, {"not"}):
        return (_parse_condition_node(raw, context),)
    if set(raw) == {"var", "op", "value"}:
        return (_parse_condition_node(raw, context),)

    conditions: list[ConditionNode] = []
    for key, expected in raw.items():
        if not isinstance(key, str) or not key:
            raise ScriptError(f"{context} 的变量名必须是非空字符串")

        if isinstance(expected, dict):
            _check_keys(expected, {"op", "value"}, f"{context}.{key}")
            if "op" not in expected or "value" not in expected:
                raise ScriptError(f"{context}.{key} 必须同时包含 op 和 value")
            op = expected["op"]
            if op == "=":
                op = "=="
            if not isinstance(op, str) or op not in _COMPARISON_OPS:
                raise ScriptError(
                    f"{context}.{key}.op 必须是 {sorted(_COMPARISON_OPS)} 之一"
                )
            value = _json_value(expected["value"], f"{context}.{key}.value")
        else:
            op = "=="
            value = _json_value(expected, f"{context}.{key}")

        conditions.append(Condition(key, op, value))
    return tuple(conditions)


def _parse_condition_node(raw: Any, context: str) -> ConditionNode:
    if isinstance(raw, str):
        try:
            validate_expression(raw)
        except ExpressionError as exc:
            raise ScriptError(f"{context} 条件表达式无效：{exc}") from exc
        return ExpressionCondition(raw)

    if not isinstance(raw, dict):
        raise ScriptError(f"{context} 必须是条件对象或表达式字符串")

    if len(raw) == 1 and next(iter(raw)) in {"all", "any", "not"}:
        operator_name, children = next(iter(raw.items()))
        if operator_name == "not":
            return ConditionGroup(
                "not",
                (_parse_condition_node(children, f"{context}.not"),),
            )
        if not isinstance(children, list) or not children:
            raise ScriptError(f"{context}.{operator_name} 必须是非空数组")
        conditions = tuple(
            _parse_condition_node(child, f"{context}.{operator_name}[{index}]")
            for index, child in enumerate(children)
        )
        return ConditionGroup(operator_name, conditions)

    if set(raw) == {"var", "op", "value"}:
        key = _required_string(raw["var"], f"{context}.var")
        op = raw["op"]
        if op == "=":
            op = "=="
        if not isinstance(op, str) or op not in _COMPARISON_OPS:
            raise ScriptError(
                f"{context}.op 必须是 {sorted(_COMPARISON_OPS)} 之一"
            )
        value = _json_value(raw["value"], f"{context}.value")
        return Condition(key, op, value)

    raise ScriptError(
        f"{context} 必须使用 all/any/not 条件树，"
        "或包含 var、op、value 的单变量条件"
    )


def _validate_targets(scenes: Mapping[str, Scene], source: str) -> None:
    for scene in scenes.values():
        if scene.next is not None and scene.next not in scenes:
            raise ScriptError(
                f"{source}.scenes[{scene.id}].next 指向不存在的场景：{scene.next!r}"
            )
        for index, line in enumerate(scene.lines):
            context = f"{source}.scenes[{scene.id}].lines[{index}]"
            if line.goto is not None and line.goto not in scenes:
                raise ScriptError(f"{context}.goto 指向不存在的场景：{line.goto!r}")
            for choice_index, choice in enumerate(line.choices):
                if choice.goto is not None and choice.goto not in scenes:
                    raise ScriptError(
                        f"{context}.choices[{choice_index}].goto "
                        f"指向不存在的场景：{choice.goto!r}"
                    )


def _check_keys(raw: Mapping[str, Any], allowed: frozenset[str], context: str) -> None:
    unknown = sorted(str(key) for key in set(raw) - allowed)
    if unknown:
        raise ScriptError(f"{context} 含未知字段：{', '.join(unknown)}")


def _required_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ScriptError(f"{context} 必须是非空字符串")
    return value


def _optional_scene_id(value: Any, context: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, context)


def _optional_reference(value: Any, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ScriptError(f"{context} 必须是字符串")
    return value.strip()


def _optional_bool(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise ScriptError(f"{context} 必须是布尔值")
    return value


def _json_value(value: Any, context: str, *, depth: int = 0) -> JSONValue:
    if depth > 32:
        raise ScriptError(f"{context} 的嵌套深度不能超过 32")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ScriptError(f"{context} 必须是有限数字")
        return value
    if isinstance(value, list):
        return [
            _json_value(item, f"{context}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ScriptError(f"{context} 的对象键必须是字符串")
            result[key] = _json_value(item, f"{context}.{key}", depth=depth + 1)
        return result
    raise ScriptError(
        f"{context} 必须是 JSON 值（字符串、数字、布尔值、null、数组或对象）"
    )
