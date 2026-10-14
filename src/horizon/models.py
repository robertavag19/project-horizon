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


@dataclass
class Usage:
    model: str | None = None
    requests: int = 0
    reserved_tokens: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None


class ProviderFailure(Exception):
    """Sanitized termination category, with no raw provider response or credentials."""
    def __init__(self, reason: str):
        allowed = {'api_error', 'request_timeout', 'network_error', 'request_limit',
                   'token_budget', 'invalid_provider_response', 'invalid_provider_state',
                   'incomplete_response', 'invalid_action'}
        self.reason = reason if reason in allowed else 'provider_error'
        super().__init__(self.reason)
