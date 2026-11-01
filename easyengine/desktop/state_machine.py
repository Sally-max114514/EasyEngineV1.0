"""Framework-agnostic application state machine."""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar

ContextT = TypeVar("ContextT", contravariant=True)


class State(Protocol[ContextT]):
    """A state in the desktop application's finite-state machine."""

    def on_enter(self, context: ContextT, /) -> None: ...

    def on_exit(self, context: ContextT, /) -> None: ...

    def handle_event(
        self,
        context: ContextT,
        event: object,
        /,
    ) -> State[ContextT] | None: ...

    def update(
        self,
        context: ContextT,
        delta_seconds: float,
        /,
    ) -> State[ContextT] | None: ...

    def render(self, context: ContextT, /) -> None: ...


class StateMachine(Generic[ContextT]):
    """Dispatch events and updates to one active state at a time."""

    def __init__(self, context: ContextT) -> None:
        self.context = context
        self.current: State[ContextT] | None = None

    def start(self, initial: State[ContextT]) -> None:
        if self.current is not None:
            raise RuntimeError("状态机已经启动")
        self.current = initial
        initial.on_enter(self.context)

    def handle_event(self, event: object) -> None:
        target = self._current().handle_event(self.context, event)
        if target is not None:
            self.transition(target)

    def update(self, delta_seconds: float) -> None:
        target = self._current().update(self.context, delta_seconds)
        if target is not None:
            self.transition(target)

    def render(self) -> None:
        self._current().render(self.context)

    def transition(self, target: State[ContextT]) -> None:
        current = self._current()
        if target is current:
            return
        current.on_exit(self.context)
        self.current = target
        target.on_enter(self.context)

    def _current(self) -> State[ContextT]:
        if self.current is None:
            raise RuntimeError("状态机尚未启动")
        return self.current
