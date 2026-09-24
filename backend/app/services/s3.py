"""Бэкенд S3/MinIO для хранилища SARIF (включается SV_STORAGE_BACKEND=s3)."""

from io import BytesIO

import boto3
from botocore.config import Config

from app.core.config import get_settings


def _client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )


def put_object(key: str, content: bytes) -> None:
    _client().put_object(
        Bucket=get_settings().s3_bucket, Key=key, Body=content, ContentType="application/json"
    )


def get_object(key: str) -> bytes:
    buf = BytesIO()
    _client().download_fileobj(get_settings().s3_bucket, key, buf)
    return buf.getvalue()


def bucket_available() -> bool:
    try:
        _client().head_bucket(Bucket=get_settings().s3_bucket)
        return True
    except Exception:
        return False
