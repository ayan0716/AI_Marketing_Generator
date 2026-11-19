"""Phase 3 - file storage for generated creatives and uploaded product images.

Images are kept on disk (not inside MongoDB documents) and served by FastAPI under /api/media/...
MongoDB only stores the relative path, so documents stay small.
"""

import shutil
from pathlib import Path

from config import get_settings

MEDIA_URL = "/api/media"

def root() -> Path:
    p = Path(get_settings().storage_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

def save_bytes(subdir: str, name: str, data: bytes) -> str:
    """Write a file and return its path relative to the storage root (what we keep in MongoDB)."""
    folder = root() / subdir
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return f"{subdir}/{name}"

def read_bytes(rel: str) -> bytes | None:
    f = _safe(rel)
    return f.read_bytes() if f and f.is_file() else None

def url_for(rel: str) -> str:
    return f"{MEDIA_URL}/{rel}"

def delete_file(rel: str | None) -> None:
    f = _safe(rel) if rel else None
    if f and f.is_file():
        f.unlink(missing_ok=True)

def delete_campaign_files(campaign_id: str) -> None:
    shutil.rmtree(root() / "creatives" / campaign_id, ignore_errors=True)
    shutil.rmtree(root() / "products" / campaign_id, ignore_errors=True)

def _safe(rel: str) -> Path | None:
    """Resolve a relative path and refuse anything that escapes the storage root."""
    base = root()
    f = (base / rel).resolve()
    return f if base in f.parents else None
