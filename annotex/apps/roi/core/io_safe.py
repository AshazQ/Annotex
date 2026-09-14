"""Safe file I/O for ROI Studio.

The implementation is the suite's shared one; this module only binds ROI
Studio's own lock file name and version to it, so existing batches keep
recognising each other's locks.
"""

from __future__ import annotations

from annotex.core.io_safe import FolderLock as _FolderLock
from annotex.core.io_safe import (MIN_FREE_BYTES, WriteReport,  # noqa: F401
                                  atomic_write, ensure_dir,
                                  folder_is_writable, free_bytes,
                                  human_bytes, read_json, rotate_backup,
                                  safe_remove, timestamped_sibling,
                                  write_text_atomic)

from ..config import APP_VERSION, LOCK_NAME


class FolderLock(_FolderLock):
    def __init__(self):
        super().__init__(LOCK_NAME, APP_VERSION)
