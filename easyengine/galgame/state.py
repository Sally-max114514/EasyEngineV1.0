"""Galgame 运行时状态与 JSON 存档。

存档只保存可序列化状态，不保存界面/播放器对象。所有文件读写都通过
with 或 pathlib 完成，句柄自动关闭；写入先落到临时文件再原子替换。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .. import __author__
from .script import JSONScalar, JSONValue, SPRITE_POSITIONS

SAVE_VERSION = 2
_SUPPORTED_SAVE_VERSIONS = frozenset({1, SAVE_VERSION})
_SLOT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class SaveError(ValueError):
    """存档格式、版本或路径错误。"""


@dataclass(frozen=True)
class SpriteState:
    image: str
    position: str = "center"


@dataclass
class GameState:
    scene_id: str
    line_index: int = 0
    variables: dict[str, JSONValue] = field(default_factory=dict)
    background: str | None = None
    bgm: str | None = None
    sprites: dict[str, SpriteState] = field(default_factory=dict)
    ended: bool = False
    seen_lines: set[str] = field(default_factory=set)

    def get(self, key: str, default: JSONValue = None) -> JSONValue:
        if key in self.variables:
            return self.variables[key]
        current: Any = self.variables
        for part in key.split("."):
            if not part or not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def set(self, key: str, value: JSONValue) -> JSONValue:
        if not isinstance(key, str) or not key:
            raise ValueError("变量名必须是非空字符串")
        checked = _ensure_json_value(value, f"变量 {key}")
        if key in self.variables or "." not in key:
            self.variables[key] = checked
            return value

        parts = key.split(".")
        if any(not part for part in parts):
            raise ValueError(f"变量路径无效：{key!r}")
        target = self.variables
        for part in parts[:-1]:
            nested = target.get(part)
            if nested is None:
                nested = {}
                target[part] = nested
            if not isinstance(nested, dict):
                raise ValueError(f"变量路径 {key!r} 的 {part!r} 不是对象")
            target = nested
        target[parts[-1]] = checked
        return value

    def add(self, key: str, amount: int | float) -> int | float:
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ValueError(f"变量 {key} 的增量必须是数字")
        current = self.get(key, 0)
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            raise ValueError(f"变量 {key} 当前不是数字，无法累加")
        value = current + amount
        self.set(key, value)
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "line_index": self.line_index,
            "variables": dict(self.variables),
            "background": self.background,
            "bgm": self.bgm,
            "sprites": {
                sprite_id: {"image": sprite.image, "position": sprite.position}
                for sprite_id, sprite in self.sprites.items()
            },
            "ended": self.ended,
            "seen_lines": sorted(self.seen_lines),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> GameState:
        if not isinstance(raw, dict):
            raise SaveError("存档中的 state 必须是对象")

        scene_id = raw.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id:
            raise SaveError("存档中的 scene_id 必须是非空字符串")

        line_index = raw.get("line_index", 0)
        if isinstance(line_index, bool) or not isinstance(line_index, int):
            raise SaveError("存档中的 line_index 必须是整数")
        if line_index < 0:
            raise SaveError("存档中的 line_index 不能为负数")

        variables_raw = raw.get("variables", {})
        if not isinstance(variables_raw, dict):
            raise SaveError("存档中的 variables 必须是对象")
        variables: dict[str, JSONValue] = {}
        for key, value in variables_raw.items():
            if not isinstance(key, str) or not key:
                raise SaveError("存档中的变量名必须是非空字符串")
            variables[key] = _ensure_json_value(value, f"变量 {key}")

        background = _optional_reference(raw.get("background"), "background")
        bgm = _optional_reference(raw.get("bgm"), "bgm")

        sprites_raw = raw.get("sprites", {})
        if not isinstance(sprites_raw, dict):
            raise SaveError("存档中的 sprites 必须是对象")
        sprites: dict[str, SpriteState] = {}
        for sprite_id, sprite_raw in sprites_raw.items():
            if not isinstance(sprite_id, str) or not sprite_id:
                raise SaveError("存档中的立绘 id 必须是非空字符串")
            if not isinstance(sprite_raw, dict):
                raise SaveError(f"存档中的立绘 {sprite_id} 必须是对象")

            image = sprite_raw.get("image")
            if not isinstance(image, str) or not image:
                raise SaveError(f"存档中的立绘 {sprite_id}.image 必须是非空字符串")
            position = sprite_raw.get("position", "center")
            if not isinstance(position, str) or position not in SPRITE_POSITIONS:
                raise SaveError(
                    f"存档中的立绘 {sprite_id}.position 必须是 "
                    f"{sorted(SPRITE_POSITIONS)} 之一"
                )
            sprites[sprite_id] = SpriteState(image, position)

        ended = raw.get("ended", False)
        if not isinstance(ended, bool):
            raise SaveError("存档中的 ended 必须是布尔值")

        seen_raw = raw.get("seen_lines", [])
        if not isinstance(seen_raw, list) or any(
            not isinstance(item, str) or not item for item in seen_raw
        ):
            raise SaveError("存档中的 seen_lines 必须是非空字符串数组")

        return cls(
            scene_id=scene_id,
            line_index=line_index,
            variables=variables,
            background=background,
            bgm=bgm,
            sprites=sprites,
            ended=ended,
            seen_lines=set(seen_raw),
        )


@dataclass(frozen=True)
class SaveData:
    version: int
    script_title: str
    state: GameState
    script_fingerprint: str | None = None


def slot_path(save_dir: str | Path, slot: str) -> Path:
    """把存档名转换为安全路径，并拒绝路径穿越。"""
    if not isinstance(slot, str) or not _SLOT_PATTERN.fullmatch(slot):
        raise SaveError("存档名只能包含字母、数字、下划线和短横线（1-64 个字符）")
    return Path(save_dir) / f"{slot}.json"


def save_game(
    path: str | Path,
    state: GameState,
    *,
    script_title: str,
    script_fingerprint: str | None = None,
) -> None:
    """原子写入存档，避免中途失败留下半个文件。"""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SaveError(f"存档目录无法创建：{path.parent}（{exc}）") from exc

    payload = {
        "engine": "EasyEngine",
        "author": __author__,
        "version": SAVE_VERSION,
        "script_title": script_title,
        "script_fingerprint": script_fingerprint,
        "state": state.to_dict(),
    }

    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary.replace(path)
    except OSError as exc:
        raise SaveError(f"存档写入失败：{path}（{exc}）") from exc
    finally:
        temporary.unlink(missing_ok=True)


def load_game(path: str | Path) -> SaveData:
    """读取并校验存档。"""
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        raise SaveError(f"存档不存在：{path}") from None
    except json.JSONDecodeError as exc:
        raise SaveError(
            f"存档 JSON 解析失败：{path}:{exc.lineno}:{exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise SaveError(f"存档无法读取：{path}（{exc}）") from exc

    if not isinstance(payload, dict):
        raise SaveError("存档顶层必须是对象")

    version = payload.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in _SUPPORTED_SAVE_VERSIONS
    ):
        raise SaveError(f"不支持的存档版本：{version!r}（当前版本 {SAVE_VERSION}）")

    script_title = payload.get("script_title", "")
    if not isinstance(script_title, str):
        raise SaveError("存档中的 script_title 必须是字符串")

    fingerprint = payload.get("script_fingerprint")
    if version == SAVE_VERSION and fingerprint is not None:
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.fullmatch(
            fingerprint
        ):
            raise SaveError("存档中的 script_fingerprint 格式无效")

    return SaveData(
        version=version,
        script_title=script_title,
        state=GameState.from_dict(payload.get("state")),
        script_fingerprint=fingerprint if isinstance(fingerprint, str) else None,
    )


def _ensure_json_value(value: Any, context: str, *, depth: int = 0) -> JSONValue:
    if depth > 32:
        raise SaveError(f"{context} 的嵌套深度不能超过 32")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SaveError(f"{context} 必须是有限数字")
        return value
    if isinstance(value, list):
        return [
            _ensure_json_value(item, f"{context}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise SaveError(f"{context} 的对象键必须是字符串")
            result[key] = _ensure_json_value(
                item,
                f"{context}.{key}",
                depth=depth + 1,
            )
        return result
    raise SaveError(
        f"{context} 必须是 JSON 值（字符串、数字、布尔值、null、数组或对象）"
    )


def _optional_reference(value: Any, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SaveError(f"存档中的 {context} 必须是字符串或 null")
    return value or None
