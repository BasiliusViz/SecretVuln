"""Хранилище SARIF-файлов: диск по умолчанию, защита от выхода из папки."""

import pytest

from app.core.config import Settings, get_settings
from app.services import storage


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    return tmp_path


def test_default_backend_is_local():
    assert Settings().storage_backend == "local"


def test_save_and_load_roundtrip(local_storage):
    key = storage.save_sarif(b'{"runs": []}', "semgrep.sarif")
    assert key.startswith("imports/")
    assert key.endswith("/semgrep.sarif")
    assert (local_storage / key).is_file()
    assert storage.load_sarif(key) == b'{"runs": []}'


def test_filename_is_sanitized(local_storage):
    key = storage.save_sarif(b"x", "../../etc/passwd")
    assert ".." not in key
    assert key.endswith("/passwd")


def test_load_rejects_path_traversal(local_storage):
    with pytest.raises(ValueError):
        storage.load_sarif("../outside.sarif")


def test_check_storage_local(local_storage):
    assert storage.check_storage() is True


async def test_health_reports_storage(client, local_storage):
    r = await client.get("/api/v1/health")
    body = r.json()
    assert body["storage"] == "up"
    assert body["storage_backend"] == "local"
