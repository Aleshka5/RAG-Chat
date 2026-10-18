from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from deletion_worker.errors import TransientStorageError

_MISSING = {"NoSuchKey", "404", "NotFound", "NoSuchBucket"}


class S3ObjectStore:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def delete_object(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in _MISSING:
                return
            raise TransientStorageError("minio") from exc
        except BotoCoreError as exc:
            raise TransientStorageError("minio") from exc


def connect_s3(endpoint: str, access_key: str, secret_key: str, region: str) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    )
