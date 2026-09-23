from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from typing import Any, Callable


class JobStore:
    """In-process scrape jobs so a caller can disconnect while work continues."""

    def __init__(self, *, max_jobs: int = 40) -> None:
        self._max_jobs = max_jobs
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def start(self, fn: Callable[[], Any]) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {"status": "running", "result": None, "error": None}
            self._trim()
        threading.Thread(
            target=self._run,
            args=(job_id, fn),
            name=f"scrape-job-{job_id[:8]}",
            daemon=True,
        ).start()
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {"job_id": job_id, **job}

    def _run(self, job_id: str, fn: Callable[[], Any]) -> None:
        try:
            result = fn()
            status, error = "done", None
        except Exception as exc:
            result, status, error = None, "error", str(exc)
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id] = {"status": status, "result": result, "error": error}

    def _trim(self) -> None:
        while len(self._jobs) > self._max_jobs:
            self._jobs.popitem(last=False)
