"""Background jobs: the model every long-running tool shares.

A Job wraps one piece of work - converting a folder of images, trimming a
video - as a callable that receives a JobContext.  The work reports progress
and checks for cancellation through the context; the runner (Qt side, in
annotex.ui.jobs) moves it through queued → running → done / failed /
cancelled.  Nothing here imports Qt, so the work functions are testable on
their own.
"""

from __future__ import annotations

import itertools
import threading
import time
import traceback
from dataclasses import dataclass, field

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

_ids = itertools.count(1)


class JobCancelled(Exception):
    """Raised inside work when the user cancelled the job."""


@dataclass(eq=False)
class Job:
    title: str
    work: object                         # callable(JobContext) -> summary str
    tool: str = ""
    detail: str = ""
    id: int = field(default_factory=lambda: next(_ids))
    state: str = QUEUED
    progress: float = 0.0
    message: str = "Waiting to start"
    summary: str = ""
    error: str = ""
    outputs: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def active(self) -> bool:
        return self.state in (QUEUED, RUNNING)

    @property
    def elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        return (self.finished_at or time.time()) - self.started_at

    def cancel(self) -> None:
        self.cancel_event.set()


class JobContext:
    """What running work sees of its job."""

    def __init__(self, job: Job, notify=None, interval: float = 0.1):
        self.job = job
        self._notify = notify or (lambda _job: None)
        self._interval = interval
        self._last = 0.0

    @property
    def cancelled(self) -> bool:
        return self.job.cancel_event.is_set()

    @property
    def cancel_event(self) -> threading.Event:
        return self.job.cancel_event

    def check(self) -> None:
        if self.job.cancel_event.is_set():
            raise JobCancelled()

    def progress(self, fraction, message=None) -> None:
        fraction = max(0.0, min(1.0, float(fraction)))
        changed = message is not None and message != self.job.message
        self.job.progress = max(self.job.progress, fraction) if fraction < 1.0 else 1.0
        if message is not None:
            self.job.message = str(message)
        now = time.monotonic()
        if changed or fraction >= 1.0 or now - self._last >= self._interval:
            self._last = now
            self._notify(self.job)

    def output(self, path) -> None:
        self.job.outputs.append(str(path))

    def warn(self, message) -> None:
        self.job.warnings.append(str(message))


def execute(job: Job, notify=None) -> Job:
    """Run a job to completion on the current thread."""
    notify = notify or (lambda _job: None)
    job.state = RUNNING
    job.started_at = time.time()
    job.message = "Starting"
    notify(job)
    context = JobContext(job, notify)
    try:
        if job.cancel_event.is_set():
            raise JobCancelled()
        summary = job.work(context)
        if job.cancel_event.is_set():
            raise JobCancelled()
        job.summary = str(summary or "Done")
        job.state = DONE
        job.progress = 1.0
        job.message = job.summary
    except JobCancelled:
        job.state = CANCELLED
        job.message = "Cancelled"
    except Exception as exc:                                   # noqa: BLE001
        job.state = FAILED
        job.error = str(exc) or exc.__class__.__name__
        job.message = "Failed: %s" % job.error
        job.detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    job.finished_at = time.time()
    notify(job)
    return job
