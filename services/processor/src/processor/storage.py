from __future__ import annotations

import time
from collections.abc import Callable

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from processor.config import Settings
from processor.errors import TransientFailure
from processor.retry import retry_call


class ObjectStorage:
    def __init__(
        self,
        settings: Settings,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        attempts: int = 3,
        client: object | None = None,
    ) -> None:
        self._bucket = settings.s3_bucket
        self._sleep = sleeper
        self._attempts = attempts
        self._client = client or boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(
                s3={"addressing_style": "path"},
                retries={"max_attempts": 1},
            ),
        )

    def get_bytes(self, key: str) -> bytes:
        def once() -> bytes:
            try:
                response = self._client.get_object(Bucket=self._bucket, Key=key)
                body = response["Body"].read()
            except (ClientError, BotoCoreError) as exc:
                raise _StorageError(exc) from exc
            if not isinstance(body, bytes):
                body = bytes(body)
            return body

        try:
            return retry_call(
                once,
                attempts=self._attempts,
                sleeper=self._sleep,
                is_retryable=lambda exc: isinstance(exc, _StorageError),
            )
        except _StorageError as exc:
            raise TransientFailure("storage_read_failed", permanent_code="storage_read_failed") from exc


class _StorageError(Exception):
    def __init__(self, cause: Exception) -> None:
        super().__init__(type(cause).__name__)
        self.cause = cause
