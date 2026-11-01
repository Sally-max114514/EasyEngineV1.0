"""Pygame image loader with bounded source and scaled-surface caches."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Literal

import pygame

from ..galgame.engine import AssetRef
from ..resources import AssetCatalog

ImageFit = Literal["cover", "contain", "stretch"]
SurfaceKey = tuple[Path, tuple[int, int], ImageFit]


class PygameAssetError(RuntimeError):
    """An asset exists but Pygame could not decode or prepare it."""


class PygameAssetLoader:
    """Load images on demand and cache decoded/scaled surfaces.

    The source and transformed caches have independent byte budgets. This avoids
    repeated disk I/O and rescaling in the frame loop without unbounded growth
    when a window is resized.
    """

    def __init__(
        self,
        catalog: AssetCatalog,
        *,
        source_cache_bytes: int = 96 * 1024 * 1024,
        scaled_cache_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        if source_cache_bytes < 0 or scaled_cache_bytes < 0:
            raise ValueError("图像缓存上限不能为负数")
        self.catalog = catalog
        self.source_cache_bytes = source_cache_bytes
        self.scaled_cache_bytes = scaled_cache_bytes
        self._source_cache: OrderedDict[Path, pygame.Surface] = OrderedDict()
        self._scaled_cache: OrderedDict[SurfaceKey, pygame.Surface] = OrderedDict()
        self._source_bytes = 0
        self._scaled_bytes = 0

    def image(
        self,
        reference: AssetRef,
        size: tuple[int, int],
        *,
        fit: ImageFit = "contain",
    ) -> pygame.Surface:
        """Return a cached image surface resized to size."""
        if reference.path is None:
            raise FileNotFoundError(f"资源不存在：{reference.name}")
        if fit not in {"cover", "contain", "stretch"}:
            raise ValueError(f"不支持的图像适配方式：{fit!r}")
        width, height = size
        if width <= 0 or height <= 0:
            raise ValueError("目标图像尺寸必须大于 0")

        path = reference.path.absolute()
        key: SurfaceKey = (path, size, fit)
        cached = self._scaled_cache.get(key)
        if cached is not None:
            self._scaled_cache.move_to_end(key)
            return cached

        source = self._load_source(path)
        transformed = self._fit_surface(source, size, fit)
        self._cache_scaled(key, transformed)
        return transformed

    def clear_scaled_cache(self) -> None:
        """Release resolution-specific images after a window resize."""
        self._scaled_cache.clear()
        self._scaled_bytes = 0

    def clear(self) -> None:
        self.clear_scaled_cache()
        self._source_cache.clear()
        self._source_bytes = 0

    def _load_source(self, path: Path) -> pygame.Surface:
        cached = self._source_cache.get(path)
        if cached is not None:
            self._source_cache.move_to_end(path)
            return cached

        try:
            surface = pygame.image.load(str(path)).convert_alpha()
        except (OSError, pygame.error) as exc:
            raise PygameAssetError(f"图片加载失败：{path}（{exc}）") from exc

        size = self._surface_bytes(surface)
        if size <= self.source_cache_bytes:
            self._source_cache[path] = surface
            self._source_bytes += size
            self._evict_sources()
        return surface

    def _fit_surface(
        self,
        source: pygame.Surface,
        target_size: tuple[int, int],
        fit: ImageFit,
    ) -> pygame.Surface:
        target_width, target_height = target_size
        source_width, source_height = source.get_size()
        if fit == "stretch":
            scaled_size = target_size
        else:
            width_ratio = target_width / source_width
            height_ratio = target_height / source_height
            ratio = (
                max(width_ratio, height_ratio)
                if fit == "cover"
                else min(width_ratio, height_ratio)
            )
            scaled_size = (
                max(1, round(source_width * ratio)),
                max(1, round(source_height * ratio)),
            )

        scaled = (
            source
            if source.get_size() == scaled_size
            else pygame.transform.smoothscale(source, scaled_size)
        )
        if fit == "cover":
            left = (scaled.get_width() - target_width) // 2
            top = (scaled.get_height() - target_height) // 2
            return scaled.subsurface(
                pygame.Rect(left, top, target_width, target_height)
            ).copy()
        if fit == "contain":
            canvas = pygame.Surface(target_size, pygame.SRCALPHA, 32)
            canvas.blit(scaled, scaled.get_rect(center=canvas.get_rect().center))
            return canvas
        return scaled

    def _cache_scaled(self, key: SurfaceKey, surface: pygame.Surface) -> None:
        size = self._surface_bytes(surface)
        if size > self.scaled_cache_bytes:
            return
        self._scaled_cache[key] = surface
        self._scaled_bytes += size
        while self._scaled_bytes > self.scaled_cache_bytes and self._scaled_cache:
            _, evicted = self._scaled_cache.popitem(last=False)
            self._scaled_bytes -= self._surface_bytes(evicted)

    def _evict_sources(self) -> None:
        while self._source_bytes > self.source_cache_bytes and self._source_cache:
            _, evicted = self._source_cache.popitem(last=False)
            self._source_bytes -= self._surface_bytes(evicted)

    @staticmethod
    def _surface_bytes(surface: pygame.Surface) -> int:
        return surface.get_pitch() * surface.get_height()
