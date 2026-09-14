"""Drafts, the audit log and the session timer for ROI Studio.

The suite's shared services, bound to the file names ROI Studio has always
written, so a draft or an audit log from before the move is still found.
"""

from __future__ import annotations

from annotex.core.session import AuditLog as _AuditLog
from annotex.core.session import DraftStore as _DraftStore
from annotex.core.session import SessionTimer  # noqa: F401

from ..config import AUDIT_NAME, DRAFT_NAME, crash_dir


class DraftStore(_DraftStore):
    def __init__(self):
        super().__init__(DRAFT_NAME, recovery_dir=crash_dir)


class AuditLog(_AuditLog):
    def __init__(self, enabled: bool = True):
        super().__init__(AUDIT_NAME, enabled)
