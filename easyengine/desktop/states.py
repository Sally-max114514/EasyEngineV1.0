"""Interactive Pygame front-end and Galgame player states."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Literal

import pygame

from ..galgame.engine import (
    ChoiceUnavailableError,
    EngineError,
    StepResult,
)
from ..galgame.state import SaveError
from .favorites import VoiceFavorite
from .renderer import MenuItem
from .state_machine import State

if TYPE_CHECKING:
    from .app import PygameApplication

_VISIBLE_STORIES = 5
_SAVE_SLOTS = ("quick", "slot1", "slot2", "slot3", "slot4", "slot5")


class FrontendMenuState:
    """Shared keyboard/mouse behavior for menu-style screens."""

    heading = ""
    subtitle = ""

    def __init__(self) -> None:
        self.selected_key: str | None = None

    def on_enter(self, app: PygameApplication) -> None:
        app.renderer.update_menu_hover((-1, -1))
        app.renderer.invalidate_full()
        items = self.menu_items(app)
        if not any(item.key == self.selected_key and item.enabled for item in items):
            self.selected_key = next(
                (item.key for item in items if item.enabled),
                None,
            )

    def on_exit(self, app: PygameApplication) -> None:
        pass

    def menu_items(self, app: PygameApplication) -> Sequence[MenuItem]:
        raise NotImplementedError

    def detail(
        self,
        app: PygameApplication,
    ) -> tuple[str, Sequence[str], pygame.Surface | None]:
        return app.story.title, (), None

    def activate(
        self,
        app: PygameApplication,
        key: str,
    ) -> State[PygameApplication] | None:
        return None

    def cancel(self, app: PygameApplication) -> State[PygameApplication] | None:
        return TitleState()

    def handle_event(
        self,
        app: PygameApplication,
        event: object,
    ) -> State[PygameApplication] | None:
        event_type = getattr(event, "type", None)
        if event_type == pygame.QUIT:
            app.running = False
            return None
        if event_type == pygame.MOUSEMOTION:
            key = app.renderer.update_menu_hover(event.pos)
            item = next((item for item in self.menu_items(app) if item.key == key), None)
            if item is not None and item.enabled and self.selected_key != key:
                self.selected_key = key
                app.renderer.invalidate_full()
            return None
        if event_type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            key = app.renderer.menu_item_at(event.pos)
            if key is None:
                return None
            item = next((item for item in self.menu_items(app) if item.key == key), None)
            if item is None:
                return None
            self.selected_key = key
            app.renderer.invalidate_full()
            if not item.enabled:
                app.set_status(f"当前不可用：{item.label}")
                return None
            return self.activate(app, key)
        if event_type != pygame.KEYDOWN:
            return None

        if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
            return self.cancel(app)
        if event.key in (pygame.K_UP, pygame.K_DOWN, pygame.K_HOME, pygame.K_END):
            self._move_selection(app, event.key)
            return None
        if event.key in (pygame.K_RETURN, pygame.K_SPACE):
            item = next(
                (item for item in self.menu_items(app) if item.key == self.selected_key),
                None,
            )
            if item is None:
                return None
            if not item.enabled:
                app.set_status(f"当前不可用：{item.label}")
                return None
            return self.activate(app, item.key)
        return None

    def update(
        self,
        app: PygameApplication,
        delta_seconds: float,
    ) -> State[PygameApplication] | None:
        return None

    def render(self, app: PygameApplication) -> None:
        detail_title, detail_lines, detail_image = self.detail(app)
        app.renderer.draw_frontend(
            self.heading,
            self.subtitle,
            self.menu_items(app),
            self.selected_key,
            detail_title=detail_title,
            detail_lines=detail_lines,
            footer="↑/↓ 选择  ·  Enter 确认  ·  Esc 返回",
            detail_image=detail_image,
        )

    def _move_selection(
        self,
        app: PygameApplication,
        key: int,
    ) -> None:
        items = [item for item in self.menu_items(app) if item.enabled]
        if not items:
            return
        keys = [item.key for item in items]
        if key == pygame.K_HOME:
            self.selected_key = keys[0]
        elif key == pygame.K_END:
            self.selected_key = keys[-1]
        else:
            step = -1 if key == pygame.K_UP else 1
            try:
                current = keys.index(self.selected_key)
            except ValueError:
                current = 0 if step > 0 else len(keys) - 1
            self.selected_key = keys[(current + step) % len(keys)]
        app.renderer.invalidate_full()


class TitleState(FrontendMenuState):
    """Main menu for starting, continuing, browsing, and configuring a story."""

    heading = "欢迎回来"
    subtitle = "选择一个故事，继续你的旅程。"

    def on_enter(self, app: PygameApplication) -> None:
        super().on_enter(app)
        app.clear_status()

    def menu_items(self, app: PygameApplication) -> Sequence[MenuItem]:
        latest = app.latest_save_slot()
        favorites = app.favorite_store.entries if app.favorite_store else ()
        return (
            MenuItem("new", "开始新游戏", "选择剧本"),
            MenuItem(
                "continue",
                "继续游戏",
                f"读取最近存档：{latest}" if latest else "暂无存档",
                enabled=latest is not None,
            ),
            MenuItem(
                "gallery",
                "CG 鉴赏",
                f"{len(app.story.gallery)} 张",
                enabled=bool(app.story.gallery),
            ),
            MenuItem(
                "favorites",
                "语音收藏",
                f"{len(favorites)} 条",
                enabled=bool(favorites),
            ),
            MenuItem("settings", "设置", "文字速度 · 音量 · 自动播放"),
            MenuItem("quit", "退出", "关闭游戏"),
        )

    def detail(
        self,
        app: PygameApplication,
    ) -> tuple[str, Sequence[str], pygame.Surface | None]:
        return (
            app.story.title,
            (
                f"{len(app.story.scenes)} 个场景 · {len(app.story.characters)} 位角色",
                f"{len(app.story.gallery)} 张 CG · {len(app.stories)} 个剧本",
                "A 自动播放 · S 跳过已读 · Backspace 回滚",
            ),
            None,
        )

    def activate(
        self,
        app: PygameApplication,
        key: str,
    ) -> State[PygameApplication] | None:
        if key == "new":
            return StorySelectState()
        if key == "continue":
            slot = app.latest_save_slot()
            return _load_save(app, slot) if slot is not None else None
        if key == "gallery":
            return GalleryState()
        if key == "favorites":
            return VoiceFavoritesState()
        if key == "settings":
            return SettingsState(self)
        if key == "quit":
            app.running = False
        return None

    def cancel(self, app: PygameApplication) -> State[PygameApplication] | None:
        app.running = False
        return None


class StorySelectState(FrontendMenuState):
    heading = "故事库"
    subtitle = "选择一个剧本开始游玩。"

    def __init__(self) -> None:
        super().__init__()
        self.story_index = 0
        self.window_start = 0

    def on_enter(self, app: PygameApplication) -> None:
        self.story_index = 0
        self.window_start = 0
        self.selected_key = "story:0" if app.stories else "back"
        super().on_enter(app)
        app.clear_status()

    def menu_items(self, app: PygameApplication) -> Sequence[MenuItem]:
        if not app.stories:
            return (
                MenuItem("empty", "没有可用剧本", enabled=False),
                MenuItem("back", "返回"),
            )
        end = min(len(app.stories), self.window_start + _VISIBLE_STORIES)
        items = [
            MenuItem(
                f"story:{index}",
                story.title,
                f"{len(story.scenes)} 场景 · {len(story.gallery)} CG",
            )
            for index, story in enumerate(app.stories[self.window_start:end], self.window_start)
        ]
        items.append(MenuItem("back", "返回"))
        return tuple(items)

    def detail(
        self,
        app: PygameApplication,
    ) -> tuple[str, Sequence[str], pygame.Surface | None]:
        if not app.stories:
            return "故事库为空", ("将 JSON 剧本放入 assets/text/scripts/。",), None
        selected = min(self.story_index, len(app.stories) - 1)
        story = app.stories[selected]
        characters = "、".join(item.name for item in story.characters.values())
        return (
            story.title,
            (
                f"起始场景：{story.start}",
                f"场景：{len(story.scenes)} · 角色：{characters or '无'}",
                f"CG：{len(story.gallery)} 张",
                f"剧本 {selected + 1}/{len(app.stories)}",
            ),
            None,
        )

    def handle_event(
        self,
        app: PygameApplication,
        event: object,
    ) -> State[PygameApplication] | None:
        if getattr(event, "type", None) == pygame.MOUSEWHEEL:
            if app.stories:
                self._move_story(app, -event.y)
            return None
        if getattr(event, "type", None) == pygame.KEYDOWN:
            if event.key == pygame.K_UP:
                if app.stories:
                    self._move_story(app, -1)
                else:
                    self._move_selection(app, event.key)
                return None
            if event.key == pygame.K_DOWN:
                if app.stories:
                    self._move_story(app, 1)
                else:
                    self._move_selection(app, event.key)
                return None
        return super().handle_event(app, event)

    def activate(
        self,
        app: PygameApplication,
        key: str,
    ) -> State[PygameApplication] | None:
        if key == "back":
            return TitleState()
        if key.startswith("story:"):
            index = int(key.partition(":")[2])
            if 0 <= index < len(app.stories):
                app.select_story(app.stories[index])
                app.auto_mode = False
                app.skip_mode = False
                return PlayingState()
        return None

    def cancel(self, app: PygameApplication) -> State[PygameApplication] | None:
        return TitleState()

    def _move_story(self, app: PygameApplication, step: int) -> None:
        if not app.stories:
            return
        total = len(app.stories) + 1
        if self.selected_key == "back":
            current = len(app.stories)
        else:
            current = self.story_index
        current = (current + step) % total
        if current == len(app.stories):
            self.selected_key = "back"
        else:
            self.story_index = current
            if current < self.window_start:
                self.window_start = current
            elif current >= self.window_start + _VISIBLE_STORIES:
                self.window_start = current - _VISIBLE_STORIES + 1
            self.selected_key = f"story:{current}"
        app.renderer.invalidate_full()


class SaveSlotState(FrontendMenuState):
    """Read or write a named slot, including a PNG thumbnail for new saves."""

    def __init__(
        self,
        mode: Literal["load", "save"],
        return_state: State[PygameApplication],
    ) -> None:
        super().__init__()
        self.mode = mode
        self.return_state = return_state
        self.window_start = 0

    @property
    def heading(self) -> str:
        return "读取存档" if self.mode == "load" else "保存进度"

    @property
    def subtitle(self) -> str:
        return "选择一个存档槽。" if self.mode == "load" else "选择槽位保存当前进度。"

    def on_enter(self, app: PygameApplication) -> None:
        self.window_start = 0
        if self.mode == "load":
            slots = app.engine.list_saves()
            self.selected_key = f"slot:{slots[0]}" if slots else "back"
        super().on_enter(app)

    def menu_items(self, app: PygameApplication) -> Sequence[MenuItem]:
        if self.mode == "load":
            slots = app.engine.list_saves()
            items = (
                [
                    MenuItem("empty", "暂无存档", enabled=False)
                ]
                if not slots
                else [
                    MenuItem(f"slot:{slot}", slot, "点击读取")
                    for slot in slots[
                        self.window_start : self.window_start + _VISIBLE_STORIES
                    ]
                ]
            )
        else:
            items = [
                MenuItem(
                    f"slot:{slot}",
                    slot,
                    "覆盖已有存档" if slot in app.engine.list_saves() else "新存档",
                )
                for slot in _SAVE_SLOTS
            ]
        items.append(MenuItem("back", "返回"))
        return tuple(items)

    def handle_event(
        self,
        app: PygameApplication,
        event: object,
    ) -> State[PygameApplication] | None:
        if self.mode == "load":
            event_type = getattr(event, "type", None)
            if event_type == pygame.MOUSEWHEEL:
                direction = getattr(event, "y", 0)
                if isinstance(direction, int):
                    self._move_load_slot(app, -direction)
                return None
            key = getattr(event, "key", None)
            if event_type == pygame.KEYDOWN and key in (
                pygame.K_UP,
                pygame.K_DOWN,
            ):
                self._move_load_slot(
                    app,
                    -1 if key == pygame.K_UP else 1,
                )
                return None
        return super().handle_event(app, event)

    def detail(
        self,
        app: PygameApplication,
    ) -> tuple[str, Sequence[str], pygame.Surface | None]:
        if self.selected_key is None or not self.selected_key.startswith("slot:"):
            return "存档槽", ("选择左侧的存档槽。",), None
        slot = self.selected_key.partition(":")[2]
        save_path = app.engine.save_dir / f"{slot}.json"
        thumb = app.renderer.load_thumbnail(
            app.engine.save_dir / f"{slot}.png"
        )
        if not save_path.is_file():
            return slot, ("该槽位目前没有存档。",), thumb
        try:
            modified = save_path.stat().st_mtime
        except OSError as exc:
            app.set_status(f"无法读取存档信息：{exc}")
            return slot, ("存档文件当前不可访问。",), thumb
        time_text = datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M")
        return slot, (f"保存时间：{time_text}",), thumb

    def activate(
        self,
        app: PygameApplication,
        key: str,
    ) -> State[PygameApplication] | None:
        if key == "back":
            return self.return_state
        if not key.startswith("slot:"):
            return None
        slot = key.partition(":")[2]
        if self.mode == "save":
            try:
                path = app.engine.save(slot)
            except SaveError as exc:
                app.set_status(f"存档失败：{exc}")
                return None
            try:
                app.renderer.save_thumbnail(
                    app.engine.save_dir / f"{slot}.png",
                    app.engine.view,
                )
            except OSError as exc:
                app.set_status(f"存档已保存，但缩略图失败：{exc}")
            else:
                app.set_status(f"已保存：{path.name}")
            return self.return_state
        return _load_save(app, slot)

    def cancel(self, app: PygameApplication) -> State[PygameApplication] | None:
        return self.return_state

    def _move_load_slot(self, app: PygameApplication, step: int) -> None:
        slots = app.engine.list_saves()
        total = len(slots) + 1
        if self.selected_key == "back":
            current = len(slots)
        else:
            selected_slot = (
                self.selected_key.partition(":")[2]
                if self.selected_key and self.selected_key.startswith("slot:")
                else ""
            )
            try:
                current = slots.index(selected_slot)
            except ValueError:
                current = 0
        current = (current + step) % total
        if current == len(slots):
            self.selected_key = "back"
        else:
            if current < self.window_start:
                self.window_start = current
            elif current >= self.window_start + _VISIBLE_STORIES:
                self.window_start = current - _VISIBLE_STORIES + 1
            self.selected_key = f"slot:{slots[current]}"
        app.renderer.invalidate_full()


class SettingsState(FrontendMenuState):
    heading = "设置"
    subtitle = "调整文字、音量与播放方式。"

    def __init__(self, return_state: State[PygameApplication]) -> None:
        super().__init__()
        self.return_state = return_state

    def menu_items(self, app: PygameApplication) -> Sequence[MenuItem]:
        audio_status = f"{app.master_volume:.1f}" if app.audio else "无音频设备"
        sync_label = "开" if app.voice_sync else "关"
        return (
            MenuItem("speed_down", "文字速度 −", f"{app.text_speed:.0f} 字/秒"),
            MenuItem("speed_up", "文字速度 +", f"{app.text_speed:.0f} 字/秒"),
            MenuItem("volume_down", "主音量 −", audio_status),
            MenuItem("volume_up", "主音量 +", audio_status),
            MenuItem("voice_sync", "语音字幕同步", sync_label),
            MenuItem("delay_down", "自动播放间隔 −", f"{app.auto_delay:.1f} 秒"),
            MenuItem("delay_up", "自动播放间隔 +", f"{app.auto_delay:.1f} 秒"),
            MenuItem("back", "返回"),
        )

    def detail(
        self,
        app: PygameApplication,
    ) -> tuple[str, Sequence[str], pygame.Surface | None]:
        return (
            "玩家偏好",
            (
                f"文字速度：{app.text_speed:.0f} 字/秒",
                f"主音量：{app.master_volume:.1f}",
                f"语音字幕同步：{'开启' if app.voice_sync else '关闭'}",
                f"自动播放间隔：{app.auto_delay:.1f} 秒",
                "语音会与字幕开始同步，并按音频时长调整打字速度。",
            ),
            None,
        )

    def activate(
        self,
        app: PygameApplication,
        key: str,
    ) -> State[PygameApplication] | None:
        if key == "back":
            return self.return_state
        if key == "speed_down":
            app.text_speed = max(5.0, app.text_speed - 5.0)
        elif key == "speed_up":
            app.text_speed = min(120.0, app.text_speed + 5.0)
        elif key in {"volume_down", "volume_up"}:
            if app.audio is None:
                app.set_status("音频设备不可用。")
                return None
            direction = -0.1 if key == "volume_down" else 0.1
            app.master_volume = round(
                min(1.0, max(0.0, app.master_volume + direction)),
                1,
            )
            app.audio.set_volume(app.master_volume)
        elif key == "voice_sync":
            app.voice_sync = not app.voice_sync
        elif key == "delay_down":
            app.auto_delay = max(0.1, app.auto_delay - 0.2)
        elif key == "delay_up":
            app.auto_delay = min(5.0, app.auto_delay + 0.2)
        app.renderer.invalidate_full()
        return None

    def cancel(self, app: PygameApplication) -> State[PygameApplication] | None:
        return self.return_state


class GalleryState:
    """Browse CG entries explicitly declared by the selected story."""

    def __init__(self, index: int = 0) -> None:
        self.index = index

    def on_enter(self, app: PygameApplication) -> None:
        if app.story.gallery:
            self.index %= len(app.story.gallery)
        else:
            self.index = 0
        app.renderer.update_menu_hover((-1, -1))
        app.renderer.invalidate_full()

    def on_exit(self, app: PygameApplication) -> None:
        pass

    def handle_event(
        self,
        app: PygameApplication,
        event: object,
    ) -> State[PygameApplication] | None:
        if event.type == pygame.QUIT:
            app.running = False
        elif event.type == pygame.MOUSEMOTION:
            app.renderer.update_menu_hover(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            key = app.renderer.menu_item_at(event.pos)
            if key == "gallery_previous":
                self._move(app, -1)
            elif key == "gallery_next":
                self._move(app, 1)
            elif key == "gallery_back":
                return TitleState()
        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                return TitleState()
            if event.key in (pygame.K_LEFT, pygame.K_UP):
                self._move(app, -1)
            elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                self._move(app, 1)
        return None

    def update(
        self,
        app: PygameApplication,
        delta_seconds: float,
    ) -> State[PygameApplication] | None:
        return None

    def render(self, app: PygameApplication) -> None:
        entries = app.story.gallery
        entry = entries[self.index] if entries else None
        image_ref = app.engine.resolve_asset(entry.image) if entry else None
        app.renderer.draw_gallery(entry, image_ref, self.index, len(entries))

    def _move(self, app: PygameApplication, amount: int) -> None:
        if app.story.gallery:
            self.index = (self.index + amount) % len(app.story.gallery)
            app.renderer.invalidate_full()


class VoiceFavoritesState(FrontendMenuState):
    heading = "语音收藏"
    subtitle = "选择收藏条目，重新播放角色语音。"

    def __init__(self) -> None:
        super().__init__()
        self.window_start = 0

    def on_enter(self, app: PygameApplication) -> None:
        self.window_start = 0
        favorites = app.favorite_store.entries if app.favorite_store else ()
        self.selected_key = "voice:0" if favorites else "back"
        super().on_enter(app)
        app.clear_status()

    def menu_items(self, app: PygameApplication) -> Sequence[MenuItem]:
        favorites = app.favorite_store.entries if app.favorite_store else ()
        items: list[MenuItem] = [
            MenuItem(
                f"voice:{index}",
                f"{favorite.speaker or favorite.story_title} · {favorite.text[:18]}",
                favorite.story_title,
            )
            for index, favorite in enumerate(
                favorites[self.window_start : self.window_start + _VISIBLE_STORIES],
                self.window_start,
            )
        ]
        if not items:
            items.append(MenuItem("empty", "暂无语音收藏", enabled=False))
        items.append(MenuItem("back", "返回"))
        return tuple(items)

    def handle_event(
        self,
        app: PygameApplication,
        event: object,
    ) -> State[PygameApplication] | None:
        favorites = app.favorite_store.entries if app.favorite_store else ()
        event_type = getattr(event, "type", None)
        if event_type == pygame.MOUSEWHEEL and favorites:
            direction = getattr(event, "y", 0)
            if isinstance(direction, int):
                self._move_favorite(app, -direction)
            return None
        key = getattr(event, "key", None)
        if event_type == pygame.KEYDOWN and key in (
            pygame.K_UP,
            pygame.K_DOWN,
        ):
            self._move_favorite(
                app,
                -1 if key == pygame.K_UP else 1,
            )
            return None
        return super().handle_event(app, event)

    def detail(
        self,
        app: PygameApplication,
    ) -> tuple[str, Sequence[str], pygame.Surface | None]:
        favorite = self._selected_favorite(app)
        if favorite is None:
            return "语音收藏", ("游玩时按 V 收藏当前对话语音。",), None
        favorites = app.favorite_store.entries if app.favorite_store else ()
        return (
            favorite.speaker or favorite.story_title,
            (
                favorite.text,
                favorite.asset_name,
                favorite.story_title,
                f"收藏 {self._selected_favorite_index(app) + 1}/{len(favorites)}",
            ),
            None,
        )

    def activate(
        self,
        app: PygameApplication,
        key: str,
    ) -> State[PygameApplication] | None:
        if key == "back":
            return TitleState()
        if key.startswith("voice:"):
            try:
                index = int(key.partition(":")[2])
                favorite = app.favorite_store.entries[index] if app.favorite_store else None
            except (ValueError, IndexError):
                return None
            if favorite is not None:
                app.play_favorite(favorite)
        return None

    def cancel(self, app: PygameApplication) -> State[PygameApplication] | None:
        return TitleState()

    def _move_favorite(self, app: PygameApplication, step: int) -> None:
        favorites = app.favorite_store.entries if app.favorite_store else ()
        total = len(favorites) + 1
        if self.selected_key == "back":
            current = len(favorites)
        else:
            selected_key = self.selected_key
            if selected_key is None or not selected_key.startswith("voice:"):
                current = 0
            else:
                try:
                    current = int(selected_key.partition(":")[2])
                except ValueError:
                    current = 0
        current = (current + step) % total
        if current == len(favorites):
            self.selected_key = "back"
        else:
            if current < self.window_start:
                self.window_start = current
            elif current >= self.window_start + _VISIBLE_STORIES:
                self.window_start = current - _VISIBLE_STORIES + 1
            self.selected_key = f"voice:{current}"
        app.renderer.invalidate_full()

    def _selected_favorite_index(self, app: PygameApplication) -> int:
        if self.selected_key and self.selected_key.startswith("voice:"):
            try:
                return int(self.selected_key.partition(":")[2])
            except ValueError:
                pass
        return 0

    def _selected_favorite(
        self,
        app: PygameApplication,
    ) -> VoiceFavorite | None:
        if self.selected_key is None or not self.selected_key.startswith("voice:"):
            return None
        try:
            index = int(self.selected_key.partition(":")[2])
            return app.favorite_store.entries[index] if app.favorite_store else None
        except (ValueError, IndexError):
            return None


class PlayingState:
    def __init__(self, *, characters_per_second: float = 42.0) -> None:
        if characters_per_second <= 0:
            raise ValueError("characters_per_second 必须大于 0")
        self.characters_per_second = characters_per_second
        self._typing_remainder = 0.0
        self._auto_elapsed = 0.0

    def on_enter(self, app: PygameApplication) -> None:
        if not app.engine.view.started or app.engine.view.ended:
            app.process_step(app.engine.start())
        app.renderer.invalidate_full()

    def on_exit(self, app: PygameApplication) -> None:
        pass

    def handle_event(
        self,
        app: PygameApplication,
        event: object,
    ) -> State[PygameApplication] | None:
        if event.type == pygame.QUIT:
            app.running = False
            return None
        if event.type == pygame.MOUSEWHEEL:
            app.renderer.scroll_choices(event.y, len(app.engine.view.choices))
            return None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._handle_click(app, event.pos)
        if event.type != pygame.KEYDOWN:
            return None

        if event.key == pygame.K_ESCAPE:
            return PausedState(self)
        if event.key == pygame.K_F5:
            self._save(app)
            return None
        if event.key == pygame.K_F9:
            self._load(app)
            return self._ending_if_needed(app)
        if event.key == pygame.K_BACKSPACE:
            self._rollback(app)
            return None
        if event.key == pygame.K_a:
            app.auto_mode = not app.auto_mode
            if app.auto_mode:
                app.skip_mode = False
            self._auto_elapsed = 0.0
            app.set_status(
                "自动播放已开启。" if app.auto_mode else "自动播放已关闭。"
            )
            return None
        if event.key == pygame.K_s:
            app.skip_mode = not app.skip_mode
            if app.skip_mode:
                app.auto_mode = False
                if app.audio is not None:
                    app.audio.stop_voice()
            app.set_status(
                "跳过已读已开启。" if app.skip_mode else "跳过已读已关闭。"
            )
            return None
        if event.key == pygame.K_v:
            app.toggle_voice_favorite()
            return None
        if event.key in (pygame.K_RETURN, pygame.K_SPACE):
            if app.engine.view.choices:
                app.set_status("请点击一个已解锁的选项。")
                return None
            return self._run_step(app, app.engine.advance())
        return None

    def update(
        self,
        app: PygameApplication,
        delta_seconds: float,
    ) -> State[PygameApplication] | None:
        view = app.engine.view
        if view.ended:
            return EndingState()
        if delta_seconds <= 0:
            return None

        if app.skip_mode:
            if view.choices:
                app.skip_mode = False
                app.set_status("遇到选项，跳过已读已停止。")
                return None
            if not app.engine.current_line_seen:
                app.skip_mode = False
                app.set_status("遇到未读文本，跳过已读已停止。")
                return None
            if not view.text_complete:
                app.engine.reveal_all()
                app.renderer.invalidate_dialogue()
                return None
            return self._run_step(app, app.engine.advance())

        if not view.text_complete:
            if self._waiting_for_voice(app):
                return None
            rate = self._typing_rate(app)
            self._typing_remainder += delta_seconds * rate
            count = int(self._typing_remainder)
            if count:
                self._typing_remainder -= count
                app.engine.tick(count)
                app.renderer.invalidate_dialogue()
            return None

        if app.auto_mode:
            if view.choices:
                app.auto_mode = False
                app.set_status("遇到选项，自动播放已暂停。")
                return None
            if app.audio is not None and app.audio.voice_playing:
                self._auto_elapsed = 0.0
                return None
            self._auto_elapsed += delta_seconds
            if self._auto_elapsed >= app.auto_delay:
                self._auto_elapsed = 0.0
                return self._run_step(app, app.engine.advance())
        return None

    def render(self, app: PygameApplication) -> None:
        app.renderer.draw_game(app.engine.view)

    def _handle_click(
        self,
        app: PygameApplication,
        position: tuple[int, int],
    ) -> State[PygameApplication] | None:
        view = app.engine.view
        choice_index = app.renderer.choice_at(position)
        if choice_index is not None:
            choice = next(
                (item for item in view.choices if item.index == choice_index),
                None,
            )
            if choice is None:
                return None
            if not choice.available:
                app.set_status("此选项尚未解锁。")
                return None
            try:
                result = app.engine.choose(choice_index)
            except ChoiceUnavailableError as exc:
                app.set_status(str(exc))
                return None
            return self._run_step(app, result)

        if app.renderer.dialogue_rect.collidepoint(position) and not view.choices:
            return self._run_step(app, app.engine.advance())
        return None

    def _run_step(
        self,
        app: PygameApplication,
        result: StepResult,
    ) -> State[PygameApplication] | None:
        app.clear_status()
        app.process_step(result)
        self._typing_remainder = 0.0
        self._auto_elapsed = 0.0
        return self._ending_if_needed(app)

    @staticmethod
    def _ending_if_needed(
        app: PygameApplication,
    ) -> State[PygameApplication] | None:
        return EndingState() if app.engine.view.ended else None

    @staticmethod
    def _waiting_for_voice(app: PygameApplication) -> bool:
        view = app.engine.view
        return bool(
            app.voice_sync
            and app.audio is not None
            and view.voice is not None
            and view.voice.path == app.audio.requested_voice_path
            and app.audio.voice_pending
        )

    def _typing_rate(self, app: PygameApplication) -> float:
        view = app.engine.view
        if (
            app.voice_sync
            and app.audio is not None
            and view.voice is not None
            and view.voice.path == app.audio.voice_path
            and app.audio.voice_duration
        ):
            return min(
                120.0,
                max(1.0, len(view.text) / app.audio.voice_duration),
            )
        return app.text_speed or self.characters_per_second

    @staticmethod
    def _save(app: PygameApplication, slot: str = "quick") -> None:
        try:
            path = app.engine.save(slot)
        except SaveError as exc:
            app.set_status(f"存档失败：{exc}")
            return
        try:
            app.renderer.save_thumbnail(
                app.engine.save_dir / f"{slot}.png",
                app.engine.view,
            )
        except OSError as exc:
            app.set_status(f"存档已保存，但缩略图失败：{exc}")
        else:
            app.set_status(f"已保存：{path.name}")

    @staticmethod
    def _load(app: PygameApplication, slot: str = "quick") -> None:
        try:
            result = app.engine.load(slot)
        except SaveError as exc:
            app.set_status(f"读档失败：{exc}")
        except EngineError as exc:
            app.set_status(f"读档失败：{exc}")
        else:
            app.process_step(result)
            if _load_was_legacy(result):
                app.set_status("已读取旧版存档；剧本指纹未校验，重新保存后会写入校验信息。")
            else:
                app.set_status("已读取快速存档。")

    @staticmethod
    def _rollback(app: PygameApplication) -> None:
        try:
            result = app.engine.rollback()
        except EngineError as exc:
            app.set_status(f"无法回滚：{exc}")
        else:
            app.process_step(result)
            app.set_status("已回滚一条剧情记录。")


class PausedState(FrontendMenuState):
    heading = "游戏菜单"
    subtitle = "暂停中。"

    def __init__(self, resume_state: PlayingState) -> None:
        super().__init__()
        self.resume_state = resume_state

    def menu_items(self, app: PygameApplication) -> Sequence[MenuItem]:
        return (
            MenuItem("resume", "继续游戏"),
            MenuItem("save", "保存进度", "选择存档槽"),
            MenuItem("load", "读取进度", "读取当前剧本存档"),
            MenuItem(
                "rollback",
                "回滚一条",
                f"可回滚 {app.engine.rollback_depth} 条",
                enabled=app.engine.rollback_depth > 0,
            ),
            MenuItem(
                "auto",
                "关闭自动播放" if app.auto_mode else "开启自动播放",
            ),
            MenuItem(
                "skip",
                "关闭跳过已读" if app.skip_mode else "开启跳过已读",
            ),
            MenuItem("settings", "设置"),
            MenuItem("title", "返回主菜单"),
        )

    def detail(
        self,
        app: PygameApplication,
    ) -> tuple[str, Sequence[str], pygame.Surface | None]:
        view = app.engine.view
        return (
            app.story.title,
            (
                f"场景：{view.scene_id or '未开始'} · 第 {view.line_index + 1} 行",
                f"自动播放：{'开' if app.auto_mode else '关'}",
                f"跳过已读：{'开' if app.skip_mode else '关'}",
                "F5 快速存档 · F9 快速读档 · Backspace 回滚",
            ),
            None,
        )

    def activate(
        self,
        app: PygameApplication,
        key: str,
    ) -> State[PygameApplication] | None:
        if key == "resume":
            return self.resume_state
        if key == "save":
            return SaveSlotState("save", self)
        if key == "load":
            return SaveSlotState("load", self)
        if key == "rollback":
            PlayingState._rollback(app)
            return self.resume_state
        if key == "auto":
            app.auto_mode = not app.auto_mode
            if app.auto_mode:
                app.skip_mode = False
            app.set_status(
                "自动播放已开启。" if app.auto_mode else "自动播放已关闭。"
            )
            app.renderer.invalidate_full()
        elif key == "skip":
            app.skip_mode = not app.skip_mode
            if app.skip_mode:
                app.auto_mode = False
                if app.audio is not None:
                    app.audio.stop_voice()
            app.set_status(
                "跳过已读已开启。" if app.skip_mode else "跳过已读已关闭。"
            )
            app.renderer.invalidate_full()
        elif key == "settings":
            return SettingsState(self)
        elif key == "title":
            app.auto_mode = False
            app.skip_mode = False
            return TitleState()
        return None

    def cancel(self, app: PygameApplication) -> State[PygameApplication] | None:
        return self.resume_state


class EndingState:
    def on_enter(self, app: PygameApplication) -> None:
        app.auto_mode = False
        app.skip_mode = False
        app.renderer.invalidate_full()

    def on_exit(self, app: PygameApplication) -> None:
        pass

    def handle_event(
        self,
        app: PygameApplication,
        event: object,
    ) -> State[PygameApplication] | None:
        if event.type == pygame.QUIT:
            app.running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return TitleState()
            if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return TitleState()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return TitleState()
        return None

    def update(
        self,
        app: PygameApplication,
        delta_seconds: float,
    ) -> State[PygameApplication] | None:
        return None

    def render(self, app: PygameApplication) -> None:
        app.renderer.draw_ending(app.engine.view)


def _load_save(
    app: PygameApplication,
    slot: str | None,
) -> State[PygameApplication] | None:
    if slot is None:
        return None
    try:
        result = app.engine.load(slot)
    except SaveError as exc:
        app.set_status(f"读档失败：{exc}")
        return None
    except EngineError as exc:
        app.set_status(f"读档失败：{exc}")
        return None
    app.process_step(result)
    if _load_was_legacy(result):
        app.set_status("旧版存档已读取，但无法校验剧本内容；重新保存后会写入指纹。")
    else:
        app.set_status(f"已读取存档：{slot}")
    return EndingState() if result.view.ended else PlayingState()


def _load_was_legacy(result: StepResult) -> bool:
    return any(
        event.kind == "load" and bool(event.data.get("unverified"))
        for event in result.events
    )
