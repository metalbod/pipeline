"""Local-filesystem stand-in for the platform's object storage (MinIO/S3 in later phases).

Path conventions follow ARCHITECTURE.md §5:
  bronze/api/{source_system}/{entity_id}/{endpoint}/{load_date}/*.parquet
  landing/{entity_id}/{doctype}/...

Swapping to S3/MinIO later means setting OBJECT_STORE_BACKEND=s3 (plus s3fs config) --
callers that go through get_fs()/the path helpers below don't change.
"""

import os
from functools import lru_cache

import fsspec
from fsspec import AbstractFileSystem


@lru_cache(maxsize=1)
def get_fs() -> AbstractFileSystem:
    backend = os.environ.get("OBJECT_STORE_BACKEND", "file")
    if backend != "file":
        raise NotImplementedError(
            f"OBJECT_STORE_BACKEND={backend!r} is not wired up yet; "
            "only the local 'file' stand-in exists as of Phase 0."
        )
    return fsspec.filesystem("file")


def store_root() -> str:
    return os.environ.get("OBJECT_STORE_ROOT", "./storage")


def bronze_api_path(source_system: str, entity_id: str, endpoint: str, load_date: str) -> str:
    return os.path.join(store_root(), "bronze", "api", source_system, entity_id, endpoint, load_date)


def landing_path(entity_id: str, doctype: str) -> str:
    return os.path.join(store_root(), "landing", entity_id, doctype)
