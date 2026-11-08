"""JSON-backed story editing operations and validated, atomic saves."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, TextIO

from easyengine import __generator__
from easyengine.galgame import Story, load_script

NodeKind = Literal["story", "scene", "line", "choice"]
UNSET = object()


class EditorModelError(ValueError):
    """An editing operation cannot be applied to the current JSON document."""


@dataclass(frozen=True)
class NodeRef:
    kind: NodeKind
    scene_id: str | None = None
    line_index: int | None = None
    choice_index: int | None = None


class StoryModel:
    """Keep the editor's only source of truth as a normal EasyEngine JSON story."""

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        *,
        path: str | Path | None = None,
    ) -> None:
        if data is not None and not isinstance(data, dict):
            raise EditorModelError("剧本 JSON 顶层必须是对象。")
        self.data = copy.deepcopy(data) if data is not None else self.new_data()
        if "generator" not in self.data and "_generator" not in self.data:
            self.data["_generator"] = __generator__
        self.path = Path(path).expanduser().resolve() if path is not None else None

    @staticmethod
    def new_data() -> dict[str, Any]:
        return {
            "title": "新剧本",
            "start": "scene_1",
            "scenes": {"scene_1": {"lines": []}},
        }

    @classmethod
    def open(cls, path: str | Path) -> StoryModel:
        source = Path(path).expanduser()
        try:
            with source.open("r", encoding="utf-8") as handle:
                data = json.load(handle, parse_constant=_reject_json_constant)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise EditorModelError(f"无法打开剧本 {source}：{exc}") from exc
        if not isinstance(data, dict):
            raise EditorModelError("剧本 JSON 顶层必须是对象。")
        return cls(data, path=source)

    @property
    def scene_ids(self) -> tuple[str, ...]:
        raw = self.data.get("scenes")
        if not isinstance(raw, dict):
            return ()
        return tuple(str(scene_id) for scene_id in raw)

    def get_scene(self, scene_id: str) -> dict[str, Any] | None:
        scenes = self.data.get("scenes")
        if not isinstance(scenes, dict):
            return None
        scene = scenes.get(scene_id)
        return scene if isinstance(scene, dict) else None

    def get_line(self, scene_id: str, line_index: int) -> dict[str, Any] | None:
        scene = self.get_scene(scene_id)
        if scene is None:
            return None
        lines = scene.get("lines")
        if not isinstance(lines, list) or not 0 <= line_index < len(lines):
            return None
        line = lines[line_index]
        return line if isinstance(line, dict) else None

    def get_choice(
        self,
        scene_id: str,
        line_index: int,
        choice_index: int,
    ) -> dict[str, Any] | None:
        line = self.get_line(scene_id, line_index)
        if line is None:
            return None
        choices = line.get("choices")
        if not isinstance(choices, list) or not 0 <= choice_index < len(choices):
            return None
        choice = choices[choice_index]
        return choice if isinstance(choice, dict) else None

    def target_for(self, ref: NodeRef) -> dict[str, Any]:
        if ref.kind == "story":
            return self.data
        if ref.scene_id is None:
            raise EditorModelError("所选节点没有关联场景。")
        if ref.kind == "scene":
            target = self.get_scene(ref.scene_id)
        elif ref.kind == "line" and ref.line_index is not None:
            target = self.get_line(ref.scene_id, ref.line_index)
        elif (
            ref.kind == "choice"
            and ref.line_index is not None
            and ref.choice_index is not None
        ):
            target = self.get_choice(ref.scene_id, ref.line_index, ref.choice_index)
        else:
            target = None
        if target is None:
            raise EditorModelError("所选剧情节点已不存在，请重新选择。")
        return target

    def set_field(self, ref: NodeRef, key: str, value: Any) -> None:
        target = self.target_for(ref)
        if value is UNSET:
            target.pop(key, None)
        else:
            target[key] = copy.deepcopy(value)

    def add_scene(self, scene_id: str | None = None) -> NodeRef:
        scenes = self.data.get("scenes")
        if not isinstance(scenes, dict):
            scenes = {}
            self.data["scenes"] = scenes
        identifier = scene_id.strip() if scene_id is not None else self.next_scene_id()
        if not identifier:
            raise EditorModelError("场景 ID 不能为空。")
        if identifier in scenes:
            raise EditorModelError(f"场景 ID 已存在：{identifier}")
        scenes[identifier] = {"lines": []}
        current_start = self.data.get("start")
        if not isinstance(current_start, str) or current_start not in scenes:
            self.data["start"] = identifier
        return NodeRef("scene", scene_id=identifier)

    def next_scene_id(self) -> str:
        existing = set(self.scene_ids)
        index = 1
        while f"scene_{index}" in existing:
            index += 1
        return f"scene_{index}"

    def add_line(self, scene_id: str, index: int | None = None) -> NodeRef:
        scene = self.get_scene(scene_id)
        if scene is None:
            raise EditorModelError(f"场景不存在：{scene_id}")
        lines = scene.get("lines")
        if not isinstance(lines, list):
            lines = []
            scene["lines"] = lines
        line_index = len(lines) if index is None else max(0, min(index, len(lines)))
        lines.insert(line_index, {"text": ""})
        return NodeRef("line", scene_id=scene_id, line_index=line_index)

    def add_choice(self, scene_id: str, line_index: int) -> NodeRef:
        line = self.get_line(scene_id, line_index)
        if line is None:
            raise EditorModelError("台词不存在。")
        if line.get("goto") or line.get("end") is True:
            raise EditorModelError("含有 goto 或 end 的台词不能添加选项，请先清除冲突字段。")
        choices = line.get("choices")
        if not isinstance(choices, list):
            choices = []
            line["choices"] = choices
        choice_index = len(choices)
        choices.append({"text": "新选项"})
        return NodeRef(
            "choice",
            scene_id=scene_id,
            line_index=line_index,
            choice_index=choice_index,
        )

    def delete(self, ref: NodeRef) -> NodeRef:
        if ref.kind == "scene" and ref.scene_id is not None:
            scenes = self.data.get("scenes")
            if not isinstance(scenes, dict) or ref.scene_id not in scenes:
                raise EditorModelError("场景已不存在。")
            if len(scenes) <= 1:
                raise EditorModelError("剧本至少需要保留一个场景。")
            references = self._references_to(ref.scene_id)
            if references:
                raise EditorModelError(
                    f"场景 {ref.scene_id!r} 仍被以下位置引用："
                    + "、".join(references)
                )
            del scenes[ref.scene_id]
            if self.data.get("start") == ref.scene_id:
                self.data["start"] = next(iter(scenes))
            return NodeRef("story")

        if ref.kind == "line" and ref.scene_id is not None and ref.line_index is not None:
            scene = self.get_scene(ref.scene_id)
            if scene is None or not isinstance(scene.get("lines"), list):
                raise EditorModelError("台词列表已不存在。")
            lines = scene["lines"]
            if not 0 <= ref.line_index < len(lines):
                raise EditorModelError("台词已不存在。")
            del lines[ref.line_index]
            return NodeRef("scene", scene_id=ref.scene_id)

        if (
            ref.kind == "choice"
            and ref.scene_id is not None
            and ref.line_index is not None
            and ref.choice_index is not None
        ):
            line = self.get_line(ref.scene_id, ref.line_index)
            if line is None or not isinstance(line.get("choices"), list):
                raise EditorModelError("选项列表已不存在。")
            choices = line["choices"]
            if not 0 <= ref.choice_index < len(choices):
                raise EditorModelError("选项已不存在。")
            del choices[ref.choice_index]
            if not choices:
                line.pop("choices", None)
            return NodeRef("line", scene_id=ref.scene_id, line_index=ref.line_index)

        raise EditorModelError("此类节点不能删除。")

    def move(self, ref: NodeRef, offset: int) -> NodeRef:
        if offset not in (-1, 1):
            raise ValueError("移动距离必须是 -1 或 1。")
        if ref.kind == "scene" and ref.scene_id is not None:
            scenes = self.data.get("scenes")
            if not isinstance(scenes, dict):
                return ref
            items = list(scenes.items())
            index = next(
                (i for i, (scene_id, _) in enumerate(items) if scene_id == ref.scene_id),
                None,
            )
            if index is None or not 0 <= index + offset < len(items):
                return ref
            items[index], items[index + offset] = items[index + offset], items[index]
            scenes.clear()
            scenes.update(items)
            return ref

        if ref.kind == "line" and ref.scene_id is not None and ref.line_index is not None:
            scene = self.get_scene(ref.scene_id)
            items = scene.get("lines") if scene is not None else None
            index = ref.line_index
            if isinstance(items, list) and 0 <= index < len(items):
                if 0 <= index + offset < len(items):
                    items[index], items[index + offset] = (
                        items[index + offset],
                        items[index],
                    )
                    return NodeRef("line", scene_id=ref.scene_id, line_index=index + offset)
            return ref

        if (
            ref.kind == "choice"
            and ref.scene_id is not None
            and ref.line_index is not None
            and ref.choice_index is not None
        ):
            line = self.get_line(ref.scene_id, ref.line_index)
            items = line.get("choices") if line is not None else None
            index = ref.choice_index
            if isinstance(items, list) and 0 <= index < len(items):
                if 0 <= index + offset < len(items):
                    items[index], items[index + offset] = items[index + offset], items[index]
                    return NodeRef(
                        "choice",
                        scene_id=ref.scene_id,
                        line_index=ref.line_index,
                        choice_index=index + offset,
                    )
            return ref
        return ref

    def validate(self) -> Story:
        """Validate a temporary JSON file with the engine's public loader."""
        with TemporaryDirectory(prefix="easyengine-editor-") as directory:
            temporary = Path(directory) / "story.json"
            self._write_json_file(temporary)
            return load_script(temporary)

    def save(self, path: str | Path | None = None) -> Path:
        """Validate and atomically replace a JSON story file."""
        target = Path(path).expanduser() if path is not None else self.path
        if target is None:
            raise EditorModelError("请先选择剧本保存位置。")
        target = target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".json",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
            self._write_json_file(temporary)
            load_script(temporary)
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

        self.path = target
        return target

    def _write_json_file(self, path: Path) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            self._write_json(handle)
            handle.flush()
            os.fsync(handle.fileno())

    def _write_json(self, handle: TextIO) -> None:
        data = copy.deepcopy(self.data)
        if "generator" not in data and "_generator" not in data:
            data["_generator"] = __generator__
        json.dump(
            data,
            handle,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        handle.write("\n")

    def _references_to(self, scene_id: str) -> list[str]:
        references: list[str] = []
        scenes = self.data.get("scenes")
        if not isinstance(scenes, dict):
            return references
        for owner_id, scene in scenes.items():
            if owner_id == scene_id or not isinstance(scene, dict):
                continue
            if scene.get("next") == scene_id:
                references.append(f"场景 {owner_id}.next")
            lines = scene.get("lines")
            if not isinstance(lines, list):
                continue
            for line_index, line in enumerate(lines):
                if not isinstance(line, dict):
                    continue
                location = f"场景 {owner_id} 第 {line_index + 1} 行"
                if line.get("goto") == scene_id:
                    references.append(f"{location}.goto")
                choices = line.get("choices")
                if isinstance(choices, list):
                    for choice_index, choice in enumerate(choices):
                        if isinstance(choice, dict) and choice.get("goto") == scene_id:
                            references.append(
                                f"{location} 的第 {choice_index + 1} 个选项.goto"
                            )
        return references


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"{value} 不是标准 JSON 数值。")
