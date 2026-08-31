"""Object storage adapter used by media uploads.

When MinIO is configured, this adapter uploads to a real MinIO bucket
via the S3-compatible SDK. If MinIO is not configured, it falls back to
deterministic local behavior so tests and lightweight dev setups still
work.
"""
from __future__ import annotations

import asyncio
import io
import secrets
from dataclasses import dataclass

import httpx
from minio import Minio
from minio.error import S3Error

from app.config import get_settings


@dataclass(slots=True)
class StoredObject:
    storage_key: str
    public_url: str


class ObjectStorageClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Minio | None = None

    def build_media_key(self, *, event_id: str, title: str, media_type: str) -> str:
        safe_title = "-".join(title.lower().split())
        return f"events/{event_id}/media/{media_type}/{safe_title}-{secrets.token_hex(6)}"

    def _has_minio(self) -> bool:
        return bool(self.settings.minio_endpoint)

    def _get_client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                endpoint=self.settings.minio_endpoint,
                access_key=self.settings.minio_access_key,
                secret_key=self.settings.minio_secret_key,
                secure=self.settings.minio_secure,
            )
        return self._client

    async def _ensure_bucket(self) -> None:
        client = self._get_client()
        bucket = self.settings.minio_bucket

        def _create_if_needed() -> None:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)

        await asyncio.to_thread(_create_if_needed)

    async def _build_public_url(self, storage_key: str) -> str:
        if self.settings.minio_public_base_url:
            base = self.settings.minio_public_base_url.rstrip("/")
            return f"{base}/{self.settings.minio_bucket}/{storage_key}"

        client = self._get_client()
        return await asyncio.to_thread(
            client.presigned_get_object,
            self.settings.minio_bucket,
            storage_key,
        )

    async def upload_media_asset(
        self,
        *,
        event_id: str,
        title: str,
        media_type: str,
        source_url: str | None = None,
    ) -> StoredObject:
        storage_key = self.build_media_key(event_id=event_id, title=title, media_type=media_type)

        if not self._has_minio():
            public_url = source_url or f"https://storage.local/{storage_key}"
            return StoredObject(storage_key=storage_key, public_url=public_url)

        await self._ensure_bucket()
        content = b""
        content_type = "application/octet-stream"
        if source_url:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(source_url)
                response.raise_for_status()
                content = response.content
                content_type = response.headers.get("content-type", content_type)

        client = self._get_client()

        def _upload() -> None:
            client.put_object(
                self.settings.minio_bucket,
                storage_key,
                io.BytesIO(content),
                len(content),
                content_type=content_type,
            )

        await asyncio.to_thread(_upload)
        public_url = await self._build_public_url(storage_key)
        return StoredObject(storage_key=storage_key, public_url=public_url)

    async def delete_media_asset(self, storage_key: str) -> None:
        if not self._has_minio():
            return None
        client = self._get_client()

        def _delete() -> None:
            try:
                client.remove_object(self.settings.minio_bucket, storage_key)
            except S3Error:
                return None

        await asyncio.to_thread(_delete)


def get_object_storage_client() -> ObjectStorageClient:
    return ObjectStorageClient()
