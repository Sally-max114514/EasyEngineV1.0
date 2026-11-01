"""Background audio decoding with main-thread playback control."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pygame

from ..galgame.engine import AssetRef
from ..resources import AssetCatalog


@dataclass(frozen=True)
class AudioLoadFailure:
    asset_name: str
    message: str


class AsyncAudioLoader:
    """Preload referenced audio without blocking the window/render thread.

    Pygame Sound decoding runs in one worker. Future completion, channel changes,
    looping, fade-outs, and sound playback are all handled by ``pump()`` on the
    main thread. Long background music is loaded as a Sound to make its first
    playback non-blocking and is kept cached for quick scene changes.
    """

    def __init__(
        self,
        catalog: AssetCatalog,
        *,
        bgm_channel: int = 0,
        voice_channel: int = 1,
        fade_ms: int = 180,
    ) -> None:
        if not pygame.mixer.get_init():
            raise RuntimeError("初始化 AsyncAudioLoader 前必须先初始化 pygame.mixer")
        if bgm_channel < 0:
            raise ValueError("bgm_channel 不能为负数")
        if voice_channel < 0 or voice_channel == bgm_channel:
            raise ValueError("voice_channel 必须是与 BGM 不同的非负频道")
        if fade_ms < 0:
            raise ValueError("fade_ms 不能为负数")

        self.catalog = catalog
        self.fade_ms = fade_ms
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="easyengine-audio",
        )
        self._futures: dict[Path, Future[pygame.mixer.Sound]] = {}
        self._sounds: dict[Path, pygame.mixer.Sound] = {}
        self._pending_sfx: list[Path] = []
        self._failures: list[AudioLoadFailure] = []
        self._desired_bgm: Path | None = None
        self._current_bgm: Path | None = None
        self._desired_voice: Path | None = None
        self._current_voice: Path | None = None
        self._bgm_channel = pygame.mixer.Channel(bgm_channel)
        self._voice_channel = pygame.mixer.Channel(voice_channel)
        self._volume = 1.0
        self._closed = False

    @property
    def pending_count(self) -> int:
        return len(self._futures)

    @property
    def loaded_count(self) -> int:
        return len(self._sounds)

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def voice_path(self) -> Path | None:
        return self._current_voice

    @property
    def requested_voice_path(self) -> Path | None:
        return self._desired_voice

    @property
    def voice_duration(self) -> float | None:
        if self._current_voice is None:
            return None
        sound = self._sounds.get(self._current_voice)
        return sound.get_length() if sound is not None else None

    @property
    def voice_playing(self) -> bool:
        return self._voice_channel.get_busy()

    @property
    def voice_pending(self) -> bool:
        return (
            self._desired_voice is not None
            and self._desired_voice not in self._sounds
        )

    def preload(self, reference: AssetRef | str | Path) -> Path | None:
        """Schedule an asset for background decoding; repeated calls are deduped."""
        self._ensure_open()
        path = self._path_for(reference)
        if path is None:
            return None
        self._submit(path)
        return path

    def preload_many(self, references: Iterable[AssetRef | str | Path]) -> None:
        for reference in references:
            self.preload(reference)

    def set_bgm(self, reference: AssetRef | None) -> None:
        """Request a looping track; a pending track starts as soon as it is ready."""
        self._ensure_open()
        if reference is None:
            self._desired_bgm = None
            self._current_bgm = None
            self._bgm_channel.fadeout(self.fade_ms)
            return

        path = self._path_for(reference)
        if path is None:
            return
        self._desired_bgm = path
        sound = self._sounds.get(path)
        if sound is not None:
            self._start_bgm(path, sound)
        else:
            self._submit(path)

    def play_se(self, reference: AssetRef) -> None:
        """Play a one-shot effect immediately if cached, otherwise queue it."""
        self._ensure_open()
        path = self._path_for(reference)
        if path is None:
            return
        sound = self._sounds.get(path)
        if sound is not None:
            sound.set_volume(self._volume)
            sound.play()
            return
        self._pending_sfx.append(path)
        self._submit(path)

    def play_voice(self, reference: AssetRef | None) -> None:
        """Play or stop a spoken line, waiting for asynchronous decode if needed."""
        self._ensure_open()
        if reference is None:
            self.stop_voice()
            return

        path = self._path_for(reference)
        if path is None:
            self._desired_voice = None
            return
        self._desired_voice = path
        sound = self._sounds.get(path)
        if sound is not None:
            self._start_voice(path, sound)
        else:
            self._submit(path)

    def stop_voice(self) -> None:
        self._ensure_open()
        self._desired_voice = None
        self._current_voice = None
        self._voice_channel.fadeout(self.fade_ms)

    def set_volume(self, volume: float) -> None:
        """Set master playback volume in the inclusive range 0.0-1.0."""
        self._ensure_open()
        if isinstance(volume, bool) or not isinstance(volume, (int, float)):
            raise TypeError("volume 必须是数字")
        if not 0.0 <= volume <= 1.0:
            raise ValueError("volume 必须在 0.0 到 1.0 之间")
        self._volume = float(volume)
        self._bgm_channel.set_volume(self._volume)
        self._voice_channel.set_volume(self._volume)

    def pump(self) -> tuple[AudioLoadFailure, ...]:
        """Collect completed worker jobs and perform playback on the caller thread."""
        self._ensure_open()
        completed = [
            (path, future)
            for path, future in self._futures.items()
            if future.done()
        ]
        for path, future in completed:
            del self._futures[path]
            try:
                sound = future.result()
            except (OSError, pygame.error, ValueError) as exc:
                self._failures.append(
                    AudioLoadFailure(path.name, f"音频解码失败：{path}（{exc}）")
                )
                self._pending_sfx = [item for item in self._pending_sfx if item != path]
                if self._desired_bgm == path:
                    self._desired_bgm = None
                if self._desired_voice == path:
                    self._desired_voice = None
                continue

            self._sounds[path] = sound
            if self._desired_bgm == path:
                self._start_bgm(path, sound)
            if self._desired_voice == path:
                self._start_voice(path, sound)
            pending = self._pending_sfx
            self._pending_sfx = []
            for pending_path in pending:
                pending_sound = self._sounds.get(pending_path)
                if pending_sound is None:
                    self._pending_sfx.append(pending_path)
                else:
                    pending_sound.set_volume(self._volume)
                    pending_sound.play()

        failures = tuple(self._failures)
        self._failures.clear()
        return failures

    def close(self) -> tuple[AudioLoadFailure, ...]:
        """Wait for outstanding decodes, report failures, and release sounds."""
        if self._closed:
            return ()
        self._closed = True
        self._bgm_channel.stop()
        self._voice_channel.stop()
        self._executor.shutdown(wait=True, cancel_futures=True)
        for path, future in self._futures.items():
            if future.cancelled():
                continue
            try:
                future.result()
            except (OSError, pygame.error, ValueError) as exc:
                self._failures.append(
                    AudioLoadFailure(path.name, f"音频解码失败：{path}（{exc}）")
                )
        self._futures.clear()
        self._pending_sfx.clear()
        self._sounds.clear()
        failures = tuple(self._failures)
        self._failures.clear()
        return failures

    def _path_for(self, reference: AssetRef | str | Path) -> Path | None:
        if isinstance(reference, AssetRef):
            if reference.path is None:
                self._failures.append(
                    AudioLoadFailure(
                        reference.name,
                        f"音频资源不存在：{reference.name}",
                    )
                )
                return None
            path = reference.path
        else:
            try:
                path = self.catalog.resolve(str(reference))
            except (FileNotFoundError, ValueError) as exc:
                self._failures.append(
                    AudioLoadFailure(str(reference), f"音频资源无法解析：{exc}")
                )
                return None
        if not path.is_file():
            self._failures.append(
                AudioLoadFailure(str(reference), f"音频文件不存在：{path}")
            )
            return None
        return path.absolute()

    def _submit(self, path: Path) -> None:
        if path not in self._sounds and path not in self._futures:
            self._futures[path] = self._executor.submit(pygame.mixer.Sound, str(path))

    def _start_bgm(self, path: Path, sound: pygame.mixer.Sound) -> None:
        if path == self._current_bgm and self._bgm_channel.get_busy():
            return
        self._bgm_channel.fadeout(self.fade_ms)
        self._bgm_channel.play(sound, loops=-1, fade_ms=self.fade_ms)
        self._current_bgm = path

    def _start_voice(self, path: Path, sound: pygame.mixer.Sound) -> None:
        if path == self._current_voice and self._voice_channel.get_busy():
            return
        self._voice_channel.fadeout(self.fade_ms)
        self._voice_channel.play(sound, fade_ms=self.fade_ms)
        self._current_voice = path

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("AsyncAudioLoader 已关闭")
