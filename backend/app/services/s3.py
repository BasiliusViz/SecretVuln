import uuid
from io import BytesIO

import boto3
from botocore.config import Config

from app.core.config import get_settings


def _get_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
        region_name="us-east-1",
    )


def upload_sarif(file_bytes: bytes, filename: str) -> str:
    s3_key = f"imports/{uuid.uuid4()}/{filename}"
    client = _get_client()
    settings = get_settings()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=s3_key,
        Body=file_bytes,
        ContentType="application/json",
    )
    return s3_key


def download_sarif(s3_key: str) -> bytes:
    client = _get_client()
    settings = get_settings()
    buf = BytesIO()
    client.download_fileobj(settings.s3_bucket, s3_key, buf)
    buf.seek(0)
    return buf.read()
