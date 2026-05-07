from __future__ import annotations

from typing import Any, Generic, TypeVar

from .descriptor import Kind, StrategyDescriptor

T = TypeVar("T")


class Registry(Generic[T]):
    """Per-kind plugin registry.

    Stores classes (not instances) so strategies that need DI can be
    constructed by the orchestrator with the right wiring. Stateless
    strategies just take `cls()`.
    """

    def __init__(self, kind: Kind) -> None:
        self.kind: Kind = kind
        self._items: dict[str, tuple[type[T], StrategyDescriptor]] = {}

    def register(
        self,
        name: str,
        *,
        summary: str = "",
        description: str = "",
        requires_layers: tuple = (),
        produces_layers: tuple = (),
        params_schema: dict[str, Any] | None = None,
        cost_hint: str | None = None,
        references: tuple[str, ...] = (),
    ):
        """Decorator. Attaches a StrategyDescriptor to the class and
        registers it under `name`. Re-registering the same name
        overwrites — handy for tests, but the orchestrator should
        complain in production logs.
        """

        def deco(cls: type[T]) -> type[T]:
            descriptor = StrategyDescriptor(
                kind=self.kind,
                name=name,
                summary=summary,
                description=description,
                requires_layers=requires_layers,
                produces_layers=produces_layers,
                params_schema=params_schema or {},
                cost_hint=cost_hint,  # type: ignore[arg-type]
                references=references,
            )
            cls.descriptor = descriptor  # type: ignore[attr-defined]
            self._items[name] = (cls, descriptor)
            return cls

        return deco

    def get(self, name: str) -> type[T]:
        try:
            return self._items[name][0]
        except KeyError as e:
            raise KeyError(
                f"{self.kind} {name!r} not registered. "
                f"Available: {sorted(self._items)}"
            ) from e

    def get_descriptor(self, name: str) -> StrategyDescriptor:
        try:
            return self._items[name][1]
        except KeyError as e:
            raise KeyError(f"{self.kind} {name!r} not registered") from e

    def list(self) -> list[StrategyDescriptor]:
        return [d for _, d in self._items.values()]

    def names(self) -> list[str]:
        return list(self._items)

    def has(self, name: str) -> bool:
        return name in self._items

    def reset(self) -> None:
        """Test helper. Don't call from prod code."""
        self._items.clear()


builders: Registry = Registry("builder")
cleaners: Registry = Registry("cleaner")
clusterers: Registry = Registry("clusterer")
reasoners: Registry = Registry("reasoner")
agents: Registry = Registry("agent")


def all_descriptors() -> dict[Kind, list[StrategyDescriptor]]:
    """Aggregator for /api/strategies-style endpoints."""

    return {
        "builder": builders.list(),
        "cleaner": cleaners.list(),
        "clusterer": clusterers.list(),
        "reasoner": reasoners.list(),
        "agent": agents.list(),
    }
