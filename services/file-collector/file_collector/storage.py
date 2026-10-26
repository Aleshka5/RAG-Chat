"""MinIO / S3 object storage."""

import asyncio
import logging
from collections.abc import Callable
from typing import BinaryIO
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from file_collector.config import Settings
from file_collector.errors import ObjectNotFound, StorageError

logger = logging.getLogger("file_collector")

_MISSING_OBJECT = {"NoSuchKey", "NoSuchObject", "NotFound"}


class S3Objects:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Minio | None = None

    async def connect(self) -> None:
        endpoint, secure = _endpoint(self._settings.s3_endpoint)
        self._client = Minio(
            endpoint,
            access_key=self._settings.s3_access_key,
            secret_key=self._settings.s3_secret_key,
            secure=secure,
            region=self._settings.s3_region,
        )

    async def close(self) -> None:
        self._client = None

    async def ensure_bucket(self) -> None:
        client = self._client_or_raise()
        bucket = self._settings.s3_bucket

        def check() -> None:
            # The storage stack owns this bucket. RAG reads it and does not create it.
            if not client.bucket_exists(bucket):
                raise StorageError("bucket")

        await self._call(check)

    async def head(self, key: str) -> int | None:
        """Return the object size, or None when the store does not report one."""
        client = self._client_or_raise()
        bucket = self._settings.s3_bucket

        def stat() -> int | None:
            try:
                info = client.stat_object(bucket, key)
            except S3Error as exc:
                if exc.code in _MISSING_OBJECT:
                    raise ObjectNotFound(key) from exc
                raise
            size = getattr(info, "size", None)
            if size is None:
                return None
            return int(size)

        return await self._call(stat)

    async def put(self, key: str, data: BinaryIO, length: int) -> None:
        client = self._client_or_raise()
        bucket = self._settings.s3_bucket

        def upload() -> None:
            data.seek(0)
            client.put_object(
                bucket,
                key,
                data,
                length=length,
                content_type="application/pdf",
            )

        await self._call(upload)

    async def delete(self, key: str) -> None:
        client = self._client_or_raise()
        bucket = self._settings.s3_bucket

        def remove() -> None:
            try:
                client.remove_object(bucket, key)
            except S3Error as exc:
                if exc.code not in {"NoSuchKey", "NoSuchObject"}:
                    raise

        await self._call(remove)

    async def get(self, key: str) -> bytes:
        client = self._client_or_raise()
        bucket = self._settings.s3_bucket

        def download() -> bytes:
            response = client.get_object(bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await self._call(download)

    def _client_or_raise(self) -> Minio:
        if self._client is None:
            raise StorageError("s3")
        return self._client

    async def _call(self, func: Callable):
        try:
            return await asyncio.to_thread(func)
        except StorageError:
            raise
        except S3Error as exc:
            logger.error("object storage error %s", exc.code or "s3")
            raise StorageError("s3") from exc
        except OSError as exc:
            logger.error("object storage error %s", type(exc).__name__)
            raise StorageError("s3") from exc


def _endpoint(url: str) -> tuple[str, bool]:
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return parsed.netloc, parsed.scheme == "https"
    if parsed.scheme == "" and parsed.path:
        return parsed.path, False
    raise StorageError("s3")
