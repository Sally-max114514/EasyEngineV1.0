from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easyengine import __generator__, config
from easyengine.galgame import (
    EngineStateError,
    GalgameEngine,
    ScriptError,
    assets_root_for_story,
    load_script,
    parse_story,
)


def _write_story(path: Path, *, title: str = "External", text: str = "before") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "title": title,
                "start": "start",
                "vars": {"score": 1},
                "scenes": {
                    "start": {
                        "lines": [
                            {"text": text},
                            {"text": "next", "end": True},
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _jump_story(jumps: int, *, terminal_line: bool = False):
    scenes: dict[str, dict[str, object]] = {}
    for index in range(jumps + 1):
        scene: dict[str, object] = {}
        if index < jumps:
            scene["next"] = f"scene-{index + 1}"
        elif terminal_line:
            scene["lines"] = [{"text": "arrival"}]
        scenes[f"scene-{index}"] = scene
    return parse_story(
        {
            "title": "Jump test",
            "start": "scene-0",
            "scenes": scenes,
        }
    )


class ExternalStoryTests(unittest.TestCase):
    def test_generator_metadata_defaults_and_does_not_change_story_fingerprint(self) -> None:
        story_data = {
            "title": "Metadata",
            "start": "start",
            "scenes": {"start": {"lines": [{"text": "Hello"}]}},
        }

        default_story = parse_story(story_data)
        custom_story = parse_story({**story_data, "_generator": "Custom generator"})

        self.assertEqual(default_story.generator, __generator__)
        self.assertEqual(custom_story.generator, "Custom generator")
        self.assertEqual(default_story.fingerprint, custom_story.fingerprint)
        with self.assertRaises(ScriptError):
            parse_story({**story_data, "generator": ""})

    def test_absolute_and_relative_paths_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            absolute_path = root / "absolute.json"
            _write_story(absolute_path)
            absolute_story = load_script(absolute_path)
            self.assertEqual(absolute_story.source_path, absolute_path.resolve())

            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                relative_path = Path("relative/story.json")
                _write_story(relative_path)
                relative_story = load_script(relative_path)
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(
                relative_story.source_path,
                (root / "relative" / "story.json").resolve(),
            )
            self.assertEqual(absolute_story, relative_story)

    def test_external_story_uses_sibling_assets_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            story_path = root / "mod" / "story.json"
            assets_root = story_path.parent / "assets"
            image = assets_root / "image" / "bg" / "room.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"image placeholder")
            _write_story(story_path)

            story = load_script(story_path)
            engine = GalgameEngine(story)

            self.assertEqual(assets_root_for_story(story), assets_root)
            self.assertEqual(engine.assets_root, assets_root)
            reference = engine.resolve_asset("image/bg/room.png")
            assert reference is not None
            self.assertEqual(reference.path, image)

    def test_story_under_assets_uses_its_enclosing_assets_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets_root = Path(directory) / "assets"
            story_path = assets_root / "text" / "scripts" / "story.json"
            _write_story(story_path)

            story = load_script(story_path)

            self.assertEqual(assets_root_for_story(story), assets_root)

    def test_reload_script_resets_runtime_and_reads_updated_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            story_path = Path(directory) / "story.json"
            _write_story(story_path)
            engine = GalgameEngine(load_script(story_path))
            engine.start()
            engine.reveal_all()
            engine.advance()
            self.assertEqual(engine.rollback_depth, 1)

            _write_story(
                story_path,
                title="Reloaded",
                text="after reload",
            )
            updated_data = json.loads(story_path.read_text(encoding="utf-8"))
            updated_data["vars"]["score"] = 9
            story_path.write_text(
                json.dumps(updated_data),
                encoding="utf-8",
            )

            result = engine.reload_script()

            self.assertEqual(engine.story.title, "Reloaded")
            self.assertEqual(result.view.text, "after reload")
            self.assertEqual(result.view.variables["score"], 9)
            self.assertEqual(result.view.line_index, 0)
            self.assertEqual(engine.rollback_depth, 0)
            self.assertEqual(engine.jump_count, 0)
            assert engine.state is not None
            self.assertEqual(engine.state.seen_lines, set())

    def test_reload_without_source_file_is_rejected(self) -> None:
        engine = GalgameEngine(_jump_story(0))
        with self.assertRaises(EngineStateError):
            engine.reload_script()

    def test_failed_reload_preserves_current_story_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            story_path = Path(directory) / "story.json"
            _write_story(story_path)
            engine = GalgameEngine(load_script(story_path))
            engine.start()
            story_path.write_text("{", encoding="utf-8")

            with self.assertRaises(ScriptError):
                engine.reload_script()

            self.assertEqual(engine.story.title, "External")
            self.assertEqual(engine.view.text, "before")


class JumpLimitTests(unittest.TestCase):
    def test_exactly_100_waitless_jumps_are_allowed(self) -> None:
        engine = GalgameEngine(_jump_story(100))
        result = engine.start()

        self.assertTrue(result.view.ended)
        self.assertEqual(engine.jump_count, 100)

    def test_line_event_resets_consecutive_jump_counter(self) -> None:
        engine = GalgameEngine(_jump_story(100, terminal_line=True))
        result = engine.start()

        self.assertEqual(result.view.text, "arrival")
        self.assertEqual(engine.jump_count, 0)

    def test_101st_waitless_jump_raises_script_error_with_scene_id(self) -> None:
        engine = GalgameEngine(_jump_story(101))

        with self.assertLogs("easyengine.galgame.engine", level="ERROR") as logs:
            with self.assertRaisesRegex(
                ScriptError,
                "检测到可能的死循环跳转，请检查剧本的 goto/next 逻辑",
            ):
                engine.start()

        self.assertTrue(any("scene-100" in message for message in logs.output))


class FrozenPathTests(unittest.TestCase):
    def test_frozen_base_path_uses_pyinstaller_extraction_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(config.sys, "frozen", True, create=True),
                patch.object(
                    config.sys,
                    "_MEIPASS",
                    directory,
                    create=True,
                ),
            ):
                self.assertEqual(config.get_base_path(), Path(directory).resolve())


if __name__ == "__main__":
    unittest.main()
