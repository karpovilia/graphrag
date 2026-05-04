from __future__ import annotations

from pathlib import Path

import pytest

from api.vectorstore.faiss_adapter import FaissAdapter


@pytest.fixture
def faiss_store(tmp_path: Path) -> FaissAdapter:
    return FaissAdapter(data_dir=tmp_path / "faiss")
