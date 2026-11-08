from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest

from easyengine import (
    __author__,
    __generator__,
    __github__,
    __github_profile__,
    __version__,
)
from main import print_banner


class BrandingTests(unittest.TestCase):
    def test_package_metadata_and_generator_marker(self) -> None:
        self.assertEqual(__author__, "Sally-max114514")
        self.assertEqual(
            __github__,
            "https://github.com/Sally-max114514/EasyEngineV1.0",
        )
        self.assertEqual(__github_profile__, "https://github.com/Sally-max114514")
        self.assertEqual(__version__, "1.0.0 (MIT License)")
        self.assertEqual(__generator__, f"EasyEngine by {__author__}")

    def test_cli_banner_displays_package_metadata(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            print_banner()

        banner = output.getvalue()
        self.assertIn("EasyEngine - 极简的 Python Galgame 引擎", banner)
        self.assertIn(f"Author: {__author__}", banner)
        self.assertIn(f"GitHub: {__github__}", banner)
        self.assertIn("License: MIT", banner)

    def test_pygame_window_caption_displays_engine_brand(self) -> None:
        if importlib.util.find_spec("pygame") is None:
            self.skipTest("Pygame-CE is not installed")

        from easyengine.desktop.app import PygameApplication
        from easyengine.galgame import parse_story

        story = parse_story(
            {
                "title": "Caption Test",
                "start": "start",
                "scenes": {"start": {"lines": [{"text": "Hello"}]}},
            }
        )

        self.assertEqual(
            PygameApplication._window_caption(story),
            "Caption Test | Powered by EasyEngine",
        )


if __name__ == "__main__":
    unittest.main()
