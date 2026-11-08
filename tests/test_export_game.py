from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from easyengine import __author__, __generator__
from export_game import (
    _EXCLUDED_MODULES,
    build_pyinstaller_command,
    create_distribution_archive,
    distribution_archive_path,
    export_game,
    stage_assets,
    write_windows_version_file,
)


class ExportStagingTests(unittest.TestCase):
    def test_stage_assets_keeps_game_assets_and_only_selected_script(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_assets = root / "source-assets"
            old_script = source_assets / "text" / "scripts" / "unused.json"
            old_script.parent.mkdir(parents=True)
            old_script.write_text("{}", encoding="utf-8")
            image = source_assets / "image" / "bg" / "room.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"image")
            selected_story = root / "chosen.json"
            selected_story.write_text('{"title":"Selected"}', encoding="utf-8")

            staged = stage_assets(
                source_assets,
                root / "staged-assets",
                selected_story,
            )

            self.assertTrue((staged / "image" / "bg" / "room.png").is_file())
            self.assertFalse(
                (staged / "text" / "scripts" / "unused.json").exists()
            )
            self.assertEqual(
                json.loads(
                    (staged / "text" / "scripts" / "demo.json").read_text(
                        encoding="utf-8"
                    )
                ),
                {"title": "Selected", "_generator": __generator__},
            )

    def test_pyinstaller_command_is_onefile_windowed_and_excludes_qt(self) -> None:
        command = build_pyinstaller_command(
            name="Sample",
            staged_assets="/tmp/staged/assets",
            output_dir="/tmp/dist",
            work_dir="/tmp/build",
            spec_dir="/tmp/spec",
            main_file="/project/main.py",
            python_executable="/python",
        )

        self.assertIn("--onefile", command)
        self.assertIn("--windowed", command)
        self.assertEqual(
            command[command.index("--add-data") + 1],
            f"/tmp/staged/assets{os.pathsep}assets",
        )
        self.assertEqual(command[-1], "/project/main.py")
        for module in _EXCLUDED_MODULES:
            with self.subTest(module=module):
                position = command.index(module)
                self.assertEqual(command[position - 1], "--exclude-module")
        self.assertIn("easyengine.desktop.app", command)

    def test_windows_version_resources_include_product_and_author(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            version_file = write_windows_version_file(
                Path(directory) / "version_info.txt",
                executable_name="Sample",
            )
            version_text = version_file.read_text(encoding="utf-8")

            compile(version_text, str(version_file), "exec")
            self.assertIn(f"StringStruct('CompanyName', '{__author__}')", version_text)
            self.assertIn("StringStruct('ProductName', 'EasyEngine')", version_text)
            self.assertIn("StringStruct('FileVersion', '1.0.0')", version_text)

            command = build_pyinstaller_command(
                name="Sample",
                staged_assets="/tmp/staged/assets",
                output_dir="/tmp/dist",
                work_dir="/tmp/build",
                spec_dir="/tmp/spec",
                version_file=version_file,
                windows=True,
            )
            self.assertEqual(
                command[command.index("--version-file") + 1],
                str(version_file),
            )

    def test_distribution_archive_contains_executable_and_existing_license(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "Sample.bin"
            executable.write_bytes(b"game executable")

            archive_path = create_distribution_archive(executable)

            self.assertEqual(
                archive_path,
                executable.with_name("Sample.bin.zip"),
            )
            with ZipFile(archive_path) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"Sample.bin", "LICENSE"},
                )
                self.assertEqual(archive.read("Sample.bin"), b"game executable")
                self.assertEqual(
                    archive.read("LICENSE"),
                    (Path(__file__).resolve().parents[1] / "LICENSE").read_bytes(),
                )
            self.assertEqual(
                distribution_archive_path(Path(directory) / "Sample.exe"),
                Path(directory) / "Sample.zip",
            )

    def test_export_uses_selected_story_and_expected_pyinstaller_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            image = assets / "image" / "room.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"image")
            story_path = root / "story.json"
            story_path.write_text(
                json.dumps(
                    {
                        "title": "My Game",
                        "start": "start",
                        "scenes": {
                            "start": {
                                "background": "image/room.png",
                                "lines": [{"text": "Hello"}],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            output = root / "dist"

            def fake_pyinstaller(
                command: list[str],
                *,
                cwd: Path,
                check: bool,
            ) -> None:
                self.assertEqual(cwd, Path(__file__).resolve().parents[1])
                self.assertTrue(check)
                self.assertIn("--onefile", command)
                self.assertIn("--windowed", command)
                name = command[command.index("--name") + 1]
                dist_dir = Path(command[command.index("--distpath") + 1])
                dist_dir.mkdir(parents=True, exist_ok=True)
                (dist_dir / name).write_bytes(b"executable")

                data_argument = command[command.index("--add-data") + 1]
                staged_assets = Path(data_argument.rsplit(os.pathsep, 1)[0])
                self.assertTrue(
                    (
                        staged_assets
                        / "text"
                        / "scripts"
                        / "demo.json"
                    ).is_file()
                )
                self.assertFalse(
                    (
                        staged_assets
                        / "text"
                        / "scripts"
                        / "unselected.json"
                    ).exists()
                )

            with patch("export_game.subprocess.run", side_effect=fake_pyinstaller):
                executable = export_game(
                    story_path,
                    output_dir=output,
                )

            self.assertEqual(executable, output / "My Game")
            self.assertTrue(executable.is_file())
            archive_path = distribution_archive_path(executable)
            self.assertTrue(archive_path.is_file())
            with ZipFile(archive_path) as archive:
                self.assertEqual(set(archive.namelist()), {"My Game", "LICENSE"})


if __name__ == "__main__":
    unittest.main()
