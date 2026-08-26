"""
Object storage adapter used by media uploads.

Phase 7 keeps this stubbed and deterministic so the media module can
record uploads and generate public URLs without depending on a real
bucket. The rest of the code talks to this adapter only.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass


@dataclass(slots=True)
class StoredObject:
    storage_key: str
    public_url: str


class ObjectStorageClient:
    def build_media_key(self, *, event_id: str, title: str, media_type: str) -> str:
        safe_title = "-".join(title.lower().split())
        return f"events/{event_id}/media/{media_type}/{safe_title}-{secrets.token_hex(6)}"

    async def upload_media_asset(self, *, event_id: str, title: str, media_type: str, source_url: str | None = None) -> StoredObject:
        storage_key = self.build_media_key(event_id=event_id, title=title, media_type=media_type)
        public_url = source_url or f"https://storage.local/{storage_key}"
        return StoredObject(storage_key=storage_key, public_url=public_url)

    async def delete_media_asset(self, storage_key: str) -> None:
        return None


def get_object_storage_client() -> ObjectStorageClient:
    return ObjectStorageClient()
