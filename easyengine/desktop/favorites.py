"""Persistent metadata for voice clips marked by the player."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class FavoriteStoreError(ValueError):
    """Invalid or unavailable voice-favorites data."""


@dataclass(frozen=True)
class VoiceFavorite:
    story_title: str
    story_fingerprint: str
    asset_name: str
    speaker: str | None
    text: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.story_fingerprint, self.asset_name.casefold(), self.text)


class VoiceFavoriteStore:
    """Load and atomically persist favorites independent of individual save slots."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._entries: dict[tuple[str, str, str], VoiceFavorite] = {}

    @property
    def entries(self) -> tuple[VoiceFavorite, ...]:
        return tuple(
            sorted(
                self._entries.values(),
                key=lambda item: (
                    item.story_title.casefold(),
                    item.speaker or "",
                    item.text,
                ),
            )
        )

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise FavoriteStoreError(
                f"语音收藏文件 JSON 无效：{self.path}:{exc.lineno}:{exc.colno}"
            ) from exc
        except OSError as exc:
            raise FavoriteStoreError(
                f"语音收藏文件无法读取：{self.path}（{exc}）"
            ) from exc

        if (
            not isinstance(payload, dict)
            or isinstance(payload.get("version"), bool)
            or payload.get("version") != 1
        ):
            raise FavoriteStoreError(f"语音收藏文件格式不支持：{self.path}")
        raw_entries = payload.get("favorites")
        if not isinstance(raw_entries, list):
            raise FavoriteStoreError("语音收藏文件中的 favorites 必须是数组")

        entries: dict[tuple[str, str, str], VoiceFavorite] = {}
        for index, raw in enumerate(raw_entries):
            if not isinstance(raw, dict):
                raise FavoriteStoreError(f"语音收藏第 {index + 1} 项必须是对象")
            title = raw.get("story_title")
            fingerprint = raw.get("story_fingerprint")
            asset_name = raw.get("asset_name")
            speaker = raw.get("speaker")
            text = raw.get("text")
            if (
                not isinstance(title, str)
                or not isinstance(fingerprint, str)
                or not isinstance(asset_name, str)
                or not asset_name
                or (speaker is not None and not isinstance(speaker, str))
                or not isinstance(text, str)
            ):
                raise FavoriteStoreError(f"语音收藏第 {index + 1} 项字段无效")
            favorite = VoiceFavorite(title, fingerprint, asset_name, speaker, text)
            entries[favorite.key] = favorite
        self._entries = entries

    def contains(self, favorite: VoiceFavorite) -> bool:
        return favorite.key in self._entries

    def toggle(self, favorite: VoiceFavorite) -> bool:
        entries = dict(self._entries)
        if favorite.key in entries:
            del entries[favorite.key]
            self._save(entries)
            self._entries = entries
            return False
        entries[favorite.key] = favorite
        self._save(entries)
        self._entries = entries
        return True

    def _save(
        self,
        entries: dict[tuple[str, str, str], VoiceFavorite],
    ) -> None:
        payload = {
            "version": 1,
            "favorites": [
                {
                    "story_title": item.story_title,
                    "story_fingerprint": item.story_fingerprint,
                    "asset_name": item.asset_name,
                    "speaker": item.speaker,
                    "text": item.text,
                }
                for item in sorted(
                    entries.values(),
                    key=lambda value: (
                        value.story_title.casefold(),
                        value.speaker or "",
                        value.text,
                    ),
                )
            ],
        }
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            temporary.replace(self.path)
        except OSError as exc:
            raise FavoriteStoreError(
                f"语音收藏文件写入失败：{self.path}（{exc}）"
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)
