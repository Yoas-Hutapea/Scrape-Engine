import time

from scrape_engine.jobs import JobStore


def test_job_finishes_after_the_caller_returns():
    store = JobStore()
    job_id = store.start(lambda: {"rows": [{"name": "baterai"}]})

    deadline = time.monotonic() + 2
    job = store.get(job_id)
    while job and job["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
        job = store.get(job_id)

    assert job is not None
    assert job["status"] == "done"
    assert job["result"]["rows"][0]["name"] == "baterai"
    assert job["error"] is None


def test_job_records_errors():
    store = JobStore()

    def fail():
        raise RuntimeError("browser hung")

    job_id = store.start(fail)
    deadline = time.monotonic() + 2
    job = store.get(job_id)
    while job and job["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
        job = store.get(job_id)

    assert job is not None
    assert job["status"] == "error"
    assert "browser hung" in (job["error"] or "")
