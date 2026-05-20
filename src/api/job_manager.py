import uuid
from datetime import datetime
from typing import Optional


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}

    def create_job(self) -> str:
        job_id = str(uuid.uuid4())
        self._jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "started_at": datetime.utcnow(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
        return job_id

    def get_job(self, job_id: str) -> Optional[dict]:
        return self._jobs.get(job_id)

    def complete_job(self, job_id: str, result: dict) -> None:
        if job_id in self._jobs:
            self._jobs[job_id].update(
                {"status": "completed", "finished_at": datetime.utcnow(), "result": result}
            )

    def fail_job(self, job_id: str, error: str) -> None:
        if job_id in self._jobs:
            self._jobs[job_id].update(
                {"status": "failed", "finished_at": datetime.utcnow(), "error": error}
            )
