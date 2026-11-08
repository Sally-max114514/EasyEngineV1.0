from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easyengine import __generator__
from easyengine.galgame import ScriptError, load_script
from editor.model import EditorModelError, NodeRef, StoryModel


def sample_story() -> dict:
    return {
        "title": "编辑器测试",
        "start": "start",
        "characters": {"hero": "主角"},
        "vars": {"score": 0},
        "scenes": {
            "start": {
                "lines": [
                    {
                        "speaker": "hero",
                        "text": "选择",
                        "choices": [
                            {"text": "继续", "goto": "ending"},
                            {"text": "稍后", "goto": "ending"},
                        ],
                    }
                ]
            },
            "ending": {"lines": [{"text": "结束", "end": True}]},
        },
    }


class StoryModelTests(unittest.TestCase):
    def test_new_story_is_validated_by_engine_loader(self) -> None:
        model = StoryModel()
        story = model.validate()
        self.assertEqual(story.title, "新剧本")
        self.assertEqual(story.start, "scene_1")

    def test_open_save_and_reload_standard_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "story.json"
            model = StoryModel(sample_story())
            saved_path = model.save(path)

            self.assertEqual(saved_path, path.resolve())
            reopened = StoryModel.open(saved_path)
            story = load_script(saved_path)
            self.assertEqual(story.title, "编辑器测试")
            self.assertEqual(reopened.data, model.data)
            self.assertEqual(json.loads(saved_path.read_text(encoding="utf-8")), model.data)
            self.assertEqual(reopened.data["_generator"], __generator__)

    def test_existing_generator_metadata_is_preserved(self) -> None:
        model = StoryModel({**sample_story(), "generator": "Existing generator"})

        self.assertEqual(model.data["generator"], "Existing generator")
        self.assertNotIn("_generator", model.data)

    def test_validate_and_save_call_the_engine_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model = StoryModel(sample_story())
            with patch("editor.model.load_script", wraps=load_script) as loader:
                model.validate()
                model.save(Path(directory) / "story.json")
            self.assertEqual(loader.call_count, 2)

    def test_invalid_save_preserves_previous_file_and_cleans_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "story.json"
            original = json.dumps(sample_story(), ensure_ascii=False)
            path.write_text(original, encoding="utf-8")
            model = StoryModel(sample_story())
            model.data["scenes"]["start"]["lines"][0]["choices"] = []

            with self.assertRaises(ScriptError):
                model.save(path)

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(Path(directory).glob(".story.json.*.json")), [])

    def test_validation_rejects_unsafe_condition_expression(self) -> None:
        model = StoryModel(sample_story())
        model.data["scenes"]["start"]["lines"][0]["choices"][0]["require"] = (
            "__import__('os')"
        )
        with self.assertRaises(ScriptError):
            model.validate()

    def test_scene_line_and_choice_reordering(self) -> None:
        model = StoryModel(sample_story())
        moved_scene = model.move(NodeRef("scene", scene_id="ending"), -1)
        self.assertEqual(model.scene_ids, ("ending", "start"))
        self.assertEqual(moved_scene.scene_id, "ending")

        model.move(NodeRef("choice", "start", 0, 1), -1)
        choices = model.get_line("start", 0)["choices"]
        self.assertEqual(choices[0]["text"], "稍后")

        inserted = model.add_line("start", 0)
        self.assertEqual(inserted.line_index, 0)
        moved_line = model.move(inserted, 1)
        self.assertEqual(moved_line.line_index, 1)

    def test_deleting_last_choice_removes_empty_choices_field(self) -> None:
        model = StoryModel(sample_story())
        line = model.get_line("start", 0)
        line["choices"] = [line["choices"][0]]
        model.delete(NodeRef("choice", "start", 0, 0))

        self.assertNotIn("choices", model.get_line("start", 0))
        self.assertEqual(model.validate().title, "编辑器测试")

    def test_referenced_scene_cannot_be_deleted(self) -> None:
        model = StoryModel(sample_story())
        with self.assertRaises(EditorModelError):
            model.delete(NodeRef("scene", scene_id="ending"))
        self.assertIn("ending", model.scene_ids)

    def test_add_choice_rejects_goto_or_end_conflicts(self) -> None:
        model = StoryModel(sample_story())
        line = model.get_line("start", 0)
        line.pop("choices")
        line["goto"] = "ending"
        with self.assertRaises(EditorModelError):
            model.add_choice("start", 0)
        line.pop("goto")
        line["end"] = True
        with self.assertRaises(EditorModelError):
            model.add_choice("start", 0)

    def test_add_scene_repairs_invalid_start_and_duplicate_ids_are_rejected(self) -> None:
        model = StoryModel({"title": "bad", "start": [], "scenes": {}})
        created = model.add_scene("first")
        self.assertEqual(created.scene_id, "first")
        self.assertEqual(model.data["start"], "first")
        with self.assertRaises(EditorModelError):
            model.add_scene("first")

    def test_open_rejects_non_object_and_nonstandard_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(EditorModelError):
                StoryModel.open(path)
            path.write_text('{"value": NaN}', encoding="utf-8")
            with self.assertRaises(EditorModelError):
                StoryModel.open(path)


if __name__ == "__main__":
    unittest.main()
