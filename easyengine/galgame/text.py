"""不依赖界面的打字机状态。

引擎只维护“已经显示到第几个字符”，由界面层决定每帧调用 tick() 的
次数和速度；没有界面时也可以直接 reveal_all()。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TextTyper:
    text: str
    visible_chars: int = 0

    def __post_init__(self) -> None:
        self.visible_chars = max(0, min(self.visible_chars, len(self.text)))

    def tick(self, count: int = 1) -> int:
        """显示接下来的 count 个字符，返回本次实际新增的字符数。"""
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError("count 必须是整数")
        if count < 0:
            raise ValueError("count 不能为负数")
        before = self.visible_chars
        self.visible_chars = min(len(self.text), before + count)
        return self.visible_chars - before

    def reveal_all(self) -> None:
        self.visible_chars = len(self.text)

    @property
    def is_complete(self) -> bool:
        return self.visible_chars >= len(self.text)

    @property
    def visible_text(self) -> str:
        return self.text[: self.visible_chars]

    @property
    def remaining(self) -> int:
        return len(self.text) - self.visible_chars
