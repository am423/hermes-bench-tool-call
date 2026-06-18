"""Backend selection and registry.

The benchmark uses one of the registered backends to actually run
commands. v0.1 ships `tmux_isolated` only; v0.2+ may add others.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from hermesbench.backend.base import BaseHermesBenchEnvironment

T = TypeVar("T", bound="BaseHermesBenchEnvironment")

_BACKENDS: dict[str, type[BaseHermesBenchEnvironment]] = {}


def register_backend(name: str) -> Callable[[type[T]], type[T]]:
    """Decorator to register a backend class.

    Backends are subclassed from `BaseHermesBenchEnvironment` and
    registered under a string name. The runner selects the backend
    via `--backend` (default: `tmux_isolated`).
    """

    def wrap(cls: type[T]) -> type[T]:
        if name in _BACKENDS:
            raise ValueError(f"backend {name!r} already registered")
        _BACKENDS[name] = cls
        return cls

    return wrap


def get_backend(name: str) -> type[BaseHermesBenchEnvironment]:
    if name not in _BACKENDS:
        raise KeyError(f"unknown backend {name!r}. Available: {sorted(_BACKENDS)}")
    return _BACKENDS[name]


def list_backends() -> list[str]:
    return sorted(_BACKENDS)
