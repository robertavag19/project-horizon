"""Typed observable actions; provider histories stay in memory."""
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Action:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Observation:
    action: Action
    result: dict[str, Any]


class Provider(Protocol):
    def choose_action(self, question: str, history: tuple[Observation, ...]) -> Action:
        """Return an action, never executable code or hidden reasoning."""
        ...
