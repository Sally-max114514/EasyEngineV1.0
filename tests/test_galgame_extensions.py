from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from easyengine import __author__
from easyengine.galgame import GalgameEngine, ScriptError, Transition, parse_story
from easyengine.galgame.expressions import ExpressionError, evaluate_expression
from easyengine.galgame.state import GameState, SAVE_VERSION, SaveError, SpriteState


class ExpressionTests(unittest.TestCase):
    def test_nested_values_and_safe_expression(self) -> None:
        variables = {
            "stats": {"affection": 3},
            "route": "good",
            "flags": {"blocked": False},
        }
        self.assertTrue(
            evaluate_expression(
                "stats.affection >= 3 and (route == 'good' or flags.blocked)",
                variables,
            )
        )
        self.assertEqual(
            evaluate_expression("stats.affection + 2", variables),
            5,
        )

    def test_expression_rejects_calls_and_private_attributes(self) -> None:
        for expression in ("__import__('os')", "vars.__class__"):
            with self.subTest(expression=expression):
                with self.assertRaises(ExpressionError):
                    evaluate_expression(expression, {})

    def test_nested_variables_expression_changes_and_condition_tree(self) -> None:
        story = parse_story(
            {
                "title": "表达式测试",
                "start": "start",
                "vars": {
                    "stats": {"affection": 1},
                    "route": "good",
                    "flags": {"locked": False},
                },
                "scenes": {
                    "start": {
                        "lines": [
                            {
                                "text": "起点",
                                "set_expr": {
                                    "stats.affection": "stats.affection + 1"
                                },
                            },
                            {
                                "text": "选择",
                                "choices": [
                                    {
                                        "text": "解锁选项",
                                        "require": {
                                            "all": [
                                                {
                                                    "var": "stats.affection",
                                                    "op": ">=",
                                                    "value": 2,
                                                },
                                                {
                                                    "any": [
                                                        "route == 'good'",
                                                        "flags.locked",
                                                    ]
                                                },
                                            ]
                                        },
                                        "goto": "end",
                                    }
                                ],
                            }
                        ]
                    },
                    "end": {"lines": [{"text": "结束", "end": True}]},
                },
            }
        )
        engine = GalgameEngine(story)
        engine.start()
        stats = engine.view.variables["stats"]
        assert isinstance(stats, dict)
        self.assertEqual(stats["affection"], 2)
        engine.reveal_all()
        engine.advance()
        self.assertTrue(engine.available_choices[0].available)

    def test_expression_is_validated_when_loading_story(self) -> None:
        with self.assertRaises(ScriptError):
            parse_story(
                {
                    "title": "无效条件",
                    "start": "start",
                    "scenes": {
                        "start": {
                            "lines": [
                                {
                                    "choices": [
                                        {
                                            "text": "bad",
                                            "require": "__import__('os')",
                                        }
                                    ]
                                }
                            ]
                        }
                    },
                }
            )


class EngineHistoryAndSaveTests(unittest.TestCase):
    def _story(self, second_line: str = "第二行"):
        return parse_story(
            {
                "title": "存档测试",
                "start": "start",
                "vars": {"nested": {"score": 0}},
                "gallery": [
                    {
                        "id": "cg-one",
                        "image": "image/cg/one.png",
                        "title": "CG 一",
                    }
                ],
                "scenes": {
                    "start": {
                        "lines": [
                            {"text": "第一行", "voice": "audio/voice/one.wav"},
                            {"text": second_line},
                        ]
                    }
                },
            }
        )

    def test_story_assets_include_voice_and_gallery(self) -> None:
        story = self._story()
        self.assertEqual(
            tuple(story.asset_references()),
            ("audio/voice/one.wav", "image/cg/one.png"),
        )

    def test_rollback_restores_previous_line(self) -> None:
        engine = GalgameEngine(self._story())
        engine.start()
        engine.reveal_all()
        engine.advance()
        self.assertEqual(engine.view.text, "第二行")
        result = engine.rollback()
        self.assertEqual(result.view.text, "第一行")
        self.assertEqual(engine.rollback_depth, 0)

    def test_save_fingerprint_rejects_changed_story(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = GalgameEngine(self._story(), save_dir=directory)
            first.start()
            first.save("slot1")
            changed = GalgameEngine(
                self._story("内容已修改"),
                save_dir=directory,
            )
            with self.assertRaises(SaveError):
                changed.load("slot1")

    def test_legacy_save_is_readable_and_marked_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            story = self._story()
            engine = GalgameEngine(story, save_dir=directory)
            engine.start()
            state = GameState(
                scene_id="start",
                line_index=0,
                variables={"nested": {"score": 4}},
                sprites={"hero": SpriteState("image/hero.png")},
            )
            legacy_path = Path(directory) / "old.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "script_title": story.title,
                        "state": state.to_dict(),
                    }
                ),
                encoding="utf-8",
            )
            result = engine.load("old")
            load_event = next(event for event in result.events if event.kind == "load")
            self.assertTrue(load_event.data["unverified"])
            nested = result.view.variables["nested"]
            assert isinstance(nested, dict)
            self.assertEqual(nested["score"], 4)

    def test_new_save_version_round_trips_nested_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = GalgameEngine(self._story(), save_dir=directory)
            engine.start()
            engine.save("slot1")
            self.assertEqual(SAVE_VERSION, 2)
            saved_payload = json.loads(
                (Path(directory) / "slot1.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved_payload["engine"], "EasyEngine")
            self.assertEqual(saved_payload["author"], __author__)
            loaded = GalgameEngine(self._story(), save_dir=directory)
            loaded.load("slot1")
            nested = loaded.view.variables["nested"]
            assert isinstance(nested, dict)
            self.assertEqual(nested["score"], 0)


class TransitionTests(unittest.TestCase):
    def test_scene_line_and_background_transitions_are_emitted(self) -> None:
        story = parse_story(
            {
                "title": "转场测试",
                "start": "start",
                "scenes": {
                    "start": {
                        "transition": {"type": "slide-left", "duration": 0.6},
                        "lines": [
                            {"text": "第一行", "transition": "crossfade"},
                            {"text": "第二行", "background": "image/bg/next.png"},
                        ],
                    }
                },
            }
        )
        engine = GalgameEngine(story)

        result = engine.start()
        scene_event = next(event for event in result.events if event.kind == "scene")
        line_transition = next(
            event for event in result.events if event.kind == "transition"
        )
        self.assertEqual(
            scene_event.data["transition"],
            Transition("slide-left", 0.6),
        )
        self.assertEqual(
            line_transition.data["transition"],
            Transition("crossfade", 0.32),
        )

        engine.reveal_all()
        result = engine.advance()
        background_transition = next(
            event for event in result.events if event.kind == "transition"
        )
        self.assertEqual(
            background_transition.data["transition"],
            Transition(),
        )

    def test_transition_configuration_is_validated(self) -> None:
        for transition in (
            {"type": "zoom"},
            {"type": "fade", "duration": 5.1},
            {"type": "fade", "duration": True},
        ):
            with self.subTest(transition=transition):
                with self.assertRaises(ScriptError):
                    parse_story(
                        {
                            "title": "无效转场",
                            "start": "start",
                            "scenes": {
                                "start": {
                                    "transition": transition,
                                    "lines": [{"text": "台词"}],
                                }
                            },
                        }
                    )


if __name__ == "__main__":
    unittest.main()
