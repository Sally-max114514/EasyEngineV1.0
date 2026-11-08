"""Pygame-CE desktop application and main loop."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pygame

from ..config import SAVE_DIR
from ..galgame.engine import (
    AssetRef,
    GalgameEngine,
    GameEvent,
    StepResult,
    assets_root_for_story,
)
from ..galgame.script import ScriptError, Story, Transition
from ..resources import AssetCatalog, GroupedResources
from .audio import AsyncAudioLoader
from .favorites import FavoriteStoreError, VoiceFavorite, VoiceFavoriteStore
from .renderer import PygameRenderer
from .state_machine import StateMachine
from .states import TitleState

_AUDIO_EXTENSIONS = frozenset(
    {"mp3", "wav", "ogg", "flac", "m4a", "aac", "wma", "opus"}
)


def _create_asset_catalog(
    root: str | Path,
    resources: GroupedResources | None = None,
) -> AssetCatalog:
    if resources is None and not Path(root).is_dir():
        resources = {}
    return AssetCatalog(root, resources=resources)


class PygameApplication:
    """Coordinates the state machine, story engine, audio, and renderer."""

    def __init__(
        self,
        story: Story,
        screen: pygame.Surface,
        catalog: AssetCatalog,
        *,
        audio: AsyncAudioLoader | None,
        save_dir: str | Path = SAVE_DIR,
        stories: Sequence[Story] = (),
        fps: int = 60,
    ) -> None:
        if fps <= 0:
            raise ValueError("fps 必须大于 0")
        self.story = story
        self.stories = self._unique_stories(story, stories)
        self.catalog = catalog
        self._base_save_dir = Path(save_dir)
        self._primary_story_id = self._story_identity(story)
        self.save_dir = self._save_dir_for_story(story)
        self.engine = self._create_engine(story)
        self.renderer = PygameRenderer(screen, catalog, story)
        self.audio = audio
        self.fps = fps
        self.running = False
        self.text_speed = 42.0
        self.auto_delay = 1.0
        self.voice_sync = True
        self.auto_mode = False
        self.skip_mode = False
        self.master_volume = 0.8
        if self.audio is not None:
            self.audio.set_volume(self.master_volume)
        self.favorite_store: VoiceFavoriteStore | None = VoiceFavoriteStore(
            self._base_save_dir / "voice-favorites.json"
        )
        favorite_error = ""
        try:
            self.favorite_store.load()
        except FavoriteStoreError as exc:
            favorite_error = str(exc)
            self.favorite_store = None
        self.machine: StateMachine[PygameApplication] = StateMachine(self)
        self.machine.start(TitleState())
        if favorite_error:
            self.set_status(favorite_error)
        self._preload_story_audio()

    @staticmethod
    def _unique_stories(story: Story, stories: Sequence[Story]) -> tuple[Story, ...]:
        result: list[Story] = []
        seen: set[str] = set()
        for item in (story, *stories):
            identity = PygameApplication._story_identity(item)
            if identity not in seen:
                seen.add(identity)
                result.append(item)
        return tuple(result)

    @staticmethod
    def _story_identity(story: Story) -> str:
        if story.fingerprint is not None:
            return story.fingerprint
        return hashlib.sha256(repr(story).encode("utf-8")).hexdigest()

    def _save_dir_for_story(self, story: Story) -> Path:
        if self._story_identity(story) == self._primary_story_id:
            return self._base_save_dir
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", story.title).strip("-").casefold()
        slug = slug or "story"
        return self._base_save_dir / f"{slug}-{self._story_identity(story)[:12]}"

    @staticmethod
    def _window_caption(story: Story) -> str:
        return f"{story.title} | Powered by EasyEngine"

    def _create_engine(self, story: Story) -> GalgameEngine:
        return GalgameEngine(
            story,
            assets_root=self.catalog.root,
            asset_catalog=self.catalog,
            save_dir=self.save_dir,
        )

    def select_story(self, story: Story) -> None:
        if story.source_path is not None:
            assets_root = assets_root_for_story(story)
            if assets_root.resolve() != self.catalog.root.resolve():
                self.catalog = _create_asset_catalog(assets_root)
                self.renderer.catalog = self.catalog
                self.renderer.assets.catalog = self.catalog
                self.renderer.assets.clear()
                if self.audio is not None:
                    self.audio.catalog = self.catalog
        self.story = story
        self.save_dir = self._save_dir_for_story(story)
        self.engine = self._create_engine(story)
        self.renderer.story = story
        self.renderer.invalidate_full()
        pygame.display.set_caption(self._window_caption(story))
        self._preload_story_audio()

    def reload_script(self) -> StepResult:
        """Reload the selected file-backed story and refresh its runtime view."""
        if self.story.source_path is None:
            return self.engine.reload_script()

        self.catalog = _create_asset_catalog(self.catalog.root)
        self.engine.asset_catalog = self.catalog
        self.engine.resources = self.catalog.resources
        self.engine.assets_root = self.catalog.root
        self.renderer.catalog = self.catalog
        self.renderer.assets.catalog = self.catalog
        self.renderer.assets.clear()
        if self.audio is not None:
            self.audio.catalog = self.catalog

        was_primary_story = (
            self._story_identity(self.story) == self._primary_story_id
        )
        result = self.engine.reload_script()
        self.story = self.engine.story
        other_stories = tuple(
            story
            for story in self.stories
            if story.source_path != self.story.source_path
        )
        self.stories = self._unique_stories(self.story, other_stories)
        if was_primary_story:
            self._primary_story_id = self._story_identity(self.story)
        self.save_dir = self._save_dir_for_story(self.story)
        self.engine.save_dir = self.save_dir
        self.renderer.story = self.story
        self.renderer.invalidate_full()
        pygame.display.set_caption(self._window_caption(self.story))
        self.process_step(result)
        self._preload_story_audio()
        return result

    def latest_save_slot(self) -> str | None:
        saves = self.engine.list_saves()
        if not saves:
            return None
        available: list[tuple[float, str]] = []
        for slot in saves:
            try:
                modified = (self.engine.save_dir / f"{slot}.json").stat().st_mtime
            except OSError:
                continue
            available.append((modified, slot))
        return max(available)[1] if available else None

    def toggle_voice_favorite(self) -> None:
        if self.favorite_store is None:
            self.set_status("语音收藏不可用：收藏文件无法读取。")
            return
        view = self.engine.view
        if view.voice is None or view.voice.path is None:
            self.set_status("当前对话没有可收藏的语音资源。")
            return
        favorite = VoiceFavorite(
            story_title=self.story.title,
            story_fingerprint=self._story_identity(self.story),
            asset_name=view.voice.name,
            speaker=view.speaker,
            text=view.text,
        )
        try:
            added = self.favorite_store.toggle(favorite)
        except FavoriteStoreError as exc:
            self.set_status(str(exc))
        else:
            self.set_status("已加入语音收藏。" if added else "已取消语音收藏。")

    def play_favorite(self, favorite: VoiceFavorite) -> None:
        if self.audio is None:
            self.set_status("音频设备不可用，无法播放语音收藏。")
            return
        reference = self.engine.resolve_asset(favorite.asset_name)
        if reference is None or not reference.exists:
            self.set_status(f"语音资源不存在：{favorite.asset_name}")
            return
        self.audio.play_voice(reference)
        self.set_status(f"正在播放：{favorite.speaker or favorite.story_title}")

    def process_step(self, result: StepResult) -> None:
        """Forward engine events to audio and mark only affected UI regions dirty."""
        for event in result.events:
            self._process_event(event)

    def set_status(self, message: str) -> None:
        self.renderer.set_status(message)

    def clear_status(self) -> None:
        self.renderer.clear_status()

    def frame(
        self,
        events: Iterable[object],
        delta_seconds: float,
    ) -> None:
        """Run one event/update/render cycle; exposed for deterministic testing."""
        for event in events:
            if self._is_resize_event(event):
                self._resize(event)
            else:
                self.machine.handle_event(event)
            if not self.running and self.machine.current is None:
                return

        if self.audio is not None:
            for failure in self.audio.pump():
                self.set_status(failure.message)
        self.machine.update(delta_seconds)
        self.renderer.update_transition(delta_seconds)
        self.machine.render()

    def run(self) -> int:
        """Run the window loop until a state handles a quit request."""
        clock = pygame.time.Clock()
        self.running = True
        try:
            while self.running:
                delta_seconds = clock.tick(self.fps) / 1000.0
                self.frame(pygame.event.get(), delta_seconds)
        finally:
            self.running = False
        return 0

    def _process_event(self, event: GameEvent) -> None:
        kind = event.kind
        if kind in {"scene", "background", "sprite_show", "sprite_hide", "sprites"}:
            self.renderer.invalidate_scene()
        if kind in {"scene", "transition"}:
            transition = event.data.get("transition")
            if not isinstance(transition, Transition):
                raise TypeError(f"{kind} 事件必须包含 Transition")
            self.renderer.start_transition(transition.kind, transition.duration)
        if kind in {"line", "choice", "variables", "text_complete", "load"}:
            self.renderer.invalidate_dialogue(reset_choices=kind == "line")

        if self.audio is None:
            return
        if kind == "bgm":
            reference = event.data.get("ref")
            if reference is not None and not isinstance(reference, AssetRef):
                raise TypeError("bgm 事件的 ref 必须是 AssetRef 或 None")
            self.audio.set_bgm(reference)
        elif kind == "se":
            reference = event.data.get("ref")
            if not isinstance(reference, AssetRef):
                raise TypeError("se 事件必须包含 AssetRef")
            self.audio.play_se(reference)
        elif kind == "line":
            reference = event.data.get("voice")
            if reference is not None and not isinstance(reference, AssetRef):
                raise TypeError("line 事件的 voice 必须是 AssetRef 或 None")
            self.audio.play_voice(reference)

    def _preload_story_audio(self) -> None:
        if self.audio is None:
            return
        for name in self.story.asset_references():
            suffix = Path(name).suffix.casefold().removeprefix(".")
            if suffix not in _AUDIO_EXTENSIONS:
                continue
            reference = self.engine.resolve_asset(name)
            if reference is not None and reference.exists:
                self.audio.preload(reference)

    def _is_resize_event(self, event: object) -> bool:
        resize_types = {pygame.VIDEORESIZE}
        window_resized = getattr(pygame, "WINDOWRESIZED", None)
        if window_resized is not None:
            resize_types.add(window_resized)
        return getattr(event, "type", None) in resize_types

    def _resize(self, event: Any) -> None:
        size = getattr(event, "size", None)
        if size is None:
            size = (event.x, event.y)
        width, height = max(640, size[0]), max(420, size[1])
        screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        self.renderer.resize(screen)


def run_window(
    story: Story,
    *,
    assets_root: str | Path | None = None,
    resources: GroupedResources | None = None,
    save_dir: str | Path = SAVE_DIR,
    stories: Sequence[Story] = (),
    size: tuple[int, int] = (1280, 720),
    fps: int = 60,
) -> int:
    """Initialize Pygame, run the desktop application, and release resources."""
    audio: AsyncAudioLoader | None = None
    root = Path(assets_root) if assets_root is not None else assets_root_for_story(story)
    try:
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=1024)
        pygame.init()
        screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        pygame.display.set_caption(PygameApplication._window_caption(story))

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            pygame.mixer.set_num_channels(16)
            pygame.mixer.set_reserved(1)
            catalog = _create_asset_catalog(root, resources)
            audio = AsyncAudioLoader(catalog)
        except pygame.error as exc:
            print(f"音频设备不可用，将以静音模式运行：{exc}")
            catalog = _create_asset_catalog(root, resources)

        app = PygameApplication(
            story,
            screen,
            catalog,
            audio=audio,
            save_dir=save_dir,
            stories=stories,
            fps=fps,
        )
        print(f"Galgame 剧本：{story.title}")
        print(f"  起始场景：{story.start}，场景数：{len(story.scenes)}")
        missing = app.engine.missing_assets()
        if missing:
            print(f"剧本有 {len(missing)} 个未找到的资源；窗口会显示占位提示。")
            for name in missing:
                print(f"  - {name}")
        return app.run()
    except pygame.error as exc:
        print(f"桌面窗口运行失败：{exc}")
        return 1
    except ScriptError as exc:
        print(f"剧本运行失败：{exc}")
        return 1
    finally:
        try:
            if audio is not None:
                for failure in audio.close():
                    print(failure.message)
        finally:
            pygame.quit()
