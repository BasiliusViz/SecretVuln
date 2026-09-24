"""Хранилище загруженных SARIF-файлов: папка на диске (по умолчанию) или S3."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from app.core.config import get_settings

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _make_key(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name
    name = _UNSAFE.sub("_", name).strip("._")[:200] or "upload.sarif"
    return f"imports/{uuid.uuid4()}/{name}"


def _root() -> Path:
    return Path(get_settings().storage_path).resolve()


def _local_path(key: str) -> Path:
    root = _root()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Недопустимый ключ хранилища: {key}")
    return path


def _is_s3() -> bool:
    return get_settings().storage_backend == "s3"


def save_sarif(content: bytes, filename: str) -> str:
    key = _make_key(filename)
    if _is_s3():
        from app.services import s3

        s3.put_object(key, content)
    else:
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return key


def load_sarif(key: str) -> bytes:
    if _is_s3():
        from app.services import s3

        return s3.get_object(key)
    return _local_path(key).read_bytes()


def check_storage() -> bool:
    if _is_s3():
        from app.services import s3

        return s3.bucket_available()
    try:
        root = _root()
        root.mkdir(parents=True, exist_ok=True)
        return os.access(root, os.W_OK)
    except OSError:
        return False
