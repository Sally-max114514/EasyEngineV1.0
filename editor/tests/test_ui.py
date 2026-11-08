from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if PYSIDE6_AVAILABLE:
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialogButtonBox,
        QDialog,
        QDoubleSpinBox,
        QFormLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPlainTextEdit,
        QSpinBox,
        QSplitter,
    )

    from editor.main import (
        ASSETS_DIRECTORY_SETTING_KEY,
        AUTO_SAVE_SETTING_KEY,
        EditorWindow,
        FONT_SIZE_SETTING_KEY,
        LAST_SCRIPT_SETTING_KEY,
        OPEN_LAST_SCRIPT_SETTING_KEY,
        SettingsDialog,
        THEME_SETTING_KEY,
        USER_ROLE,
        WELCOME_GUIDE_SUPPRESSED_KEY,
    )
    from editor.model import NodeRef, StoryModel
    from easyengine import __author__, __github__, __github_profile__


@unittest.skipUnless(PYSIDE6_AVAILABLE, "Install editor/requirements.txt for GUI tests")
class EditorUiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.settings_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.settings_directory.cleanup)
        self.settings_path = Path(self.settings_directory.name) / "settings.ini"
        self.settings = QSettings(
            str(self.settings_path),
            QSettings.Format.IniFormat,
        )
        self.settings.setValue(WELCOME_GUIDE_SUPPRESSED_KEY, True)
        self.settings.sync()

    def make_window(self) -> EditorWindow:
        return EditorWindow(settings=self.settings)

    def test_window_has_three_panes_and_resource_categories(self) -> None:
        window = self.make_window()
        splitter = window.centralWidget()
        self.assertIsInstance(splitter, QSplitter)
        self.assertEqual(splitter.count(), 3)
        self.assertEqual(window.asset_tree.topLevelItemCount(), 5)
        self.assertEqual(window.story_tree.topLevelItemCount(), 1)
        story_root = window.story_tree.topLevelItem(0)
        self.assertIsNotNone(story_root)
        assert story_root is not None
        self.assertEqual(story_root.childCount(), 1)
        window.close()

    def test_assigning_a_resource_updates_native_story_json(self) -> None:
        window = self.make_window()
        window.model = StoryModel(
            {
                "title": "资源测试",
                "start": "start",
                "scenes": {"start": {"lines": [{"text": "你好"}]}},
            }
        )
        ref = NodeRef("line", scene_id="start", line_index=0)
        window._refresh_tree(ref)
        resource_field = next(
            field for field in window._resource_fields if field.parent() is window.form_panel
        )
        window._active_resource_field = resource_field
        window._assign_asset("image/bg/classroom.png")

        line = window.model.get_line("start", 0)
        if line is None:
            self.fail("Expected the selected line to exist")
        self.assertEqual(
            line["background"],
            "image/bg/classroom.png",
        )
        window._dirty = False
        window.close()

    def test_asset_browser_drag_payload_is_relative_path(self) -> None:
        window = self.make_window()
        demo_item = None
        for category_index in range(window.asset_tree.topLevelItemCount()):
            category = window.asset_tree.topLevelItem(category_index)
            for item_index in range(category.childCount()):
                item = category.child(item_index)
                if item.data(0, USER_ROLE) == "text/scripts/demo.json":
                    demo_item = item
                    break
        if demo_item is None:
            self.fail("Expected demo script to appear in the asset browser")
        mime = window.asset_tree.mimeData([demo_item])
        self.assertEqual(mime.text(), "text/scripts/demo.json")
        window.close()

    def test_switching_condition_modes_clears_unrepresentable_value(self) -> None:
        window = self.make_window()
        window.model = StoryModel(
            {
                "title": "条件测试",
                "start": "start",
                "scenes": {
                    "start": {
                        "lines": [
                            {
                                "text": "选择",
                                "choices": [
                                    {
                                        "text": "继续",
                                        "require": "score >= 1",
                                    }
                                ],
                            }
                        ]
                    }
                },
            }
        )
        ref = NodeRef("choice", scene_id="start", line_index=0, choice_index=0)
        window._refresh_tree(ref)
        condition_mode = window.form_panel.findChildren(QComboBox)[-1]
        condition_mode.setCurrentIndex(1)

        choice = window.model.get_choice("start", 0, 0)
        if choice is None:
            self.fail("Expected the selected choice to exist")
        self.assertNotIn("require", choice)
        window._dirty = False
        window.close()

    def test_form_inputs_have_tooltips_and_chinese_labels(self) -> None:
        window = self.make_window()
        window.model = StoryModel(
            {
                "title": "新手教程测试",
                "start": "classroom",
                "characters": {"yuki": "雪乃"},
                "vars": {"affection.yuki": 0},
                "gallery": [],
                "scenes": {
                    "classroom": {
                        "background": "image/bg/classroom.png",
                        "bgm": "audio/bgm/daily.mp3",
                        "transition": {"type": "fade", "duration": 0.32},
                        "next": "ending",
                        "lines": [
                            {
                                "speaker": "yuki",
                                "text": "今天的晚霞真好看。",
                                "background": "image/bg/classroom.png",
                                "bgm": "audio/bgm/daily.mp3",
                                "voice": "audio/voice/yuki_001.wav",
                                "se": "audio/se/click.wav",
                                "transition": {"type": "fade", "duration": 0.32},
                                "show": [],
                                "hide": [],
                                "set": {},
                                "add": {},
                                "set_expr": {},
                                "add_expr": {},
                                "choices": [
                                    {
                                        "text": "和雪乃一起回家",
                                        "goto": "ending",
                                        "require": "affection.yuki >= 3",
                                    }
                                ],
                            }
                        ],
                    },
                    "ending": {"lines": [], "end": True},
                },
            }
        )

        def form_labels() -> list[str]:
            labels: list[str] = []
            for row in range(window.form_layout.rowCount()):
                item = window.form_layout.itemAt(
                    row, QFormLayout.ItemRole.LabelRole
                )
                if item is not None and isinstance(item.widget(), QLabel):
                    labels.append(item.widget().text())
            return labels

        def assert_inputs_have_tooltips() -> None:
            input_types = (
                QComboBox,
                QLineEdit,
                QPlainTextEdit,
                QCheckBox,
                QDoubleSpinBox,
            )
            for input_type in input_types:
                for widget in window.form_panel.findChildren(input_type):
                    self.assertTrue(
                        widget.toolTip().strip(),
                        f"{input_type.__name__} is missing a tooltip",
                    )

        forbidden_keys = (
            "title",
            "start",
            "speaker",
            "text",
            "background",
            "bgm",
            "voice",
            "se",
            "transition",
            "require",
            "goto",
            "next",
            "end",
            "characters",
            "vars",
            "gallery",
            "show",
            "hide",
            "set",
            "add",
            "set_expr",
            "add_expr",
            "choices",
        )
        refs = (
            NodeRef("story"),
            NodeRef("scene", scene_id="classroom"),
            NodeRef("line", scene_id="classroom", line_index=0),
            NodeRef(
                "choice",
                scene_id="classroom",
                line_index=0,
                choice_index=0,
            ),
        )
        for ref in refs:
            window._refresh_tree(ref)
            assert_inputs_have_tooltips()
            label_text = " ".join(form_labels()).lower()
            for field_key in forbidden_keys:
                self.assertNotIn(field_key, label_text)

        window._refresh_tree(NodeRef("line", scene_id="classroom", line_index=0))
        line_tooltips: list[str] = []
        for input_type in (QComboBox, QLineEdit, QPlainTextEdit):
            line_tooltips.extend(
                widget.toolTip()
                for widget in window.form_panel.findChildren(input_type)
            )
        joined_tooltips = " ".join(line_tooltips)
        self.assertIn("当前这句台词是谁说的", joined_tooltips)
        self.assertIn("打字机效果", joined_tooltips)
        self.assertIn("循环播放", joined_tooltips)
        self.assertIn("image/bg/classroom.png", joined_tooltips)
        transition_picker = next(
            widget
            for widget in window.form_panel.findChildren(QComboBox)
            if "动画效果" in widget.toolTip()
        )
        self.assertEqual(transition_picker.currentText(), "淡入（fade）")
        self.assertEqual(transition_picker.currentData(USER_ROLE), "fade")
        choices_hint = next(
            label
            for label in window.form_panel.findChildren(QLabel)
            if label.text().startswith("玩家选项：")
        )
        self.assertIn("玩家可以选择的剧情分支", choices_hint.toolTip())

        window._refresh_tree(
            NodeRef("choice", scene_id="classroom", line_index=0, choice_index=0)
        )
        jump_picker = next(
            widget
            for widget in window.form_panel.findChildren(QComboBox)
            if "跳到哪个场景" in widget.toolTip()
        )
        self.assertEqual(jump_picker.currentData(USER_ROLE), "ending")
        self.assertIn(
            "affection.yuki >= 3",
            " ".join(
                widget.toolTip()
                for widget in window.form_panel.findChildren(QPlainTextEdit)
            ),
        )
        window.close()

    def test_welcome_guide_is_non_modal_and_remembers_opt_out(self) -> None:
        self.settings.setValue(WELCOME_GUIDE_SUPPRESSED_KEY, False)
        window = self.make_window()
        self.application.processEvents()

        guide = window._welcome_dialog
        guide_text = guide.findChild(QLabel, "welcomeGuideText")
        self.assertTrue(guide.isVisible())
        self.assertFalse(guide.isModal())
        self.assertTrue(window.isEnabled())
        self.assertEqual(guide.windowTitle(), "欢迎使用 EasyEngine 剧情编辑器")
        self.assertIsNotNone(guide_text)
        assert guide_text is not None
        self.assertIn("三步操作指南", guide_text.text())

        guide.dont_show_checkbox.setChecked(True)
        self.assertTrue(
            self.settings.value(WELCOME_GUIDE_SUPPRESSED_KEY, False, type=bool)
        )
        guide.hide()
        window.close()

        next_window = self.make_window()
        self.application.processEvents()
        self.assertFalse(next_window._welcome_dialog.isVisible())
        next_window.close()

    def test_help_menu_can_reopen_welcome_guide(self) -> None:
        window = self.make_window()
        help_action = next(
            action for action in window.menuBar().actions() if action.text() == "帮助"
        )
        help_menu = help_action.menu()
        self.assertIsNotNone(help_menu)
        assert help_menu is not None
        tutorial_action = next(
            action for action in help_menu.actions()
            if action.text() == "新手教程"
        )

        tutorial_action.trigger()

        self.assertTrue(window._welcome_dialog.isVisible())
        self.assertFalse(window._welcome_dialog.isModal())
        window._welcome_dialog.hide()
        window.close()

    def test_about_menu_shows_project_branding_without_blocking(self) -> None:
        window = self.make_window()
        self.assertIn(__author__, window.windowTitle())
        help_action = next(
            action for action in window.menuBar().actions() if action.text() == "帮助"
        )
        help_menu = help_action.menu()
        self.assertIsNotNone(help_menu)
        assert help_menu is not None
        about_action = next(
            action for action in help_menu.actions()
            if action.text() == "关于 EasyEngine"
        )

        with patch("editor.main.QMessageBox.about") as show_about:
            about_action.trigger()

        self.assertEqual(show_about.call_count, 1)
        about_text = show_about.call_args.args[2]
        self.assertIn(__author__, about_text)
        self.assertIn(__github__, about_text)
        self.assertIn("Powered by EasyEngine", about_text)
        self.assertIn(f"作者Github：{__github_profile__}", about_text)
        self.assertIn("MIT License", about_text)
        window.close()

    def test_settings_dialog_persists_and_applies_preferences(self) -> None:
        window = self.make_window()
        system_style = QApplication.style().objectName()
        system_window_color = QApplication.palette().color(QPalette.ColorRole.Window)
        custom_assets = Path(self.settings_directory.name) / "custom-assets"
        image_directory = custom_assets / "image" / "bg"
        image_directory.mkdir(parents=True)
        custom_image = image_directory / "custom.png"
        custom_image.touch()

        dialog = SettingsDialog(self.settings, window._assets_dir, window)
        dialog.settingsApplied.connect(window._apply_user_preferences)
        dialog.theme_combo.setCurrentIndex(
            dialog.theme_combo.findData("dark", USER_ROLE)
        )
        dialog.font_size_spin.setValue(18)
        dialog.auto_save_checkbox.setChecked(True)
        dialog.open_last_script_checkbox.setChecked(True)
        dialog.assets_directory_edit.setText(str(custom_assets))
        dialog.show()

        apply_button = dialog.button_box.button(QDialogButtonBox.StandardButton.Apply)
        self.assertIsNotNone(apply_button)
        assert apply_button is not None
        apply_button.click()

        self.assertTrue(dialog.isVisible())
        self.assertEqual(self.settings.value(THEME_SETTING_KEY), "dark")
        self.assertEqual(self.settings.value(FONT_SIZE_SETTING_KEY), 18)
        self.assertIs(self.settings.value(AUTO_SAVE_SETTING_KEY), True)
        self.assertIs(self.settings.value(OPEN_LAST_SCRIPT_SETTING_KEY), True)
        self.assertEqual(
            Path(self.settings.value(ASSETS_DIRECTORY_SETTING_KEY)),
            custom_assets.resolve(),
        )
        self.assertEqual(window._theme, "dark")
        self.assertEqual(window._font_size, 18)
        self.assertTrue(window._auto_save)
        self.assertTrue(window._open_last_script)
        self.assertEqual(
            QApplication.palette().color(QPalette.ColorRole.Window).name(),
            "#202124",
        )
        self.assertEqual(window.font().pointSize(), 18)
        self.assertEqual(
            window.form_panel.findChild(QPlainTextEdit).font().pointSize(),
            18,
        )
        self.assertEqual(window._assets["image"], ["image/bg/custom.png"])
        self.assertEqual(
            Path(window.asset_tree.topLevelItem(0).child(0).toolTip(0)),
            custom_image.resolve(),
        )
        self.assertIsInstance(dialog.font_size_spin, QSpinBox)
        self.assertEqual(dialog.font_size_spin.minimum(), 10)
        self.assertEqual(dialog.font_size_spin.maximum(), 24)

        reloaded_settings = QSettings(
            str(self.settings_path),
            QSettings.Format.IniFormat,
        )
        reloaded_window = EditorWindow(settings=reloaded_settings)
        self.assertEqual(reloaded_window._theme, "dark")
        self.assertEqual(reloaded_window._font_size, 18)
        self.assertTrue(reloaded_window._auto_save)
        self.assertEqual(reloaded_window._assets_dir, custom_assets.resolve())
        reloaded_window.close()

        dialog.theme_combo.setCurrentIndex(
            dialog.theme_combo.findData("system", USER_ROLE)
        )
        apply_button.click()
        self.assertEqual(window._theme, "system")
        self.assertEqual(QApplication.style().objectName(), system_style)
        self.assertEqual(
            QApplication.palette().color(QPalette.ColorRole.Window),
            system_window_color,
        )

        dialog.close()
        window.close()

    def test_cancelled_settings_dialog_does_not_persist_changes(self) -> None:
        window = self.make_window()
        dialog = SettingsDialog(self.settings, window._assets_dir, window)
        dialog.theme_combo.setCurrentIndex(
            dialog.theme_combo.findData("dark", USER_ROLE)
        )
        dialog.font_size_spin.setValue(20)
        dialog.auto_save_checkbox.setChecked(True)

        cancel_button = dialog.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        self.assertIsNotNone(cancel_button)
        assert cancel_button is not None
        cancel_button.click()

        self.assertIsNone(self.settings.value(THEME_SETTING_KEY))
        self.assertIsNone(self.settings.value(FONT_SIZE_SETTING_KEY))
        self.assertIsNone(self.settings.value(AUTO_SAVE_SETTING_KEY))
        self.assertEqual(window._theme, "system")
        self.assertFalse(window._auto_save)
        window.close()

    def test_ok_button_saves_and_accepts_settings(self) -> None:
        window = self.make_window()
        dialog = SettingsDialog(self.settings, window._assets_dir, window)
        dialog.font_size_spin.setValue(16)
        ok_button = dialog.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.assertIsNotNone(ok_button)
        assert ok_button is not None
        ok_button.click()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.settings.value(FONT_SIZE_SETTING_KEY), 16)
        window.close()

    def test_last_script_is_reopened_from_string_boolean_setting(self) -> None:
        recent_path = Path(self.settings_directory.name) / "recent.json"
        StoryModel().save(recent_path)
        self.settings.setValue(OPEN_LAST_SCRIPT_SETTING_KEY, "true")
        self.settings.setValue(LAST_SCRIPT_SETTING_KEY, str(recent_path))

        window = self.make_window()

        self.assertEqual(window.model.path, recent_path.resolve())
        self.assertEqual(
            Path(self.settings.value(LAST_SCRIPT_SETTING_KEY)),
            recent_path.resolve(),
        )
        window.close()

    def test_false_boolean_settings_are_parsed_from_strings_and_numbers(self) -> None:
        self.settings.setValue(AUTO_SAVE_SETTING_KEY, "false")
        self.settings.setValue(OPEN_LAST_SCRIPT_SETTING_KEY, 0)

        window = self.make_window()

        self.assertFalse(window._auto_save)
        self.assertFalse(window._open_last_script)
        window.close()

    def test_auto_save_runs_when_switching_tree_nodes(self) -> None:
        story_path = Path(self.settings_directory.name) / "autosave.json"
        StoryModel(
            {
                "title": "保存前",
                "start": "start",
                "scenes": {"start": {"lines": [{"text": "你好"}]}},
            }
        ).save(story_path)
        self.settings.setValue(AUTO_SAVE_SETTING_KEY, "true")
        window = self.make_window()
        window.model = StoryModel.open(story_path)
        window._refresh_tree(NodeRef("story"))
        title_input = window.form_panel.findChild(QLineEdit)
        self.assertIsNotNone(title_input)
        assert title_input is not None
        title_input.setText("自动保存后")

        scene_item = window._tree_items[NodeRef("scene", scene_id="start")]
        window.story_tree.setCurrentItem(scene_item)

        saved_model = StoryModel.open(story_path)
        self.assertEqual(saved_model.data["title"], "自动保存后")
        self.assertFalse(window._dirty)
        self.assertEqual(window._active_ref, NodeRef("scene", scene_id="start"))
        window.close()

    def test_auto_save_without_file_path_keeps_unsaved_edits(self) -> None:
        self.settings.setValue(AUTO_SAVE_SETTING_KEY, "true")
        window = self.make_window()
        title_input = window.form_panel.findChild(QLineEdit)
        self.assertIsNotNone(title_input)
        assert title_input is not None
        title_input.setText("尚未命名")

        scene_item = window._tree_items[NodeRef("scene", scene_id="scene_1")]
        window.story_tree.setCurrentItem(scene_item)

        self.assertTrue(window._dirty)
        self.assertEqual(window._active_ref, NodeRef("scene", scene_id="scene_1"))
        self.assertIn("先手动保存", window.statusBar().currentMessage())
        window._dirty = False
        window.close()

    def test_preferences_menu_exposes_dialog_action_and_shortcut(self) -> None:
        window = self.make_window()
        tools_action = next(
            action for action in window.menuBar().actions() if action.text() == "工具"
        )
        tools_menu = tools_action.menu()
        self.assertIsNotNone(tools_menu)
        assert tools_menu is not None
        preferences_action = next(
            action
            for action in tools_menu.actions()
            if action.text() == "偏好设置..."
        )
        self.assertEqual(preferences_action.shortcut().toString(), "Ctrl+,")
        self.assertIs(window._preferences_action, preferences_action)
        with patch.object(window, "show_settings_dialog") as open_settings:
            preferences_action.trigger()
            open_settings.assert_called_once_with()
        window.close()


if __name__ == "__main__":
    unittest.main()
