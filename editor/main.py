"""Standalone Qt story editor for the EasyEngine JSON script format."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QMimeData,
    QSettings,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QKeySequence,
    QPalette,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from easyengine import __author__, __github__, __github_profile__, __version__
from easyengine.config import ASSETS_DIR
from easyengine.galgame import ScriptError
from easyengine.resources import scan_assets

from editor.model import EditorModelError, NodeRef, StoryModel, UNSET

USER_ROLE = Qt.ItemDataRole.UserRole
ASSET_MIME_TYPE = "application/x-easyengine-asset"
UNSET_TOKEN = "__easyengine_editor_unset__"
CLEAR_TOKEN = "__easyengine_editor_clear__"
TRANSITIONS = (
    ("淡入（fade）", "fade"),
    ("交叉淡化（crossfade）", "crossfade"),
    ("从左侧滑入（slide-left）", "slide-left"),
    ("从右侧滑入（slide-right）", "slide-right"),
    ("无特效（none）", "none"),
)
RESOURCE_CATEGORIES = ("image", "audio", "text", "video", "other")
WELCOME_GUIDE_SUPPRESSED_KEY = "editor/welcomeGuideSuppressed"
THEME_SETTING_KEY = "appearance/theme"
FONT_SIZE_SETTING_KEY = "appearance/fontSize"
AUTO_SAVE_SETTING_KEY = "behavior/autoSave"
OPEN_LAST_SCRIPT_SETTING_KEY = "behavior/openLastScript"
ASSETS_DIRECTORY_SETTING_KEY = "paths/assetsDirectory"
LAST_SCRIPT_SETTING_KEY = "files/lastScript"
THEMES = ("system", "light", "dark")
DEFAULT_FONT_SIZE = 12

_DEFAULT_QT_APPEARANCE: dict[str, Any] | None = None


def _setting_bool(settings: QSettings, key: str, default: bool) -> bool:
    value = settings.value(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def _setting_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _setting_text(settings: QSettings, key: str, default: str = "") -> str:
    value = settings.value(key, default)
    if isinstance(value, (str, Path)):
        return str(value).strip()
    return default


def _resolve_assets_directory(value: Any) -> Path:
    raw = str(value).strip() if isinstance(value, (str, Path)) else ""
    directory = Path(raw).expanduser() if raw else ASSETS_DIR
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    return directory.resolve()


def _read_preferences(settings: QSettings) -> dict[str, Any]:
    theme = _setting_text(settings, THEME_SETTING_KEY, "system").casefold()
    if theme not in THEMES:
        theme = "system"
    font_size = _setting_int(
        settings.value(FONT_SIZE_SETTING_KEY, DEFAULT_FONT_SIZE),
        DEFAULT_FONT_SIZE,
    )
    return {
        "theme": theme,
        "font_size": min(24, max(10, font_size)),
        "auto_save": _setting_bool(settings, AUTO_SAVE_SETTING_KEY, False),
        "open_last_script": _setting_bool(
            settings, OPEN_LAST_SCRIPT_SETTING_KEY, False
        ),
        "assets_directory": _resolve_assets_directory(
            settings.value(ASSETS_DIRECTORY_SETTING_KEY, str(ASSETS_DIR))
        ),
    }


def _create_settings() -> QSettings:
    settings = QSettings("EasyEngine", "Editor")
    legacy_settings = QSettings("EasyEngine", "StoryEditor")
    if (
        not settings.contains(WELCOME_GUIDE_SUPPRESSED_KEY)
        and legacy_settings.contains(WELCOME_GUIDE_SUPPRESSED_KEY)
    ):
        settings.setValue(
            WELCOME_GUIDE_SUPPRESSED_KEY,
            _setting_bool(legacy_settings, WELCOME_GUIDE_SUPPRESSED_KEY, False),
        )
        settings.sync()
    return settings

FIELD_TOOLTIPS = {
    "title": "给剧本起个容易辨认的名字，例如：放学后的约定。",
    "start": "玩家进入游戏后从哪个场景开始？请从列表中选择。",
    "characters": '登记剧中角色，例如：{"yuki": "雪乃"}。说话人可从这里选择。',
    "vars": '设置剧情变量的初始值，例如：{"affection.yuki": 0, "met_yuki": false}。',
    "gallery": '填写 CG 鉴赏图片列表，例如：[{"id": "sunset", "image": "image/cg/sunset.png", "title": "晚霞"}]。',
    "speaker": "当前这句台词是谁说的？选择角色名；留空或选择“旁白”表示没有角色在说话。",
    "text": "角色要说的话。支持逐字显示的打字机效果，例如：今天的晚霞真好看。",
    "background": "当前场景要显示的背景图，例如 image/bg/classroom.png。可从右侧素材库双击或拖入。",
    "bgm": "场景里的背景音乐，会循环播放；例如 audio/bgm/daily.mp3。可从右侧素材库选择。",
    "voice": "这句台词对应的角色语音，例如 audio/voice/yuki_001.wav。",
    "se": "说到这句台词时播放一次的短音效，例如 audio/se/click.wav。",
    "goto": "这句台词说完或玩家选中此项后，剧情要跳到哪个场景？请从下拉列表选择。",
    "next": "本场景的台词全部播放完后，自动进入哪个场景？留空表示剧情结束。",
    "require": "玩家满足什么条件后才会看到这个选项？例如好感度 >= 3。支持安全表达式或 JSON 条件树。",
    "end": "勾选后，读完这句台词或本场景后结束剧情；结束时不能再设置跳转或选项。",
    "transition": "切换背景或场景时使用的动画效果，例如 fade（淡入）或 slide-left（从左侧滑入）。",
    "show": '填写要显示的立绘，例如：[{"id": "yuki", "image": "image/characters/yuki/normal.png", "position": "center"}]。',
    "hide": '填写要隐藏的角色立绘 ID，例如 ["yuki"]；填写 "all" 可隐藏全部立绘。',
    "set": '把剧情变量直接设为指定值，例如：{"route": "good"}。',
    "add": "把数字加到某个剧情变量上，例如好感度增加 1：{\"affection.yuki\": 1}。",
    "set_expr": '用安全表达式计算后设置变量，例如：{"score": "score + 1"}。',
    "add_expr": '用安全表达式算出数字并累加，例如：{"score": "bonus * 2"}。',
    "choice_text": "玩家在此处看到并选择的分支内容，例如：和雪乃一起回家。",
    "condition_mode": "选择用简单表达式，还是用 JSON 写一组条件。",
    "condition_editor": "简单示例：affection.yuki >= 3。可使用变量、比较、and/or/not 和括号。",
    "transition_duration": "动画持续时间，单位为秒；可以设置 0 到 5 秒。",
    "choices": "这些是玩家可以选择的剧情分支。选中左侧选项可编辑内容；在台词上右键可新增选项。",
}

RESOURCE_TOOLTIPS = {
    "background": FIELD_TOOLTIPS["background"],
    "bgm": FIELD_TOOLTIPS["bgm"],
    "voice": FIELD_TOOLTIPS["voice"],
    "se": FIELD_TOOLTIPS["se"],
}

SCENE_COMBO_TOOLTIPS = {
    "start": FIELD_TOOLTIPS["start"],
    "goto": FIELD_TOOLTIPS["goto"],
    "next": FIELD_TOOLTIPS["next"],
}


class WelcomeDialog(QDialog):
    """Non-modal first-run guide with a persistent opt-out setting."""

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("欢迎使用 EasyEngine 剧情编辑器")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumWidth(530)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(self)
        guide = QLabel(
            "<p>欢迎！这里是简单的三步操作指南：</p>"
            "<ol>"
            "<li><b>左侧</b>是剧情树，用来新建场景和台词。</li>"
            "<li><b>中间</b>是编辑区，这里填写台词和角色。</li>"
            "<li><b>右侧</b>是素材库，你只需要<b>把图片或音乐双击"
            "（或拖拽）</b>到中间对应的框里，就能自动分配资源！</li>"
            "</ol>"
            "<p>遇到不懂的词，把鼠标放上去会有提示哦！</p>"
        )
        guide.setObjectName("welcomeGuideText")
        guide.setTextFormat(Qt.TextFormat.RichText)
        guide.setWordWrap(True)
        layout.addWidget(guide)

        self.dont_show_checkbox = QCheckBox("不再提示")
        self.dont_show_checkbox.setObjectName("dontShowWelcomeGuide")
        self.dont_show_checkbox.setToolTip("勾选后，下次启动编辑器不再自动显示本教程。")
        self.dont_show_checkbox.setChecked(
            _setting_bool(settings, WELCOME_GUIDE_SUPPRESSED_KEY, False)
        )
        self.dont_show_checkbox.toggled.connect(self._save_preference)
        layout.addWidget(self.dont_show_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.clicked.connect(self.hide)
        buttons.rejected.connect(self.hide)
        layout.addWidget(buttons)

    def _save_preference(self, suppressed: bool) -> None:
        self.settings.setValue(WELCOME_GUIDE_SUPPRESSED_KEY, suppressed)
        self.settings.sync()


class SettingsDialog(QDialog):
    """Edit persistent editor preferences and apply them without restarting."""

    settingsApplied = Signal()

    def __init__(
        self,
        settings: QSettings,
        assets_directory: Path = ASSETS_DIR,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("偏好设置")
        self.setModal(True)
        self.setMinimumWidth(440)

        preferences = _read_preferences(settings)
        layout = QVBoxLayout(self)

        appearance = QGroupBox("外观设置")
        appearance_form = QFormLayout(appearance)
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("themeComboBox")
        self.theme_combo.addItem("浅色（Light）", "light")
        self.theme_combo.addItem("深色（Dark）", "dark")
        self.theme_combo.addItem("系统默认（System）", "system")
        theme_index = self.theme_combo.findData(preferences["theme"], USER_ROLE)
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        appearance_form.addRow("主题", self.theme_combo)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setObjectName("editorFontSize")
        self.font_size_spin.setRange(10, 24)
        self.font_size_spin.setValue(preferences["font_size"])
        self.font_size_spin.setSuffix(" pt")
        appearance_form.addRow("编辑器字体大小", self.font_size_spin)
        layout.addWidget(appearance)

        behavior = QGroupBox("行为设置")
        behavior_layout = QVBoxLayout(behavior)
        self.auto_save_checkbox = QCheckBox("切换剧情节点时自动保存")
        self.auto_save_checkbox.setObjectName("autoSave")
        self.auto_save_checkbox.setChecked(preferences["auto_save"])
        self.auto_save_checkbox.setToolTip(
            "已有保存位置时，切换左侧剧情节点会自动保存当前修改。"
        )
        behavior_layout.addWidget(self.auto_save_checkbox)

        self.open_last_script_checkbox = QCheckBox("启动时打开上次编辑的剧本")
        self.open_last_script_checkbox.setObjectName("openLastScript")
        self.open_last_script_checkbox.setChecked(preferences["open_last_script"])
        behavior_layout.addWidget(self.open_last_script_checkbox)
        layout.addWidget(behavior)

        paths = QGroupBox("路径设置")
        paths_form = QFormLayout(paths)
        assets_row = QWidget(paths)
        assets_layout = QHBoxLayout(assets_row)
        assets_layout.setContentsMargins(0, 0, 0, 0)
        configured_assets_directory = settings.value(
            ASSETS_DIRECTORY_SETTING_KEY,
            str(assets_directory),
        )
        self.assets_directory_edit = QLineEdit(
            str(_resolve_assets_directory(configured_assets_directory))
        )
        self.assets_directory_edit.setObjectName("assetsDirectory")
        self.assets_directory_edit.setToolTip("设置编辑器扫描图片、音频等素材的目录。")
        assets_layout.addWidget(self.assets_directory_edit, 1)
        self.browse_assets_button = QPushButton("浏览…")
        self.browse_assets_button.setObjectName("browseAssetsDirectory")
        self.browse_assets_button.clicked.connect(self._browse_assets_directory)
        assets_layout.addWidget(self.browse_assets_button)
        paths_form.addRow("默认资源目录（assets）", assets_row)
        layout.addWidget(paths)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        self.button_box.accepted.connect(self._accept_settings)
        self.button_box.rejected.connect(self.reject)
        apply_button = self.button_box.button(QDialogButtonBox.StandardButton.Apply)
        if apply_button is not None:
            apply_button.clicked.connect(
                lambda _checked=False: self._save_and_apply()
            )
        layout.addWidget(self.button_box)

    def _browse_assets_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择默认资源目录",
            self.assets_directory_edit.text(),
        )
        if directory:
            self.assets_directory_edit.setText(directory)

    def _save_and_apply(self) -> bool:
        assets_directory = _resolve_assets_directory(
            self.assets_directory_edit.text()
        )
        if not assets_directory.is_dir():
            QMessageBox.warning(
                self,
                "资源目录无效",
                f"请选择一个已存在的文件夹：\n{assets_directory}",
            )
            return False

        self.settings.setValue(
            THEME_SETTING_KEY,
            str(self.theme_combo.currentData(USER_ROLE)),
        )
        self.settings.setValue(FONT_SIZE_SETTING_KEY, self.font_size_spin.value())
        self.settings.setValue(
            AUTO_SAVE_SETTING_KEY,
            self.auto_save_checkbox.isChecked(),
        )
        self.settings.setValue(
            OPEN_LAST_SCRIPT_SETTING_KEY,
            self.open_last_script_checkbox.isChecked(),
        )
        self.settings.setValue(ASSETS_DIRECTORY_SETTING_KEY, str(assets_directory))
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            QMessageBox.critical(
                self,
                "设置保存失败",
                "无法写入编辑器设置，请检查设置文件的权限。",
            )
            return False
        self.settingsApplied.emit()
        return True

    def _accept_settings(self) -> None:
        if self._save_and_apply():
            self.accept()


class ResourceComboBox(QComboBox):
    """Editable resource picker which accepts drops from the asset browser."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setAcceptDrops(True)
        self.setToolTip("可从右侧资源浏览器拖入，也可输入相对 assets/ 的路径。")

    def set_resources(self, references: list[str], value: Any = UNSET) -> None:
        blocked = self.blockSignals(True)
        self.clear()
        self.addItem("（不设置）", UNSET_TOKEN)
        self.addItem("（清除资源）", CLEAR_TOKEN)
        for reference in references:
            self.addItem(reference, reference)
        self.set_value(value)
        self.blockSignals(blocked)

    def set_value(self, value: Any) -> None:
        if value is UNSET or value is None:
            self.setCurrentIndex(0)
            return
        if value == "":
            self.setCurrentIndex(1)
            return
        reference = str(value)
        index = self.findData(reference, USER_ROLE)
        if index < 0:
            self.addItem(reference, reference)
            index = self.count() - 1
        self.setCurrentIndex(index)

    def value(self) -> Any:
        text = self.currentText().strip()
        index = self.currentIndex()
        if index >= 0 and text == self.itemText(index):
            data = self.itemData(index, USER_ROLE)
            if data == UNSET_TOKEN:
                return UNSET
            if data == CLEAR_TOKEN:
                return ""
            return data
        return text if text else UNSET

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(ASSET_MIME_TYPE) or event.mimeData().hasText():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if mime.hasFormat(ASSET_MIME_TYPE):
            reference = bytes(mime.data(ASSET_MIME_TYPE)).decode("utf-8")
        elif mime.hasText():
            reference = mime.text().strip()
        else:
            super().dropEvent(event)
            return
        if reference:
            self.setEditText(reference)
            event.acceptProposedAction()


class ResourceTreeWidget(QTreeWidget):
    """A categorized tree that drags the relative asset reference as text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabel("资源浏览器")
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def mimeTypes(self) -> list[str]:
        return [ASSET_MIME_TYPE, "text/plain"]

    def mimeData(self, items: list[QTreeWidgetItem]) -> QMimeData:
        mime = QMimeData()
        if items:
            reference = items[0].data(0, USER_ROLE)
            if isinstance(reference, str) and reference:
                encoded = QByteArray(reference.encode("utf-8"))
                mime.setData(ASSET_MIME_TYPE, encoded)
                mime.setText(reference)
        return mime


class EditorWindow(QMainWindow):
    def __init__(
        self,
        story_path: str | Path | None = None,
        *,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings if settings is not None else _create_settings()
        preferences = _read_preferences(self.settings)
        self._theme = preferences["theme"]
        self._font_size = preferences["font_size"]
        self._auto_save = preferences["auto_save"]
        self._open_last_script = preferences["open_last_script"]
        self._assets_dir = preferences["assets_directory"]
        self._capture_default_appearance()
        self._apply_appearance()
        self.model = StoryModel()
        self._dirty = False
        self._active_ref = NodeRef("story")
        self._tree_items: dict[NodeRef, QTreeWidgetItem] = {}
        self._form_errors: dict[QWidget, str] = {}
        self._resource_fields: list[ResourceComboBox] = []
        self._active_resource_field: ResourceComboBox | None = None
        self._assets: dict[str, list[str]] = {}

        self.setWindowTitle(f"EasyEngine 剧情编辑器 | by {__author__}")
        self.resize(1440, 900)
        self._build_ui()
        self._build_actions()
        self._refresh_resources(rebuild_form=False)
        self._refresh_tree(NodeRef("story"))
        self._welcome_dialog = WelcomeDialog(self.settings, self)
        if story_path is not None:
            self._open_path(story_path)
        elif self._open_last_script:
            last_script = _setting_text(self.settings, LAST_SCRIPT_SETTING_KEY)
            if last_script:
                last_script_path = Path(last_script).expanduser()
                if last_script_path.is_file():
                    self._open_path(last_script_path)
                else:
                    self.statusBar().showMessage(
                        f"未找到上次编辑的剧本：{last_script_path}"
                    )
        QTimer.singleShot(0, self._show_welcome_guide_on_first_run)

    def _capture_default_appearance(self) -> None:
        global _DEFAULT_QT_APPEARANCE
        application = QApplication.instance()
        if application is None or _DEFAULT_QT_APPEARANCE is not None:
            return
        _DEFAULT_QT_APPEARANCE = {
            "style": application.style().objectName(),
            "palette": QPalette(application.palette()),
            "stylesheet": application.styleSheet(),
            "font": QFont(application.font()),
        }

    def _apply_appearance(self) -> None:
        application = QApplication.instance()
        if application is None or _DEFAULT_QT_APPEARANCE is None:
            return

        if self._theme == "system":
            application.setStyle(_DEFAULT_QT_APPEARANCE["style"])
            application.setPalette(_DEFAULT_QT_APPEARANCE["palette"])
            application.setStyleSheet(_DEFAULT_QT_APPEARANCE["stylesheet"])
        else:
            application.setStyle("Fusion")
            palette = application.style().standardPalette()
            application.setStyleSheet("")
            if self._theme == "dark":
                dark_colors = {
                    QPalette.ColorRole.Window: "#202124",
                    QPalette.ColorRole.WindowText: "#e8eaed",
                    QPalette.ColorRole.Base: "#292a2d",
                    QPalette.ColorRole.AlternateBase: "#34363a",
                    QPalette.ColorRole.ToolTipBase: "#f8f9fa",
                    QPalette.ColorRole.ToolTipText: "#202124",
                    QPalette.ColorRole.Text: "#e8eaed",
                    QPalette.ColorRole.Button: "#3c4043",
                    QPalette.ColorRole.ButtonText: "#e8eaed",
                    QPalette.ColorRole.BrightText: "#ff6b6b",
                    QPalette.ColorRole.Link: "#8ab4f8",
                    QPalette.ColorRole.Highlight: "#8ab4f8",
                    QPalette.ColorRole.HighlightedText: "#202124",
                    QPalette.ColorRole.PlaceholderText: "#9aa0a6",
                }
                for role, color in dark_colors.items():
                    palette.setColor(role, QColor(color))
                palette.setColor(
                    QPalette.ColorGroup.Disabled,
                    QPalette.ColorRole.Text,
                    QColor("#8a8d91"),
                )
                palette.setColor(
                    QPalette.ColorGroup.Disabled,
                    QPalette.ColorRole.ButtonText,
                    QColor("#8a8d91"),
                )
            application.setPalette(palette)

        font = QFont(_DEFAULT_QT_APPEARANCE["font"])
        font.setPointSize(self._font_size)
        application.setFont(font)
        self.setFont(font)

    def _apply_user_preferences(self) -> None:
        preferences = _read_preferences(self.settings)
        self._theme = preferences["theme"]
        self._font_size = preferences["font_size"]
        self._auto_save = preferences["auto_save"]
        self._open_last_script = preferences["open_last_script"]
        assets_directory = preferences["assets_directory"]
        self._apply_appearance()
        if assets_directory != self._assets_dir:
            self._assets_dir = assets_directory
            self._refresh_resources()

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.story_tree = QTreeWidget(splitter)
        self.story_tree.setHeaderLabel("剧情结构")
        self.story_tree.setMinimumWidth(230)
        self.story_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.story_tree.currentItemChanged.connect(self._on_selection_changed)
        self.story_tree.customContextMenuRequested.connect(self._show_tree_menu)

        self.form_scroll = QScrollArea(splitter)
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setMinimumWidth(430)
        self.form_panel = QWidget()
        self.form_layout = QFormLayout(self.form_panel)
        self.form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.form_scroll.setWidget(self.form_panel)

        right_panel = QWidget(splitter)
        right_layout = QVBoxLayout(right_panel)
        asset_header = QHBoxLayout()
        asset_header.addWidget(QLabel("资源浏览器"))
        refresh_button = QAction("刷新", self)
        refresh_button.triggered.connect(lambda _checked=False: self._refresh_resources())
        self._refresh_assets_action = refresh_button
        asset_header.addStretch(1)
        right_layout.addLayout(asset_header)
        self.asset_tree = ResourceTreeWidget(right_panel)
        self.asset_tree.itemDoubleClicked.connect(self._on_asset_double_click)
        right_layout.addWidget(self.asset_tree)
        asset_help = QLabel("双击或拖拽资源到当前资源输入框。路径相对于 assets/。")
        asset_help.setWordWrap(True)
        right_layout.addWidget(asset_help)

        splitter.addWidget(self.story_tree)
        splitter.addWidget(self.form_scroll)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([280, 760, 320])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("就绪")

    def _build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        new_action = self._action("新建", QKeySequence.StandardKey.New, self.new_story)
        open_action = self._action("打开…", QKeySequence.StandardKey.Open, self.open_story)
        save_action = self._action("保存", QKeySequence.StandardKey.Save, self.save_story)
        save_as_action = self._action(
            "另存为…", QKeySequence.StandardKey.SaveAs, self.save_story_as
        )
        test_action = self._action("测试剧本", "F6", self.test_story)
        quit_action = self._action("退出", QKeySequence.StandardKey.Quit, self.close)
        for action in (new_action, open_action, save_action, save_as_action):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(test_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        tools_menu = self.menuBar().addMenu("工具")
        preferences_action = QAction("偏好设置...", self)
        preferences_action.setShortcut(QKeySequence("Ctrl+,"))
        preferences_action.triggered.connect(
            lambda _checked=False: self.show_settings_dialog()
        )
        tools_menu.addAction(preferences_action)
        self._preferences_action = preferences_action

        help_menu = self.menuBar().addMenu("帮助")
        tutorial_action = QAction("新手教程", self)
        tutorial_action.triggered.connect(
            lambda _checked=False: self.show_welcome_guide()
        )
        help_menu.addAction(tutorial_action)
        self._tutorial_action = tutorial_action
        about_action = QAction("关于 EasyEngine", self)
        about_action.triggered.connect(
            lambda _checked=False: self.show_about_dialog()
        )
        help_menu.addAction(about_action)
        self._about_action = about_action

        toolbar = QToolBar("剧本操作", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for action in (new_action, open_action, save_action, test_action):
            toolbar.addAction(action)
        toolbar.addAction(self._refresh_assets_action)

    def _action(
        self,
        label: str,
        shortcut: QKeySequence.StandardKey | str,
        callback: Callable[[], Any],
    ) -> QAction:
        action = QAction(label, self)
        action.setShortcut(shortcut)
        action.triggered.connect(lambda _checked=False: callback())
        return action

    def _show_welcome_guide_on_first_run(self) -> None:
        if not _setting_bool(self.settings, WELCOME_GUIDE_SUPPRESSED_KEY, False):
            self.show_welcome_guide()

    def show_welcome_guide(self) -> None:
        self._welcome_dialog.dont_show_checkbox.setChecked(
            _setting_bool(self.settings, WELCOME_GUIDE_SUPPRESSED_KEY, False)
        )
        self._welcome_dialog.show()
        self._welcome_dialog.raise_()
        self._welcome_dialog.activateWindow()

    def show_settings_dialog(self) -> None:
        dialog = SettingsDialog(self.settings, self._assets_dir, self)
        dialog.settingsApplied.connect(self._apply_user_preferences)
        dialog.exec()

    def show_about_dialog(self) -> None:
        QMessageBox.about(
            self,
            "关于 EasyEngine",
            (
                "<div style='text-align:center'>"
                "<h1>◆ EasyEngine ◆</h1>"
                "<p>极简的 Python Galgame 引擎</p>"
                "</div>"
                f"<p><b>版本：</b>{__version__}<br>"
                f"<b>作者：</b>{__author__}<br>"
                f"<b>GitHub：</b><a href='{__github__}'>{__github__}</a></p>"
                "<p><b>Powered by EasyEngine "
                f"(作者Github：{__github_profile__})</b></p>"
                "<p>本软件按 MIT License 开源，官方版本可免费获取。"
                "MIT 许可允许再分发和商业销售，但必须保留原版权声明和许可证。"
                "如付费副本未遵守许可证，请向销售平台申请退款或举报。</p>"
            ),
        )

    def _refresh_resources(self, *, rebuild_form: bool = True) -> None:
        try:
            grouped = scan_assets(self._assets_dir, group_by="type")
        except (FileNotFoundError, OSError, ValueError) as exc:
            self._assets = {category: [] for category in RESOURCE_CATEGORIES}
            self.statusBar().showMessage(f"资源扫描失败：{exc}")
        else:
            self._assets = {
                category: [
                    path.relative_to(self._assets_dir).as_posix()
                    for path in grouped.get(category, [])
                ]
                for category in RESOURCE_CATEGORIES
            }
            count = sum(len(paths) for paths in self._assets.values())
            self.statusBar().showMessage(f"已扫描 {count} 个资源")

        self.asset_tree.clear()
        for category in RESOURCE_CATEGORIES:
            category_item = QTreeWidgetItem([category])
            category_item.setFlags(
                category_item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled
            )
            self.asset_tree.addTopLevelItem(category_item)
            for reference in self._assets[category]:
                item = QTreeWidgetItem([reference])
                item.setData(0, USER_ROLE, reference)
                item.setToolTip(0, str(self._assets_dir / reference))
                category_item.addChild(item)
            category_item.setExpanded(True)

        if rebuild_form and not self._form_errors:
            self._rebuild_form(self._active_ref)

    def _refresh_tree(self, selected: NodeRef | None = None) -> None:
        selected = selected or NodeRef("story")
        was_blocked = self.story_tree.blockSignals(True)
        try:
            self.story_tree.clear()
            self._tree_items.clear()
            title = self.model.data.get("title", "剧本")
            root = QTreeWidgetItem([str(title)])
            root.setData(0, USER_ROLE, NodeRef("story"))
            self.story_tree.addTopLevelItem(root)
            self._tree_items[NodeRef("story")] = root

            scenes = self.model.data.get("scenes")
            if isinstance(scenes, dict):
                for scene_id, raw_scene in scenes.items():
                    scene_key = str(scene_id)
                    scene_ref = NodeRef("scene", scene_id=scene_key)
                    scene_item = QTreeWidgetItem([f"场景：{scene_key}"])
                    scene_item.setData(0, USER_ROLE, scene_ref)
                    root.addChild(scene_item)
                    self._tree_items[scene_ref] = scene_item
                    if not isinstance(raw_scene, dict):
                        continue
                    lines = raw_scene.get("lines")
                    if not isinstance(lines, list):
                        continue
                    for line_index, raw_line in enumerate(lines):
                        line_ref = NodeRef(
                            "line",
                            scene_id=scene_key,
                            line_index=line_index,
                        )
                        line_item = QTreeWidgetItem(
                            [self._line_label(raw_line, line_index)]
                        )
                        line_item.setData(0, USER_ROLE, line_ref)
                        scene_item.addChild(line_item)
                        self._tree_items[line_ref] = line_item
                        if not isinstance(raw_line, dict):
                            continue
                        choices = raw_line.get("choices")
                        if not isinstance(choices, list):
                            continue
                        for choice_index, raw_choice in enumerate(choices):
                            choice_ref = NodeRef(
                                "choice",
                                scene_id=scene_key,
                                line_index=line_index,
                                choice_index=choice_index,
                            )
                            choice_item = QTreeWidgetItem(
                                [self._choice_label(raw_choice, choice_index)]
                            )
                            choice_item.setData(0, USER_ROLE, choice_ref)
                            line_item.addChild(choice_item)
                            self._tree_items[choice_ref] = choice_item

            root.setExpanded(True)
            for item in self._tree_items.values():
                item.setExpanded(True)
            item = self._tree_items.get(selected, root)
            self.story_tree.setCurrentItem(item)
        finally:
            self.story_tree.blockSignals(was_blocked)
        item = self._tree_items.get(selected, root)
        self._on_selection_changed(item, None)

    @staticmethod
    def _line_label(line: Any, index: int) -> str:
        if not isinstance(line, dict):
            return f"台词 {index + 1}（无效 JSON）"
        speaker = line.get("speaker")
        text = str(line.get("text", "")).replace("\n", " ").strip()
        prefix = f"{speaker}：" if speaker else ""
        excerpt = text[:36] + ("…" if len(text) > 36 else "")
        return f"台词 {index + 1}：{prefix}{excerpt or '（空）'}"

    @staticmethod
    def _choice_label(choice: Any, index: int) -> str:
        if not isinstance(choice, dict):
            return f"选项 {index + 1}（无效 JSON）"
        text = str(choice.get("text", "")).replace("\n", " ").strip()
        excerpt = text[:36] + ("…" if len(text) > 36 else "")
        return f"选项 {index + 1}：{excerpt or '（空）'}"

    def _on_selection_changed(
        self,
        current: QTreeWidgetItem | None,
        previous: QTreeWidgetItem | None,
    ) -> None:
        if self._form_errors:
            if previous is not None:
                blocked = self.story_tree.blockSignals(True)
                self.story_tree.setCurrentItem(previous)
                self.story_tree.blockSignals(blocked)
            self._show_form_errors()
            return
        if previous is not None and self._auto_save and self._dirty:
            if self.model.path is None:
                self.statusBar().showMessage(
                    "自动保存尚未执行：请先手动保存一次以选择剧本文件位置。"
                )
            elif not self._save_to(self.model.path):
                blocked = self.story_tree.blockSignals(True)
                self.story_tree.setCurrentItem(previous)
                self.story_tree.blockSignals(blocked)
                return
        ref = current.data(0, USER_ROLE) if current is not None else None
        if not isinstance(ref, NodeRef):
            ref = NodeRef("story")
        self._active_ref = ref
        self._rebuild_form(ref)

    def _rebuild_form(self, ref: NodeRef) -> None:
        old_panel = self.form_scroll.takeWidget()
        if old_panel is not None:
            old_panel.deleteLater()
        self.form_panel = QWidget()
        self.form_layout = QFormLayout(self.form_panel)
        self.form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.form_scroll.setWidget(self.form_panel)
        self._form_errors.clear()
        self._resource_fields.clear()
        self._active_resource_field = None

        try:
            target = self.model.target_for(ref)
        except EditorModelError:
            ref = NodeRef("story")
            self._active_ref = ref
            target = self.model.data

        if ref.kind == "story":
            self._build_story_form(target)
        elif ref.kind == "scene":
            self._build_scene_form(ref, target)
        elif ref.kind == "line":
            self._build_line_form(ref, target)
        elif ref.kind == "choice":
            self._build_choice_form(ref, target)

    def _build_story_form(self, target: dict[str, Any]) -> None:
        self._add_line_edit(
            "剧本标题",
            NodeRef("story"),
            "title",
            target.get("title", ""),
        )
        self._add_scene_combo(
            "剧情起始场景",
            NodeRef("story"),
            "start",
            target.get("start", UNSET),
            required=True,
        )
        self._add_json_editor(
            "角色信息",
            NodeRef("story"),
            "characters",
            target.get("characters", {}),
            expected=(dict,),
        )
        self._add_json_editor(
            "初始剧情变量",
            NodeRef("story"),
            "vars",
            target.get("vars", {}),
            expected=(dict,),
        )
        self._add_json_editor(
            "CG 鉴赏图片列表",
            NodeRef("story"),
            "gallery",
            target.get("gallery", []),
            expected=(list,),
        )
        self.form_layout.addRow(
            QLabel("使用右键菜单创建场景、台词和选项。复杂字段以标准 JSON 编辑。")
        )

    def _build_scene_form(self, ref: NodeRef, target: dict[str, Any]) -> None:
        self.form_layout.addRow("场景编号", QLabel(ref.scene_id or ""))
        self._add_resource_field(
            "切换背景图",
            ref,
            "background",
            target.get("background", UNSET),
            "image",
        )
        self._add_resource_field(
            "背景音乐",
            ref,
            "bgm",
            target.get("bgm", UNSET),
            "audio",
        )
        self._add_transition_field(ref, target.get("transition", UNSET))
        self._add_scene_combo(
            "场景结束后进入",
            ref,
            "next",
            target.get("next", UNSET),
            can_change=lambda value: self._allow_scene_next(ref, value),
        )
        self._add_bool_field(
            "结束本场景",
            ref,
            "end",
            target.get("end", False),
        )
        self.form_layout.addRow(QLabel("台词请在左侧选中或通过右键菜单管理。"))

    def _build_line_form(self, ref: NodeRef, target: dict[str, Any]) -> None:
        self._add_speaker_field(ref, target.get("speaker", UNSET))
        self._add_text_edit("台词内容", ref, "text", target.get("text", ""))
        self._add_resource_field(
            "切换背景图", ref, "background", target.get("background", UNSET), "image"
        )
        self._add_resource_field(
            "背景音乐", ref, "bgm", target.get("bgm", UNSET), "audio"
        )
        self._add_resource_field(
            "角色语音", ref, "voice", target.get("voice", UNSET), "audio"
        )
        self._add_resource_field(
            "播放音效", ref, "se", target.get("se", UNSET), "audio"
        )
        self._add_transition_field(ref, target.get("transition", UNSET))
        self._add_scene_combo(
            "台词后跳转场景",
            ref,
            "goto",
            target.get("goto", UNSET),
            can_change=lambda value: self._allow_line_goto(ref, value),
        )
        self._add_bool_field(
            "结束剧情",
            ref,
            "end",
            target.get("end", False),
        )
        self._add_json_editor(
            "显示角色立绘",
            ref,
            "show",
            target.get("show", []),
            expected=(list,),
        )
        self._add_json_editor(
            "隐藏角色立绘",
            ref,
            "hide",
            target.get("hide", []),
            expected=(str, list),
        )
        self._add_change_fields(ref, target)
        choices_hint = QLabel("玩家选项：在左侧台词上右键添加或管理分支。")
        choices_hint.setToolTip(FIELD_TOOLTIPS["choices"])
        self.form_layout.addRow(choices_hint)
        if target.get("choices"):
            self.form_layout.addRow(
                QLabel("此台词包含玩家选项，不能同时设置跳转场景或结束剧情。")
            )

    def _build_choice_form(self, ref: NodeRef, target: dict[str, Any]) -> None:
        choice_text = self._add_line_edit(
            "选项内容", ref, "text", target.get("text", "")
        )
        choice_text.setToolTip(FIELD_TOOLTIPS["choice_text"])
        self._add_scene_combo(
            "选择后跳转场景",
            ref,
            "goto",
            target.get("goto", UNSET),
        )
        self._add_require_field(ref, target.get("require", UNSET))
        self._add_change_fields(ref, target)

    def _add_line_edit(
        self,
        label: str,
        ref: NodeRef,
        key: str,
        value: Any,
    ) -> QLineEdit:
        widget = QLineEdit("" if value is UNSET or value is None else str(value))
        widget.setToolTip(FIELD_TOOLTIPS.get(key, "在此填写对应内容。"))
        widget.textChanged.connect(
            lambda text, node=ref, field=key: self._set_field(node, field, text)
        )
        self.form_layout.addRow(label, widget)
        return widget

    def _add_text_edit(
        self,
        label: str,
        ref: NodeRef,
        key: str,
        value: Any,
    ) -> QPlainTextEdit:
        widget = QPlainTextEdit("" if value is UNSET or value is None else str(value))
        widget.setMinimumHeight(110)
        widget.setToolTip(FIELD_TOOLTIPS.get(key, "在此填写对应内容。"))
        widget.textChanged.connect(
            lambda node=ref, field=key, editor=widget: self._set_field(
                node, field, editor.toPlainText()
            )
        )
        self.form_layout.addRow(label, widget)
        return widget

    def _add_resource_field(
        self,
        label: str,
        ref: NodeRef,
        key: str,
        value: Any,
        category: str,
    ) -> ResourceComboBox:
        widget = ResourceComboBox()
        tooltip = RESOURCE_TOOLTIPS.get(key, "从右侧素材库选择资源。")
        widget.setToolTip(tooltip)
        widget.set_resources(self._assets.get(category, []), value)
        if widget.lineEdit() is not None:
            widget.lineEdit().setToolTip(tooltip)
        widget.currentTextChanged.connect(
            lambda _text, node=ref, field=key, control=widget: self._set_field(
                node, field, control.value()
            )
        )
        widget.installEventFilter(self)
        if widget.lineEdit() is not None:
            widget.lineEdit().installEventFilter(self)
        self._resource_fields.append(widget)
        self.form_layout.addRow(label, widget)
        return widget

    def _add_scene_combo(
        self,
        label: str,
        ref: NodeRef,
        key: str,
        value: Any,
        *,
        required: bool = False,
        can_change: Callable[[Any], bool] | None = None,
    ) -> QComboBox:
        widget = QComboBox()
        widget.setToolTip(SCENE_COMBO_TOOLTIPS.get(key, "从列表中选择场景。"))
        widget.setEditable(False)
        if not required:
            widget.addItem("（不跳转）", UNSET_TOKEN)
        for scene_id in self.model.scene_ids:
            widget.addItem(scene_id, scene_id)
        if required and not self.model.scene_ids:
            widget.addItem("（请先创建场景）", UNSET_TOKEN)
        if value is UNSET or value is None:
            if required and self.model.scene_ids:
                widget.setCurrentIndex(0)
            else:
                widget.setCurrentIndex(0)
        else:
            comparable_value = value if isinstance(value, str) else str(value)
            index = widget.findData(comparable_value, USER_ROLE)
            if index < 0:
                widget.addItem(f"缺失：{comparable_value}", comparable_value)
                index = widget.count() - 1
            widget.setCurrentIndex(index)

        def changed(index: int) -> None:
            selected = widget.itemData(index, USER_ROLE)
            new_value = UNSET if selected == UNSET_TOKEN else selected
            if can_change is not None and not can_change(new_value):
                blocked = widget.blockSignals(True)
                self._set_combo_value(widget, self.model.target_for(ref).get(key, UNSET))
                widget.blockSignals(blocked)
                return
            self._set_field(ref, key, new_value)

        widget.currentIndexChanged.connect(changed)
        self.form_layout.addRow(label, widget)
        return widget

    def _add_speaker_field(self, ref: NodeRef, value: Any) -> QComboBox:
        widget = QComboBox()
        widget.setToolTip(FIELD_TOOLTIPS["speaker"])
        widget.setEditable(True)
        widget.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        widget.addItem("（旁白）", UNSET_TOKEN)
        characters = self.model.data.get("characters", {})
        if isinstance(characters, dict):
            for character_id, character in characters.items():
                if isinstance(character, str):
                    name = character
                elif isinstance(character, dict):
                    name = character.get("name", character_id)
                else:
                    name = character_id
                widget.addItem(f"{character_id} — {name}", str(character_id))
        if value is UNSET or value is None:
            widget.setCurrentIndex(0)
        else:
            identifier = str(value)
            index = widget.findData(identifier, USER_ROLE)
            if index < 0:
                widget.addItem(identifier, identifier)
                index = widget.count() - 1
            widget.setCurrentIndex(index)
        if widget.lineEdit() is not None:
            widget.lineEdit().setToolTip(FIELD_TOOLTIPS["speaker"])

        def changed(_text: str) -> None:
            index = widget.currentIndex()
            if index >= 0 and widget.currentText() == widget.itemText(index):
                selected = widget.itemData(index, USER_ROLE)
                new_value = UNSET if selected == UNSET_TOKEN else selected
            else:
                text = widget.currentText().strip()
                new_value = text if text else UNSET
            self._set_field(ref, "speaker", new_value)

        widget.currentTextChanged.connect(changed)
        self.form_layout.addRow("说话人", widget)
        return widget

    def _add_bool_field(
        self,
        label: str,
        ref: NodeRef,
        key: str,
        value: Any,
    ) -> QCheckBox:
        widget = QCheckBox()
        widget.setToolTip(FIELD_TOOLTIPS.get(key, "勾选以启用此设置。"))
        widget.setChecked(value is True)
        widget.toggled.connect(
            lambda checked, node=ref, field=key, control=widget: self._set_boolean(
                node, field, checked, control
            )
        )
        self.form_layout.addRow(label, widget)
        return widget

    def _set_boolean(
        self,
        ref: NodeRef,
        key: str,
        checked: bool,
        control: QCheckBox,
    ) -> None:
        target = self.model.target_for(ref)
        if checked and key == "end":
            if ref.kind == "scene" and target.get("next"):
                self._revert_checkbox(control)
                QMessageBox.warning(
                    self,
                    "字段冲突",
                    "场景不能同时设置后续场景和结束标记。",
                )
                return
            if ref.kind == "line" and (target.get("goto") or target.get("choices")):
                self._revert_checkbox(control)
                QMessageBox.warning(
                    self,
                    "字段冲突",
                    "台词不能同时设置结束剧情、跳转场景或玩家选项。",
                )
                return
        self.model.set_field(ref, key, checked if checked else UNSET)
        self._mark_dirty(ref)

    @staticmethod
    def _revert_checkbox(control: QCheckBox) -> None:
        blocked = control.blockSignals(True)
        control.setChecked(False)
        control.blockSignals(blocked)

    def _allow_scene_next(self, ref: NodeRef, value: Any) -> bool:
        target = self.model.target_for(ref)
        if value is not UNSET and target.get("end") is True:
            QMessageBox.warning(
                self,
                "字段冲突",
                "场景不能同时设置后续场景和结束标记。",
            )
            return False
        return True

    def _allow_line_goto(self, ref: NodeRef, value: Any) -> bool:
        target = self.model.target_for(ref)
        if value is not UNSET and (target.get("end") is True or target.get("choices")):
            QMessageBox.warning(
                self,
                "字段冲突",
                "台词不能同时设置跳转场景与玩家选项或结束剧情。",
            )
            return False
        return True

    @staticmethod
    def _set_combo_value(widget: QComboBox, value: Any) -> None:
        if value is UNSET or value is None:
            token = UNSET_TOKEN
            index = widget.findData(token, USER_ROLE)
            if index >= 0:
                widget.setCurrentIndex(index)
            return
        index = widget.findData(value, USER_ROLE)
        if index >= 0:
            widget.setCurrentIndex(index)

    def _add_json_editor(
        self,
        label: str,
        ref: NodeRef,
        key: str,
        value: Any,
        *,
        expected: tuple[type[Any], ...],
    ) -> QPlainTextEdit:
        widget = QPlainTextEdit()
        widget.setMinimumHeight(92)
        widget.setToolTip(FIELD_TOOLTIPS.get(key, "在此填写 JSON 内容。"))
        try:
            content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        except (TypeError, ValueError):
            content = ""
        widget.setPlainText(content)

        def changed(node: NodeRef = ref, field: str = key, control: QPlainTextEdit = widget) -> None:
            text = control.toPlainText()
            if not text.strip():
                self.model.set_field(node, field, UNSET)
                self._clear_form_error(control)
                self._mark_dirty(node)
                return
            try:
                parsed = json.loads(text, parse_constant=_reject_json_constant)
                if not isinstance(parsed, expected):
                    names = " / ".join(item.__name__ for item in expected)
                    raise ValueError(f"{label} 必须是 {names}。")
            except (json.JSONDecodeError, ValueError) as exc:
                self._set_form_error(control, f"{label} JSON 无效：{exc}")
                return
            self.model.set_field(node, field, parsed)
            self._clear_form_error(control)
            self._mark_dirty(node)

        widget.textChanged.connect(changed)
        self.form_layout.addRow(label, widget)
        return widget

    def _add_change_fields(self, ref: NodeRef, target: dict[str, Any]) -> None:
        change_labels = {
            "set": "直接设置变量",
            "add": "增加变量数值",
            "set_expr": "用表达式设置变量",
            "add_expr": "用表达式增加变量",
        }
        for key, label in change_labels.items():
            self._add_json_editor(label, ref, key, target.get(key, {}), expected=(dict,))

    def _add_require_field(self, ref: NodeRef, value: Any) -> None:
        mode = QComboBox()
        mode.setToolTip(FIELD_TOOLTIPS["condition_mode"])
        mode.addItem("安全表达式", "expression")
        mode.addItem("JSON 条件树", "json")
        initial_mode = "json" if isinstance(value, (dict, list)) else "expression"
        mode.setCurrentIndex(1 if initial_mode == "json" else 0)
        editor = QPlainTextEdit()
        editor.setMinimumHeight(115)
        editor.setToolTip(FIELD_TOOLTIPS["condition_editor"])
        if value is not UNSET and value is not None:
            if initial_mode == "json":
                try:
                    editor.setPlainText(
                        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
                    )
                except (TypeError, ValueError):
                    editor.setPlainText("")
            elif isinstance(value, str):
                editor.setPlainText(value)

        previous_mode = initial_mode

        def apply_condition() -> None:
            text = editor.toPlainText().strip()
            selected_mode = str(mode.currentData(USER_ROLE))
            if not text:
                self.model.set_field(ref, "require", UNSET)
                self._clear_form_error(editor)
                self._mark_dirty(ref)
                return
            if selected_mode == "expression":
                self.model.set_field(ref, "require", text)
                self._clear_form_error(editor)
                self._mark_dirty(ref)
                return
            try:
                condition = json.loads(text, parse_constant=_reject_json_constant)
                if not isinstance(condition, (dict, list)):
                    raise ValueError("JSON 条件必须是对象或数组。")
            except (json.JSONDecodeError, ValueError) as exc:
                self._set_form_error(editor, f"选项条件 JSON 无效：{exc}")
                return
            self.model.set_field(ref, "require", condition)
            self._clear_form_error(editor)
            self._mark_dirty(ref)

        def mode_changed(index: int) -> None:
            nonlocal previous_mode
            new_mode = str(mode.itemData(index, USER_ROLE))
            if new_mode == previous_mode:
                return
            if editor in self._form_errors:
                blocked = mode.blockSignals(True)
                mode.setCurrentIndex(0 if previous_mode == "expression" else 1)
                mode.blockSignals(blocked)
                self._show_form_errors()
                return
            current = self.model.target_for(ref).get("require", UNSET)
            compatible = (
                current is UNSET
                or current is None
                or (
                    new_mode == "expression"
                    and isinstance(current, str)
                )
                or (
                    new_mode == "json"
                    and isinstance(current, (dict, list))
                )
            )
            if not compatible:
                self.model.set_field(ref, "require", UNSET)
                self._mark_dirty(ref)
                self.statusBar().showMessage(
                    "编辑模式已切换，原有选项出现条件已清除。"
                )
            editor.blockSignals(True)
            if new_mode == "expression" and isinstance(current, str):
                editor.setPlainText(current)
            elif new_mode == "json" and isinstance(current, (dict, list)):
                editor.setPlainText(
                    json.dumps(current, ensure_ascii=False, indent=2, allow_nan=False)
                )
            else:
                editor.setPlainText("")
            editor.blockSignals(False)
            previous_mode = new_mode

        editor.textChanged.connect(apply_condition)
        mode.currentIndexChanged.connect(mode_changed)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(mode)
        layout.addWidget(editor)
        layout.addWidget(
            QLabel("切换条件编辑模式会清除无法转换的旧条件；保存或测试时会由引擎校验。")
        )
        self.form_layout.addRow("选项出现条件", container)

    def _add_transition_field(self, ref: NodeRef, value: Any) -> None:
        kind = QComboBox()
        kind.setToolTip(FIELD_TOOLTIPS["transition"])
        kind.addItem("（默认转场）", UNSET_TOKEN)
        for label, transition_type in TRANSITIONS:
            kind.addItem(label, transition_type)
        duration_value = 0.32
        transition_type: Any = UNSET
        if isinstance(value, str):
            transition_type = value
        elif isinstance(value, dict):
            transition_type = value.get("type", UNSET)
            duration_value = value.get("duration", 0.32)
        elif value is not UNSET and value is not None:
            transition_type = value
        if transition_type is not UNSET and not isinstance(transition_type, str):
            transition_type = str(transition_type)
        if transition_type is UNSET or transition_type is None:
            kind.setCurrentIndex(0)
        else:
            index = kind.findData(transition_type, USER_ROLE)
            if index < 0:
                kind.addItem(f"无效：{transition_type}", transition_type)
                index = kind.count() - 1
            kind.setCurrentIndex(index)

        duration = QDoubleSpinBox()
        duration.setToolTip(FIELD_TOOLTIPS["transition_duration"])
        duration.lineEdit().setToolTip(FIELD_TOOLTIPS["transition_duration"])
        duration.setRange(0.0, 5.0)
        duration.setSingleStep(0.05)
        duration.setDecimals(2)
        if isinstance(duration_value, (int, float)) and not isinstance(duration_value, bool):
            duration.setValue(float(duration_value))
        else:
            duration.setValue(0.32)
        duration.setSuffix(" 秒")
        duration.setEnabled(kind.currentData(USER_ROLE) != UNSET_TOKEN)

        def update_transition(_value: Any = None) -> None:
            selected = kind.currentData(USER_ROLE)
            duration.setEnabled(selected != UNSET_TOKEN)
            if selected == UNSET_TOKEN:
                transition_value: Any = UNSET
            else:
                transition_value = {
                    "type": selected,
                    "duration": duration.value(),
                }
            self.model.set_field(ref, "transition", transition_value)
            self._mark_dirty(ref)

        kind.currentIndexChanged.connect(update_transition)
        duration.valueChanged.connect(update_transition)
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(kind, 1)
        layout.addWidget(duration)
        self.form_layout.addRow("特效转场", container)

    def _set_field(self, ref: NodeRef, key: str, value: Any) -> None:
        try:
            self.model.set_field(ref, key, value)
        except EditorModelError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self._mark_dirty(ref)

    def _mark_dirty(self, ref: NodeRef) -> None:
        self._dirty = True
        self._update_tree_label(ref)
        self._update_window_title()

    def _update_tree_label(self, ref: NodeRef) -> None:
        if ref.kind == "story":
            root = self._tree_items.get(NodeRef("story"))
            if root is not None:
                root.setText(0, str(self.model.data.get("title", "剧本")))
            return
        item = self._tree_items.get(ref)
        if item is None:
            return
        if ref.kind == "line":
            raw_line = self.model.get_line(ref.scene_id or "", ref.line_index or 0)
            item.setText(0, self._line_label(raw_line, ref.line_index or 0))
        elif ref.kind == "choice":
            raw_choice = self.model.get_choice(
                ref.scene_id or "",
                ref.line_index or 0,
                ref.choice_index or 0,
            )
            item.setText(0, self._choice_label(raw_choice, ref.choice_index or 0))

    def _set_form_error(self, widget: QWidget, message: str) -> None:
        self._form_errors[widget] = message
        self.statusBar().showMessage(message)

    def _clear_form_error(self, widget: QWidget) -> None:
        self._form_errors.pop(widget, None)
        if not self._form_errors:
            self.statusBar().showMessage("JSON 字段有效")

    def _show_form_errors(self) -> bool:
        if not self._form_errors:
            return False
        details = "\n".join(self._form_errors.values())
        QMessageBox.warning(
            self,
            "请先修正编辑内容",
            f"当前表单有尚未完成的 JSON 内容，修正后才能继续：\n\n{details}",
        )
        return True

    def _on_asset_double_click(
        self,
        item: QTreeWidgetItem,
        _column: int,
    ) -> None:
        reference = item.data(0, USER_ROLE)
        if isinstance(reference, str):
            self._assign_asset(reference)

    def _assign_asset(self, reference: str) -> None:
        widget = self._active_resource_field
        if widget is None:
            self.statusBar().showMessage("请先选中一个资源输入框，再指定资源。")
            return
        widget.setEditText(reference)

    def eventFilter(self, watched: Any, event: QEvent) -> bool:
        if isinstance(watched, ResourceComboBox) and event.type() == QEvent.Type.FocusIn:
            self._active_resource_field = watched
        elif isinstance(watched, QLineEdit) and event.type() == QEvent.Type.FocusIn:
            parent = watched.parentWidget()
            if isinstance(parent, ResourceComboBox):
                self._active_resource_field = parent
        return super().eventFilter(watched, event)

    def _show_tree_menu(self, position: Any) -> None:
        item = self.story_tree.itemAt(position)
        if item is None or self._show_form_errors():
            return
        self.story_tree.setCurrentItem(item)
        ref = item.data(0, USER_ROLE)
        if not isinstance(ref, NodeRef) or self._form_errors:
            return

        menu = QMenu(self)
        if ref.kind == "story":
            self._menu_action(menu, "新建场景", self._new_scene)
        elif ref.kind == "scene":
            self._menu_action(menu, "新建台词", lambda: self._new_line(ref))
            menu.addSeparator()
            self._menu_action(menu, "上移", lambda: self._move_node(ref, -1))
            self._menu_action(menu, "下移", lambda: self._move_node(ref, 1))
            self._menu_action(menu, "删除场景", lambda: self._delete_node(ref))
        elif ref.kind == "line":
            self._menu_action(menu, "新建台词", lambda: self._new_line(ref))
            self._menu_action(menu, "新建选项", lambda: self._new_choice(ref))
            menu.addSeparator()
            self._menu_action(menu, "上移", lambda: self._move_node(ref, -1))
            self._menu_action(menu, "下移", lambda: self._move_node(ref, 1))
            self._menu_action(menu, "删除台词", lambda: self._delete_node(ref))
        elif ref.kind == "choice":
            self._menu_action(menu, "新建选项", lambda: self._new_choice(ref))
            menu.addSeparator()
            self._menu_action(menu, "上移", lambda: self._move_node(ref, -1))
            self._menu_action(menu, "下移", lambda: self._move_node(ref, 1))
            self._menu_action(menu, "删除选项", lambda: self._delete_node(ref))
        menu.exec(self.story_tree.viewport().mapToGlobal(position))

    def _menu_action(
        self,
        menu: QMenu,
        title: str,
        callback: Callable[[], Any],
    ) -> QAction:
        action = menu.addAction(title)
        action.triggered.connect(lambda _checked=False: callback())
        return action

    def _new_scene(self) -> None:
        if self._show_form_errors():
            return
        scene_id, accepted = QInputDialog.getText(
            self,
            "新建场景",
            "场景 ID：",
            text=self.model.next_scene_id(),
        )
        if not accepted:
            return
        try:
            ref = self.model.add_scene(scene_id)
        except EditorModelError as exc:
            QMessageBox.warning(self, "无法新建场景", str(exc))
            return
        self._mark_dirty(ref)
        self._refresh_tree(ref)

    def _new_line(self, selected: NodeRef) -> None:
        if self._show_form_errors():
            return
        scene_id = selected.scene_id
        index = None
        if selected.kind == "line" and selected.line_index is not None:
            index = selected.line_index + 1
        elif selected.kind == "choice" and selected.line_index is not None:
            index = selected.line_index + 1
        if scene_id is None:
            return
        try:
            ref = self.model.add_line(scene_id, index)
        except EditorModelError as exc:
            QMessageBox.warning(self, "无法新建台词", str(exc))
            return
        self._mark_dirty(ref)
        self._refresh_tree(ref)

    def _new_choice(self, selected: NodeRef) -> None:
        if self._show_form_errors():
            return
        scene_id = selected.scene_id
        line_index = selected.line_index
        if selected.kind == "choice" and selected.line_index is not None:
            line_index = selected.line_index
        if scene_id is None or line_index is None:
            return
        try:
            ref = self.model.add_choice(scene_id, line_index)
        except EditorModelError as exc:
            QMessageBox.warning(self, "无法新建选项", str(exc))
            return
        self._mark_dirty(ref)
        self._refresh_tree(ref)

    def _move_node(self, ref: NodeRef, offset: int) -> None:
        if self._show_form_errors():
            return
        moved = self.model.move(ref, offset)
        self._mark_dirty(moved)
        self._refresh_tree(moved)

    def _delete_node(self, ref: NodeRef) -> None:
        if self._show_form_errors():
            return
        label = {"scene": "场景", "line": "台词", "choice": "选项"}.get(
            ref.kind, "节点"
        )
        answer = QMessageBox.question(
            self,
            f"删除{label}",
            f"确定删除所选{label}吗？此操作会立即从内存中的剧本移除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            parent_ref = self.model.delete(ref)
        except EditorModelError as exc:
            QMessageBox.warning(self, f"无法删除{label}", str(exc))
            return
        self._mark_dirty(parent_ref)
        self._refresh_tree(parent_ref)

    def new_story(self) -> None:
        if not self._confirm_discard():
            return
        self.model = StoryModel()
        self._dirty = False
        self._refresh_tree(NodeRef("story"))
        self._update_window_title()
        self.statusBar().showMessage("已新建剧本")

    def open_story(self) -> None:
        if not self._confirm_discard():
            return
        initial = (
            self.model.path.parent
            if self.model.path
            else self._assets_dir / "text" / "scripts"
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开 JSON 剧本",
            str(initial),
            "JSON 剧本 (*.json);;所有文件 (*)",
        )
        if path:
            self._open_path(path)

    def _open_path(self, path: str | Path) -> bool:
        try:
            model = StoryModel.open(path)
        except EditorModelError as exc:
            QMessageBox.critical(self, "打开失败", str(exc))
            return False
        self.model = model
        self._dirty = False
        self._refresh_tree(NodeRef("story"))
        self._update_window_title()
        self.statusBar().showMessage(f"已打开 {model.path}")
        if model.path is not None:
            self._remember_last_script(model.path)
        return True

    def save_story(self) -> bool:
        if self._show_form_errors():
            return False
        if self.model.path is None:
            return self.save_story_as()
        return self._save_to(self.model.path)

    def save_story_as(self) -> bool:
        if self._show_form_errors():
            return False
        initial = self.model.path or (
            self._assets_dir / "text" / "scripts" / "story.json"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存 JSON 剧本",
            str(initial),
            "JSON 剧本 (*.json)",
        )
        if not path:
            return False
        target = Path(path)
        if target.suffix.casefold() != ".json":
            target = target.with_suffix(".json")
        return self._save_to(target)

    def _save_to(self, path: str | Path) -> bool:
        try:
            saved_path = self.model.save(path)
        except ScriptError as exc:
            QMessageBox.critical(
                self,
                "剧本校验失败",
                f"未保存文件，原文件保持不变。\n\n{exc}",
            )
            self.statusBar().showMessage("保存失败：剧本校验未通过")
            return False
        except (EditorModelError, OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            self.statusBar().showMessage(f"保存失败：{exc}")
            return False
        self._dirty = False
        self._update_window_title()
        self.statusBar().showMessage(f"已校验并保存：{saved_path}")
        self._remember_last_script(saved_path)
        return True

    def _remember_last_script(self, path: str | Path) -> None:
        self.settings.setValue(
            LAST_SCRIPT_SETTING_KEY,
            str(Path(path).expanduser().resolve()),
        )
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            self.statusBar().showMessage(
                "剧本文件已处理，但无法保存“上次编辑的剧本”设置。"
            )

    def test_story(self) -> None:
        if self._show_form_errors():
            return
        try:
            story = self.model.validate()
        except ScriptError as exc:
            QMessageBox.critical(self, "剧本测试失败", str(exc))
            self.statusBar().showMessage("测试失败：剧本校验未通过")
            return
        except (EditorModelError, OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "剧本测试失败", str(exc))
            self.statusBar().showMessage(f"测试失败：{exc}")
            return
        QMessageBox.information(
            self,
            "剧本测试通过",
            f"剧本《{story.title}》校验通过。\n"
            f"起始场景：{story.start}\n"
            f"场景数量：{len(story.scenes)}\n"
            "保存或测试时均使用引擎 load_script() 校验。",
        )
        self.statusBar().showMessage(f"测试通过：{story.title}")

    def _confirm_discard(self) -> bool:
        if self._form_errors:
            return not self._show_form_errors()
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "未保存的修改",
            "当前剧本有未保存的修改。要先保存吗？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_story()
        return answer == QMessageBox.StandardButton.Discard

    def _update_window_title(self) -> None:
        name = self.model.path.name if self.model.path else "未命名剧本"
        marker = " *" if self._dirty else ""
        self.setWindowTitle(
            f"EasyEngine 剧情编辑器 — {name}{marker} | by {__author__}"
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"{value} 不是标准 JSON 数值。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EasyEngine 图形化剧本编辑器")
    parser.add_argument(
        "story",
        nargs="?",
        help="启动时打开的 JSON 剧本；省略时新建空白剧本",
    )
    arguments, qt_arguments = parser.parse_known_args(argv)
    application = QApplication([sys.argv[0], *qt_arguments])
    window = EditorWindow(arguments.story, settings=_create_settings())
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
