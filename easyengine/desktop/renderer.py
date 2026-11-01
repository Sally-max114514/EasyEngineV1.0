"""Cached Pygame renderer with partial display updates."""

from __future__ import annotations

import math
from collections.abc import Sequence
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from ..galgame.engine import GameView
from ..resources import AssetCatalog
from .assets import PygameAssetError, PygameAssetLoader

if TYPE_CHECKING:
    from ..galgame.engine import AssetRef
    from ..galgame.script import GalleryEntry
    from ..galgame.script import Story

Color = tuple[int, int, int]


@dataclass(frozen=True)
class MenuItem:
    key: str
    label: str
    detail: str = ""
    enabled: bool = True


class PygameRenderer:
    """Draw a Galgame view using cached surfaces and dirty rectangles."""

    def __init__(
        self,
        screen: pygame.Surface,
        catalog: AssetCatalog,
        story: Story,
    ) -> None:
        self.screen = screen
        self.catalog = catalog
        self.story = story
        self.assets = PygameAssetLoader(catalog)
        self._font_cache: dict[tuple[int, bool], pygame.font.Font] = {}
        self._text_cache: OrderedDict[
            tuple[str, int, Color, bool], pygame.Surface
        ] = OrderedDict()
        self._wrap_cache: OrderedDict[
            tuple[str, int, int, bool], tuple[str, ...]
        ] = OrderedDict()
        self._cache_limit = 512
        self._choice_rects: dict[int, pygame.Rect] = {}
        self._menu_rects: dict[str, pygame.Rect] = {}
        self._hovered_menu_item: str | None = None
        self._thumbnail_cache: OrderedDict[Path, pygame.Surface] = OrderedDict()
        self._frontend_background: pygame.Surface | None = None
        self._transition_duration = 0.0
        self._transition_elapsed = 0.0
        self._transition_kind = "fade"
        self._transition_surface: pygame.Surface | None = None
        self._choice_scroll = 0
        self._last_line_key: tuple[str | None, int, str] | None = None
        self._status_message = ""
        self._reported_asset_errors: set[str] = set()
        self._full_dirty = True
        self._scene_dirty = True
        self._dialogue_dirty = True
        self._rebuild_layout()

    @property
    def dialogue_rect(self) -> pygame.Rect:
        return self._dialogue_rect.copy()

    def resize(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.assets.clear_scaled_cache()
        self._frontend_background = None
        self._rebuild_layout()
        self.invalidate_full()

    def invalidate_full(self) -> None:
        self._full_dirty = True
        self._scene_dirty = True
        self._dialogue_dirty = True

    def invalidate_scene(self) -> None:
        self._scene_dirty = True

    def invalidate_dialogue(self, *, reset_choices: bool = False) -> None:
        self._dialogue_dirty = True
        if reset_choices:
            self._choice_scroll = 0

    def set_status(self, message: str) -> None:
        self._status_message = message
        self.invalidate_full()

    def clear_status(self) -> None:
        if self._status_message:
            self._status_message = ""
            self.invalidate_dialogue()

    def choice_at(self, position: tuple[int, int]) -> int | None:
        for index, rect in self._choice_rects.items():
            if rect.collidepoint(position):
                return index
        return None

    def menu_item_at(self, position: tuple[int, int]) -> str | None:
        for key, rect in self._menu_rects.items():
            if rect.collidepoint(position):
                return key
        return None

    def update_menu_hover(self, position: tuple[int, int]) -> str | None:
        item = self.menu_item_at(position)
        if item != self._hovered_menu_item:
            self._hovered_menu_item = item
            self.invalidate_full()
        return item

    def draw_frontend(
        self,
        heading: str,
        subtitle: str,
        items: Sequence[MenuItem],
        selected_key: str | None,
        *,
        detail_title: str = "",
        detail_lines: Sequence[str] = (),
        footer: str = "",
        detail_image: pygame.Surface | None = None,
    ) -> None:
        if not self._full_dirty:
            return

        width, height = self.screen.get_size()
        self.screen.fill((10, 14, 26))
        self._draw_frontend_background(width, height)

        left = int(width * 0.075)
        menu_width = min(440, int(width * 0.42))
        right = int(width * 0.55)
        detail_width = max(180, width - right - left)

        self._blit_text(
            "EASYENGINE  /  VISUAL NOVEL",
            self._font(16, bold=True),
            (117, 191, 216),
            (left, 32),
        )
        self._blit_text(heading, self._font(42, bold=True), (245, 240, 229), (left, 68))
        self._blit_text(
            self._truncate(subtitle, self._font(17), menu_width),
            self._font(17),
            (166, 178, 199),
            (left, 119),
        )

        gap = 9 if len(items) <= 5 else 6
        item_height = max(
            24,
            min(
                52,
                (height - 174 - gap * max(0, len(items) - 1))
                // max(1, len(items)),
            ),
        )
        total_height = len(items) * item_height + max(0, len(items) - 1) * gap
        top = max(
            122,
            min(
                height - total_height - 44,
                (height - total_height) // 2 + 52,
            ),
        )

        self._menu_rects.clear()
        for index, item in enumerate(items):
            rect = pygame.Rect(
                left,
                top + index * (item_height + gap),
                menu_width,
                item_height,
            )
            self._menu_rects[item.key] = rect
            focused = item.key == selected_key or item.key == self._hovered_menu_item
            fill = (38, 60, 86) if focused else (22, 31, 48)
            border = (92, 179, 207) if focused else (47, 64, 88)
            text_color = (247, 245, 238) if item.enabled else (109, 118, 136)
            pygame.draw.rect(self.screen, fill, rect, border_radius=9)
            pygame.draw.rect(self.screen, border, rect, width=2 if focused else 1, border_radius=9)
            if focused:
                pygame.draw.rect(
                    self.screen,
                    (125, 218, 226),
                    pygame.Rect(rect.left, rect.top + 9, 3, rect.height - 18),
                    border_radius=2,
                )
            self._blit_text(
                item.label,
                self._font(19, bold=focused),
                text_color,
                (rect.left + 20, rect.centery - self._font(19).get_height() // 2),
            )
            if item.detail:
                self._blit_text(
                    self._truncate(item.detail, self._font(13), rect.width - 42),
                    self._font(13),
                    (154, 169, 190) if item.enabled else (103, 111, 126),
                    (rect.right - min(rect.width - 34, self._font(13).size(item.detail)[0]) - 18,
                     rect.centery - self._font(13).get_height() // 2),
                )

        panel_height = min(310, max(190, height - 104))
        panel = pygame.Rect(
            right,
            max(52, (height - panel_height) // 2),
            detail_width,
            panel_height,
        )
        pygame.draw.rect(self.screen, (17, 24, 39), panel, border_radius=16)
        pygame.draw.rect(self.screen, (52, 76, 101), panel, width=1, border_radius=16)
        pygame.draw.circle(self.screen, (44, 82, 103), (panel.right - 42, panel.top + 40), 7)
        pygame.draw.circle(self.screen, (69, 133, 151), (panel.right - 64, panel.top + 58), 3)
        self._blit_text(
            detail_title or "EASYENGINE",
            self._font(25, bold=True),
            (232, 238, 240),
            (panel.left + 28, panel.top + 35),
        )
        line_y = panel.top + 92
        if detail_image is not None:
            image_box = pygame.Rect(
                panel.left + 28,
                panel.top + 78,
                panel.width - 56,
                min(132, panel.height // 2),
            )
            ratio = min(
                image_box.width / detail_image.get_width(),
                image_box.height / detail_image.get_height(),
            )
            fitted = pygame.transform.smoothscale(
                detail_image,
                (
                    max(1, round(detail_image.get_width() * ratio)),
                    max(1, round(detail_image.get_height() * ratio)),
                ),
            )
            self.screen.blit(fitted, fitted.get_rect(center=image_box.center))
            line_y = image_box.bottom + 14
        line_limit = max(1, (panel.bottom - line_y - 16) // 27)
        for line in detail_lines[: min(8, line_limit)]:
            wrapped = self._wrap(line, self._font(16), panel.width - 56)
            for wrapped_line in wrapped[:2]:
                self._blit_text(
                    wrapped_line,
                    self._font(16),
                    (168, 183, 201),
                    (panel.left + 28, line_y),
                )
                line_y += 27
            line_y += 5

        if footer:
            self._blit_text(
                self._truncate(footer, self._font(14), width - 2 * left),
                self._font(14),
                (112, 129, 151),
                (left, height - 31),
            )

        if self._status_message:
            status_font = self._font(15)
            self._blit_text(
                self._truncate(self._status_message, status_font, width - 2 * left),
                status_font,
                (255, 205, 125),
                (left, height - 56),
            )
        self._present([self.screen.get_rect()])
        self._clear_dirty()

    def draw_gallery(
        self,
        entry: GalleryEntry | None,
        image_ref: AssetRef | None,
        index: int,
        count: int,
    ) -> None:
        if not self._full_dirty:
            return

        width, height = self.screen.get_size()
        self.screen.fill((10, 14, 26))
        self._draw_frontend_background(width, height)
        left = int(width * 0.075)
        self._blit_text(
            "EASYENGINE  /  CG GALLERY",
            self._font(16, bold=True),
            (117, 191, 216),
            (left, 30),
        )
        self._blit_text("CG 鉴赏", self._font(36, bold=True), (245, 240, 229), (left, 60))

        image_box = pygame.Rect(
            int(width * 0.14),
            116,
            int(width * 0.72),
            max(150, height - 270),
        )
        pygame.draw.rect(self.screen, (17, 24, 39), image_box, border_radius=14)
        pygame.draw.rect(self.screen, (52, 76, 101), image_box, width=1, border_radius=14)
        if entry is None or image_ref is None:
            self._draw_text_center(
                "剧本未声明可鉴赏 CG",
                23,
                (185, 198, 216),
                image_box.centery,
            )
        elif image_ref.exists:
            try:
                image = self.assets.image(image_ref, image_box.size, fit="contain")
            except (FileNotFoundError, PygameAssetError) as exc:
                self._report_asset_error(str(exc))
                self._draw_missing_asset(entry.image, image_box)
            else:
                self.screen.blit(image, image_box.topleft)
        else:
            self._draw_missing_asset(entry.image if entry else "", image_box)

        if entry is not None:
            title = entry.title
            description = entry.description
            self._blit_text(
                self._truncate(title, self._font(23, bold=True), width - 2 * left),
                self._font(23, bold=True),
                (238, 240, 245),
                (left, height - 116),
            )
            if description:
                self._blit_text(
                    self._truncate(description, self._font(16), width - 2 * left),
                    self._font(16),
                    (166, 178, 199),
                    (left, height - 82),
                )
            self._blit_text(
                f"{index + 1}/{count}",
                self._font(15),
                (166, 178, 199),
                (width - left - 58, height - 112),
            )

        self._menu_rects.clear()
        controls = (
            ("gallery_previous", "‹ 上一张", left),
            ("gallery_next", "下一张 ›", width - left - 132),
            ("gallery_back", "返回", width // 2 - 62),
        )
        for key, label, x in controls:
            button = pygame.Rect(x, height - 48, 124, 34)
            self._menu_rects[key] = button
            pygame.draw.rect(self.screen, (25, 37, 55), button, border_radius=8)
            pygame.draw.rect(self.screen, (63, 87, 113), button, width=1, border_radius=8)
            surface = self._text_surface(label, 15, (218, 228, 238))
            self.screen.blit(surface, surface.get_rect(center=button.center))
        if count == 0:
            for key in ("gallery_previous", "gallery_next"):
                self._menu_rects.pop(key, None)

        self._present([self.screen.get_rect()])
        self._clear_dirty()

    def save_thumbnail(
        self,
        path: str | Path,
        view: GameView | None = None,
    ) -> None:
        """Write a bounded screenshot thumbnail atomically."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.stem}.tmp{path.suffix}")
        if view is None:
            source = self.screen.copy()
        else:
            original_screen = self.screen
            try:
                self.screen = pygame.Surface((640, 360), depth=32)
                self._rebuild_layout()
                self.invalidate_full()
                self._draw_game_surfaces(view)
                source = self.screen.copy()
            finally:
                self.screen = original_screen
                self._rebuild_layout()
                self.invalidate_full()
        thumbnail = pygame.transform.smoothscale(source, (320, 180))
        try:
            pygame.image.save(thumbnail, str(temporary))
            temporary.replace(path)
        except (OSError, pygame.error) as exc:
            raise OSError(f"存档缩略图写入失败：{path}（{exc}）") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def load_thumbnail(self, path: str | Path) -> pygame.Surface | None:
        path = Path(path)
        cached = self._thumbnail_cache.get(path)
        if cached is not None:
            self._thumbnail_cache.move_to_end(path)
            return cached
        if not path.is_file():
            return None
        try:
            surface = pygame.image.load(str(path)).convert()
            surface = pygame.transform.smoothscale(surface, (320, 180))
        except (OSError, pygame.error) as exc:
            self._report_asset_error(f"存档缩略图加载失败：{path}（{exc}）")
            return None
        self._thumbnail_cache[path] = surface
        while len(self._thumbnail_cache) > 16:
            self._thumbnail_cache.popitem(last=False)
        return surface

    def start_transition(self, kind: str = "fade", duration: float = 0.32) -> None:
        if kind not in {"none", "fade", "crossfade", "slide-left", "slide-right"}:
            raise ValueError(f"不支持的转场类型：{kind!r}")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or not 0 <= duration <= 5
        ):
            raise ValueError("转场时长必须是 0 到 5 秒之间的有限数字")
        if kind == "none" or duration == 0:
            self._transition_duration = 0.0
            self._transition_elapsed = 0.0
            self._transition_surface = None
            return
        self._transition_duration = duration
        self._transition_elapsed = 0.0
        self._transition_kind = kind
        self._transition_surface = self.screen.copy()
        self.invalidate_full()

    def update_transition(self, delta_seconds: float) -> None:
        if self._transition_elapsed >= self._transition_duration:
            return
        was_active = self._transition_elapsed < self._transition_duration
        self._transition_elapsed = min(
            self._transition_duration,
            self._transition_elapsed + max(0.0, delta_seconds),
        )
        if was_active and self._transition_elapsed >= self._transition_duration:
            self._transition_surface = None
            self.invalidate_full()

    def scroll_choices(self, direction: int, choice_count: int) -> None:
        if direction == 0:
            return
        visible_count = self._visible_choice_count()
        max_scroll = max(0, choice_count - visible_count)
        self._choice_scroll = max(
            0,
            min(max_scroll, self._choice_scroll - direction),
        )
        self.invalidate_dialogue()

    def draw_title(self, title: str) -> None:
        if not self._full_dirty:
            return
        self.screen.fill((15, 20, 35))
        self._draw_text_center(title, 54, (245, 240, 225), self.screen.get_rect().centery - 40)
        self._draw_text_center(
            "按 Enter / Space 开始 · Esc 退出",
            24,
            (175, 190, 210),
            self.screen.get_rect().centery + 40,
        )
        if self._status_message:
            self._draw_text_center(
                self._status_message,
                17,
                (255, 205, 125),
                self.screen.get_height() - 36,
            )
        self._present([self.screen.get_rect()])
        self._clear_dirty()

    def draw_game(self, view: GameView) -> None:
        transition_active = self._transition_elapsed < self._transition_duration
        if transition_active:
            self.invalidate_full()
        dirty = self._draw_game_surfaces(view)
        if transition_active:
            progress = self._transition_elapsed / self._transition_duration
            previous = self._transition_surface
            if self._transition_kind == "fade":
                overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA, 32)
                overlay.fill((0, 0, 0, round(255 * (1 - progress))))
                self.screen.blit(overlay, (0, 0))
            elif previous is not None and self._transition_kind == "crossfade":
                overlay = previous.copy()
                overlay.set_alpha(round(255 * (1 - progress)))
                self.screen.blit(overlay, (0, 0))
            elif previous is not None:
                current = self.screen.copy()
                width = self.screen.get_width()
                offset = round(width * progress)
                if self._transition_kind == "slide-left":
                    self.screen.blit(previous, (-offset, 0))
                    self.screen.blit(current, (width - offset, 0))
                else:
                    self.screen.blit(previous, (offset, 0))
                    self.screen.blit(current, (-width + offset, 0))
            dirty = [self.screen.get_rect()]
        if dirty:
            self._present(dirty)

    def draw_pause(self, view: GameView) -> None:
        if not self._needs_redraw():
            return
        self._draw_game_surfaces(view)
        self._draw_overlay("已暂停", "Esc / Enter 继续 · F5 存档 · F9 读档")
        self._present([self.screen.get_rect()])
        self._clear_dirty()

    def draw_ending(self, view: GameView) -> None:
        if not self._needs_redraw():
            return
        self._draw_game_surfaces(view)
        self._draw_overlay("剧情结束", "按 Enter / Space 返回标题")
        self._present([self.screen.get_rect()])
        self._clear_dirty()

    def _draw_game_surfaces(self, view: GameView) -> list[pygame.Rect]:
        if self._full_dirty:
            self._scene_dirty = True
            self._dialogue_dirty = True

        dirty: list[pygame.Rect] = []
        if self._scene_dirty:
            self._draw_scene(view)
            dirty.append(self._scene_rect.copy())
            self._scene_dirty = False
        if self._dialogue_dirty:
            self._draw_dialogue(view)
            dirty.append(self._dialogue_rect.copy())
            self._dialogue_dirty = False
        self._full_dirty = False
        return dirty

    def _draw_scene(self, view: GameView) -> None:
        self.screen.fill((20, 26, 42), self._scene_rect)
        if view.background is not None:
            if view.background.exists:
                try:
                    background = self.assets.image(
                        view.background,
                        self._scene_rect.size,
                        fit="cover",
                    )
                except (FileNotFoundError, PygameAssetError) as exc:
                    self._report_asset_error(str(exc))
                    self._draw_missing_asset(view.background.name, self._scene_rect)
                else:
                    self.screen.blit(background, self._scene_rect.topleft)
            else:
                self._draw_missing_asset(view.background.name, self._scene_rect)

        positions = {
            "left": 0.25,
            "center": 0.5,
            "right": 0.75,
        }
        sprite_size = (max(1, int(self._scene_rect.width * 0.48)), self._scene_rect.height)
        for sprite in view.sprites:
            x = self._scene_rect.left + int(
                self._scene_rect.width * positions[sprite.position]
            )
            if sprite.image.exists:
                try:
                    image = self.assets.image(
                        sprite.image,
                        sprite_size,
                        fit="contain",
                    )
                except (FileNotFoundError, PygameAssetError) as exc:
                    self._report_asset_error(str(exc))
                    self._draw_sprite_placeholder(sprite.id, x)
                else:
                    rect = image.get_rect(midbottom=(x, self._scene_rect.bottom))
                    self.screen.blit(image, rect)
            else:
                self._draw_sprite_placeholder(sprite.id, x)

    def _draw_dialogue(self, view: GameView) -> None:
        line_key = (view.scene_id, view.line_index, view.text)
        if line_key != self._last_line_key:
            self._choice_scroll = 0
            self._last_line_key = line_key

        self._choice_rects.clear()
        self.screen.fill((13, 18, 30), self._dialogue_rect)
        pygame.draw.rect(self.screen, (90, 112, 145), self._dialogue_rect, width=2)

        padding = 28
        speaker_y = self._dialogue_rect.top + 14
        if view.speaker:
            color = self._speaker_color(view.speaker_id)
            self._blit_text(
                view.speaker,
                self._font(25, bold=True),
                color,
                (self._dialogue_rect.left + padding, speaker_y),
            )

        content_top = self._dialogue_rect.top + 50
        choice_top = self._dialogue_rect.top + 108
        max_text_height = (
            choice_top - content_top - 4
            if view.choices
            else self._dialogue_rect.bottom - content_top - 38
        )
        dialogue_font = self._font(22)
        dialogue_lines = self._wrap(
            view.visible_text,
            dialogue_font,
            self._dialogue_rect.width - padding * 2,
        )
        line_height = dialogue_font.get_linesize() + 3
        max_text_lines = max(1, max_text_height // line_height)
        self._draw_lines(
            dialogue_lines[:max_text_lines],
            dialogue_font,
            (238, 240, 245),
            (self._dialogue_rect.left + padding, content_top),
            line_height,
        )

        if view.choices:
            self._draw_choices(view)
        if self._status_message:
            status_font = self._font(16)
            self._blit_text(
                self._truncate(self._status_message, status_font, self._dialogue_rect.width - 56),
                status_font,
                (255, 205, 125),
                (self._dialogue_rect.left + padding, self._dialogue_rect.bottom - 25),
            )

    def _draw_choices(self, view: GameView) -> None:
        padding = 28
        available_height = self._dialogue_rect.bottom - (
            self._dialogue_rect.top + 108
        ) - 34
        gap = 5
        button_height = 31
        row_height = button_height + gap
        visible_count = max(1, (available_height + gap) // row_height)
        start = min(self._choice_scroll, max(0, len(view.choices) - visible_count))
        end = min(len(view.choices), start + visible_count)
        self._choice_scroll = start

        for row, choice in enumerate(view.choices[start:end]):
            rect = pygame.Rect(
                self._dialogue_rect.left + padding,
                self._dialogue_rect.top + 108 + row * row_height,
                self._dialogue_rect.width - padding * 2,
                button_height,
            )
            self._choice_rects[choice.index] = rect
            background = (55, 76, 106) if choice.available else (44, 48, 57)
            foreground = (245, 246, 250) if choice.available else (137, 142, 151)
            pygame.draw.rect(self.screen, background, rect, border_radius=5)
            label = self._truncate(
                f"{choice.index + 1}. {choice.text}",
                self._font(18),
                rect.width - 24,
            )
            text_surface = self._text_surface(label, 18, foreground)
            self.screen.blit(
                text_surface,
                text_surface.get_rect(midleft=(rect.left + 12, rect.centery)),
            )

        if len(view.choices) > visible_count:
            hint = f"{start + 1}-{end}/{len(view.choices)} · 滚轮浏览"
            self._blit_text(
                hint,
                self._font(14),
                (160, 175, 195),
                (self._dialogue_rect.right - 180, self._dialogue_rect.bottom - 22),
            )

    def _draw_overlay(self, heading: str, instruction: str) -> None:
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA, 32)
        overlay.fill((0, 0, 0, 155))
        self.screen.blit(overlay, (0, 0))
        box = pygame.Rect(0, 0, min(620, self.screen.get_width() - 48), 190)
        box.center = self.screen.get_rect().center
        pygame.draw.rect(self.screen, (23, 30, 46), box, border_radius=12)
        pygame.draw.rect(self.screen, (130, 155, 190), box, width=2, border_radius=12)
        self._draw_text_center(heading, 38, (248, 240, 220), box.centery - 22)
        self._draw_text_center(instruction, 18, (190, 204, 222), box.centery + 30)

    def _draw_missing_asset(self, name: str, rect: pygame.Rect) -> None:
        inset = rect.inflate(-24, -24)
        pygame.draw.rect(self.screen, (36, 44, 60), inset, border_radius=8)
        pygame.draw.rect(self.screen, (90, 112, 145), inset, width=2, border_radius=8)
        self._draw_text_center(
            f"资源待添加：{name}",
            20,
            (205, 215, 230),
            rect.centery,
        )

    def _draw_sprite_placeholder(self, sprite_id: str, center_x: int) -> None:
        width = max(120, int(self._scene_rect.width * 0.24))
        height = max(180, int(self._scene_rect.height * 0.68))
        rect = pygame.Rect(0, 0, width, height)
        rect.midbottom = (center_x, self._scene_rect.bottom)
        pygame.draw.rect(self.screen, (70, 82, 105), rect, border_radius=12)
        pygame.draw.rect(self.screen, (130, 150, 180), rect, width=2, border_radius=12)
        label = self._text_surface(sprite_id, 22, (240, 240, 245))
        self.screen.blit(label, label.get_rect(center=rect.center))

    def _draw_lines(
        self,
        lines: tuple[str, ...],
        font: pygame.font.Font,
        color: Color,
        position: tuple[int, int],
        line_height: int,
    ) -> None:
        x, y = position
        for line in lines:
            self._blit_text(line, font, color, (x, y))
            y += line_height

    def _draw_text_center(
        self,
        text: str,
        size: int,
        color: Color,
        center_y: int,
    ) -> None:
        surface = self._text_surface(text, size, color, bold=True)
        rect = surface.get_rect(center=(self.screen.get_width() // 2, center_y))
        self.screen.blit(surface, rect)

    def _draw_frontend_background(self, width: int, height: int) -> None:
        if (
            self._frontend_background is None
            or self._frontend_background.get_size() != (width, height)
        ):
            background = pygame.Surface((width, height))
            for y in range(0, height, 4):
                ratio = y / max(1, height - 1)
                color = (
                    round(10 + 8 * ratio),
                    round(14 + 12 * ratio),
                    round(26 + 16 * ratio),
                )
                pygame.draw.rect(background, color, (0, y, width, 4))
            for index in range(24):
                x = (index * 197 + 71) % max(1, width)
                y = (index * 113 + 43) % max(1, height)
                pygame.draw.circle(background, (36, 55, 75), (x, y), 1)
            self._frontend_background = background
        self.screen.blit(self._frontend_background, (0, 0))

    def _blit_text(
        self,
        text: str,
        font: pygame.font.Font,
        color: Color,
        position: tuple[int, int],
    ) -> None:
        key = (text, font.get_height(), color, font.get_bold())
        surface = self._text_cache.get(key)
        if surface is None:
            surface = font.render(text, True, color)
            self._text_cache[key] = surface
            while len(self._text_cache) > self._cache_limit:
                self._text_cache.popitem(last=False)
        else:
            self._text_cache.move_to_end(key)
        self.screen.blit(surface, position)

    def _font(self, size: int, *, bold: bool = False) -> pygame.font.Font:
        key = (size, bold)
        font = self._font_cache.get(key)
        if font is None:
            font_path = next(
                (
                    path
                    for name in (
                        "Noto Sans CJK SC",
                        "Microsoft YaHei",
                        "SimHei",
                        "WenQuanYi Zen Hei",
                        "Arial",
                    )
                    if (path := pygame.font.match_font(name)) is not None
                ),
                None,
            )
            font = pygame.font.Font(font_path, size)
            font.set_bold(bold)
            self._font_cache[key] = font
        return font

    def _text_surface(
        self,
        text: str,
        size: int,
        color: Color,
        *,
        bold: bool = False,
    ) -> pygame.Surface:
        key = (text, size, color, bold)
        surface = self._text_cache.get(key)
        if surface is not None:
            self._text_cache.move_to_end(key)
            return surface
        surface = self._font(size, bold=bold).render(text, True, color)
        self._text_cache[key] = surface
        while len(self._text_cache) > self._cache_limit:
            self._text_cache.popitem(last=False)
        return surface

    def _wrap(
        self,
        text: str,
        font: pygame.font.Font,
        max_width: int,
    ) -> tuple[str, ...]:
        size = font.get_height()
        key = (text, size, max_width, font.get_bold())
        cached = self._wrap_cache.get(key)
        if cached is not None:
            self._wrap_cache.move_to_end(key)
            return cached

        lines: list[str] = []
        for paragraph in text.splitlines() or [""]:
            current = ""
            for character in paragraph:
                candidate = current + character
                if current and font.size(candidate)[0] > max_width:
                    lines.append(current)
                    current = character
                else:
                    current = candidate
            lines.append(current)
        result = tuple(lines)
        self._wrap_cache[key] = result
        while len(self._wrap_cache) > self._cache_limit:
            self._wrap_cache.popitem(last=False)
        return result

    @staticmethod
    def _truncate(text: str, font: pygame.font.Font, max_width: int) -> str:
        if font.size(text)[0] <= max_width:
            return text
        suffix = "…"
        shortened = text
        while shortened and font.size(shortened + suffix)[0] > max_width:
            shortened = shortened[:-1]
        return shortened + suffix

    def _speaker_color(self, speaker_id: str | None) -> Color:
        if speaker_id is None:
            return (220, 225, 235)
        character = self.story.characters.get(speaker_id)
        if character is None or character.color is None:
            return (220, 225, 235)
        try:
            color = pygame.Color(character.color)
        except ValueError:
            return (220, 225, 235)
        return (color.r, color.g, color.b)

    def _report_asset_error(self, message: str) -> None:
        if message not in self._reported_asset_errors:
            self._reported_asset_errors.add(message)
            print(message)
        if self._status_message != message:
            self._status_message = message
            self._dialogue_dirty = True

    def _rebuild_layout(self) -> None:
        width, height = self.screen.get_size()
        dialogue_height = max(190, min(270, int(height * 0.34)))
        scene_height = height - dialogue_height
        self._scene_rect = pygame.Rect(0, 0, width, scene_height)
        self._dialogue_rect = pygame.Rect(0, scene_height, width, dialogue_height)

    def _visible_choice_count(self) -> int:
        available_height = self._dialogue_rect.bottom - (
            self._dialogue_rect.top + 108
        ) - 34
        return max(1, (available_height + 5) // 36)

    def _needs_redraw(self) -> bool:
        return self._full_dirty or self._scene_dirty or self._dialogue_dirty

    def _present(self, rectangles: list[pygame.Rect]) -> None:
        if rectangles:
            pygame.display.update(rectangles)

    def _clear_dirty(self) -> None:
        self._full_dirty = False
        self._scene_dirty = False
        self._dialogue_dirty = False
