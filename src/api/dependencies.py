from fastapi import Request

from .job_manager import JobManager
from ..db.queries import Neo4jConnection


def get_connection(request: Request) -> Neo4jConnection:
    return request.app.state.conn


def get_job_manager(request: Request) -> JobManager:
    return request.app.state.job_manager
