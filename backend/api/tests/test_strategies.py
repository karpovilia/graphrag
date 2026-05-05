from __future__ import annotations

import pytest

from api.domain.graph import Layer
from api.strategies import (
    BuilderProtocol,
    CleanerProtocol,
    Registry,
    StrategyDescriptor,
)
from api.strategies.registry import builders, cleaners


@pytest.fixture(autouse=True)
def _reset() -> None:
    saved_b = dict(builders._items)
    saved_c = dict(cleaners._items)
    builders.reset()
    cleaners.reset()
    yield
    builders.reset()
    cleaners.reset()
    builders._items.update(saved_b)
    cleaners._items.update(saved_c)


def test_register_attaches_descriptor_to_class() -> None:
    @cleaners.register(
        "test_x",
        summary="A test cleaner.",
        produces_layers=(Layer.ENTITY,),
        cost_hint="cheap",
        references=("docs/raw/2410.05779v3.pdf",),
    )
    class _Cleaner:
        async def clean(self, state, params):  # type: ignore[no-untyped-def]
            return state

    assert _Cleaner.descriptor.name == "test_x"
    assert _Cleaner.descriptor.summary == "A test cleaner."
    assert _Cleaner.descriptor.kind == "cleaner"
    assert Layer.ENTITY in _Cleaner.descriptor.produces_layers
    assert _Cleaner.descriptor.cost_hint == "cheap"


def test_get_returns_class_not_instance() -> None:
    @cleaners.register("test_y")
    class _Cleaner:
        async def clean(self, state, params): ...  # type: ignore[no-untyped-def]

    cls = cleaners.get("test_y")
    assert cls is _Cleaner


def test_unknown_name_raises_with_listing() -> None:
    @cleaners.register("registered_one")
    class _C:
        async def clean(self, state, params): ...  # type: ignore[no-untyped-def]

    with pytest.raises(KeyError) as exc:
        cleaners.get("nope")
    assert "registered_one" in str(exc.value)


def test_list_is_descriptor_only_no_class_leak() -> None:
    @cleaners.register("a")
    class _A:
        async def clean(self, state, params): ...  # type: ignore[no-untyped-def]

    @cleaners.register("b")
    class _B:
        async def clean(self, state, params): ...  # type: ignore[no-untyped-def]

    descriptors = cleaners.list()
    assert {d.name for d in descriptors} == {"a", "b"}
    assert all(isinstance(d, StrategyDescriptor) for d in descriptors)


def test_reregister_overwrites() -> None:
    @cleaners.register("dup", summary="first")
    class _First:
        async def clean(self, state, params): ...  # type: ignore[no-untyped-def]

    @cleaners.register("dup", summary="second")
    class _Second:
        async def clean(self, state, params): ...  # type: ignore[no-untyped-def]

    assert cleaners.get("dup") is _Second
    assert cleaners.get_descriptor("dup").summary == "second"


def test_protocol_satisfied_by_registered_class() -> None:
    @cleaners.register("p")
    class _Pruner:
        async def clean(self, state, params):  # type: ignore[no-untyped-def]
            return state

    inst = _Pruner()
    assert isinstance(inst, CleanerProtocol)


def test_separate_registries_dont_clash() -> None:
    @cleaners.register("same")
    class _C:
        async def clean(self, state, params): ...  # type: ignore[no-untyped-def]

    @builders.register("same")
    class _B:
        async def build(self, corpus_id, documents, params): ...  # type: ignore[no-untyped-def]

    assert cleaners.get("same") is _C
    assert builders.get("same") is _B
    assert isinstance(_B(), BuilderProtocol)


def test_kind_assigned_correctly() -> None:
    r: Registry = Registry("reasoner")

    @r.register("x")
    class _X: ...

    assert _X.descriptor.kind == "reasoner"
