from __future__ import annotations

from pathlib import Path

import pytest

from api.vectorstore.faiss_adapter import FaissAdapter


@pytest.fixture
def faiss_store(tmp_path: Path) -> FaissAdapter:
    return FaissAdapter(data_dir=tmp_path / "faiss")


@pytest.fixture(autouse=True)
def isolate_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets its own STORAGE__DATA_DIR + a fresh repository.

    Without this, the SnapshotRepository auto-loaded by `get_repository`
    keeps writing to the real `./data/state.json`, so tests that mutate
    persisted entities (users, corpora, …) leak state between runs and
    blow up in surprising ways the second time you invoke pytest.
    """

    monkeypatch.setenv("STORAGE__DATA_DIR", str(tmp_path / "state"))
    from api import runtime
    from api.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    runtime.get_repository.cache_clear()
    yield
    settings_mod.get_settings.cache_clear()
    runtime.get_repository.cache_clear()
