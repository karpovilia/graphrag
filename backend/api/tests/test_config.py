from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def fresh_config(monkeypatch: pytest.MonkeyPatch):
    """Reset the lru_cache on get_settings between tests so env overrides
    actually take effect.
    """

    import api.config as cfg
    importlib.reload(cfg.settings)
    importlib.reload(cfg)
    yield cfg
    importlib.reload(cfg.settings)
    importlib.reload(cfg)


def test_defaults_have_deepseek_as_completion(
    monkeypatch: pytest.MonkeyPatch, fresh_config
) -> None:
    monkeypatch.setenv("DEEPSEEK__API_KEY", "sk-test")
    s = fresh_config.get_settings()
    assert s.default_completion_provider == "deepseek"
    assert s.deepseek.api_key == "sk-test"


def test_postgres_dsn_round_trip(
    monkeypatch: pytest.MonkeyPatch, fresh_config
) -> None:
    monkeypatch.setenv("POSTGRES__USER", "u")
    monkeypatch.setenv("POSTGRES__PASSWORD", "p")
    monkeypatch.setenv("POSTGRES__HOST", "db.local")
    monkeypatch.setenv("POSTGRES__PORT", "6543")
    monkeypatch.setenv("POSTGRES__DATABASE", "graphrag_r2")
    s = fresh_config.get_settings()
    assert s.postgres.dsn == "postgresql://u:p@db.local:6543/graphrag_r2"


def test_storage_data_dir_env(
    monkeypatch: pytest.MonkeyPatch, fresh_config
) -> None:
    monkeypatch.setenv("STORAGE__DATA_DIR", "/tmp/r2-data")
    s = fresh_config.get_settings()
    assert str(s.storage.data_dir) == "/tmp/r2-data"
